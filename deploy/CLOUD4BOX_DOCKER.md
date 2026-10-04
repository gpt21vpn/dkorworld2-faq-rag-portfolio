# Cloud4box Docker deployment

This package is prepared for the existing Cloud4box host.

- image: `dkorworld/portfolio-site:13.0` + `dkorworld/portfolio-faq-rag:13.0`
- containers: `dkorworld2-site` and `dkorworld2-faq-rag`
- app port inside Docker network: `8008`
- persistent SQLite/runtime directory: `./instance:/app/instance`
- external Caddy network: `n8n-automation_default`
- `.env` is intentionally excluded from the Docker image.

The site supports optional `PROXY_URL`, `TELEGRAM_PROXY`, and `GROQ_PROXY`.
On the current Cloud4box network, OpenAI and Telegram should use the working outbound proxy.

Build the image locally, save it as a tar file, copy it to the server, load it, and start with:

```bash
docker compose up -d --no-build
```

Do not use `docker compose down -v` for neighboring projects.


PECF11 note: the FAQ FastAPI service is internal on `app_net` port 8011; Caddy still exposes only the Flask site.
