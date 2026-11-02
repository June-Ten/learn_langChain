from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class EmployeeOut(BaseModel):
    id: str
    name: str
    department: str
    title: str
    email: str
    role: str
    manager_id: str | None = None


class TicketOut(BaseModel):
    id: int
    title: str
    description: str
    category: str
    priority: str
    status: str
    requester_id: str
    requester_name: str
    requester_department: str
    created_at: str


class TicketIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=2000)
    category: Literal["it", "hr", "finance", "other"]
    priority: Literal["low", "medium", "high"] = "medium"


class TicketUpdate(BaseModel):
    status: Literal["open", "in_progress", "resolved"]


class SuggestIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None


class ToolCallOut(BaseModel):
    name: str
    args: dict


class ChatOut(BaseModel):
    conversation_id: str
    answer: str
    tools: list[ToolCallOut]


class ConversationOut(BaseModel):
    id: str
    user_id: str
    title: str
    created_at: str


class MessageOut(BaseModel):
    id: int
    conversation_id: str
    role: str
    content: str
    created_at: str


class KnowledgeHit(BaseModel):
    source: str
    title: str
    content: str
    score: int


class KnowledgeDoc(BaseModel):
    source: str
    title: str


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=4000)


class NoteOut(BaseModel):
    id: int
    title: str
    body: str
    author_id: str
    created_at: str


class AuditOut(BaseModel):
    id: int
    actor_id: str
    action: str
    resource: str
    detail: str
    created_at: str


class MetricsOut(BaseModel):
    employees: int
    open_tickets: int
    conversations: int
    knowledge_notes: int
    knowledge_chunks: int
