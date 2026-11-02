from datetime import datetime

from langchain_core.tools import tool

from corp_assistant import knowledge, store
from corp_assistant.context import current_user_id
from corp_assistant.errors import AppError


def _requester() -> str:
    user_id = current_user_id.get()
    if not user_id:
        raise AppError(401, "未识别当前用户")
    return user_id


@tool
def search_knowledge(query: str) -> str:
    """检索公司制度。query 用具体词，例如年假、报销、VPN、密码。"""
    hits = knowledge.search(query, limit=3)
    if not hits:
        return "知识库没有相关内容。请直接说明不知道，不要编造制度。"
    blocks = []
    for hit in hits:
        blocks.append(f"[{hit['source']}] {hit['title']}\n{hit['content']}")
    return "\n\n".join(blocks)


@tool
def lookup_employee(name: str) -> str:
    """按姓名或工号查同事。name 例如王芳或 E002。"""
    rows, _total = store.list_employees(q=name, department="", limit=5, offset=0)
    if not rows:
        return "没有找到匹配的同事。"
    lines = [
        f"{row['id']} {row['name']} {row['department']} {row['title']} {row['email']}"
        for row in rows
    ]
    return "\n".join(lines)


@tool
def create_ticket(title: str, description: str, category: str, priority: str = "medium") -> str:
    """提交工单。category 取 it、hr、finance、other；priority 取 low、medium、high。"""
    try:
        ticket = store.create_ticket(
            requester_id=_requester(),
            title=title,
            description=description,
            category=category,
            priority=priority,
        )
    except AppError as exc:
        return exc.message
    return f"已创建工单 #{ticket['id']}，状态 {ticket['status']}，标题：{ticket['title']}"


@tool
def list_tickets(status: str = "") -> str:
    """查看当前用户可见的工单。status 可空，或 open、in_progress、resolved。"""
    user = store.get_employee(_requester())
    if user is None:
        return "未识别当前用户。"
    try:
        rows, total = store.list_tickets(user, status=status, limit=10, offset=0)
    except AppError as exc:
        return exc.message
    if not rows:
        return f"没有工单（共 {total} 条）。"
    lines = [
        f"#{row['id']} [{row['status']}] {row['category']}/{row['priority']} {row['title']}（{row['requester_name']}）"
        for row in rows
    ]
    return f"共 {total} 条，显示 {len(lines)} 条：\n" + "\n".join(lines)


@tool
def current_time() -> str:
    """返回当前本地时间。"""
    clock = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    return f"现在是 {clock}"


TOOLS = [search_knowledge, lookup_employee, create_ticket, list_tickets, current_time]
