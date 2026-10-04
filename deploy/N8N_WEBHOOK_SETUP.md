# Резервная доставка заявок в n8n

Сайт всегда сначала сохраняет заявку в SQLite. Затем независимо пытается:
1. отправить её в Telegram;
2. отправить копию в n8n webhook.

## В n8n

1. Создайте Workflow.
2. Первый узел: **Webhook**.
3. Method: `POST`.
4. Path, например: `dkorworld2-lead`.
5. После Webhook поставьте IF/Code-проверку заголовка `x-dkor-webhook-secret`.
6. Секрет должен совпасть с `N8N_WEBHOOK_SECRET` из `.env`.
7. После проверки можно отправлять уведомление в Telegram, email, Google Sheets или CRM.
8. Активируйте Workflow и скопируйте **Production URL**.

## В `.env` сайта

```env
N8N_LEAD_WEBHOOK_URL=https://YOUR_N8N_DOMAIN/webhook/dkorworld2-lead
N8N_WEBHOOK_SECRET=long-random-secret
```

Перезапустите сайт.

## Payload

```json
{
  "event": "quiz.created",
  "source": "dkorworld2-site",
  "sent_at": "2026-09-10T19:00:00Z",
  "payload": {
    "id": 1,
    "request_id": "abc123",
    "name": "Имя",
    "contact": "@telegram",
    "answers": {},
    "comment": ""
  }
}
```

Для обычной формы `event` будет `contact.created`.
