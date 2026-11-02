import re
from pathlib import Path

from corp_assistant import store

DOCS_DIR = Path(__file__).resolve().parent / "knowledge_docs"
_chunks: list[dict[str, str]] = []


def load() -> None:
    global _chunks
    loaded: list[dict[str, str]] = []
    if DOCS_DIR.exists():
        for path in sorted(DOCS_DIR.glob("*.md")):
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            title = text.splitlines()[0].lstrip("# ").strip() or path.stem
            parts = [part.strip() for part in re.split(r"\n(?=## )", text) if part.strip()]
            for part in parts:
                loaded.append({"source": path.name, "title": title, "content": part})
    _chunks = loaded


def chunk_count() -> int:
    return len(_chunks)


def list_docs() -> list[dict[str, str]]:
    seen: list[dict[str, str]] = []
    for chunk in _chunks:
        if any(item["source"] == chunk["source"] for item in seen):
            continue
        seen.append({"source": chunk["source"], "title": chunk["title"]})
    return seen


def _tokens(query: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", query)
    tokens: list[str] = []
    for word in words:
        if re.fullmatch(r"[A-Za-z0-9]+", word):
            tokens.append(word.lower())
            continue
        if len(word) <= 4:
            tokens.append(word)
            continue
        tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
    return tokens


def _score(query: str, text: str) -> int:
    haystack = text.lower()
    return sum(len(token) for token in _tokens(query) if token.lower() in haystack)


def search(query: str, limit: int = 3) -> list[dict]:
    candidates = [dict(chunk) for chunk in _chunks]
    notes, _total = store.list_notes(limit=100, offset=0)
    for note in notes:
        candidates.append(
            {
                "source": f"note:{note['id']}",
                "title": note["title"],
                "content": note["body"],
            }
        )
    ranked = []
    for item in candidates:
        score = _score(query, f"{item['title']}\n{item['content']}")
        if score:
            ranked.append({**item, "score": score})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:limit]
