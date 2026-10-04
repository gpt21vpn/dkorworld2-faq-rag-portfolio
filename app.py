"""
Главный файл Flask приложения
Веб-сайт с кейсами, формой обратной связи и админ-панелью
"""
import os
import json
import re
import logging
import httpx
import time
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from flask import Flask, Response, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text as sql_text
from sqlalchemy.exc import IntegrityError
from wtforms import StringField, TextAreaField, EmailField, TelField, SelectField, SubmitField
from wtforms.validators import DataRequired, Email, Length
from flask_wtf import FlaskForm, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config, startup_notice
from backend.rag_index import generate_answer as rag_generate_answer, local_answer as rag_local_answer

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
# httpx logs full request URLs at INFO. Telegram Bot API puts the bot token
# in the URL path, so keep transport logs at WARNING to avoid secret leakage.
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

# Простое ограничение частоты для публичных API без новой зависимости.
# Для одного/нескольких небольших Gunicorn workers этого достаточно как базовой защиты;
# для высоконагруженного проекта лучше вынести счётчики в Redis/nginx.
_RATE_BUCKETS = defaultdict(deque)
_RATE_LOCK = threading.Lock()

def _client_ip() -> str:
    # ProxyFix below resolves the trusted single reverse proxy (nginx).
    # We deliberately do not parse X-Forwarded-For by hand.
    return request.remote_addr or 'unknown'

def rate_limit(bucket: str, limit: int, window_seconds: int):
    now = time.monotonic()
    key = f"{bucket}:{_client_ip()}"
    with _RATE_LOCK:
        q = _RATE_BUCKETS[key]
        cutoff = now - window_seconds
        while q and q[0] <= cutoff:
            q.popleft()
        if len(q) >= limit:
            retry_after = max(1, int(window_seconds - (now - q[0])))
            return jsonify({
                'error': 'Слишком много запросов. Попробуйте чуть позже.',
                'code': 'RATE_LIMITED',
                'retry_after': retry_after,
            }), 429
        q.append(now)
    return None


def _faq_rag_url(path: str = "") -> str:
    base = (app.config.get('FAQ_RAG_URL') if 'app' in globals() else Config.FAQ_RAG_URL) or ''
    return f"{base.rstrip('/')}/{path.lstrip('/')}" if base else ''


def _faq_rag_health(timeout: float = 2.5):
    """Probe the internal FastAPI/FAISS service without exposing it publicly."""
    url = _faq_rag_url('/health')
    if not url:
        return {'configured': False, 'status': 'disabled'}
    try:
        response = httpx.get(url, timeout=timeout)
        payload = response.json() if response.content else {}
        return {'configured': True, 'http_status': response.status_code, **payload}
    except Exception as exc:
        return {'configured': True, 'status': 'unavailable', 'error': str(exc)[:180]}


def _faq_rag_chat(message: str, history, top_k: int):
    """Forward browser chat to the separate PECF11 FastAPI + FAISS backend."""
    url = _faq_rag_url('/chat')
    if not url:
        return None
    payload = {'message': message, 'history': history[-8:], 'top_k': top_k}
    timeout = float(app.config.get('FAQ_RAG_TIMEOUT') or 45.0)
    response = httpx.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict) or not result.get('answer'):
        raise RuntimeError('FAQ RAG service returned an invalid response')
    return result

# Инициализация Flask приложения
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config.from_object(Config)

# Инициализация расширений
db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login'
login_manager.login_message = 'Пожалуйста, войдите в систему для доступа к этой странице.'
login_manager.login_message_category = 'info'

@app.context_processor
def inject_flags():
    """Флаги, доступные во всех шаблонах."""
    return {
        'chat_enabled': True,
        'rag_enabled': bool(app.config.get('FAQ_RAG_URL') or app.config.get('RAG_ENABLED', False)),
        'groq_enabled': app.config.get('GROQ_ENABLED', False),
        'telegram_enabled': bool(app.config.get('TELEGRAM_BOT_TOKEN') and app.config.get('TELEGRAM_ADMIN_CHAT_ID')),
        'n8n_enabled': bool(app.config.get('N8N_LEAD_WEBHOOK_URL')),
    }

@app.after_request
def add_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    return response

# Стартовые предупреждения (пароль админа, отсутствие ключей)
for _line in startup_notice():
    logger.warning(_line)

# Модели базы данных

def utc_now_naive() -> datetime:
    """UTC без tzinfo — для колонок SQLite. Замена устаревшего datetime.utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_now_iso() -> str:
    """UTC со зоной — для payload в сеть."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


class Contact(db.Model):
    """Модель для хранения заявок из формы обратной связи"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now_naive)
    is_read = db.Column(db.Boolean, default=False)
    
    def __repr__(self):
        return f'<Contact {self.name} - {self.subject}>'
    
    def to_dict(self):
        """Преобразование объекта в словарь для JSON"""
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'subject': self.subject,
            'message': self.message,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'is_read': self.is_read
        }

class QuizLead(db.Model):
    """Заявка из пятишагового квиза."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    contact = db.Column(db.String(160), nullable=False)
    answers_json = db.Column(db.Text, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now_naive)
    is_read = db.Column(db.Boolean, default=False)

    @property
    def answers(self):
        try:
            return json.loads(self.answers_json)
        except Exception:
            return {}



