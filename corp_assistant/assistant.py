import logging

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langchain_deepseek import ChatDeepSeek
from pydantic import BaseModel, Field

from corp_assistant.config import get_settings
from corp_assistant.context import current_user_id
from corp_assistant.errors import AppError
from corp_assistant.tools import TOOLS
from corp_assistant import store

logger = logging.getLogger(__name__)

CATEGORIES = {"it", "hr", "finance", "other"}
PRIORITIES = {"low", "medium", "high"}


class TicketDraft(BaseModel):
    title: str = Field(description="不超过 40 字的标题")
    category: str = Field(description="it、hr、finance、other 之一")
    priority: str = Field(description="low、medium、high 之一")
    description: str = Field(description="给处理人看的说明")


class ToolLogMiddleware(AgentMiddleware):
    """记录工具调用。不传 tool_choice，避免 DeepSeek flash 思考模式报错。"""

    def wrap_tool_call(self, request, handler):
        logger.info("tool %s", request.tool_call.get("name"))
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        logger.info("tool %s", request.tool_call.get("name"))
        return await handler(request)


def get_llm() -> ChatDeepSeek:
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise AppError(503, "未配置 DEEPSEEK_API_KEY")
    return ChatDeepSeek(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        api_base=settings.deepseek_api_base,
        temperature=0,
    )


def _prompt(user: dict) -> str:
    return (
        "你是星澜科技的内部助手，用中文简洁回答。"
        "制度问题必须先调用 search_knowledge，只根据检索结果回答；没有结果就说明不知道，不要编造。"
        "查同事用 lookup_employee。用户明确要求提交、报修、请假或报销落地时用 create_ticket。"
        "查进度用 list_tickets。问现在几点用 current_time。"
        f"当前用户：{user['name']}（工号 {user['id']}，{user['department']}，{user['title']}，角色 {user['role']}）。"
    )


def _as_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def _tool_calls(messages) -> list[dict]:
    calls = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            name = call.get("name")
            if name:
                calls.append({"name": name, "args": call.get("args") or {}})
    return calls


def chat(user: dict, message: str, conversation_id: str | None) -> dict:
    if conversation_id:
        store.require_conversation(user, conversation_id)
    else:
        conversation_id = store.create_conversation(user["id"], message.strip())
    store.add_message(conversation_id, "user", message.strip())

    history = []
    for item in store.recent_messages(conversation_id, limit=8):
        if item["role"] == "user":
            history.append(HumanMessage(content=item["content"]))
        elif item["role"] == "assistant":
            history.append(AIMessage(content=item["content"]))

    # create_agent 默认 tool_choice 为空。DeepSeek flash 思考模式不支持强制 tool_choice。
    agent = create_agent(
        get_llm(),
        TOOLS,
        system_prompt=_prompt(user),
        middleware=[ToolLogMiddleware()],
    )
    token = current_user_id.set(user["id"])
    try:
        try:
            result = agent.invoke({"messages": history}, {"recursion_limit": 12})
        except AppError:
            raise
        except Exception as exc:
            raise AppError(502, f"模型调用失败: {exc}") from exc
    finally:
        current_user_id.reset(token)

    messages = result["messages"]
    answer = _as_text(messages[-1].content).strip() or "（没有生成回答）"
    calls = _tool_calls(messages)
    store.add_message(conversation_id, "assistant", answer)
    store.add_audit(user["id"], "chat", conversation_id, message.strip()[:80])
    return {"conversation_id": conversation_id, "answer": answer, "tools": calls}


def suggest_ticket(text: str) -> TicketDraft:
    # DeepSeek 不支持 json_schema。json_mode 要求提示词里出现 json。
    structured = get_llm().with_structured_output(TicketDraft, method="json_mode")
    try:
        draft = structured.invoke(
            "把下面的需求整理成 JSON，字段 title, category, priority, description。"
            "category 只能是 it、hr、finance、other；priority 只能是 low、medium、high。\n"
            f"需求：{text}"
        )
    except AppError:
        raise
    except Exception as exc:
        raise AppError(502, f"模型调用失败: {exc}") from exc
    if not isinstance(draft, TicketDraft):
        draft = TicketDraft.model_validate(draft)
    if draft.category not in CATEGORIES:
        draft.category = "other"
    if draft.priority not in PRIORITIES:
        draft.priority = "medium"
    return draft
