import json
import logging

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
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


def open_turn(user: dict, message: str, conversation_id: str | None) -> tuple[str, list]:
    text = message.strip()
    if conversation_id:
        store.require_conversation(user, conversation_id)
    else:
        conversation_id = store.create_conversation(user["id"], text)
    store.add_message(conversation_id, "user", text)
    history = []
    for item in store.recent_messages(conversation_id, limit=8):
        if item["role"] == "user":
            history.append(HumanMessage(content=item["content"]))
        elif item["role"] == "assistant":
            history.append(AIMessage(content=item["content"]))
    return conversation_id, history


def build_agent(user: dict):
    # create_agent 默认 tool_choice 为空。DeepSeek flash 思考模式不支持强制 tool_choice。
    return create_agent(
        get_llm(),
        TOOLS,
        system_prompt=_prompt(user),
        middleware=[ToolLogMiddleware()],
    )


def _finish(user: dict, conversation_id: str, message: str, answer: str, calls: list[dict]) -> dict:
    store.add_message(conversation_id, "assistant", answer)
    store.add_audit(user["id"], "chat", conversation_id, message.strip()[:80])
    return {"conversation_id": conversation_id, "answer": answer, "tools": calls}


def _delta_parts(message) -> tuple[str, str]:
    """从一条流式消息里拆出可见回答和思考文本。"""
    content = getattr(message, "content", "")
    texts: list[str] = []
    reasons: list[str] = []
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                texts.append(block)
            elif isinstance(block, dict):
                kind = block.get("type")
                if kind == "reasoning":
                    reasons.append(str(block.get("reasoning") or block.get("text") or ""))
                elif kind in (None, "text", "output_text"):
                    texts.append(str(block.get("text") or ""))
    extra = (getattr(message, "additional_kwargs", None) or {}).get("reasoning_content")
    if isinstance(extra, str) and extra:
        reasons = [extra]
    return "".join(texts), "".join(reasons)


def _update_messages(payload):
    if not isinstance(payload, dict):
        return
    for update in payload.values():
        messages = update.get("messages") if isinstance(update, dict) else update
        if messages is None:
            continue
        if not isinstance(messages, list):
            messages = [messages]
        yield from messages


def iter_chat_events(user: dict, message: str, conversation_id: str, history: list, agent):
    """逐段产出对话事件。调用方负责把它们写成 SSE。"""
    yield {"event": "meta", "conversation_id": conversation_id}
    token = current_user_id.set(user["id"])
    answer_parts: list[str] = []
    calls: list[dict] = []
    seen_calls: set[str] = set()
    fallback = ""
    try:
        try:
            stream = agent.stream(
                {"messages": history},
                {"recursion_limit": 12},
                stream_mode=["messages", "updates"],
            )
            for item in stream:
                if not isinstance(item, tuple) or len(item) != 2:
                    continue
                mode, payload = item
                if mode == "messages":
                    if not isinstance(payload, tuple) or not payload:
                        continue
                    chunk = payload[0]
                    # 完整消息会在 updates 里再出现一次，这里只取 token。
                    if not isinstance(chunk, AIMessageChunk):
                        continue
                    text, reasoning = _delta_parts(chunk)
                    if reasoning:
                        yield {"event": "reasoning", "text": reasoning}
                    if text:
                        answer_parts.append(text)
                        yield {"event": "delta", "text": text}
                elif mode == "updates":
                    for update in _update_messages(payload):
                        tool_calls = getattr(update, "tool_calls", None) or []
                        if isinstance(update, AIMessage) and not isinstance(update, AIMessageChunk) and not tool_calls:
                            fallback = _as_text(update.content).strip() or fallback
                        for call in tool_calls:
                            name = call.get("name")
                            call_id = call.get("id") or name
                            if not name or not call_id or call_id in seen_calls:
                                continue
                            seen_calls.add(call_id)
                            calls.append({"name": name, "args": call.get("args") or {}})
                            yield {"event": "tool", "name": name}
        except AppError as exc:
            _save_partial(user, message, conversation_id, answer_parts, calls)
            yield {"event": "error", "detail": exc.message}
            return
        except Exception as exc:
            logger.exception("chat stream failed")
            _save_partial(user, message, conversation_id, answer_parts, calls)
            yield {"event": "error", "detail": f"模型调用失败: {exc}"}
            return
        answer = "".join(answer_parts).strip() or fallback or "（没有生成回答）"
        if not answer_parts and fallback:
            yield {"event": "delta", "text": fallback}
        _finish(user, conversation_id, message, answer, calls)
        yield {
            "event": "done",
            "conversation_id": conversation_id,
            "answer": answer,
            "tools": calls,
        }
    finally:
        current_user_id.reset(token)


def _save_partial(user: dict, message: str, conversation_id: str, answer_parts: list[str], calls: list[dict]) -> None:
    partial = "".join(answer_parts).strip()
    if partial:
        _finish(user, conversation_id, message, partial, calls)


def encode_sse(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def chat(user: dict, message: str, conversation_id: str | None) -> dict:
    conversation_id, history = open_turn(user, message, conversation_id)
    agent = build_agent(user)
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
    return _finish(user, conversation_id, message, answer, calls)


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
