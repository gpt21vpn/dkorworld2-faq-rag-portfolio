FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY faq_service/requirements.txt /app/faq_service/requirements.txt
RUN pip install --no-cache-dir -r /app/faq_service/requirements.txt

COPY faq_service /app/faq_service
COPY data /app/data

EXPOSE 8011

CMD ["uvicorn", "faq_service.app:app", "--host", "0.0.0.0", "--port", "8011"]
