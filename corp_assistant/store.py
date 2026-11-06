import re
import uuid
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import (
    Column,
    ForeignKey,
    MetaData,
    String,
    Table,
    Text,
    and_,
    create_engine,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.engine import Engine, URL

from corp_assistant.config import get_settings
from corp_assistant.errors import AppError

CATEGORIES = {"it", "hr", "finance", "other"}
PRIORITIES = {"low", "medium", "high"}
STATUSES = {"open", "in_progress", "resolved"}

metadata = MetaData()

employees = Table(
    "employees",
    metadata,
    Column("id", String(16), primary_key=True),
    Column("name", String(64), nullable=False),
    Column("department", String(64), nullable=False),
    Column("title", String(64), nullable=False),
    Column("email", String(128), nullable=False),
    Column("role", String(16), nullable=False),
    Column("manager_id", String(16)),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_0900_ai_ci",
)

tickets = Table(
    "tickets",
    metadata,
    Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
    Column("title", String(80), nullable=False),
    Column("description", Text, nullable=False),
    Column("category", String(16), nullable=False),
    Column("priority", String(16), nullable=False),
    Column("status", String(16), nullable=False),
    Column("requester_id", String(16), ForeignKey("employees.id"), nullable=False),
    Column("created_at", String(40), nullable=False),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_0900_ai_ci",
)

conversations = Table(
    "conversations",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", String(16), ForeignKey("employees.id"), nullable=False),
    Column("title", String(40), nullable=False),
    Column("created_at", String(40), nullable=False),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_0900_ai_ci",
)

messages = Table(
    "messages",
    metadata,
    Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
    Column("conversation_id", String(32), ForeignKey("conversations.id"), nullable=False),
    Column("role", String(16), nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", String(40), nullable=False),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_0900_ai_ci",
)

audit_logs = Table(
    "audit_logs",
    metadata,
    Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
    Column("actor_id", String(16), nullable=False),
    Column("action", String(64), nullable=False),
    Column("resource", String(64), nullable=False),
    Column("detail", String(500), nullable=False),
    Column("created_at", String(40), nullable=False),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_0900_ai_ci",
)

knowledge_notes = Table(
    "knowledge_notes",
    metadata,
    Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
    Column("title", String(80), nullable=False),
    Column("body", Text, nullable=False),
    Column("author_id", String(16), nullable=False),
    Column("created_at", String(40), nullable=False),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_0900_ai_ci",
)

EMPLOYEES = [
    ("E001", "李明", "信息技术部", "技术负责人", "liming@xinglan.example", "admin", None),
    ("E002", "王芳", "人力资源部", "人力资源总监", "wangfang@xinglan.example", "manager", "E001"),
    ("E003", "张伟", "财务部", "会计", "zhangwei@xinglan.example", "employee", "E005"),
    ("E004", "赵敏", "信息技术部", "软件工程师", "zhaomin@xinglan.example", "employee", "E001"),
    ("E005", "陈静", "财务部", "财务经理", "chenjing@xinglan.example", "manager", "E001"),
]

_TICKET_FROM = tickets.join(employees, employees.c.id == tickets.c.requester_id)
_TICKET_SELECT = select(
    tickets.c.id,
    tickets.c.title,
    tickets.c.description,
    tickets.c.category,
    tickets.c.priority,
    tickets.c.status,
    tickets.c.requester_id,
    tickets.c.created_at,
    employees.c.name.label("requester_name"),
    employees.c.department.label("requester_department"),
).select_from(_TICKET_FROM)

_engines: dict[str, Engine] = {}


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _database_url(database: str | None) -> URL:
    settings = get_settings()
    return URL.create(
        "mysql+pymysql",
        username=settings.mysql_user,
        password=settings.mysql_password,
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=database,
        query={"charset": "utf8mb4"},
    )


def _engine_for(database: str | None) -> Engine:
    url = _database_url(database)
    key = url.render_as_string(hide_password=False)
    engine = _engines.get(key)
    if engine is None:
        engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600)
        _engines[key] = engine
    return engine


def get_engine() -> Engine:
    return _engine_for(get_settings().mysql_database)


def _ensure_database() -> None:
    settings = get_settings()
    name = settings.mysql_database
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise AppError(500, "MySQL 库名只能包含字母、数字和下划线")
    with _engine_for(None).begin() as conn:
        conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
        )


@contextmanager
def get_conn():
    with get_engine().begin() as conn:
        yield conn


def _rows(conn, stmt) -> list[dict]:
    return [dict(row) for row in conn.execute(stmt).mappings().all()]


