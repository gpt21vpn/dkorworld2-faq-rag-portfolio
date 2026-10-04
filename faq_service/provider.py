"""OpenAI client factory with optional outbound proxy support."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import OpenAI

PROJECT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_DIR / ".env", override=False)


@lru_cache(maxsize=1)
def get_openai_client() -> OpenAI:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    proxy = (os.getenv("OPENAI_PROXY") or os.getenv("PROXY_URL") or "").strip()
    if proxy:
        return OpenAI(
            api_key=api_key,
            http_client=httpx.Client(proxy=proxy, timeout=90.0),
        )
    return OpenAI(api_key=api_key)
