# DKORWORLD2 — PECF11 FAQ RAG V13.4

Портфолио-проект DKORWORLD2 для задания PECF11: личный Flask-сайт с FAQ-ассистентом на **FastAPI + FAISS + dialogue memory + OpenAI**, голосовым вводом через Groq, квизом, записью на консультацию и Telegram-уведомлениями.

Рабочий сайт: `https://portfolio.dkor.space`

## Архитектура

```text
Browser
  ↓
Flask site (dkorworld2-site :8008)
  ↓
FastAPI FAQ service (dkorworld2-faq-rag :8011)
  ↓
FAISS (31 FAQ-карточка)
  ↓
OpenAI embeddings + chat model
```

FastAPI-сервис доступен только во внутренней Docker-сети. Публично наружу выходит только Flask-сайт через Caddy.

Основной FAQ-контур:
- embeddings: `text-embedding-3-small`;
- chat model: `gpt-4.1-mini`;
- vector store: FAISS;
- база знаний: 31 карточка из `data/faqs.json`;
- память короткого диалога;
- отказ на вопросы вне базы знаний;
- режим ответа в логах: `rag_faiss` / `refusal`.

## Что реализовано

- FAQ-ассистент отвечает только по базе знаний DKORWORLD2.
- FAISS-поиск по 31 карточке.
- Память продолжений диалога: например, после вопроса о боте фраза «А сколько это будет стоить?» сохраняет контекст.
- Отказ на нерелевантные вопросы.
- Чат-виджет на сайте.
- Голосовой ввод: серверная транскрипция через Groq Whisper.
- Квиз с сохранением заявки в SQLite и отправкой уведомления в Telegram.
- Запись на консультацию с созданием `.ics` и безопасной отменой.
- Telegram-уведомления о новой записи и отмене.
- Health endpoint без раскрытия секретов.
- Docker Compose из двух сервисов.
- Production-деплой на Cloud4box через Caddy.

## Проверенный результат V13.4

Локально и в production проверены:

```text
FAISS index_items: 31
FAISS index_dim: 1536
memory: true
vector_store: FAISS
version: 13.4-faiss-fastapi
smoke tests: TOTAL FAILED: 0
```

Также вручную проверены:
- цена и сроки лендинга;
- цена и сроки AI-бота;
- AI-проморолик;
- реальные кейсы;
- отказ на вопрос про погоду;
- отказ на услуги вне базы;
- память диалога;
- Voice → Groq → RAG;
- квиз → SQLite → Telegram;
- запись → Telegram;
- отмена записи → Telegram.

Измеряемые бизнес-метрики вроде «снижение времени поддержки на X%» не заявляются без отдельного периода измерений. В README фиксируются только реально проверенные технические результаты.

## Первый запуск после клонирования

### 1. Создать `.env`

Скопировать шаблон:

```powershell
Copy-Item .env.example .env
```

Заполнить необходимые значения.

Минимально для полного FAQ-RAG:

```env
OPENAI_API_KEY=
OPENAI_CHAT_MODEL=gpt-4.1-mini

FAQ_CHAT_MODEL=gpt-4.1-mini
FAQ_EMBEDDING_MODEL=text-embedding-3-small
FAQ_MIN_SCORE=0.30
FAQ_RAG_TIMEOUT=45
```

Дополнительно:

```env
GROQ_API_KEY=
GROQ_WHISPER_MODEL=whisper-large-v3-turbo

TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_CHAT_ID=

PROXY_URL=
OPENAI_PROXY=
GROQ_PROXY=
TELEGRAM_PROXY=
```

Реальные ключи, токены и адреса прокси не должны попадать в Git.

### 2. Установить зависимости

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-pecf11.txt
```

### 3. Построить FAISS-индекс

Это обязательный шаг после первого клонирования и после изменения `data/faqs.json`.

```powershell
.\BUILD_FAISS.ps1
```

Ожидаемый результат для текущей базы:

```text
ITEMS: 31
DIM: 1536
```

Сгенерированные файлы:

```text
faq_service/index/faiss_index.bin
faq_service/index/faqs_metadata.npy
```

Они не хранятся в Git и пересобираются из `data/faqs.json`.

### 4. Запустить локально

FastAPI:

```powershell
.\START_FAQ.ps1
```

Проверка:

```powershell
Invoke-RestMethod http://127.0.0.1:8011/health
python -m faq_service.smoke_http
```

Ожидается:

```text
TOTAL FAILED: 0
```

В отдельном PowerShell:

```powershell
.\START_SITE.ps1
```

Сайт:

```text
http://127.0.0.1:5000
```

Health:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health
```

