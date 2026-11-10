import asyncio
import threading

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from corp_assistant import assistant, knowledge, store
from corp_assistant.auth import current_user, require_admin
from corp_assistant.schemas import (
    AuditOut,
    ChatIn,
    ConversationOut,
    EmployeeOut,
    KnowledgeDoc,
    KnowledgeHit,
    MessageOut,
    MetricsOut,
    NoteIn,
    NoteOut,
    Page,
    SuggestIn,
    TicketIn,
    TicketOut,
    TicketUpdate,
)
from corp_assistant.assistant import TicketDraft

router = APIRouter(prefix="/api/v1")


def _page(items, total: int, limit: int, offset: int) -> dict:
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/me", response_model=EmployeeOut)
def me(user: dict = Depends(current_user)):
    return user


@router.get("/employees", response_model=Page[EmployeeOut])
def employees(
    q: str = "",
    department: str = "",
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    user: dict = Depends(current_user),
):
    del user
    rows, total = store.list_employees(q=q, department=department, limit=limit, offset=offset)
    return _page(rows, total, limit, offset)


@router.get("/employees/{employee_id}", response_model=EmployeeOut)
def employee(employee_id: str, user: dict = Depends(current_user)):
    del user
    from corp_assistant.errors import AppError

    row = store.get_employee(employee_id)
    if row is None:
        raise AppError(404, "员工不存在")
    return row


@router.get("/departments", response_model=list[str])
def departments(user: dict = Depends(current_user)):
    del user
    return store.list_departments()


@router.get("/tickets", response_model=Page[TicketOut])
def tickets(
    status: str = "",
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    user: dict = Depends(current_user),
):
    rows, total = store.list_tickets(user, status=status, limit=limit, offset=offset)
    return _page(rows, total, limit, offset)


@router.post("/tickets", response_model=TicketOut)
def create_ticket(body: TicketIn, user: dict = Depends(current_user)):
    return store.create_ticket(
        requester_id=user["id"],
        title=body.title,
        description=body.description,
        category=body.category,
        priority=body.priority,
    )


@router.get("/tickets/{ticket_id}", response_model=TicketOut)
def ticket(ticket_id: int, user: dict = Depends(current_user)):
    from corp_assistant.errors import AppError

    row = store.get_ticket(ticket_id)
    if row is None or not store.can_view_ticket(user, row):
        raise AppError(404, "工单不存在")
    return row


@router.patch("/tickets/{ticket_id}", response_model=TicketOut)
def update_ticket(ticket_id: int, body: TicketUpdate, user: dict = Depends(current_user)):
    return store.update_ticket_status(user, ticket_id, body.status)


@router.post("/tickets/suggest", response_model=TicketDraft)
def suggest_ticket(body: SuggestIn, user: dict = Depends(current_user)):
    del user
    return assistant.suggest_ticket(body.text)

@router.post("/chat")
def chat(body: ChatIn, user: dict = Depends(current_user)):
    """流式对话。响应是 SSE：meta、reasoning、delta、tool、done、error。"""
    conversation_id, history = assistant.open_turn(user, body.message, body.conversation_id)
    agent = assistant.build_agent(user)

    async def generate():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def produce():
            try:
                for event in assistant.iter_chat_events(
                    user, body.message, conversation_id, history, agent
                ):
                    asyncio.run_coroutine_threadsafe(queue.put(event), loop).result()
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(
                    queue.put({"event": "error", "detail": f"模型调用失败: {exc}"}),
                    loop,
                ).result()
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop).result()

        threading.Thread(target=produce, daemon=True).start()
        while True:
            event = await queue.get()
            if event is None:
                break
            name = event.pop("event")
            yield assistant.encode_sse(name, event)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations", response_model=Page[ConversationOut])
def conversations(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    user: dict = Depends(current_user),
):
    rows, total = store.list_conversations(user, limit=limit, offset=offset)
    return _page(rows, total, limit, offset)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def messages(conversation_id: str, user: dict = Depends(current_user)):
    store.require_conversation(user, conversation_id)
    return store.list_messages(conversation_id)


@router.get("/knowledge", response_model=list[KnowledgeDoc])
def knowledge_docs(user: dict = Depends(current_user)):
    del user
    return knowledge.list_docs()


@router.get("/knowledge/search", response_model=Page[KnowledgeHit])
def knowledge_search(
    q: str = Query(min_length=1),
    limit: int = Query(3, ge=1, le=10),
    user: dict = Depends(current_user),
):
    del user
    hits = knowledge.search(q, limit=limit)
    return _page(hits, len(hits), limit, 0)


@router.post("/knowledge/reload", response_model=list[KnowledgeDoc])
def reload_knowledge(user: dict = Depends(current_user)):
    require_admin(user)
    knowledge.load()
    store.add_audit(user["id"], "knowledge.reload", "docs", str(knowledge.chunk_count()))
    return knowledge.list_docs()


@router.get("/knowledge/notes", response_model=Page[NoteOut])
def notes(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    user: dict = Depends(current_user),
):
    del user
    rows, total = store.list_notes(limit=limit, offset=offset)
    return _page(rows, total, limit, offset)


@router.post("/knowledge/notes", response_model=NoteOut)
def create_note(body: NoteIn, user: dict = Depends(current_user)):
    require_admin(user)
    return store.add_note(user["id"], body.title, body.body)


@router.get("/audit", response_model=Page[AuditOut])
def audit(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    user: dict = Depends(current_user),
):
    require_admin(user)
    rows, total = store.list_audit(limit=limit, offset=offset)
    return _page(rows, total, limit, offset)


@router.get("/metrics", response_model=MetricsOut)
def metrics(user: dict = Depends(current_user)):
    require_admin(user)
    data = store.counts()
    data["knowledge_chunks"] = knowledge.chunk_count()
    return data
