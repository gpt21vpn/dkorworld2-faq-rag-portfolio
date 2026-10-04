"""FAISS index loading and semantic retrieval for DKORWORLD2 FAQ cards.

The site already has a deterministic local knowledge layer.  This module is the
separate *real vector RAG* required by the PECF11 lesson: OpenAI embeddings ->
FAISS cosine search -> source metadata.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import faiss  # type: ignore
import numpy as np

from .provider import get_openai_client

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_PATH = Path(os.getenv("FAQ_DATA_PATH") or PROJECT_DIR / "data" / "faqs.json")
INDEX_DIR = Path(os.getenv("FAQ_INDEX_DIR") or Path(__file__).resolve().parent / "index")
INDEX_PATH = INDEX_DIR / "faiss_index.bin"
META_PATH = INDEX_DIR / "faqs_metadata.npy"

EMBEDDING_MODEL = os.getenv("FAQ_EMBEDDING_MODEL", "text-embedding-3-small")
MIN_SCORE = float(os.getenv("FAQ_MIN_SCORE", "0.30"))

_index: Any | None = None
_metadata: np.ndarray | None = None


def load_cards(path: Path = DATA_PATH) -> List[Dict[str, Any]]:
    """Load verified DKORWORLD2 KB cards and validate mandatory fields."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("data/faqs.json must contain a JSON list")

    cards: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if not question or not answer:
            continue
        cards.append(dict(item))
    if not cards:
        raise RuntimeError("No valid knowledge-base cards found")
    return cards


def card_to_embedding_text(card: Dict[str, Any]) -> str:
    """Build the text embedded into FAISS while keeping fact + price + term together."""
    keywords = card.get("keywords") or []
    tags = card.get("tags") or []
    parts = [
        f"Тема: {card.get('title') or card.get('question') or ''}",
        f"Вопрос: {card.get('question') or ''}",
        f"Ответ: {card.get('answer') or ''}",
    ]
    if keywords:
        parts.append("Ключевые формулировки: " + ", ".join(map(str, keywords)))
    if tags:
        parts.append("Теги: " + ", ".join(map(str, tags)))
    return "\n".join(parts)


def embed_texts(texts: Sequence[str]) -> np.ndarray:
    """Create normalized embeddings so IndexFlatIP behaves as cosine similarity."""
    client = get_openai_client()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=list(texts))
    vectors = np.asarray([row.embedding for row in response.data], dtype="float32")
    faiss.normalize_L2(vectors)
    return vectors


def build_index() -> Tuple[Any, np.ndarray]:
    """Build FAISS index from the current verified 31-card DKORWORLD2 knowledge base."""
    cards = load_cards()
    texts = [card_to_embedding_text(card) for card in cards]
    vectors = embed_texts(texts)

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)

    metadata = np.asarray(
        [
            {
                "id": card.get("id", ""),
                "title": card.get("title") or card.get("question") or "База знаний",
                "question": card.get("question", ""),
                "answer": card.get("answer", ""),
                "source": card.get("source", "База знаний DKORWORLD2"),
            }
            for card in cards
        ],
        dtype=object,
    )

    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    # On Windows, faiss.write_index() may fail when the project path contains
    # non-ASCII/Cyrillic characters because the native FAISS writer receives
    # a narrow-char path. Serialize in memory and let Python write the bytes;
    # Python file I/O handles Unicode paths correctly.
    serialized = faiss.serialize_index(index)
    with INDEX_PATH.open("wb") as fh:
        fh.write(serialized.tobytes())

    np.save(META_PATH, metadata)
    return index, metadata


def load_index() -> Tuple[Any, np.ndarray]:
    """Load an existing index or build it on first start when a key is available."""
    if not INDEX_PATH.exists() or not META_PATH.exists():
        return build_index()

    # Read through Python so Windows Unicode/Cyrillic project paths are safe.
    raw = np.frombuffer(INDEX_PATH.read_bytes(), dtype="uint8")
    index = faiss.deserialize_index(raw)
    return index, np.load(META_PATH, allow_pickle=True)


def ensure_index() -> Tuple[Any, np.ndarray]:
    global _index, _metadata
    if _index is None or _metadata is None:
        _index, _metadata = load_index()
    return _index, _metadata


def reset_index_cache() -> None:
    global _index, _metadata
    _index = None
    _metadata = None


def _clean_history(history: Iterable[Dict[str, str]] | None, current: str) -> List[Dict[str, str]]:
    cleaned: List[Dict[str, str]] = []
    current_norm = " ".join((current or "").lower().split())
    for item in list(history or [])[-8:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if role == "user" and " ".join(content.lower().split()) == current_norm:
            continue
        cleaned.append({"role": role, "content": content[:1600]})
    return cleaned


def build_retrieval_query(message: str, history: Iterable[Dict[str, str]] | None = None) -> str:
    """Add recent user context only for genuine follow-ups, not for a new standalone request."""
    message = (message or "").strip()
    if not message:
        return message

    words = message.split()
    lower = message.lower()

    # Normalize generic capability questions before embedding, but still send them
    # through FAISS. This keeps the lesson's vector-RAG path while making natural
    # phrases like "а что ещё можешь?" land on the overview card.
    capability_phrases = (
        "что еще можешь", "что ещё можешь",
        "а что еще можешь", "а что ещё можешь",
        "что еще умеешь", "что ещё умеешь",
        "что ты можешь", "что вы можете",
    )
    if any(phrase in lower for phrase in capability_phrases):
        return f"Чем занимается DKORWORLD2? Что ты можешь? {message}".strip()

    # Terse fragments like "лендинг", "а бот?", "сроки?" depend on the previous turn.
    very_short = len(words) <= 2
    conversational_start = lower.startswith(("а ", "и ", "тогда "))
    referential = any(
        token in lower.split()
        for token in ("это", "этот", "эта", "эти", "такой", "такая", "он", "она", "там")
    )

    # "Сколько это будет стоить?" / "Какие сроки?" are follow-ups only when
    # the current message does not already name a concrete subject.
    explicit_subject_markers = (
        "бот", "чат-бот", "ассистент", "лендинг", "сайт",
        "видео", "ролик", "квиз", "запис", "консультац",
        "autoneuro", "сто", "автомой",
    )
    has_explicit_subject = any(marker in lower for marker in explicit_subject_markers)
    generic_question = (
        lower.startswith(("сколько ", "какие сроки", "какой срок", "какая цена", "какие цены"))
        and not has_explicit_subject
    )

    followup = very_short or conversational_start or referential or generic_question
    if not followup:
        return message

    cleaned = _clean_history(history, message)
    previous_users = [row["content"] for row in cleaned if row["role"] == "user"][-2:]
    return "\n".join(previous_users + [message]).strip()


def search_similar(
    message: str,
    history: Iterable[Dict[str, str]] | None = None,
    top_k: int = 4,
    min_score: float | None = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Semantic search over FAISS with a refusal threshold for unrelated questions."""
    index, metadata = ensure_index()
    query = build_retrieval_query(message, history)
    query_vec = embed_texts([query])

    k = max(1, min(int(top_k or 4), 8, len(metadata)))
    scores, indices = index.search(query_vec, k)
    threshold = MIN_SCORE if min_score is None else float(min_score)

    results: List[Dict[str, Any]] = []
    for idx, score in zip(indices[0], scores[0]):
        if idx < 0 or idx >= len(metadata):
            continue
        score = float(score)
        if score < threshold:
            continue
        item = dict(metadata[idx])
        item["score"] = round(score, 4)
        results.append(item)
    return query, results
