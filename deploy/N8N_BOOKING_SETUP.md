# DKORWORLD2 V11 — n8n + Google Calendar

## Что делает V11

Сайт всегда сохраняет запись в SQLite первым.
Дальше отправляет `booking.created` в n8n.

Новый workflow должен:
1. создать событие Google Calendar;
2. вернуть сайту JSON с `event_id`;
3. сайт сохранит `event_id` в `booking.calendar_event_id`.

При отмене сайт отправляет `booking.cancelled` с:
- `id`;
- `event_id`;
- `booking_ref`;
- `slot_start_msk`;
- `slot_end_msk`;
- `slot_label`;
- `name`;
- `contact`;
- `cancelled_by`.

n8n удаляет событие по `event_id`.

## Импорт

Импортируйте:

`deploy/n8n_dkorworld2_lead_workflow.json`

После импорта вручную выберите:
- Header Auth credential для Webhook;
- Google Calendar credential;
- нужный календарь в обеих Google Calendar нодах.

## Header Auth

Имя заголовка:

`X-DKOR-Webhook-Secret`

Значение должно совпадать с `N8N_WEBHOOK_SECRET` из `.env`.

## Production URL

Workflow должен быть активирован.

В `.env` сайта:

```env
N8N_LEAD_WEBHOOK_URL=https://ВАШ_N8N_ДОМЕН/webhook/dkorworld2-lead
N8N_WEBHOOK_SECRET=тот_же_секрет
```

Не используйте `/webhook-test/` для постоянной работы.

## Время

Сайт отправляет:

`2026-09-11T15:00:00+03:00`

Это уже московское время с явным UTC+3.
Дополнительный сдвиг времени в n8n не нужен.

## Важная проверка

После создания записи откройте админку.
В колонке `Calendar` должно появиться `sync`.

Если стоит `local`, запись в SQLite сохранена, но `event_id` от n8n не вернулся.
Проверьте выполнение workflow и output Google Calendar node.

## Отмена

Ссылка отмены теперь безопасна:
- GET только показывает подтверждение;
- удаление выполняется только POST + CSRF.

Telegram может делать preview ссылки — запись от этого больше не отменится.

## Данные после Telegram-ноды

Если позднее добавите Telegram / Sheets между узлами, не полагайтесь на `$json`
после этих нод. Исходное событие берите так:

`$('Webhook').first().json.body.payload`