class Booking(db.Model):
    """Запись на консультацию. Время слота — наивный MSK (UTC+3, без переходов).

    Уникальный индекс на slot_start — единственная надёжная защита от двойной
    брони: проверка "сначала посмотрел, свободно ли" ломается на двух
    одновременных клиентах, поэтому вставка идёт в try/except IntegrityError.
    """
    __tablename__ = 'booking'
    id = db.Column(db.Integer, primary_key=True)
    slot_start = db.Column(db.DateTime, nullable=False, unique=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    contact = db.Column(db.String(160), nullable=False)
    client_key = db.Column(db.String(160), nullable=False, index=True)
    comment = db.Column(db.Text, nullable=True)
    cancel_token = db.Column(db.String(40), nullable=False, unique=True)
    calendar_event_id = db.Column(db.String(255), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=utc_now_naive)
    is_read = db.Column(db.Boolean, default=False)

    @property
    def slot_end(self):
        return self.slot_start + timedelta(minutes=Config.BOOKING_SLOT_MINUTES)

    @property
    def slot_label(self):
        return f"{self.slot_start.strftime('%d.%m.%Y')} {self.slot_start.strftime('%H:%M')}-{self.slot_end.strftime('%H:%M')} МСК"


def msk_now() -> datetime:
    """Текущее московское время. MSK фиксирован UTC+3, поэтому смещение постоянно."""
    return (datetime.now(timezone.utc) + timedelta(hours=app.config.get('BOOKING_TZ_OFFSET_HOURS', 3))).replace(tzinfo=None)


def normalize_client_key(contact: str) -> str:
    """Один клиент = один ключ.

    Без нормализации '+7 999 123-45-67' и '79991234567' считались бы разными
    людьми, и лимит записей в день обходился бы пробелом.
    """
    raw = (contact or '').strip().lower()
    digits = re.sub(r'\D', '', raw)
    if len(digits) >= 10:
        return 'tel:' + digits[-10:]
    handle = re.sub(r'^(https?://)?(t\.me/|telegram\.me/)?@?', '', raw)
    handle = re.sub(r'[^a-z0-9_.@-]', '', handle)
    return 'id:' + (handle or raw)[:60]


def build_slots(days_ahead: int | None = None) -> list[dict]:
    """Свободные слоты на горизонт вперёд. Прошедшее и занятое не показываем."""
    first = int(app.config.get('BOOKING_FIRST_HOUR', 9))
    last = int(app.config.get('BOOKING_LAST_HOUR', 20))
    minutes = int(app.config.get('BOOKING_SLOT_MINUTES', 60))
    horizon = int(days_ahead or app.config.get('BOOKING_DAYS_AHEAD', 14))
    lead = timedelta(hours=float(app.config.get('BOOKING_MIN_LEAD_HOURS', 2)))
    now = msk_now()
    earliest = now + lead

    taken = {b.slot_start for b in Booking.query.filter(Booking.slot_start >= now.replace(hour=0, minute=0, second=0, microsecond=0)).all()}
    days = []
    for offset in range(horizon):
        day = (now + timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        slots = []
        for hour in range(first, last + 1):
            start = day.replace(hour=hour)
            if start < earliest:
                continue
            if start in taken:
                continue
            end = start + timedelta(minutes=minutes)
            slots.append({
                'start': start.strftime('%Y-%m-%dT%H:%M'),
                'label': f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}",
            })
        if slots:
            days.append({
                'date': day.strftime('%Y-%m-%d'),
                'date_label': day.strftime('%d.%m'),
                'weekday': ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][day.weekday()],
                'slots': slots,
            })
    return days



def notify_telegram(text: str) -> bool:
    """Опционально отправляет заявку владельцу через Telegram Bot API.

    Токен хранится только на сервере в .env. Если переменные не заданы,
    сайт просто сохраняет заявку в SQLite и продолжает работать.
    """
    token = app.config.get('TELEGRAM_BOT_TOKEN')
    chat_id = app.config.get('TELEGRAM_ADMIN_CHAT_ID')
    if not token or not chat_id:
        return False
    try:
        telegram_proxy = (os.environ.get('TELEGRAM_PROXY') or os.environ.get('PROXY_URL') or '').strip()
        if telegram_proxy:
            with httpx.Client(proxy=telegram_proxy, timeout=12.0) as client:
                response = client.post(
                    f'https://api.telegram.org/bot{token}/sendMessage',
                    json={'chat_id': chat_id, 'text': text[:3900]},
                )
        else:
            response = httpx.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat_id, 'text': text[:3900]},
                timeout=12.0,
            )
        response.raise_for_status()
        return True
    except Exception as exc:
        safe_error = str(exc).replace(str(token), '[REDACTED]')
        logger.warning('Telegram notification failed: %s', safe_error)
        return False

def notify_n8n_result(event_type: str, payload: dict) -> tuple[bool, dict]:
    """Отправляет событие в n8n и, если workflow ответил JSON, возвращает его.

    Это позволяет для booking.created получить Google Calendar event_id
    синхронно и сохранить его в SQLite. Ошибка n8n никогда не откатывает
    уже сохранённую локальную заявку/запись.
    """
    url = app.config.get('N8N_LEAD_WEBHOOK_URL')
    if not url:
        return False, {}

    headers = {'Content-Type': 'application/json'}
    secret = app.config.get('N8N_WEBHOOK_SECRET')
    if secret:
        headers['X-DKOR-Webhook-Secret'] = secret

    envelope = {
        'event': event_type,
        'source': 'dkorworld2-site',
        'sent_at': utc_now_iso(),
        'payload': payload,
    }
    try:
        response = httpx.post(url, json=envelope, headers=headers, timeout=20.0)
        response.raise_for_status()
        try:
            data = response.json()
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        return True, data
    except Exception as exc:
        logger.warning('n8n webhook notification failed: %s', exc)
        return False, {}


def notify_n8n(event_type: str, payload: dict) -> bool:
    """Совместимый bool-wrapper для квиза и обычной формы."""
    ok, _ = notify_n8n_result(event_type, payload)
    return ok


class AdminUser(UserMixin):
    """Модель пользователя для админ-панели"""
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def load_user(user_id):
    """Загрузка пользователя для Flask-Login"""
    if user_id == 'admin':
        return AdminUser('admin')
    return None

# Формы
class ContactForm(FlaskForm):
    """Форма обратной связи"""
    name = StringField('Имя', validators=[DataRequired(message='Поле обязательно для заполнения'), 
                                          Length(min=2, max=100, message='Имя должно быть от 2 до 100 символов')])
    email = EmailField('Email', validators=[DataRequired(message='Поле обязательно для заполнения'), 
                                            Email(message='Введите корректный email адрес')])
    phone = TelField('Телефон', validators=[DataRequired(message='Поле обязательно для заполнения')])
    subject = SelectField(
        'Тема сообщения',
        choices=[
            ('', 'Выберите тему'),
            ('ai_assistant', 'AI-ассистент для бизнеса'),
            ('telegram_bot', 'Telegram-бот для клиентов'),
            ('automation', 'Автоматизация заявок и процессов'),
            ('ai_video', 'AI-проморолик или видео'),
            ('site_ai', 'Сайт или лендинг с AI-консультантом'),
            ('visual_3d', '3D-визуализация, интерьер, моушн'),
            ('other', 'Другое')
        ],
        validators=[DataRequired(message='Выберите тему сообщения')],
        default=''
    )
    message = TextAreaField('Сообщение', validators=[DataRequired(message='Поле обязательно для заполнения'),
                                                     Length(min=10, max=1000, message='Сообщение должно быть от 10 до 1000 символов')])
    submit = SubmitField('Отправить')

