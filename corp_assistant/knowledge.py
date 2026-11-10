import hashlib
import logging
import re
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import (
    BigInteger,
    Column,
    Identity,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    create_engine,
    delete,
    func,
    select,
    text,
)
from sqlalchemy.engine import Engine, URL
from pgvector.sqlalchemy import Vector

from corp_assistant.config import get_settings
from corp_assistant.errors import AppError
from corp_assistant import store

logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).resolve().parent / "knowledge_docs"
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
EMBEDDING_DIM = 512

metadata = MetaData()
knowledge_chunks = Table(
    "knowledge_chunks",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("source", String(255), nullable=False),
    Column("chunk_index", Integer, nullable=False),
    Column("title", String(255), nullable=False),
    Column("content", Text, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
    UniqueConstraint("source", "chunk_index", name="uq_knowledge_chunk"),
)

_engines: dict[str, Engine] = {}
_embedder = None


def _database_url(database: str) -> URL:
    settings = get_settings()
    return URL.create(
        "postgresql+psycopg",
        username=settings.pg_user,
        password=settings.pg_password,
        host=settings.pg_host,
        port=settings.pg_port,
        database=database,
    )


def _engine_for(database: str) -> Engine:
    url = _database_url(database)
    key = url.render_as_string(hide_password=False)
    engine = _engines.get(key)
    if engine is None:
        engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600)
        _engines[key] = engine
    return engine


def get_engine() -> Engine:
    return _engine_for(get_settings().pg_database)


@contextmanager
def get_conn():
    with get_engine().begin() as conn:
        yield conn


def _ensure_database() -> None:
    settings = get_settings()
    name = settings.pg_database
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise AppError(500, "PostgreSQL 库名只能包含字母、数字和下划线")
    admin = create_engine(
        _database_url("postgres"),
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": name},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()


def _ensure_schema() -> None:
    with get_conn() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    metadata.create_all(get_engine())
    with get_conn() as conn:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_hnsw "
                "ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)"
            )
        )


def _embedder_model():
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding

        logger.info("加载嵌入模型 %s", EMBEDDING_MODEL)
        _embedder = TextEmbedding(EMBEDDING_MODEL)
    return _embedder


def _passage_vectors(texts: list[str]) -> list[list[float]]:
    vectors = _embedder_model().passage_embed(texts)
    return [vector.tolist() for vector in vectors]


def _query_vector(query: str) -> list[float]:
    vector = next(iter(_embedder_model().query_embed([query])))
    return vector.tolist()


def _similarity_score(similarity: float) -> int:
    return max(0, min(1000, int(round(similarity * 1000))))


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _read_chunks() -> list[dict]:
    loaded: list[dict] = []
    if not DOCS_DIR.exists():
        return loaded
    for path in sorted(DOCS_DIR.glob("*.md")):
        text_body = path.read_text(encoding="utf-8").strip()
        if not text_body:
            continue
        title = text_body.splitlines()[0].lstrip("# ").strip() or path.stem
        parts = [part.strip() for part in re.split(r"\n(?=## )", text_body) if part.strip()]
        for index, part in enumerate(parts):
            loaded.append(
                {
                    "source": path.name,
                    "chunk_index": index,
                    "title": title,
                    "content": part,
                    "content_hash": hashlib.sha256(part.encode("utf-8")).hexdigest(),
                }
            )
    return loaded


def load() -> None:
    _ensure_database()
    _ensure_schema()
    desired = _read_chunks()
    with get_conn() as conn:
        rows = conn.execute(
            select(
                knowledge_chunks.c.source,
                knowledge_chunks.c.chunk_index,
                knowledge_chunks.c.content_hash,
            )
        ).mappings().all()
    existing = {(row["source"], row["chunk_index"]): row["content_hash"] for row in rows}
    desired_keys = {(chunk["source"], chunk["chunk_index"]) for chunk in desired}
    stale = [key for key in existing if key not in desired_keys]
    changed = [
        chunk
        for chunk in desired
        if existing.get((chunk["source"], chunk["chunk_index"])) != chunk["content_hash"]
    ]
    vectors = _passage_vectors([chunk["content"] for chunk in changed]) if changed else []
    with get_conn() as conn:
        for source, index in stale:
            conn.execute(
                delete(knowledge_chunks).where(
                    and_(
                        knowledge_chunks.c.source == source,
                        knowledge_chunks.c.chunk_index == index,
                    )
                )
            )
        for chunk in changed:
            conn.execute(
                delete(knowledge_chunks).where(
                    and_(
                        knowledge_chunks.c.source == chunk["source"],
                        knowledge_chunks.c.chunk_index == chunk["chunk_index"],
                    )
                )
            )
        if changed:
            conn.execute(
                knowledge_chunks.insert(),
                [{**chunk, "embedding": vector} for chunk, vector in zip(changed, vectors)],
            )
    if changed or stale:
        logger.info("制度段落已同步到 PostgreSQL，更新 %s 条，删除 %s 条", len(changed), len(stale))


def chunk_count() -> int:
    with get_conn() as conn:
        return int(conn.execute(select(func.count()).select_from(knowledge_chunks)).scalar_one())


def list_docs() -> list[dict[str, str]]:
    with get_conn() as conn:
        rows = conn.execute(
            select(knowledge_chunks.c.source, knowledge_chunks.c.title)
            .distinct()
            .order_by(knowledge_chunks.c.source)
        ).mappings().all()
    return [{"source": row["source"], "title": row["title"]} for row in rows]


def ping() -> None:
    with get_conn() as conn:
        conn.execute(text("SELECT 1"))


def search(query: str, limit: int = 3) -> list[dict]:
    query_vector = _query_vector(query)
    distance = knowledge_chunks.c.embedding.cosine_distance(query_vector)
    with get_conn() as conn:
        rows = conn.execute(
            select(
                knowledge_chunks.c.source,
                knowledge_chunks.c.title,
                knowledge_chunks.c.content,
                distance.label("distance"),
            )
            .order_by(distance)
            .limit(max(limit, 8))
        ).mappings().all()
    hits = [
        {
            "source": row["source"],
            "title": row["title"],
            "content": row["content"],
            "score": _similarity_score(1 - float(row["distance"])),
        }
        for row in rows
    ]
    notes, _total = store.list_notes(limit=100, offset=0)
    if notes:
        note_vectors = _passage_vectors([f"{note['title']}\n{note['body']}" for note in notes])
        for note, vector in zip(notes, note_vectors):
            hits.append(
                {
                    "source": f"note:{note['id']}",
                    "title": note["title"],
                    "content": note["body"],
                    "score": _similarity_score(_dot(query_vector, vector)),
                }
            )
    hits.sort(key=lambda item: item["score"], reverse=True)
    return hits[:limit]