## Docker

Перед сборкой FAISS-индекс должен быть создан.

```powershell
.\BUILD_FAISS.ps1
docker compose build
docker compose up -d
```

Проверка:

```powershell
docker compose ps
```

Основные контейнеры:

```text
dkorworld2-site
dkorworld2-faq-rag
```

В Docker Compose сайт обращается к FAQ-сервису по внутреннему адресу:

```text
http://dkorworld2-faq-rag:8011
```

Порт FastAPI наружу не публикуется.

## Production

Текущий production:

```text
https://portfolio.dkor.space
```

Схема:

```text
Internet
  ↓
Cloudflare
  ↓
Caddy
  ↓
dkorworld2-site:8008
  ↓
internal app_net
  ↓
dkorworld2-faq-rag:8011
```

Caddy проксирует публичный домен на `dkorworld2-site:8008`.

На сервере внешние API могут требовать outbound proxy. Для этого предусмотрены:

```env
PROXY_URL=
OPENAI_PROXY=
GROQ_PROXY=
TELEGRAM_PROXY=
```

Секретные server-only env-файлы не хранятся в репозитории.

## Health

Публичная проверка:

```text
GET /api/health
```

В рабочем production V13.4 возвращаются, среди прочего:

```text
status: ok
database: true
vector_store: FAISS
knowledge_base_items: 31
groq_voice: true
telegram_leads: true
faq_rag.status: ok
faq_rag.index_items: 31
faq_rag.memory: true
```

`n8n_backup` является отдельным резервным каналом и не обязателен для основной работы FAQ, SQLite и Telegram.

## Безопасность репозитория

В Git не должны попадать:

```text
.env
.env.*
*.db
instance/
.venv/
venv/
*.tar
*.tar.gz
faq_service/index/faiss_index.bin
faq_service/index/faqs_metadata.npy
backups/
```

`.env.example` хранится как безопасный шаблон без реальных секретов.

Перед первым коммитом рекомендуется проверить staged-файлы:

```powershell
git add -A
git status --short
git diff --cached --name-only | Select-String -Pattern "\.env|\.tar$|\.db$|faiss_index|faqs_metadata"
```

Последняя команда не должна показывать секретные или генерируемые файлы.

## Если изменена база знаний

После любого изменения:

```text
data/faqs.json
```

обязательно пересобрать индекс:

```powershell
.\BUILD_FAISS.ps1
```

и только после этого пересобирать Docker-образ.

## Основные файлы

```text
app.py                         Flask-сайт и интеграция FAQ
data/faqs.json                 база знаний
faq_service/app.py             FastAPI API
faq_service/rag_index.py       embeddings, FAISS, retrieval, memory
faq_service/build_index.py     сборка индекса
faq_service/smoke_http.py      HTTP smoke-тест
docker-compose.yml             Flask + FastAPI/FAISS
Dockerfile                     образ сайта
faq_service/Dockerfile         образ FAQ-сервиса
.env.example                   безопасный шаблон настроек
BUILD_FAISS.ps1                пересборка FAISS
START_FAQ.ps1                  локальный запуск FastAPI
START_SITE.ps1                 локальный запуск Flask
```

## Проверенные контрольные вопросы

```text
Сколько стоит лендинг и какой срок?
Сколько стоит сделать AI-бота?
Сколько стоит AI-проморолик?
Где посмотреть реальные работы?
Что умеет AutoNeuro?
Какая погода завтра?
Возьмёте ведение Яндекс Директа?
Работаете с персональными данными и соблюдаете 152-ФЗ?
Отлично, а что еще можешь?
```

Для проверки памяти:

```text
Расскажи про бота для записи клиентов
А сколько это будет стоить?
```

## Статус

**V13.4 — deployed / production verified**

FAQ-ассистент, сайт, FAISS, память, Voice, Telegram-заявки, запись и отмена проверены на `portfolio.dkor.space`.