class AdminLoginForm(FlaskForm):
    """Форма входа в админ-панель"""
    username = StringField('Логин', validators=[DataRequired()])
    password = StringField('Пароль', validators=[DataRequired()])
    submit = SubmitField('Войти')

# Данные кейсов — только реальные проекты DKORWORLD2
CASES_DATA = {
    'autoneuro': {
        'id': 'autoneuro',
        'icon': 'car-front',
        'title': 'AI-бот для СТО и магазина автозапчастей',
        'short_description': 'Запись на сервис, ответы по прайсу и заявки в одном месте',
        'description': """
        <h4>Задача</h4>
        <p>Владельцу СТО и магазина автозапчастей нужно было принимать запись через Telegram
        и видеть обращения клиентов в одном месте со статусами. Дополнительно — оценка
        автомобиля, трейд-ин, ответы по вакансиям и сравнение машин.</p>

        <h4>Решение</h4>
        <p>Собрал Telegram-бота: он отвечает по реальному прайсу и правилам трейд-ина,
        принимает запись на сервис, распознаёт голосовые сообщения, принимает фото
        повреждений. Заявка сразу приходит владельцу карточкой, дополнительно есть
        панель со статусами обращений.</p>

        <h4>Результат для клиента</h4>
        <p>Бот может отвечать на типовые вопросы клиентов в любое время суток,
        без привязки к графику менеджера. Владелец получает обращения
        в одном интерфейсе и не ищет их вручную по разным перепискам.</p>

        <p><strong>Работающий пример:</strong>
        <a href="https://t.me/carsautohelperAibot" target="_blank" rel="noopener">@carsautohelperAibot</a></p>
        """,
    },
    'astro_bot': {
        'id': 'astro_bot',
        'icon': 'stars',
        'title': 'Telegram-бот для консультаций, записи и оплаты',
        'short_description': 'Первичное общение, запись, оплата и передача заявок в CRM',
        'description': """
        <h4>Задача</h4>
        <p>Нужно было объединить бесплатный расчёт, запись на консультацию, оплату
        и передачу заявок в CRM, не заставляя специалиста переносить данные вручную.
        Отдельно нужно было безопасно работать с персональными данными.</p>

        <h4>Решение</h4>
        <p>Собрал Telegram-бота: он выполняет расчёт, принимает запись, передаёт заявку
        в Битрикс24, принимает оплату через ЮKassa и после оплаты выдаёт материал клиенту.
        Персональные данные шифруются перед записью и маскируются в логах.</p>

        <h4>Результат для клиента</h4>
        <p>Основные этапы общения с клиентом собраны в одном сценарии. Бот передан
        заказчице с чек-листом из шести разделов; цены можно менять самостоятельно,
        без обращения к разработчику.</p>

        <p><strong>Работающий пример:</strong>
        <a href="https://t.me/astronum108bot" target="_blank" rel="noopener">@astronum108bot</a></p>
        """,
    },
    'promo_video': {
        'id': 'promo_video',
        'icon': 'camera-reels',
        'title': 'AI-проморолик 2:30',
        'short_description': 'Сценарий заказчика — готовый ролик без съёмочной группы',
        'description': """
        <h4>Задача</h4>
        <p>Заказчик пришёл со сценарием и художественной метафорой — противопоставление
        «мира гигантов» и мира клиента. Нужен был готовый промо-ролик, снять который
        обычным способом было бы дорого и долго.</p>

        <h4>Решение</h4>
        <p>До обсуждения бюджета сделал 3–4 тестовых кадра по метафоре заказчика, чтобы
        он увидел стиль заранее и согласование не шло вслепую. Дальше — генерация кадров,
        дикторская озвучка, цветовая драматургия (холодный синий для мира гигантов,
        тёплый для мира клиента), титры и логотип.</p>

        <h4>Результат для клиента</h4>
        <p>Ролик 2:30 сдан 22.04.2026 после 6 итераций правок. Заказчик видел стиль
        до старта работы, поэтому правки шли по деталям, а не по общей идее.</p>

        <figure class="mt-4">
          <img src="/static/images/promo_montage.png" class="img-fluid rounded"
               alt="Кадры из AI-роликов студии DKORWORLD2">
          <figcaption class="text-muted small mt-2">
            Кадры из AI-роликов студии — примеры визуального языка, с которым я работаю.
          </figcaption>
        </figure>
        """,
    },
}

# Отзывы заказчиков. Только реальные — три штуки.
# Тексты и аватары перенесены со старого сайта студии.
REVIEWS = [
    {
        'name': 'Тамара Ивановна',
        'role': 'владелец ателье «Витея»',
        'image': 'review_tamara.png',
        'text': 'Далека от ИИ и не люблю быть в кадре. Дмитрий помог создать проморолик '
                'для рекламы ателье с проработанной озвучкой. Была довольна результатом.',
    },
    {
        'name': 'Ольга',
        'role': 'астролог',
        'image': 'review_olga.jpg',
        'text': 'Сначала обратилась к Дмитрию за лендингом, а после выполнения работы — '
                'за AI-помощником в Telegram. Результат превзошёл ожидания: бот работает '
                'отлично и экономит много времени.',
    },
    {
        'name': 'Марина Петрова',
        'role': 'блогер',
        'image': 'review_marina.png',
        'text': 'Дмитрий создал для меня базовый лендинг. Получился хороший результат, '
                'рекомендую его услуги.',
    },
]