def _first(conn, stmt) -> dict | None:
    row = conn.execute(stmt).mappings().first()
    return dict(row) if row else None


def init_db() -> None:
    _ensure_database()
    metadata.create_all(get_engine())


def seed() -> None:
    with get_conn() as conn:
        count = conn.execute(select(func.count()).select_from(employees)).scalar_one()
        if count:
            return
        conn.execute(
            employees.insert(),
            [
                {
                    "id": item[0],
                    "name": item[1],
                    "department": item[2],
                    "title": item[3],
                    "email": item[4],
                    "role": item[5],
                    "manager_id": item[6],
                }
                for item in EMPLOYEES
            ],
        )


def add_audit(actor_id: str, action: str, resource: str, detail: str) -> None:
    with get_conn() as conn:
        conn.execute(
            audit_logs.insert().values(
                actor_id=actor_id,
                action=action,
                resource=resource,
                detail=detail[:500],
                created_at=now(),
            )
        )


def get_employee(employee_id: str) -> dict | None:
    with get_conn() as conn:
        return _first(conn, select(employees).where(employees.c.id == employee_id))


def list_employees(q: str, department: str, limit: int, offset: int) -> tuple[list[dict], int]:
    filters = []
    if q:
        like = f"%{q}%"
        filters.append(
            or_(
                employees.c.name.like(like),
                employees.c.id.like(like),
                employees.c.title.like(like),
            )
        )
    if department:
        filters.append(employees.c.department == department)
    stmt = select(employees)
    count_stmt = select(func.count()).select_from(employees)
    if filters:
        condition = and_(*filters)
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    with get_conn() as conn:
        total = int(conn.execute(count_stmt).scalar_one())
        rows = _rows(conn, stmt.order_by(employees.c.id).limit(limit).offset(offset))
    return rows, total


def list_departments() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            select(employees.c.department).distinct().order_by(employees.c.department)
        ).scalars()
        return list(rows)


def can_view_ticket(user: dict, ticket: dict) -> bool:
    if user["role"] == "admin":
        return True
    if user["role"] == "manager":
        return ticket["requester_department"] == user["department"]
    return ticket["requester_id"] == user["id"]


def get_ticket(ticket_id: int) -> dict | None:
    with get_conn() as conn:
        return _first(conn, _TICKET_SELECT.where(tickets.c.id == ticket_id))


def list_tickets(user: dict, status: str, limit: int, offset: int) -> tuple[list[dict], int]:
    filters = []
    if user["role"] == "employee":
        filters.append(tickets.c.requester_id == user["id"])
    elif user["role"] == "manager":
        filters.append(employees.c.department == user["department"])
    if status:
        if status not in STATUSES:
            raise AppError(400, "status 只能是 open、in_progress、resolved")
        filters.append(tickets.c.status == status)
    stmt = _TICKET_SELECT
    count_stmt = select(func.count()).select_from(_TICKET_FROM)
    if filters:
        condition = and_(*filters)
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    with get_conn() as conn:
        total = int(conn.execute(count_stmt).scalar_one())
        rows = _rows(conn, stmt.order_by(tickets.c.id.desc()).limit(limit).offset(offset))
    return rows, total


def create_ticket(
    requester_id: str,
    title: str,
    description: str,
    category: str,
    priority: str,
) -> dict:
    if category not in CATEGORIES:
        raise AppError(400, "category 只能是 it、hr、finance、other")
    if priority not in PRIORITIES:
        raise AppError(400, "priority 只能是 low、medium、high")
    with get_conn() as conn:
        result = conn.execute(
            tickets.insert().values(
                title=title.strip(),
                description=description.strip(),
                category=category,
                priority=priority,
                status="open",
                requester_id=requester_id,
                created_at=now(),
            )
        )
        ticket_id = int(result.inserted_primary_key[0])
    add_audit(requester_id, "ticket.create", str(ticket_id), title.strip())
    ticket = get_ticket(ticket_id)
    if ticket is None:
        raise AppError(500, "工单写入后读取失败")
    return ticket


def update_ticket_status(user: dict, ticket_id: int, status: str) -> dict:
    if status not in STATUSES:
        raise AppError(400, "status 只能是 open、in_progress、resolved")
    if user["role"] not in {"manager", "admin"}:
        raise AppError(403, "只有主管或管理员可以更新工单")
    ticket = get_ticket(ticket_id)
    if ticket is None or not can_view_ticket(user, ticket):
        raise AppError(404, "工单不存在")
    with get_conn() as conn:
        conn.execute(update(tickets).where(tickets.c.id == ticket_id).values(status=status))
    add_audit(user["id"], "ticket.update", str(ticket_id), status)
    updated = get_ticket(ticket_id)
    if updated is None:
        raise AppError(500, "工单更新后读取失败")
    return updated


