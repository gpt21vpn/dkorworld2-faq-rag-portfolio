# PECF11 — FAQ assistant architecture for DKORWORLD2

## What is reused

The site is not rebuilt from scratch. The base is the tested DKORWORLD2 Flask portfolio from DZ8/DZ9:

- real cases and portfolio blocks;
- quiz, contact form and SQLite/admin;
- Telegram notifications;
- booking/cancellation;
- Groq voice demo;
- 31 verified knowledge-base cards;
- existing short-term browser conversation history;
- existing Cloud4box + Caddy production path.

## What PECF11 adds

A separate service that follows the lesson architecture:

`site widget -> Flask /chat -> FastAPI -> embedding -> FAISS -> context -> LLM -> answer`

The FastAPI service:

1. loads the same 31 verified cards from `data/faqs.json`;
2. creates `text-embedding-3-small` vectors;
3. normalizes vectors and stores them in FAISS (`IndexFlatIP`, cosine similarity);
4. builds the retrieval query using the latest dialogue history for short follow-ups;
5. rejects unrelated requests below a configurable similarity threshold;
6. passes only retrieved facts + recent dialogue to the LLM;
7. returns answer + sources + scores to the site.

The old deterministic V12 knowledge layer remains only as a fallback if FastAPI is unavailable. This keeps the portfolio site usable while making FastAPI/FAISS the primary PECF11 path when `FAQ_RAG_URL` is configured.

## Why this architecture

- It follows the lesson requirement: real FAISS RAG + FastAPI + browser widget + dialogue memory.
- It does not throw away the stronger functionality already built in DZ8.
- The FastAPI service is internal in Docker and does not need a second public domain or permissive CORS.
- Existing Caddy configuration for `portfolio.dkor.space` can remain unchanged.