# Собственные проекты и учебные работы. Держим отдельно от клиентских кейсов:
# смешивать их нельзя, иначе размывается то, что сделано для заказчиков.
OWN_PROJECTS = [
    {
        'icon': 'bi-database-check',
        'title': 'RAG-ассистент с логированием и мониторингом',
        'stack': 'Python · ChromaDB · OpenAI · Telegram · Docker',
        'text': 'Ассистент DKORWORLD2 отвечает по собственной базе знаний: 17 чанков в ChromaDB, кеш ответов, SQLite-журнал, команды /stats и /logs с CSV-экспортом. Telegram ID обезличивается, контактные данные маскируются. Проект развёрнут на Cloud4box; ChromaDB, кеш и логи сохраняются после рестарта контейнера.',
        'link': 'https://t.me/dimaseopro2',
        'link_label': 'Открыть RAG-бота',
    },
    {
        'icon': 'bi-egg-fried',
        'title': 'EDA-бот — кулинарный AI-ассистент',
        'stack': 'Python · aiogram · Vision',
        'text': 'Из списка продуктов текстом или голосом — рецепты с расчётом КБЖУ. По фото холодильника распознаёт ингредиенты, по фото блюда определяет его и даёт рецепт. Диалог с уточняющими вопросами, избранное.',
        'link': 'https://t.me/EDA5tgtestZbot',
        'link_label': 'Открыть бота',
    },
    {
        'icon': 'bi-calendar-check',
        'title': 'TaskZero — голосовой задачник на n8n',
        'stack': 'n8n · Whisper · Google Calendar',
        'text': 'Около 70 нод. Задача ставится голосом: распознавание, извлечение полей, парсер русских дат («завтра в 15 часов» → точная дата по Москве). Синхронизация с Google Calendar по OAuth2, поиск задачи по тексту без номера.',
        'link': '',
        'link_label': '',
    },
    {
        'icon': 'bi-graph-up-arrow',
        'title': 'Competitor Monitor — анализ конкурентов',
        'stack': 'Python · FastAPI · Selenium',
        'text': 'Разбор сайта и макетов конкурента по калиброванной шкале, режим A/B-сравнения двух конкурентов, досье из ссылки, фото и файлов PDF/DOCX. Парсер с обходом антибота и автоматическим откатом на резервный способ.',
        'link': 'https://github.com/gpt21vpn/8cursorZ-monitor',
        'link_label': 'Код на GitHub',
    },
    {
        'icon': 'bi-robot',
        'title': 'Мульти-сервис бот студии',
        'stack': 'aiogram · Docker · VPS',
        'text': 'Согласие по 152-ФЗ, тап-квиз заявки текстом и голосом, инлайн-календарь записи, FAQ на ИИ, уведомления владельцу. Развёрнут на боевом сервере в Docker, работа в российском контуре.',
        'link': 'https://t.me/dkorai2cbot',
        'link_label': 'Открыть бота',
    },
    {
        'icon': 'bi-diagram-3',
        'title': 'Эксперименты с RAG и векторными базами',
        'stack': 'FAISS · Pinecone · Weaviate',
        'text': 'Сравнение двух облачных векторных баз на одинаковых данных показало, что качество определяют эмбеддинги и нарезка, а не инфраструктура. Замер по нарезке: релевантность на целевом запросе выросла с 0.44 до 0.73.',
        'link': '',
        'link_label': '',
    },
]


@app.route('/favicon.ico')
def favicon():
    """Favicon без лишнего 404 в браузере."""
    return send_from_directory(
        os.path.join(app.root_path, 'static', 'images'),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon'
    )

# Роуты для основных страниц
@app.route('/')
def index():
    """Главная страница"""
    logger.info('Главная страница запрошена')
    form = ContactForm()
    return render_template('index.html', cases=CASES_DATA, reviews=REVIEWS, form=form,
                           own_projects=OWN_PROJECTS)

@app.route('/cases')
def cases():
    """Страница со всеми кейсами"""
    logger.info('Страница кейсов запрошена')
    return render_template('cases.html', cases=CASES_DATA)

@app.route('/case/<case_id>')
def case_detail(case_id):
    """Страница с детальным описанием кейса"""
    case = CASES_DATA.get(case_id)
    if not case:
        flash('Кейс не найден', 'error')
        return redirect(url_for('cases'))
    logger.info(f'Детальная страница кейса {case_id} запрошена')
    return render_template('case_detail.html', case=case)

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    """Страница с формой обратной связи"""
    form = ContactForm()

    if request.method == 'POST':
        limited = rate_limit('contact', 8, 600)
        if limited:
            return limited

    if form.validate_on_submit():
        try:
            # Создание новой заявки
            contact = Contact(
                name=form.name.data,
                email=form.email.data,
                phone=form.phone.data,
                subject=form.subject.data,
                message=form.message.data
            )
            db.session.add(contact)
            db.session.commit()
            text = (
                'Новая заявка с сайта DKORWORLD2\n'
                f'Имя: {contact.name}\nEmail: {contact.email}\nТелефон: {contact.phone}\n'
                f'Тема: {contact.subject}\nСообщение: {contact.message}'
            )
            telegram_sent = notify_telegram(text)
            n8n_sent = notify_n8n('contact.created', {
                'id': contact.id,
                'name': contact.name,
                'email': contact.email,
                'phone': contact.phone,
                'subject': contact.subject,
                'message': contact.message,
            })
            logger.info(
                'Новая заявка создана: %s - %s; telegram=%s n8n=%s',
                contact.name, contact.subject, telegram_sent, n8n_sent
            )
            flash('Спасибо! Сообщение отправлено. Я свяжусь с вами в ближайшее время.', 'success')
            return redirect(url_for('contact'))
        except Exception as e:
            db.session.rollback()
            logger.error(f'Ошибка при создании заявки: {str(e)}')
            flash('Произошла ошибка при отправке сообщения. Попробуйте позже.', 'error')
    
    return render_template('contact.html', form=form)

@app.route('/quiz')
def quiz():
    """Отдельная страница пятишагового квиза."""
    return render_template('quiz.html')


@app.route('/privacy')
def privacy():
    """Короткая политика обработки данных для форм сайта."""
    return render_template('privacy.html')