def create_conversation(user_id: str, title: str) -> str:
    conversation_id = uuid.uuid4().hex
    with get_conn() as conn:
        conn.execute(
            conversations.insert().values(
                id=conversation_id,
                user_id=user_id,
                title=title[:40] or "新会话",
                created_at=now(),
            )
        )
    return conversation_id


def get_conversation(conversation_id: str) -> dict | None:
    with get_conn() as conn:
        return _first(conn, select(conversations).where(conversations.c.id == conversation_id))


def require_conversation(user: dict, conversation_id: str) -> dict:
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise AppError(404, "会话不存在")
    if user["role"] != "admin" and conversation["user_id"] != user["id"]:
        raise AppError(404, "会话不存在")
    return conversation


def list_conversations(user: dict, limit: int, offset: int) -> tuple[list[dict], int]:
    stmt = select(conversations)
    count_stmt = select(func.count()).select_from(conversations)
    if user["role"] != "admin":
        condition = conversations.c.user_id == user["id"]
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    with get_conn() as conn:
        total = int(conn.execute(count_stmt).scalar_one())
        rows = _rows(
            conn,
            stmt.order_by(conversations.c.created_at.desc()).limit(limit).offset(offset),
        )
    return rows, total


def add_message(conversation_id: str, role: str, content: str) -> None:
    with get_conn() as conn:
        conn.execute(
            messages.insert().values(
                conversation_id=conversation_id,
                role=role,
                content=content,
                created_at=now(),
            )
        )


def recent_messages(conversation_id: str, limit: int = 8) -> list[dict]:
    with get_conn() as conn:
        rows = _rows(
            conn,
            select(messages)
            .where(messages.c.conversation_id == conversation_id)
            .order_by(messages.c.id.desc())
            .limit(limit),
        )
    return list(reversed(rows))


def list_messages(conversation_id: str) -> list[dict]:
    with get_conn() as conn:
        return _rows(
            conn,
            select(messages)
            .where(messages.c.conversation_id == conversation_id)
            .order_by(messages.c.id),
        )


def add_note(author_id: str, title: str, body: str) -> dict:
    with get_conn() as conn:
        result = conn.execute(
            knowledge_notes.insert().values(
                title=title.strip(),
                body=body.strip(),
                author_id=author_id,
                created_at=now(),
            )
        )
        note_id = int(result.inserted_primary_key[0])
    add_audit(author_id, "note.create", str(note_id), title.strip())
    note = get_note(note_id)
    if note is None:
        raise AppError(500, "笔记写入后读取失败")
    return note


def get_note(note_id: int) -> dict | None:
    with get_conn() as conn:
        return _first(conn, select(knowledge_notes).where(knowledge_notes.c.id == note_id))


def list_notes(limit: int, offset: int) -> tuple[list[dict], int]:
    with get_conn() as conn:
        total = int(conn.execute(select(func.count()).select_from(knowledge_notes)).scalar_one())
        rows = _rows(
            conn,
            select(knowledge_notes).order_by(knowledge_notes.c.id.desc()).limit(limit).offset(offset),
        )
    return rows, total


def list_audit(limit: int, offset: int) -> tuple[list[dict], int]:
    with get_conn() as conn:
        total = int(conn.execute(select(func.count()).select_from(audit_logs)).scalar_one())
        rows = _rows(
            conn,
            select(audit_logs).order_by(audit_logs.c.id.desc()).limit(limit).offset(offset),
        )
    return rows, total


def counts() -> dict[str, int]:
    with get_conn() as conn:
        employee_count = int(conn.execute(select(func.count()).select_from(employees)).scalar_one())
        open_tickets = int(
            conn.execute(
                select(func.count()).select_from(tickets).where(tickets.c.status != "resolved")
            ).scalar_one()
        )
        conversation_count = int(
            conn.execute(select(func.count()).select_from(conversations)).scalar_one()
        )
        note_count = int(conn.execute(select(func.count()).select_from(knowledge_notes)).scalar_one())
    return {
        "employees": employee_count,
        "open_tickets": open_tickets,
        "conversations": conversation_count,
        "knowledge_notes": note_count,
    }
