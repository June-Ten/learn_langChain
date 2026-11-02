import re
import uuid
from contextlib import contextmanager
from datetime import datetime

import pymysql
from pymysql.cursors import DictCursor

from corp_assistant.config import get_settings
from corp_assistant.errors import AppError

CATEGORIES = {"it", "hr", "finance", "other"}
PRIORITIES = {"low", "medium", "high"}
STATUSES = {"open", "in_progress", "resolved"}

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS employees (
        id VARCHAR(16) PRIMARY KEY,
        name VARCHAR(64) NOT NULL,
        department VARCHAR(64) NOT NULL,
        title VARCHAR(64) NOT NULL,
        email VARCHAR(128) NOT NULL,
        role VARCHAR(16) NOT NULL,
        manager_id VARCHAR(16) NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS tickets (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(80) NOT NULL,
        description TEXT NOT NULL,
        category VARCHAR(16) NOT NULL,
        priority VARCHAR(16) NOT NULL,
        status VARCHAR(16) NOT NULL,
        requester_id VARCHAR(16) NOT NULL,
        created_at VARCHAR(40) NOT NULL,
        CONSTRAINT fk_ticket_employee FOREIGN KEY (requester_id) REFERENCES employees (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS conversations (
        id VARCHAR(32) PRIMARY KEY,
        user_id VARCHAR(16) NOT NULL,
        title VARCHAR(40) NOT NULL,
        created_at VARCHAR(40) NOT NULL,
        CONSTRAINT fk_conversation_employee FOREIGN KEY (user_id) REFERENCES employees (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        conversation_id VARCHAR(32) NOT NULL,
        role VARCHAR(16) NOT NULL,
        content TEXT NOT NULL,
        created_at VARCHAR(40) NOT NULL,
        CONSTRAINT fk_message_conversation FOREIGN KEY (conversation_id) REFERENCES conversations (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        actor_id VARCHAR(16) NOT NULL,
        action VARCHAR(64) NOT NULL,
        resource VARCHAR(64) NOT NULL,
        detail VARCHAR(500) NOT NULL,
        created_at VARCHAR(40) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_notes (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(80) NOT NULL,
        body TEXT NOT NULL,
        author_id VARCHAR(16) NOT NULL,
        created_at VARCHAR(40) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]

EMPLOYEES = [
    ("E001", "李明", "信息技术部", "技术负责人", "liming@xinglan.example", "admin", None),
    ("E002", "王芳", "人力资源部", "人力资源总监", "wangfang@xinglan.example", "manager", "E001"),
    ("E003", "张伟", "财务部", "会计", "zhangwei@xinglan.example", "employee", "E005"),
    ("E004", "赵敏", "信息技术部", "软件工程师", "zhaomin@xinglan.example", "employee", "E001"),
    ("E005", "陈静", "财务部", "财务经理", "chenjing@xinglan.example", "manager", "E001"),
]

TICKET_FROM = "FROM tickets t JOIN employees e ON e.id = t.requester_id"
TICKET_SELECT = f"""
SELECT t.id, t.title, t.description, t.category, t.priority, t.status,
       t.requester_id, t.created_at,
       e.name AS requester_name, e.department AS requester_department
{TICKET_FROM}
"""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class _Row(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return dict.__getitem__(self, key)


class _Result:
    def __init__(self, cursor):
        self.lastrowid = cursor.lastrowid
        self._cursor = cursor

    def fetchone(self):
        row = self._cursor.fetchone()
        return _Row(row) if row else None

    def fetchall(self):
        return [_Row(row) for row in self._cursor.fetchall()]


class _Conn:
    def __init__(self, raw: pymysql.Connection):
        self.raw = raw

    def execute(self, sql: str, params: tuple | list | None = None):
        cursor = self.raw.cursor()
        cursor.execute(sql, params or ())
        return _Result(cursor)

    def executemany(self, sql: str, seq):
        cursor = self.raw.cursor()
        cursor.executemany(sql, seq)
        return _Result(cursor)


def _connect(database: str | None) -> pymysql.Connection:
    settings = get_settings()
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


def _ensure_database() -> None:
    settings = get_settings()
    name = settings.mysql_database
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise AppError(500, "MySQL 库名只能包含字母、数字和下划线")
    conn = _connect(None)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_conn():
    raw = _connect(get_settings().mysql_database)
    try:
        yield _Conn(raw)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def init_db() -> None:
    _ensure_database()
    with get_conn() as conn:
        for statement in SCHEMA:
            conn.execute(statement)


def seed() -> None:
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        if count:
            return
        conn.executemany(
            """
            INSERT INTO employees (id, name, department, title, email, role, manager_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            EMPLOYEES,
        )


def add_audit(actor_id: str, action: str, resource: str, detail: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO audit_logs (actor_id, action, resource, detail, created_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (actor_id, action, resource, detail[:500], now()),
        )


def get_employee(employee_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM employees WHERE id = %s", (employee_id,)).fetchone()
    return dict(row) if row else None


def list_employees(q: str, department: str, limit: int, offset: int) -> tuple[list[dict], int]:
    clauses: list[str] = []
    params: list[str] = []
    if q:
        clauses.append("(name LIKE %s OR id LIKE %s OR title LIKE %s)")
        like = f"%{q}%"
        params.extend([like, like, like])
    if department:
        clauses.append("department = %s")
        params.append(department)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM employees{where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM employees{where} ORDER BY id LIMIT %s OFFSET %s",
            [*params, limit, offset],
        ).fetchall()
    return [dict(row) for row in rows], total


def list_departments() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT department FROM employees ORDER BY department"
        ).fetchall()
    return [row[0] for row in rows]


def can_view_ticket(user: dict, ticket: dict) -> bool:
    if user["role"] == "admin":
        return True
    if user["role"] == "manager":
        return ticket["requester_department"] == user["department"]
    return ticket["requester_id"] == user["id"]


def get_ticket(ticket_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(TICKET_SELECT + " WHERE t.id = %s", (ticket_id,)).fetchone()
    return dict(row) if row else None


def list_tickets(user: dict, status: str, limit: int, offset: int) -> tuple[list[dict], int]:
    clauses: list[str] = []
    params: list[str | int] = []
    if user["role"] == "employee":
        clauses.append("t.requester_id = %s")
        params.append(user["id"])
    elif user["role"] == "manager":
        clauses.append("e.department = %s")
        params.append(user["department"])
    if status:
        if status not in STATUSES:
            raise AppError(400, "status 只能是 open、in_progress、resolved")
        clauses.append("t.status = %s")
        params.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) {TICKET_FROM}{where}", params).fetchone()[0]
        rows = conn.execute(
            TICKET_SELECT + where + " ORDER BY t.id DESC LIMIT %s OFFSET %s",
            [*params, limit, offset],
        ).fetchall()
    return [dict(row) for row in rows], total


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
        cursor = conn.execute(
            """
            INSERT INTO tickets
                (title, description, category, priority, status, requester_id, created_at)
            VALUES (%s, %s, %s, %s, 'open', %s, %s)
            """,
            (title.strip(), description.strip(), category, priority, requester_id, now()),
        )
        ticket_id = int(cursor.lastrowid)
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
        conn.execute("UPDATE tickets SET status = %s WHERE id = %s", (status, ticket_id))
    add_audit(user["id"], "ticket.update", str(ticket_id), status)
    updated = get_ticket(ticket_id)
    if updated is None:
        raise AppError(500, "工单更新后读取失败")
    return updated


def create_conversation(user_id: str, title: str) -> str:
    conversation_id = uuid.uuid4().hex
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO conversations (id, user_id, title, created_at)
            VALUES (%s, %s, %s, %s)
            """,
            (conversation_id, user_id, title[:40] or "新会话", now()),
        )
    return conversation_id


def get_conversation(conversation_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = %s",
            (conversation_id,),
        ).fetchone()
    return dict(row) if row else None


def require_conversation(user: dict, conversation_id: str) -> dict:
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise AppError(404, "会话不存在")
    if user["role"] != "admin" and conversation["user_id"] != user["id"]:
        raise AppError(404, "会话不存在")
    return conversation


def list_conversations(user: dict, limit: int, offset: int) -> tuple[list[dict], int]:
    clauses: list[str] = []
    params: list[str | int] = []
    if user["role"] != "admin":
        clauses.append("user_id = %s")
        params.append(user["id"])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM conversations{where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM conversations{where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            [*params, limit, offset],
        ).fetchall()
    return [dict(row) for row in rows], total


def add_message(conversation_id: str, role: str, content: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, created_at)
            VALUES (%s, %s, %s, %s)
            """,
            (conversation_id, role, content, now()),
        )


def recent_messages(conversation_id: str, limit: int = 8) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM messages
            WHERE conversation_id = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (conversation_id, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def list_messages(conversation_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = %s ORDER BY id",
            (conversation_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def add_note(author_id: str, title: str, body: str) -> dict:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO knowledge_notes (title, body, author_id, created_at)
            VALUES (%s, %s, %s, %s)
            """,
            (title.strip(), body.strip(), author_id, now()),
        )
        note_id = int(cursor.lastrowid)
    add_audit(author_id, "note.create", str(note_id), title.strip())
    note = get_note(note_id)
    if note is None:
        raise AppError(500, "笔记写入后读取失败")
    return note


def get_note(note_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM knowledge_notes WHERE id = %s", (note_id,)).fetchone()
    return dict(row) if row else None


def list_notes(limit: int, offset: int) -> tuple[list[dict], int]:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM knowledge_notes").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM knowledge_notes ORDER BY id DESC LIMIT %s OFFSET %s",
            (limit, offset),
        ).fetchall()
    return [dict(row) for row in rows], total


def list_audit(limit: int, offset: int) -> tuple[list[dict], int]:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT %s OFFSET %s",
            (limit, offset),
        ).fetchall()
    return [dict(row) for row in rows], total


def counts() -> dict[str, int]:
    with get_conn() as conn:
        employees = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        open_tickets = conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE status != 'resolved'"
        ).fetchone()[0]
        conversations = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        notes = conn.execute("SELECT COUNT(*) FROM knowledge_notes").fetchone()[0]
    return {
        "employees": employees,
        "open_tickets": open_tickets,
        "conversations": conversations,
        "knowledge_notes": notes,
    }