@app.route('/api/quiz-submit', methods=['POST'])
def quiz_submit():
    """Сохраняет ответы квиза и при наличии настроек отправляет их в Telegram."""
    limited = rate_limit('quiz', 10, 600)
    if limited:
        return limited
    data = request.get_json(silent=True) or {}
    name = str(data.get('name') or '').strip()[:100]
    contact_value = str(data.get('contact') or '').strip()[:160]
    comment = str(data.get('comment') or '').strip()[:1500]
    answers = data.get('answers') or {}
    required_answer_keys = ('who', 'niche', 'need', 'readiness', 'budget')
    if not name or not contact_value or not isinstance(answers, dict):
        return jsonify({'error': 'Заполните имя, контакт и ответы квиза.'}), 400
    if len(name) < 2 or len(contact_value) < 5:
        return jsonify({'error': 'Проверьте имя и контакт.'}), 400
    if any(not str(answers.get(key) or '').strip() for key in required_answer_keys):
        return jsonify({'error': 'Ответьте на все пять вопросов квиза.'}), 400

    clean_answers = {key: str(answers.get(key) or '').strip()[:300] for key in required_answer_keys}
    request_id = uuid4().hex[:10]
    lead = QuizLead(
        name=name,
        contact=contact_value,
        answers_json=json.dumps(clean_answers, ensure_ascii=False),
        comment=comment,
    )
    try:
        db.session.add(lead)
        db.session.commit()
        labels = {
            'who': 'Кто вы', 'niche': 'Ниша', 'need': 'Что нужно',
            'readiness': 'Готовность', 'budget': 'Бюджет'
        }
        lines = ['Новая заявка из квиза DKORWORLD2', f'Имя: {name}', f'Контакт: {contact_value}']
        for key in ('who','niche','need','readiness','budget'):
            if clean_answers.get(key):
                lines.append(f"{labels[key]}: {clean_answers[key]}")
        if comment:
            lines.append(f'Комментарий: {comment}')
        telegram_sent = notify_telegram('\n'.join(lines))
        n8n_sent = notify_n8n('quiz.created', {
            'id': lead.id,
            'request_id': request_id,
            'name': name,
            'contact': contact_value,
            'answers': clean_answers,
            'comment': comment,
        })
        logger.info('Новая заявка из квиза: %s; telegram=%s n8n=%s', name, telegram_sent, n8n_sent)
        return jsonify({
            'ok': True,
            'id': lead.id,
            'request_id': request_id,
            'saved': True,
            'telegram_sent': telegram_sent,
            'telegram_configured': bool(app.config.get('TELEGRAM_BOT_TOKEN') and app.config.get('TELEGRAM_ADMIN_CHAT_ID')),
            'n8n_sent': n8n_sent,
            'n8n_configured': bool(app.config.get('N8N_LEAD_WEBHOOK_URL')),
        })
    except Exception as exc:
        db.session.rollback()
        logger.exception('Ошибка сохранения квиза: %s', exc)
        return jsonify({'error': 'Не удалось сохранить заявку.'}), 500



@app.route('/booking')
def booking_page():
    """Страница записи на консультацию."""
    return render_template(
        'booking.html',
        first_hour=app.config.get('BOOKING_FIRST_HOUR', 9),
        last_hour=app.config.get('BOOKING_LAST_HOUR', 20),
        per_day=app.config.get('BOOKING_MAX_PER_CLIENT_PER_DAY', 2),
        days_ahead=app.config.get('BOOKING_DAYS_AHEAD', 14),
    )


@app.route('/api/booking-slots')
def booking_slots():
    """Свободные слоты. Время московское."""
    return jsonify({
        'timezone': 'Europe/Moscow (МСК, UTC+3)',
        'slot_minutes': app.config.get('BOOKING_SLOT_MINUTES', 60),
        'max_per_client_per_day': app.config.get('BOOKING_MAX_PER_CLIENT_PER_DAY', 2),
        'days': build_slots(),
    })


@app.route('/api/booking-create', methods=['POST'])
def booking_create():
    """Создаёт запись. Порядок: SQLite -> Telegram -> n8n."""
    limited = rate_limit('booking', 8, 600)
    if limited:
        return limited

    data = request.get_json(silent=True) or {}
    name = str(data.get('name') or '').strip()[:100]
    contact_value = str(data.get('contact') or '').strip()[:160]
    comment = str(data.get('comment') or '').strip()[:1000]
    slot_raw = str(data.get('slot') or '').strip()

    if len(name) < 2 or len(contact_value) < 5:
        return jsonify({'error': 'Укажите имя и контакт для связи.'}), 400
    try:
        slot_start = datetime.strptime(slot_raw, '%Y-%m-%dT%H:%M')
    except ValueError:
        return jsonify({'error': 'Выберите время из списка.'}), 400

    first = int(app.config.get('BOOKING_FIRST_HOUR', 9))
    last = int(app.config.get('BOOKING_LAST_HOUR', 20))
    if slot_start.minute or not (first <= slot_start.hour <= last):
        return jsonify({'error': f'Запись возможна с {first}:00 до {last + 1}:00 МСК, слотами по часу.'}), 400

    now = msk_now()
    lead = timedelta(hours=float(app.config.get('BOOKING_MIN_LEAD_HOURS', 2)))
    if slot_start < now + lead:
        return jsonify({'error': 'Это время уже слишком близко. Выберите слот позже.'}), 400
    if slot_start > now + timedelta(days=int(app.config.get('BOOKING_DAYS_AHEAD', 14))):
        return jsonify({'error': 'Запись открыта на две недели вперёд.'}), 400

    client_key = normalize_client_key(contact_value)
    limit = int(app.config.get('BOOKING_MAX_PER_CLIENT_PER_DAY', 2))
    day_start = slot_start.replace(hour=0, minute=0, second=0, microsecond=0)
    same_day = Booking.query.filter(
        Booking.client_key == client_key,
        Booking.slot_start >= day_start,
        Booking.slot_start < day_start + timedelta(days=1),
    ).count()
    if same_day >= limit:
        return jsonify({
            'error': f'На этот день у вас уже {same_day} запис(и). Больше {limit} в день не оформляем.',
            'code': 'CLIENT_DAY_LIMIT',
        }), 409

    # Общий предел: дневного лимита не хватает, иначе можно набрать
    # по две брони на каждый день горизонта.
    active_limit = int(app.config.get('BOOKING_MAX_ACTIVE_PER_CLIENT', 2))
    active = Booking.query.filter(
        Booking.client_key == client_key,
        Booking.slot_start >= now,
    ).count()
    if active >= active_limit:
        return jsonify({
            'error': (f'У вас уже {active} активных запис(и). Проведём их или отмените '
                      f'ненужную по ссылке из уведомления — после этого можно записаться снова.'),
            'code': 'CLIENT_ACTIVE_LIMIT',
        }), 409

    token = uuid4().hex[:24]
    record = Booking(
        slot_start=slot_start, name=name, contact=contact_value,
        client_key=client_key, comment=comment, cancel_token=token,
    )
    try:
        db.session.add(record)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Этот слот только что заняли. Выберите другое время.', 'code': 'SLOT_TAKEN'}), 409
    except Exception as exc:
        db.session.rollback()
        logger.exception('Ошибка сохранения записи: %s', exc)
        return jsonify({'error': 'Не удалось сохранить запись.'}), 500

    cancel_url = url_for('booking_cancel', token=token, _external=True)
    lines = [
        'Новая запись на консультацию DKORWORLD2',
        f'Время: {record.slot_label}',
        f'Имя: {name}',
        f'Контакт: {contact_value}',
    ]
    if comment:
        lines.append(f'Комментарий: {comment}')
    lines.append(f'Отмена: {cancel_url}')
    telegram_sent = notify_telegram('\n'.join(lines))
    n8n_sent, n8n_result = notify_n8n_result('booking.created', {
        'id': record.id,
        'booking_ref': record.cancel_token,
        'slot_start_msk': slot_start.strftime('%Y-%m-%dT%H:%M:00+03:00'),
        'slot_end_msk': record.slot_end.strftime('%Y-%m-%dT%H:%M:00+03:00'),
        'slot_label': record.slot_label,
        'name': name, 'contact': contact_value, 'comment': comment,
        'cancel_url': cancel_url,
    })

    # Новый n8n workflow отвечает event_id созданного события Google Calendar.
    calendar_event_id = str(
        n8n_result.get('event_id')
        or n8n_result.get('calendar_event_id')
        or ''
    ).strip()[:255]
    if calendar_event_id:
        record.calendar_event_id = calendar_event_id
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.warning('Не удалось сохранить Google Calendar event_id: %s', exc)

    logger.info(
        'Новая запись: %s на %s; telegram=%s n8n=%s calendar_event_id=%s',
        name, record.slot_label, telegram_sent, n8n_sent, bool(record.calendar_event_id)
    )
    return jsonify({
        'ok': True, 'id': record.id, 'saved': True,
        'slot_label': record.slot_label,
        'cancel_url': cancel_url,
        'ics_url': url_for('booking_ics', token=token),
        'telegram_sent': telegram_sent,
        'n8n_sent': n8n_sent,
        'calendar_synced': bool(record.calendar_event_id),
    })


