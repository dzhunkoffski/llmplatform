# LLM Platform — API Gateway & Smart Balancer

Умный балансировщик LLM-запросов с реестром агентов, мониторингом и трассировкой.

## Содержание

- [Архитектура](#архитектура)
- [Быстрый старт](#быстрый-старт)
- [Развёртывание](#развёртывание)
- [Конфигурация провайдеров](#конфигурация-провайдеров)
- [API Reference](#api-reference)
  - [Балансировщик / Прокси](#балансировщик--прокси)
  - [Управление провайдерами](#управление-провайдерами)
  - [Реестр агентов](#реестр-агентов)
  - [Мониторинг и служебные эндпоинты](#мониторинг-и-служебные-эндпоинты)
- [Алгоритм маршрутизации](#алгоритм-маршрутизации)
- [Метрики Prometheus](#метрики-prometheus)
- [Трассировка в MLflow](#трассировка-в-mlflow)
- [Устранение неполадок](#устранение-неполадок)

---

## Архитектура

```
Клиент
  │
  ▼
┌─────────────────────────────────┐
│   Balancer  :8000               │   ← FastAPI + SmartBalancer
│   Metrics   :9464               │   ← Prometheus endpoint
└────────┬──────────┬─────────────┘
         │          │   model-aware routing
         ▼          ▼
  ┌──────────┐  ┌──────────┐
  │provider-1│  │provider-2│       ← Ollama :11434
  └──────────┘  └──────────┘

┌──────────┐  ┌──────────┐  ┌───────────┐
│  Redis   │  │  MLflow  │  │Prometheus │  → Grafana :3000
│  :6379   │  │  :5000   │  │  :9090    │
└──────────┘  └──────────┘  └───────────┘
```

| Сервис | Порт | Назначение |
|---|---|---|
| `balancer` | 8000 | API Gateway — единая точка входа |
| `balancer` | 9464 | Prometheus metrics scrape endpoint |
| `provider-1/2` | 11434 | Ollama LLM-провайдеры (внутренняя сеть) |
| `redis` | 6379 | Хранилище реестров провайдеров и агентов |
| `mlflow` | 5000 | Трассировка LLM-вызовов и операций агентов |
| `prometheus` | 9090 | Сбор и хранение метрик |
| `grafana` | 3000 | Дашборды |

---

## Быстрый старт

### Предварительные требования

- [Docker](https://docs.docker.com/get-docker/) >= 24.0
- [Docker Compose](https://docs.docker.com/compose/) >= 2.20
- NVIDIA GPU + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) (опционально, для GPU-ускорения Ollama)

### 1. Клонирование и настройка переменных окружения

```bash
git clone <repo-url>
cd llmplatform

# Создайте файл с секретами
cat > .env <<'EOF'
ADMIN_KEY=your-secret-admin-key
EOF
```

> `ADMIN_KEY` используется для защиты административных эндпоинтов (управление провайдерами).
> По умолчанию — `admin`; **обязательно смените в продакшене**.

### 2. Запуск

```bash
docker compose up -d
```

Docker Compose автоматически:
1. Запустит Redis, MLflow, оба Ollama-провайдера
2. Дождётся их `healthy`-состояния
3. Запустит балансировщик
4. Скачает модель `qwen:0.5b` на `provider-1` через `ollama-init`

### 3. Проверка готовности

```bash
# Балансировщик
curl http://localhost:8000/health
# {"status":"ok"}

# Prometheus собирает метрики
curl -s http://localhost:9464/metrics | head -20

# Grafana — http://localhost:3000  (admin / admin)
# MLflow   — http://localhost:5000
```

### 4. Первый запрос

```bash
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen:0.5b",
    "messages": [{"role": "user", "content": "Привет!"}],
    "stream": true
  }'
```

---

## Развёртывание

### Без GPU (CPU-режим)

Закомментируйте секцию `deploy.resources` в `docker-compose.yml` для `provider-1` и `provider-2`:

```yaml
# deploy:
#   resources:
#     reservations:
#       devices:
#         - driver: nvidia
#           count: 1
#           capabilities: [gpu]
```

### Подключение внешних провайдеров (OpenAI, Anthropic и т.д.)

Внешние провайдеры регистрируются динамически через API (см. [Управление провайдерами](#управление-провайдерами)) без изменения `docker-compose.yml`.

Пример для OpenAI:

```bash
curl -X POST http://localhost:8000/providers/register \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: your-secret-admin-key" \
  -d '{
    "name": "openai",
    "url": "https://api.openai.com",
    "api_key": "sk-...",
    "models": ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
    "token_price": 0.005,
    "priority": 1
  }'
```

### Остановка и очистка

```bash
# Остановить все сервисы (данные сохраняются в volumes)
docker compose down

# Остановить и удалить все данные
docker compose down -v
```

### Просмотр логов

```bash
# Все сервисы
docker compose logs -f

# Только балансировщик
docker compose logs -f balancer

# Файл детальных логов внутри контейнера
docker exec llm_balancer cat app.log
```

---

## Конфигурация провайдеров

Провайдеры регистрируются **динамически** через REST API. Данные хранятся в Redis и переживают перезапуск балансировщика.

### Поля провайдера

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `name` | string | да | Отображаемое имя провайдера |
| `url` | string | да | Базовый URL провайдера (без `/v1/chat/completions`) |
| `api_key` | string | нет | Bearer-токен для внешних API |
| `models` | string[] | нет | Список поддерживаемых моделей. **Пустой массив = обслуживает любую модель** |
| `model_alias` | string | нет | Перезаписывает поле `model` в запросе перед отправкой провайдеру |
| `token_price` | float | нет | Цена за 1 000 токенов в USD (по умолчанию `0.0`) |
| `rate_limit` | int | нет | Максимум запросов в минуту (`0` = без ограничений) |
| `priority` | int | нет | Приоритет: меньше = выше (по умолчанию `1`) |
| `is_active` | bool | нет | Включён ли провайдер (по умолчанию `true`) |

### Примеры регистрации

**Локальный Ollama с конкретными моделями:**
```bash
curl -X POST http://localhost:8000/providers/register \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: your-secret-admin-key" \
  -d '{
    "name": "ollama-local",
    "url": "http://provider-1:11434",
    "models": ["qwen:0.5b", "llama3:8b"],
    "priority": 2
  }'
```

**Несколько реплик одной модели (round-robin через latency):**
```bash
# Replica A
curl -X POST http://localhost:8000/providers/register \
  -H "X-Admin-Key: your-secret-admin-key" \
  -H "Content-Type: application/json" \
  -d '{"name":"ollama-a","url":"http://provider-1:11434","models":["qwen:0.5b"],"priority":1}'

# Replica B — тот же priority, балансировщик выберет по latency
curl -X POST http://localhost:8000/providers/register \
  -H "X-Admin-Key: your-secret-admin-key" \
  -H "Content-Type: application/json" \
  -d '{"name":"ollama-b","url":"http://provider-2:11434","models":["qwen:0.5b"],"priority":1}'
```

---

## API Reference

Базовый URL: `http://localhost:8000`

Интерактивная документация Swagger UI: **http://localhost:8000/docs**

---

### Балансировщик / Прокси

#### `POST /v1/chat/completions`

Принимает запрос в формате OpenAI Chat Completions, выбирает подходящего провайдера и проксирует запрос с поддержкой потоковой передачи (SSE).

**Заголовки:**
| Заголовок | Значение |
|---|---|
| `Content-Type` | `application/json` |

**Тело запроса** (OpenAI-совместимый формат):

```json
{
  "model": "qwen:0.5b",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Объясни балансировку нагрузки."}
  ],
  "stream": true,
  "temperature": 0.7,
  "max_tokens": 512
}
```

| Поле | Тип | Описание |
|---|---|---|
| `model` | string | Имя модели. Используется для маршрутизации к нужному провайдеру |
| `messages` | array | История диалога |
| `stream` | bool | `true` — SSE-поток; `false` — единый JSON-ответ |
| `temperature` | float | Температура генерации (0.0–2.0) |
| `max_tokens` | int | Максимальная длина ответа в токенах |

**Ответ (stream: true)** — Server-Sent Events:

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"delta":{"content":"Привет"},"index":0}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"delta":{"content":"!"},"index":0}]}

data: [DONE]
```

**Ответ (stream: false)**:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "choices": [{
    "message": {"role": "assistant", "content": "Привет!"},
    "finish_reason": "stop",
    "index": 0
  }],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 5,
    "total_tokens": 17
  }
}
```

**Коды ответов:**
| Код | Описание |
|---|---|
| 200 | Успешный ответ (или начало потока) |
| 503 | Все провайдеры недоступны (circuit open) |

**Пример:**
```bash
# Потоковый запрос
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen:0.5b",
    "messages": [{"role": "user", "content": "Что такое LLM?"}],
    "stream": true
  }'
```

---

### Управление провайдерами

Все эндпоинты требуют заголовок **`X-Admin-Key`**.

---

#### `POST /providers/register`

Зарегистрировать нового LLM-провайдера.

**Заголовки:** `X-Admin-Key`, `Content-Type: application/json`

**Тело запроса:**
```json
{
  "name": "openai-gpt4",
  "url": "https://api.openai.com",
  "api_key": "sk-...",
  "models": ["gpt-4o", "gpt-4-turbo"],
  "model_alias": null,
  "token_price": 0.005,
  "rate_limit": 0,
  "priority": 1,
  "is_active": true
}
```

**Ответ `201 Created`:**
```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "name": "openai-gpt4",
  "url": "https://api.openai.com",
  "api_key": "****...sk-1",
  "models": ["gpt-4o", "gpt-4-turbo"],
  "model_alias": null,
  "token_price": 0.005,
  "rate_limit": 0,
  "priority": 1,
  "is_active": true
}
```

> `api_key` в ответе маскируется: отображаются только последние 4 символа.

---

#### `GET /providers`

Список всех зарегистрированных провайдеров.

**Ответ `200 OK`:** массив объектов `ProviderResponse` (см. выше).

```bash
curl http://localhost:8000/providers \
  -H "X-Admin-Key: your-secret-admin-key"
```

---

#### `GET /providers/{provider_id}`

Получить провайдера по ID.

**Ответ `200 OK`:** объект `ProviderResponse`.
**Ответ `404 Not Found`:** `{"detail": "Provider not found"}`

---

#### `PATCH /providers/{provider_id}`

Частично обновить параметры провайдера. Незаданные поля не изменяются.

**Тело запроса** (все поля опциональные):
```json
{
  "is_active": false,
  "priority": 2,
  "token_price": 0.003,
  "models": ["gpt-4o"]
}
```

**Ответ `200 OK`:** обновлённый `ProviderResponse`.

```bash
# Деактивировать провайдера
curl -X PATCH http://localhost:8000/providers/<id> \
  -H "X-Admin-Key: your-secret-admin-key" \
  -H "Content-Type: application/json" \
  -d '{"is_active": false}'
```

---

#### `DELETE /providers/{provider_id}`

Удалить провайдера из реестра.

**Ответ `204 No Content`** — успешно удалён.
**Ответ `404 Not Found`** — провайдер не найден.

---

#### `GET /providers/health`

Состояние circuit breaker и метрики латентности для каждого провайдера.

**Ответ `200 OK`:**
```json
[
  {
    "id": "3fa85f64-...",
    "name": "ollama-local",
    "url": "http://provider-1:11434",
    "circuit_state": "closed",
    "avg_latency_ms": 342.5,
    "total_requests": 150,
    "total_errors": 2,
    "consecutive_errors": 0,
    "last_failure_time": 1712345600.0,
    "last_success_time": 1712348800.0
  }
]
```

| Поле | Описание |
|---|---|
| `circuit_state` | `closed` — норма; `open` — провайдер исключён из пула; `half_open` — проба после восстановления |
| `avg_latency_ms` | Экспоненциальное скользящее среднее TTFT в миллисекундах |
| `consecutive_errors` | Число ошибок подряд (порог открытия circuit: 3) |

---

### Реестр агентов

Управление A2A-агентами. Аутентификация не требуется.

---

#### `POST /agents/register`

Зарегистрировать агента с его Agent Card.

**Тело запроса:**
```json
{
  "name": "summarizer-agent",
  "description": "Суммаризирует длинные тексты с помощью LLM",
  "supported_methods": ["summarize", "extract_keywords"],
  "url": "http://summarizer-agent:9000",
  "metadata": {
    "version": "1.2.0",
    "max_input_tokens": 32000
  }
}
```

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `name` | string | да | Уникальное имя агента |
| `description` | string | да | Описание возможностей |
| `supported_methods` | string[] | да | Список поддерживаемых методов/операций |
| `url` | string | нет | Endpoint агента для прямых вызовов |
| `metadata` | object | нет | Произвольные дополнительные данные |

**Ответ `201 Created`:**
```json
{
  "id": "a1b2c3d4-...",
  "name": "summarizer-agent",
  "description": "Суммаризирует длинные тексты с помощью LLM",
  "supported_methods": ["summarize", "extract_keywords"],
  "url": "http://summarizer-agent:9000",
  "metadata": {"version": "1.2.0", "max_input_tokens": 32000}
}
```

```bash
curl -X POST http://localhost:8000/agents/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "summarizer-agent",
    "description": "Суммаризирует тексты",
    "supported_methods": ["summarize"]
  }'
```

---

#### `GET /agents`

Список всех зарегистрированных агентов.

**Ответ `200 OK`:** массив `AgentCard`.

```bash
curl http://localhost:8000/agents
```

---

#### `GET /agents/{agent_id}`

Получить Agent Card по ID.

**Ответ `200 OK`:** объект `AgentCard`.
**Ответ `404 Not Found`:** `{"detail": "Agent '<id>' not found"}`

---

#### `PATCH /agents/{agent_id}`

Частично обновить Agent Card.

**Тело запроса** (все поля опциональные):
```json
{
  "supported_methods": ["summarize", "translate"],
  "metadata": {"version": "1.3.0"}
}
```

**Ответ `200 OK`:** обновлённая `AgentCard`.

---

#### `DELETE /agents/{agent_id}`

Удалить агента из реестра.

**Ответ `204 No Content`** — успешно.
**Ответ `404 Not Found`** — агент не найден.

---

### Мониторинг и служебные эндпоинты

#### `GET /health`

Проверка доступности балансировщика. Используется Docker healthcheck.

**Ответ `200 OK`:**
```json
{"status": "ok"}
```

---

#### `GET /metrics` (порт 9464)

Prometheus scrape endpoint. Возвращает все метрики в формате Prometheus text exposition.

```bash
curl http://localhost:9464/metrics
```

---

## Алгоритм маршрутизации

Для каждого входящего запроса `POST /v1/chat/completions`:

```
1. Извлечь model из тела запроса
        │
        ▼
2. Загрузить активных провайдеров из реестра (Redis)
        │
        ▼
3. Фильтр по model:
   - Провайдеры, у которых models содержит запрошенную модель
   - Провайдеры с пустым models [] — wildcards, всегда в пуле
   - Если ни один не подходит — используются все активные (warning в лог)
        │
        ▼
4. Фильтр по circuit breaker:
   - Исключить провайдеров с state = OPEN
   - Если все OPEN — вернуть 503
        │
        ▼
5. Выбрать группу с наименьшим priority (наивысший приоритет)
        │
        ▼
6. Внутри группы — выбрать провайдера с минимальным EMA-TTFT
   (новые провайдеры без измерений получают нейтральный placeholder = 1.0s)
        │
        ▼
7. Опционально: перезаписать model → model_alias провайдера
        │
        ▼
8. Проксировать запрос, сохраняя SSE-поток
```

**Circuit Breaker:**
- `CLOSED` → `OPEN`: 3 последовательные ошибки (5xx, timeout)
- `OPEN` → `HALF_OPEN`: через 60 секунд
- `HALF_OPEN` → `CLOSED`: успешный запрос
- `HALF_OPEN` → `OPEN`: ещё одна ошибка

**Fallback:** если ни один провайдер не зарегистрирован в Redis, используется статический список из `settings.PROVIDERS` с round-robin.

---

## Метрики Prometheus

Scrape endpoint: `http://localhost:9464/metrics`

### Метрики запросов

| Метрика | Тип | Лейблы | Описание |
|---|---|---|---|
| `llm_platform_requests_total` | Counter | `method`, `path`, `status_code`, `provider` | Общее число запросов |
| `llm_platform_request_duration_seconds` | Histogram | `method`, `path`, `provider` | Полное время ответа (p50, p95, p99) |
| `llm_platform_cpu_usage_percent` | Gauge | — | Загрузка CPU процесса балансировщика |

### LLM-метрики

| Метрика | Тип | Лейблы | Описание |
|---|---|---|---|
| `llm_ttft_seconds` | Histogram | `provider` | Time-to-first-token в секундах |
| `llm_tpot_milliseconds` | Histogram | `provider` | Time-per-output-token в миллисекундах |
| `llm_input_tokens_total` | Counter | `provider` | Суммарные входные токены |
| `llm_output_tokens_total` | Counter | `provider` | Суммарные выходные токены |
| `llm_request_cost_usd_total` | Counter | `provider` | Суммарная стоимость запросов в USD |

### Примеры PromQL-запросов

```promql
# p95 латентность за последние 5 минут
histogram_quantile(0.95,
  rate(llm_platform_request_duration_seconds_bucket[5m])
)

# Запросов в секунду по провайдерам
rate(llm_platform_requests_total[1m])

# Среднее TTFT по провайдеру
histogram_quantile(0.50, rate(llm_ttft_seconds_bucket[5m]))

# Коэффициент ошибок
rate(llm_platform_requests_total{status_code=~"5.."}[5m])
  / rate(llm_platform_requests_total[5m])
```

---

## Трассировка в MLflow

MLflow UI доступен на **http://localhost:5000**.

Все операции записываются в два эксперимента:

### Эксперимент `llm_calls`

Каждый завершённый LLM-запрос создаёт run с именем `{provider_name}_completion`.

**Теги:** `provider_id`, `provider_name`, `model`, `status`

**Метрики:**
| Метрика | Описание |
|---|---|
| `ttft_seconds` | Время до первого токена |
| `tpot_ms` | Время на токен (мс) |
| `input_tokens` | Число входных токенов |
| `output_tokens` | Число выходных токенов |
| `cost_usd` | Стоимость запроса |
| `total_duration_s` | Полное время выполнения |

### Эксперимент `agent_operations`

Каждая операция с реестром агентов (register/update/unregister) создаёт run с именем `agent_{operation}`.

**Теги:** `operation`, `agent_id`, `agent_name`, `status`

**Метрики:**
| Метрика | Описание |
|---|---|
| `duration_ms` | Время выполнения операции |
| `success` | `1.0` = успех, `0.0` = ошибка |

---

## Устранение неполадок

### Балансировщик возвращает 503

```bash
# Проверить состояние circuit breaker всех провайдеров
curl http://localhost:8000/providers/health \
  -H "X-Admin-Key: your-secret-admin-key"
```

Circuit в состоянии `open` восстанавливается автоматически через 60 секунд.

### Модель не найдена у провайдера

Убедитесь, что модель скачана на нужном Ollama-провайдере:

```bash
docker exec provider-1 ollama list
docker exec provider-1 ollama pull <model-name>
```

### Нет метрик в Grafana

1. Проверьте, что Prometheus достигает балансировщика:
   ```
   http://localhost:9090/targets
   ```
   Статус `llm_balancer` должен быть `UP`.

2. Убедитесь, что datasource в Grafana настроен на `http://prometheus:9090`.

### Медленный старт

`ollama-init` скачивает `qwen:0.5b` (~300 MB) при первом запуске — это занимает время в зависимости от скорости интернета. Следить за прогрессом:

```bash
docker compose logs -f ollama-init
```

### Посмотреть детальные логи балансировщика

```bash
docker compose logs -f balancer
# или файл с debug-уровнем
docker exec llm_balancer cat app.log
```
