"""
Конфигурация Flask-приложения DKORWORLD2.

Приоритет настроек:
1) переменные окружения;
2) .env рядом с app.py;
3) локальный instance/runtime_secrets.env для автоматически созданных
   SECRET_KEY и ADMIN_PASSWORD.

Таким образом, даже без .env сессии и CSRF больше не меняются при каждом
перезапуске. Для публичного сервера всё равно рекомендуется явный .env.
"""
from __future__ import annotations

import os
import secrets
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
RUNTIME_SECRETS_PATH = INSTANCE_DIR / "runtime_secrets.env"

# Сначала читаем пользовательский .env.
load_dotenv(BASE_DIR / ".env", override=False)

# Затем локальные автоматически созданные секреты.
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
if RUNTIME_SECRETS_PATH.exists():
    load_dotenv(RUNTIME_SECRETS_PATH, override=False)

_GENERATED_ADMIN_PASSWORD = False
_GENERATED_SECRET_KEY = False

runtime_values: dict[str, str] = {}

if not os.environ.get("SECRET_KEY"):
    os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
    runtime_values["SECRET_KEY"] = os.environ["SECRET_KEY"]
    _GENERATED_SECRET_KEY = True

if not os.environ.get("ADMIN_PASSWORD"):
    os.environ["ADMIN_PASSWORD"] = secrets.token_urlsafe(12)
    runtime_values["ADMIN_PASSWORD"] = os.environ["ADMIN_PASSWORD"]
    _GENERATED_ADMIN_PASSWORD = True

# Если одного секрета не хватало, сохраняем полный комплект, не затирая уже
# существующие значения из runtime-файла.
if runtime_values:
    existing = {}
    if RUNTIME_SECRETS_PATH.exists():
        for line in RUNTIME_SECRETS_PATH.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                existing[key.strip()] = value.strip()
    existing.update(runtime_values)
    RUNTIME_SECRETS_PATH.write_text(
        "# Generated locally. Do not commit this file.\n"
        + "\n".join(f"{k}={v}" for k, v in existing.items())
        + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(RUNTIME_SECRETS_PATH, 0o600)
    except OSError:
        pass


class Config:
    """Базовая конфигурация сайта."""

    SECRET_KEY = os.environ["SECRET_KEY"]

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or "sqlite:///site.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)

    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME") or "admin"
    ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]

    # AI chat: без ключа работает детерминированная локальная KB,
    # с OPENAI_API_KEY включается RAG + LLM.
    # ---- Запись на консультацию ----
    # Время всегда московское (МСК = UTC+3, без переходов на летнее время),
    # поэтому храним и считаем слоты в наивном MSK, а не в локальной зоне сервера.
    BOOKING_TZ_LABEL = 'МСК'
    BOOKING_TZ_OFFSET_HOURS = int(os.environ.get('BOOKING_TZ_OFFSET_HOURS', '3'))
    BOOKING_FIRST_HOUR = int(os.environ.get('BOOKING_FIRST_HOUR', '9'))          # первый слот 09:00-10:00
    BOOKING_LAST_HOUR = int(os.environ.get('BOOKING_LAST_HOUR', '20'))          # последний слот 20:00-21:00 -> ровно 12 слотов
    BOOKING_SLOT_MINUTES = int(os.environ.get('BOOKING_SLOT_MINUTES', '60'))
    BOOKING_DAYS_AHEAD = int(os.environ.get('BOOKING_DAYS_AHEAD', '14'))         # горизонт показа
    BOOKING_MIN_LEAD_HOURS = float(os.environ.get('BOOKING_MIN_LEAD_HOURS', '2'))      # нельзя записаться впритык
    BOOKING_MAX_PER_CLIENT_PER_DAY = int(os.environ.get('BOOKING_MAX_PER_CLIENT_PER_DAY', '2'))
    # Общий предел активных будущих записей на одного клиента.
    # Дневного лимита мало: 2 на вторник + 2 на среду — это уже 4 брони.
    BOOKING_MAX_ACTIVE_PER_CLIENT = int(os.environ.get('BOOKING_MAX_ACTIVE_PER_CLIENT', '2'))

    CHAT_ENABLED = True
    RAG_ENABLED = bool(os.environ.get("OPENAI_API_KEY"))
    OPENAI_CHAT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4.1-mini")

    # PECF11: отдельный FastAPI + FAISS FAQ-service. Если URL не задан,
    # сайт продолжает работать на проверенном локальном KB/RAG из ДЗ8.
    FAQ_RAG_URL = (os.environ.get("FAQ_RAG_URL") or "").rstrip("/")
    FAQ_RAG_TIMEOUT = float(os.environ.get("FAQ_RAG_TIMEOUT", "45"))

    # Voice STT via Groq. Без ключа браузер использует встроенное распознавание.
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
    GROQ_ENABLED = bool(GROQ_API_KEY)
    GROQ_WHISPER_MODEL = os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")

    # Канал 1: Telegram.
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    TELEGRAM_ADMIN_CHAT_ID = os.environ.get("TELEGRAM_ADMIN_CHAT_ID")

    # Канал 2: резервный webhook в n8n.
    N8N_LEAD_WEBHOOK_URL = os.environ.get("N8N_LEAD_WEBHOOK_URL")
    N8N_WEBHOOK_SECRET = os.environ.get("N8N_WEBHOOK_SECRET")

    # Reverse proxy / deployment.
    PREFERRED_URL_SCHEME = os.environ.get("PREFERRED_URL_SCHEME", "https")
    DEBUG = os.environ.get("FLASK_DEBUG", "0").lower() in {"1", "true", "yes", "on"}


def startup_notice() -> list[str]:
    lines: list[str] = []

    if _GENERATED_ADMIN_PASSWORD or _GENERATED_SECRET_KEY:
        lines.append(
            "Persistent runtime secrets created in instance/runtime_secrets.env. "
            "They survive restarts; create .env before public deployment."
        )
    if _GENERATED_ADMIN_PASSWORD:
        lines.append(
            f"ADMIN: login '{Config.ADMIN_USERNAME}', password '{Config.ADMIN_PASSWORD}' "
            "(saved locally in instance/runtime_secrets.env)"
        )

    if not Config.RAG_ENABLED:
        lines.append("OPENAI_API_KEY not set: chat uses local KB fallback; RAG generation is disabled")
    if not Config.FAQ_RAG_URL:
        lines.append("FAQ_RAG_URL not set: PECF11 FastAPI/FAISS service is not connected; local chat fallback remains active")
    if not Config.GROQ_ENABLED:
        lines.append("GROQ_API_KEY not set: voice demo uses browser speech recognition when available")
    if not (Config.TELEGRAM_BOT_TOKEN and Config.TELEGRAM_ADMIN_CHAT_ID):
        lines.append("Telegram lead notification not configured: leads are still saved in SQLite/admin")
    if not Config.N8N_LEAD_WEBHOOK_URL:
        lines.append("n8n backup webhook not configured: SQLite/Telegram path continues to work")
    return lines