@app.route('/booking/cancel/<token>', methods=['GET', 'POST'])
def booking_cancel(token):
    """Безопасная отмена.

    GET ничего не изменяет и только показывает подтверждение. Это важно,
    потому что Telegram/браузеры/антивирусы могут открывать ссылку для preview.
    Реальная отмена выполняется только POST с CSRF.
    """
    record = Booking.query.filter_by(cancel_token=(token or '')[:40]).first()
    if not record:
        return render_template(
            'booking_result.html',
            ok=False,
            title='Запись не найдена',
            message='Возможно, она уже отменена.',
        ), 404

    if request.method == 'GET':
        return render_template('booking_cancel_confirm.html', booking=record)

    limited = rate_limit('booking_cancel', 8, 600)
    if limited:
        return limited

    # Сохраняем данные ДО удаления локальной записи.
    payload = {
        'id': record.id,
        'event_id': record.calendar_event_id,
        'booking_ref': record.cancel_token,
        'slot_start_msk': record.slot_start.strftime('%Y-%m-%dT%H:%M:00+03:00'),
        'slot_end_msk': record.slot_end.strftime('%Y-%m-%dT%H:%M:00+03:00'),
        'slot_label': record.slot_label,
        'name': record.name,
        'contact': record.contact,
        'comment': record.comment or '',
        'cancelled_by': 'client',
    }
    label, name, contact_value = record.slot_label, record.name, record.contact

    try:
        db.session.delete(record)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception('Ошибка отмены записи: %s', exc)
        return render_template(
            'booking_result.html',
            ok=False,
            title='Не удалось отменить',
            message='Напишите в Telegram @dimaseo2.',
        ), 500

    telegram_sent = notify_telegram(
        f'Запись отменена клиентом\nВремя: {label}\nИмя: {name}\nКонтакт: {contact_value}'
    )
    n8n_sent = notify_n8n('booking.cancelled', payload)
    logger.info(
        'Запись отменена клиентом: %s; telegram=%s n8n=%s event_id=%s',
        label, telegram_sent, n8n_sent, bool(payload.get('event_id'))
    )

    return render_template(
        'booking_result.html',
        ok=True,
        title='Запись отменена',
        message=f'Слот {label} снова свободен.',
    )


@app.route('/booking/ics/<token>')
def booking_ics(token):
    """Файл календаря для клиента — без всякого OAuth."""
    record = Booking.query.filter_by(cancel_token=(token or '')[:40]).first()
    if not record:
        return jsonify({'error': 'Запись не найдена'}), 404
    offset = int(app.config.get('BOOKING_TZ_OFFSET_HOURS', 3))
    start_utc = record.slot_start - timedelta(hours=offset)
    end_utc = record.slot_end - timedelta(hours=offset)
    fmt = '%Y%m%dT%H%M%SZ'
    ics = '\r\n'.join([
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//DKORWORLD2//Booking//RU',
        'BEGIN:VEVENT', f'UID:{record.cancel_token}@dkorworld2',
        f'DTSTAMP:{utc_now_naive().strftime(fmt)}',
        f'DTSTART:{start_utc.strftime(fmt)}', f'DTEND:{end_utc.strftime(fmt)}',
        'SUMMARY:Консультация DKORWORLD2',
        f'DESCRIPTION:Консультация с Дмитрием (DKORWORLD2). Контакт: {record.contact}',
        'END:VEVENT', 'END:VCALENDAR', '',
    ])
    return Response(ics, mimetype='text/calendar',
                    headers={'Content-Disposition': 'attachment; filename=dkorworld2-consultation.ics'})


@app.route('/api/capabilities')
def capabilities():
    return jsonify({
        'chat': True,
        'kb': True,
        'rag': bool(app.config.get('FAQ_RAG_URL') or app.config.get('RAG_ENABLED')),
        'faq_rag': bool(app.config.get('FAQ_RAG_URL')),
        'vector_store': 'FAISS' if app.config.get('FAQ_RAG_URL') else 'local-kb',
        'groq_voice': bool(app.config.get('GROQ_ENABLED')),
        'telegram_leads': bool(app.config.get('TELEGRAM_BOT_TOKEN') and app.config.get('TELEGRAM_ADMIN_CHAT_ID')),
        'n8n_backup': bool(app.config.get('N8N_LEAD_WEBHOOK_URL')),
        'version': '13.4-faiss-fastapi',
    })


