"""FastAPI FAQ assistant: memory + FAISS retrieval + constrained LLM generation."""
from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .provider import get_openai_client
from .rag_index import (
    EMBEDDING_MODEL,
    INDEX_PATH,
    META_PATH,
    MIN_SCORE,
    ensure_index,
    search_similar,
)

CHAT_MODEL = os.getenv("FAQ_CHAT_MODEL") or os.getenv("OPENAI_CHAT_MODEL") or "gpt-4.1-mini"
REFUSAL = (
    "В базе знаний DKORWORLD2 нет точного ответа на этот вопрос. "
    "Можно спросить про AI-ботов, AI-видео, сайты, цены, сроки или реальные кейсы. "
    "Для своей задачи можно пройти квиз или написать Дмитрию в Telegram @dimaseo2."
)
REFUSAL_TOKEN = "__NO_KB_MATCH__"

app = FastAPI(title="DKORWORLD2 FAQ RAG", version="13.4-faiss-fastapi")


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=8)
    history: List[ChatTurn] = Field(default_factory=list)


class Source(BaseModel):
    id: str = ""
    title: str = ""
    source: str = ""
    score: float = 0.0


class ChatResponse(BaseModel):
    answer: str
    sources: List[Source] = Field(default_factory=list)
    context: List[Dict[str, Any]] = Field(default_factory=list)
    mode: str
    resolved_query: str


def _history_dicts(req: ChatRequest) -> List[Dict[str, str]]:
    return [{"role": x.role, "content": x.content} for x in req.history[-8:]]


@app.get("/health")
def health() -> Dict[str, Any]:
    try:
        index, metadata = ensure_index()
        return {
            "status": "ok",
            "version": "13.4-faiss-fastapi",
            "vector_store": "FAISS",
            "index_items": int(len(metadata)),
            "index_dim": int(index.d),
            "memory": True,
            "chat_model": CHAT_MODEL,
            "embedding_model": EMBEDDING_MODEL,
            "min_score": MIN_SCORE,
            "index_file": INDEX_PATH.name,
            "metadata_file": META_PATH.name,
        }
    except Exception as exc:
        return {
            "status": "degraded",
            "version": "13.4-faiss-fastapi",
            "vector_store": "FAISS",
            "memory": True,
            "error": str(exc),
        }


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is empty")

    history = _history_dicts(req)
    try:
        resolved_query, similar_items = search_similar(
            message,
            history=history,
            top_k=req.top_k,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"RAG retrieval unavailable: {exc}") from exc

    if not similar_items:
        return ChatResponse(
            answer=REFUSAL,
            sources=[],
            context=[],
            mode="refusal",
            resolved_query=resolved_query,
        )

    context_blocks = []
    for item in similar_items:
        context_blocks.append(
            "\n".join(
                [
                    f"ID: {item.get('id', '')}",
                    f"Тема: {item.get('title', '')}",
                    f"Вопрос: {item.get('question', '')}",
                    f"Факт/ответ: {item.get('answer', '')}",
                    f"Источник: {item.get('source', 'База знаний DKORWORLD2')}",
                ]
            )
        )
    context_text = "\n\n---\n\n".join(context_blocks)

    system_prompt = (
        "Ты AI-консультант сайта DKORWORLD2. Отвечай на русском языке, кратко и по делу. "
        "Используй ТОЛЬКО факты из блока КОНТЕКСТ. Не добавляй знания из памяти модели. "
        "Не придумывай цены, сроки, проценты, клиентов, функции, кейсы, гарантии или юридические обещания. "
        f"Если контекст НЕ содержит прямого факта, который отвечает на текущий вопрос, верни РОВНО "
        f"{REFUSAL_TOKEN} без пояснений. Не отвечай общими знаниями модели и не делай предположений. "
        "Учитывай историю диалога только для понимания, о чём говорит пользователь. "
        "Если пользователь просит несколько услуг или параметров, ответь на все части только теми фактами, "
        "которые реально присутствуют в контексте."
    )

    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    current_norm = " ".join(message.lower().split())
    for row in history[-6:]:
        role = row.get("role", "")
        content = row.get("content", "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if role == "user" and " ".join(content.lower().split()) == current_norm:
            continue
        messages.append({"role": role, "content": content[:1600]})

    messages.append(
        {
            "role": "user",
            "content": (
                f"КОНТЕКСТ:\n{context_text}\n\n"
                f"УТОЧНЁННЫЙ ЗАПРОС ДЛЯ ПОИСКА:\n{resolved_query}\n\n"
                f"ТЕКУЩАЯ РЕПЛИКА:\n{message}"
            ),
        }
    )

    try:
        client = get_openai_client()
        completion = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            temperature=0.1,
            max_tokens=450,
        )
        answer = (completion.choices[0].message.content or "").strip()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"LLM generation unavailable: {exc}") from exc

    refusal_markers = (
        "в базе нет точного ответа",
        "в базе знаний нет точного ответа",
        "в контексте нет точного ответа",
        "нет точной информации в базе",
        "нет точной информации в контексте",
    )
    answer_low = answer.lower()
    if (
        not answer
        or answer.strip() == REFUSAL_TOKEN
        or any(marker in answer_low for marker in refusal_markers)
    ):
        return ChatResponse(
            answer=REFUSAL,
            sources=[],
            context=similar_items,
            mode="refusal",
            resolved_query=resolved_query,
        )

    public_sources = [
        Source(
            id=str(item.get("id") or ""),
            title=str(item.get("title") or item.get("question") or "База знаний"),
            source=str(item.get("source") or "База знаний DKORWORLD2"),
            score=float(item.get("score") or 0.0),
        )
        for item in similar_items[:3]
    ]

    return ChatResponse(
        answer=answer,
        sources=public_sources,
        context=similar_items,
        mode="rag_faiss",
        resolved_query=resolved_query,
    )
