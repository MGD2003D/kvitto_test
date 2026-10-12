# Kvitto Payments API

API приёма оплаты курсов: тарифы, платежи с промокодом и рассрочкой, вебхуки банка.

- Требования: [SPEC.md](SPEC.md)
- Принятые решения: [ASSUMPTIONS.md](ASSUMPTIONS.md)
- Работа с ИИ: [AI_LOG.md](AI_LOG.md)

## Запуск

Нужен Docker

```sh
cp .env.example .env
docker compose up -d --build
```

Документация и запросы из браузера: <http://localhost:8000/docs>.
Остановить: `docker compose down`.

## Тесты

Нужен [uv](https://docs.astral.sh/uv/). База для тестов — SQLite в памяти, внешние сервисы не нужны.

```sh
uv sync
uv run pytest
```

Тесты и линтер также запускаются в GitHub Actions на каждый push.

## Примеры запросов

Выполняются в bash (Linux, macOS, на Windows — WSL или Git Bash) из корня проекта:
вебхук читает `WEBHOOK_SECRET` из `.env`. Запускать можно сразу после старта (тк есть seed миграция)

```sh
# Тарифы
curl -s localhost:8000/tariffs

# Платёж в рассрочку с промокодом; id сохраняется для вебхука
PAYMENT_ID=$(curl -s -X POST localhost:8000/payments \
  -H 'Content-Type: application/json' \
  -d '{"tariff_id": 2, "email": "student@example.com", "method": "installment", "installment_months": 3, "promo_code": "kvitto10"}' \
  | sed -E 's/.*"id":"([^"]+)".*/\1/')
curl -s localhost:8000/payments/$PAYMENT_ID

# Вебхук банка: оплата прошла (подпись — HMAC-SHA256 от тела с WEBHOOK_SECRET из .env)
WEBHOOK_SECRET=$(grep '^WEBHOOK_SECRET=' .env | cut -d= -f2-)
BODY="{\"payment_id\":\"$PAYMENT_ID\",\"status\":\"succeeded\"}"
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | awk '{print $NF}')
curl -s -X POST localhost:8000/webhooks/bank \
  -H 'Content-Type: application/json' \
  -H "X-Signature: $SIG" \
  -d "$BODY"
```