@app.route('/api/health')
def api_health():
    """Небольшой self-check без раскрытия секретов."""
    try:
        from backend.rag_index import load_faqs
        kb_items = len(load_faqs())
        db.session.execute(sql_text('SELECT 1'))
        db_ok = True
    except Exception as exc:
        logger.warning('Health check warning: %s', exc)
        kb_items = 0
        db_ok = False
    return jsonify({
        'status': 'ok' if db_ok and kb_items else 'degraded',
        'database': db_ok,
        'knowledge_base_items': kb_items,
        'rag_llm': bool(app.config.get('RAG_ENABLED')),
        'faq_rag': _faq_rag_health(),
        'vector_store': 'FAISS' if app.config.get('FAQ_RAG_URL') else 'local-kb',
        'groq_voice': bool(app.config.get('GROQ_ENABLED')),
        'telegram_leads': bool(app.config.get('TELEGRAM_BOT_TOKEN') and app.config.get('TELEGRAM_ADMIN_CHAT_ID')),
        'n8n_backup': bool(app.config.get('N8N_LEAD_WEBHOOK_URL')),
        'version': '13.4-faiss-fastapi',
    })


@app.route('/voice/transcribe', methods=['POST'])
def voice_transcribe():
    """Распознавание аудио через Groq Whisper. Ключ никогда не уходит в браузер."""
    limited = rate_limit('voice', 12, 60)
    if limited:
        return limited
    if not app.config.get('GROQ_ENABLED'):
        return jsonify({'error': 'Groq API не настроен на сервере.', 'code': 'GROQ_DISABLED'}), 503
    audio = request.files.get('audio')
    if not audio or not audio.filename:
        return jsonify({'error': 'Аудиофайл не получен.'}), 400
    raw = audio.read()
    if not raw:
        return jsonify({'error': 'Аудиофайл пуст.'}), 400
    if len(raw) > 15 * 1024 * 1024:
        return jsonify({'error': 'Запись слишком большая. Максимум 15 МБ.'}), 413
    try:
        groq_proxy = (os.environ.get('GROQ_PROXY') or os.environ.get('PROXY_URL') or '').strip()
        request_kwargs = {
            'headers': {'Authorization': f"Bearer {app.config['GROQ_API_KEY']}"},
            'data': {
                'model': app.config.get('GROQ_WHISPER_MODEL', 'whisper-large-v3-turbo'),
                'language': 'ru',
                'response_format': 'json',
            },
            'files': {'file': (audio.filename, raw, audio.mimetype or 'audio/webm')},
        }
        if groq_proxy:
            with httpx.Client(proxy=groq_proxy, timeout=70.0) as client:
                response = client.post(
                    'https://api.groq.com/openai/v1/audio/transcriptions',
                    **request_kwargs,
                )
        else:
            response = httpx.post(
                'https://api.groq.com/openai/v1/audio/transcriptions',
                timeout=70.0,
                **request_kwargs,
            )
        if response.status_code >= 400:
            logger.warning('Groq transcription HTTP %s: %s', response.status_code, response.text[:400])
            return jsonify({'error': 'Groq не смог распознать запись.'}), 502
        payload = response.json()
        text = str(payload.get('text') or '').strip()
        return jsonify({'text': text, 'provider': 'groq'})
    except Exception as exc:
        logger.exception('Ошибка Groq voice: %s', exc)
        return jsonify({'error': 'Ошибка голосового сервиса.'}), 502


