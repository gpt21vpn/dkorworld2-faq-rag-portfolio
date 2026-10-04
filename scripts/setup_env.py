"""Create a persistent .env without exposing API keys in source control."""
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"

if ENV.exists():
    print(f".env already exists: {ENV}")
    raise SystemExit(0)

admin_password = secrets.token_urlsafe(14)
secret_key = secrets.token_urlsafe(48)
webhook_secret = secrets.token_urlsafe(24)

text = f"""# Generated locally. Keep private and do not commit.
SECRET_KEY={secret_key}
ADMIN_USERNAME=admin
ADMIN_PASSWORD={admin_password}
FLASK_DEBUG=0
PREFERRED_URL_SCHEME=https

OPENAI_API_KEY=
OPENAI_CHAT_MODEL=gpt-4.1-mini

GROQ_API_KEY=
GROQ_WHISPER_MODEL=whisper-large-v3-turbo

TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_CHAT_ID=

N8N_LEAD_WEBHOOK_URL=
N8N_WEBHOOK_SECRET={webhook_secret}
"""
ENV.write_text(text, encoding="utf-8")
try:
    ENV.chmod(0o600)
except OSError:
    pass

print(f"Created: {ENV}")
print("ADMIN_USERNAME=admin")
print(f"ADMIN_PASSWORD={admin_password}")
print("Now open .env and add only the API keys/channels you want to enable.")