# Роуты для админ-панели
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Страница входа в админ-панель"""
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard'))
    
    form = AdminLoginForm()
    
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        
        # Проверка учетных данных
        if username == app.config['ADMIN_USERNAME'] and password == app.config['ADMIN_PASSWORD']:
            user = AdminUser('admin')
            login_user(user, remember=True)
            logger.info(f'Администратор {username} вошел в систему')
            flash('Вы успешно вошли в систему', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            logger.warning(f'Неудачная попытка входа: {username}')
            flash('Неверный логин или пароль', 'error')
    
    return render_template('admin/login.html', form=form)

@app.route('/admin/logout')
@login_required
def admin_logout():
    """Выход из админ-панели"""
    logger.info(f'Администратор {current_user.id} вышел из системы')
    logout_user()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    """Главная страница админ-панели"""
    contacts = Contact.query.order_by(Contact.created_at.desc()).all()
    quiz_leads = QuizLead.query.order_by(QuizLead.created_at.desc()).all()
    bookings = Booking.query.order_by(Booking.slot_start.asc()).all()
    unread_count = Contact.query.filter_by(is_read=False).count()
    quiz_unread_count = QuizLead.query.filter_by(is_read=False).count()
    total_count = Contact.query.count()
    quiz_total_count = QuizLead.query.count()
    
    from backend.rag_index import load_faqs
    system_status = {
        'knowledge_base_items': len(load_faqs()),
        'rag': bool(app.config.get('RAG_ENABLED')),
        'groq': bool(app.config.get('GROQ_ENABLED')),
        'telegram': bool(app.config.get('TELEGRAM_BOT_TOKEN') and app.config.get('TELEGRAM_ADMIN_CHAT_ID')),
        'n8n': bool(app.config.get('N8N_LEAD_WEBHOOK_URL')),
    }
    logger.info('Админ-панель запрошена')
    return render_template('admin/dashboard.html', 
                         contacts=contacts,
                         quiz_leads=quiz_leads,
                         bookings=bookings,
                         unread_count=unread_count,
                         quiz_unread_count=quiz_unread_count,
                         total_count=total_count,
                         quiz_total_count=quiz_total_count,
                         system_status=system_status)

@app.route('/admin/contact/<int:contact_id>/read', methods=['POST'])
@login_required
def mark_as_read(contact_id):
    """Отметить заявку как прочитанную"""
    contact = Contact.query.get_or_404(contact_id)
    contact.is_read = True
    db.session.commit()
    logger.info(f'Заявка {contact_id} отмечена как прочитанная')
    return jsonify({'success': True})

@app.route('/admin/contact/<int:contact_id>/delete', methods=['POST'])
@login_required
def delete_contact(contact_id):
    """Удалить заявку"""
    contact = Contact.query.get_or_404(contact_id)
    db.session.delete(contact)
    db.session.commit()
    logger.info(f'Заявка {contact_id} удалена')
    flash('Заявка успешно удалена', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/quiz/<int:lead_id>/read', methods=['POST'])
@login_required
def mark_quiz_read(lead_id):
    lead = QuizLead.query.get_or_404(lead_id)
    lead.is_read = True
    db.session.commit()
    return jsonify({'success': True})


@app.route('/admin/quiz/<int:lead_id>/delete', methods=['POST'])
@login_required
def delete_quiz_lead(lead_id):
    lead = QuizLead.query.get_or_404(lead_id)
    db.session.delete(lead)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/admin/booking/<int:booking_id>/delete', methods=['POST'])
@login_required
def delete_booking(booking_id):
    """Отмена записи владельцем: SQLite -> Telegram -> n8n/Calendar."""
    record = Booking.query.get_or_404(booking_id)
    payload = {
        'id': record.id,
        'event_id': record.calendar_event_id,
        'booking_ref': record.cancel_token,
        'slot_start_msk': record.slot_start.strftime('%Y-%m-%dT%H:%M:00+03:00'),
        'slot_end_msk': record.slot_end.strftime('%Y-%m-%dT%H:%M:00+03:00'),
        'slot_label': record.slot_label,
        'name': record.name,
        'contact': record.contact,
        'comment': record.comment or '',
        'cancelled_by': 'admin',
    }
    label, name, contact_value = record.slot_label, record.name, record.contact

    try:
        db.session.delete(record)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception('Ошибка отмены записи владельцем: %s', exc)
        flash('Не удалось отменить запись.', 'danger')
        return redirect(url_for('admin_dashboard'))

    telegram_sent = notify_telegram(
        f'Запись отменена вами\nВремя: {label}\nИмя: {name}\nКонтакт: {contact_value}'
    )
    n8n_sent = notify_n8n('booking.cancelled', payload)
    logger.info(
        'Запись отменена владельцем: %s; telegram=%s n8n=%s event_id=%s',
        label, telegram_sent, n8n_sent, bool(payload.get('event_id'))
    )
    flash(f'Запись на {label} отменена.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/bookings/clear', methods=['POST'])
@login_required
def clear_bookings():
    """Удаляет все записи — нужно для чистки тестовых броней."""
    count = Booking.query.count()
    Booking.query.delete()
    db.session.commit()
    logger.info('Админ удалил все записи: %s шт.', count)
    flash(f'Удалено записей: {count}.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/chat', methods=['POST'])
def chat():
    """API-эндпоинт для RAG-чатбота на главной странице."""
    limited = rate_limit('chat', 30, 60)
    if limited:
        return limited
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    top_k = data.get('top_k') or 3

    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        top_k = 3

    history = data.get('history') or []
    if not isinstance(history, list):
        history = []
    history = [item for item in history[-6:] if isinstance(item, dict)]

    if not message:
        return jsonify({'error': 'Пустое сообщение'}), 400
    if len(message) > 2000:
        return jsonify({'error': 'Сообщение слишком длинное.'}), 413

    # PECF11 primary path: separate FastAPI service with real FAISS semantic retrieval.
    # Existing V12 local KB remains as a safe fallback if the service is unavailable.
    if app.config.get('FAQ_RAG_URL'):
        try:
            result = _faq_rag_chat(message, history, top_k)
            logger.info('Чат: mode=%s via FastAPI/FAISS', result.get('mode'))
            return jsonify(result)
        except Exception as exc:
            logger.warning('FastAPI/FAISS service unavailable, using local fallback: %s', exc)

    try:
        # FAST PATH. Локальная база отвечает сама, если:
        #  - вопрос попал в известный интент (цены, сроки, услуги, кейсы, контакты, privacy);
        #  - или совпадений нет вовсе -> честный отказ.
        # В OpenAI уходят только неоднозначные вопросы. Это и быстрее, и дешевле,
        # и — главное — отказ остаётся локальным: иначе модель начнёт отвечать
        # на вопросы вне базы знаний из общих соображений.
        local = rag_local_answer(message, history=history)
        confidence = float(local.get('confidence') or 0.0)
        has_context = bool(local.get('context'))

        if not has_context:
            local['mode'] = 'refusal'
            logger.info('Чат: mode=refusal (нет совпадений в базе знаний)')
            return jsonify(local)

        if confidence >= 0.9:
            local['mode'] = 'kb'
            logger.info('Чат: mode=kb (быстрый путь, confidence=%.2f)', confidence)
            return jsonify(local)

        if app.config.get('RAG_ENABLED'):
            result = rag_generate_answer(message, top_k=top_k, history=history)
            result['mode'] = 'rag'
        else:
            result = local
            result['mode'] = 'kb'
        logger.info('Чат обработал сообщение, mode=%s', result.get('mode'))
        return jsonify(result)
    except Exception as e:
        logger.exception(f'Ошибка чат-бота: {e}')
        fallback = rag_local_answer(message, history=history)
        fallback['mode'] = 'kb_fallback'
        return jsonify(fallback)

# Инициализация базы данных
def init_db():
    """Создание таблиц и минимальная миграция старых локальных SQLite."""
    with app.app_context():
        db.create_all()

        # create_all() не добавляет новые столбцы в существующие таблицы.
        # V11 хранит Google Calendar event_id, поэтому старую V10/V9 БД
        # обновляем одной безопасной ALTER TABLE.
        try:
            columns = {
                row[1]
                for row in db.session.execute(sql_text("PRAGMA table_info(booking)")).fetchall()
            }
            if columns and 'calendar_event_id' not in columns:
                db.session.execute(
                    sql_text("ALTER TABLE booking ADD COLUMN calendar_event_id VARCHAR(255)")
                )
                db.session.commit()
                logger.info('Миграция БД V11: добавлен booking.calendar_event_id')
        except Exception as exc:
            db.session.rollback()
            logger.warning('Миграция booking.calendar_event_id не выполнена: %s', exc)

        logger.info('База данных инициализирована')

# Обработчик ошибок
@app.errorhandler(404)
def not_found_error(error):
    """Обработка ошибки 404"""
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    """Обработка ошибки 500"""
    db.session.rollback()
    return render_template('errors/500.html'), 500

if __name__ == '__main__':
    # Создание таблиц при запуске
    init_db()
    logger.info('Приложение запущено')
    app.run(debug=app.config.get('DEBUG', False), host='0.0.0.0', port=5000)

