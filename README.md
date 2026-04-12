# LLM Platform — API Gateway & Smart Balancer

A smart LLM request balancer with an agent registry, monitoring, and tracing.

## Table of Contents

- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Deployment](#deployment)
- [Provider Configuration](#provider-configuration)
- [API Reference](#api-reference)
  - [Balancer / Proxy](#balancer--proxy)
  - [Provider Management](#provider-management)
  - [Agent Registry](#agent-registry)
  - [Monitoring & Utility Endpoints](#monitoring--utility-endpoints)
- [Routing Algorithm](#routing-algorithm)
- [Prometheus Metrics](#prometheus-metrics)
- [MLflow Tracing](#mlflow-tracing)
- [Troubleshooting](#troubleshooting)

---

## Architecture

```
Client
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

| Service | Port | Purpose |
|---|---|---|
| `balancer` | 8000 | API Gateway — single entry point |
| `balancer` | 9464 | Prometheus metrics scrape endpoint |
| `provider-1/2` | 11434 | Ollama LLM providers (internal network) |
| `redis` | 6379 | Storage for provider and agent registries |
| `mlflow` | 5000 | Tracing for LLM calls and agent operations |
| `prometheus` | 9090 | Metrics collection and storage |
| `grafana` | 3000 | Dashboards |

---

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) >= 24.0
- [Docker Compose](https://docs.docker.com/compose/) >= 2.20
- NVIDIA GPU + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) (optional, for GPU-accelerated Ollama)

### 1. Clone and configure environment variables

```bash
git clone https://github.com/dzhunkoffski/llmplatform
cd llmplatform

# Create the secrets file
cat > .env <<'EOF'
ADMIN_KEY=your-secret-admin-key
EOF
```

> `ADMIN_KEY` protects all admin endpoints (provider management).
> Defaults to `admin` — **change this in production**.

### 2. Start

```bash
docker compose up -d
```

Docker Compose will automatically:
1. Start Redis, MLflow, and both Ollama providers
2. Wait for all of them to become `healthy`
3. Start the balancer
4. Pull the `qwen:0.5b` model onto `provider-1` via `ollama-init`

### 3. Verify readiness

```bash
# Balancer
curl http://localhost:8000/health
# {"status":"ok"}

# Prometheus is scraping metrics
curl -s http://localhost:9464/metrics | head -20

# Grafana — http://localhost:3000  (admin / admin)
# MLflow   — http://localhost:5000
```

### 4. First request

```bash
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen:0.5b",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

---

## Deployment

### Without GPU (CPU mode)

Comment out the `deploy.resources` section in `docker-compose.yml` for both `provider-1` and `provider-2`:

```yaml
# deploy:
#   resources:
#     reservations:
#       devices:
#         - driver: nvidia
#           count: 1
#           capabilities: [gpu]
```

### Connecting external providers (OpenAI, Anthropic, etc.)

External providers are registered dynamically via the API (see [Provider Management](#provider-management)) — no changes to `docker-compose.yml` required.

Example for OpenAI:

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

### Stop and clean up

```bash
# Stop all services (data is preserved in volumes)
docker compose down

# Stop all services and delete all data
docker compose down -v
```

### View logs

```bash
# All services
docker compose logs -f

# Balancer only
docker compose logs -f balancer

# Detailed debug log file inside the container
docker exec llm_balancer cat app.log
```

---

## Provider Configuration

Providers are registered **dynamically** via the REST API. Data is stored in Redis and survives balancer restarts.

> **Important — URL format:** The balancer always appends `/v1/chat/completions` to the provider URL internally. Register only the **base URL without any path**. Adding `/v1` or `/v1/chat/completions` to the URL will result in a doubled path and a 404 from the provider.
>
> | Provider | Correct `url` value |
> |---|---|
> | OpenRouter | `https://openrouter.ai/api` |
> | OpenAI | `https://api.openai.com` |
> | Anthropic (OpenAI-compat) | `https://api.anthropic.com` |
> | Local Ollama | `http://provider-1:11434` |

### Provider fields

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Display name of the provider |
| `url` | string | yes | Base URL of the provider (without `/v1/chat/completions`) |
| `api_key` | string | no | Bearer token for external APIs |
| `models` | string[] | no | List of supported model names. **Empty array = serves any model** |
| `model_alias` | string | no | Rewrites the `model` field in the request before forwarding to this provider |
| `token_price` | float | no | Price per 1,000 tokens in USD (default `0.0`) |
| `rate_limit` | int | no | Max requests per minute (`0` = unlimited) |
| `priority` | int | no | Lower value = higher priority (default `1`) |
| `is_active` | bool | no | Whether the provider is enabled (default `true`) |

### Registration examples

**Local Ollama with specific models:**
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

**External provider with an API key (OpenAI, Anthropic, etc.):**
```bash
curl -X POST http://localhost:8000/providers/register \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: your-secret-admin-key" \
  -d '{
    "name": "openai-gpt4o",
    "url": "https://api.openai.com",
    "api_key": "sk-...",
    "models": ["gpt-4o", "gpt-4-turbo"],
    "token_price": 0.005,
    "priority": 1
  }'
```

The `api_key` value is sent as a `Bearer` token in the `Authorization` header of every request forwarded to that provider. It is stored in Redis and masked (`****<last 4 chars>`) in all API responses.

**Multiple replicas of the same model (latency-based selection):**
```bash
# Replica A
curl -X POST http://localhost:8000/providers/register \
  -H "X-Admin-Key: your-secret-admin-key" \
  -H "Content-Type: application/json" \
  -d '{"name":"ollama-a","url":"http://provider-1:11434","models":["qwen:0.5b"],"priority":1}'

# Replica B — same priority, balancer picks by latency
curl -X POST http://localhost:8000/providers/register \
  -H "X-Admin-Key: your-secret-admin-key" \
  -H "Content-Type: application/json" \
  -d '{"name":"ollama-b","url":"http://provider-2:11434","models":["qwen:0.5b"],"priority":1}'
```

---

## API Reference

Base URL: `http://localhost:8000`

Interactive Swagger UI: **http://localhost:8000/docs**

---

### Balancer / Proxy

#### `POST /v1/chat/completions`

Accepts an OpenAI Chat Completions request, selects the appropriate provider, and proxies the request with full streaming (SSE) support.

**Headers:**
| Header | Value |
|---|---|
| `Content-Type` | `application/json` |

**Request body** (OpenAI-compatible format):

```json
{
  "model": "qwen:0.5b",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Explain load balancing."}
  ],
  "stream": true,
  "temperature": 0.7,
  "max_tokens": 512
}
```

| Field | Type | Description |
|---|---|---|
| `model` | string | Model name. Used to route the request to the correct provider |
| `messages` | array | Conversation history |
| `stream` | bool | `true` — SSE stream; `false` — single JSON response |
| `temperature` | float | Sampling temperature (0.0–2.0) |
| `max_tokens` | int | Maximum number of tokens to generate |

**Response (stream: true)** — Server-Sent Events:

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"delta":{"content":"Hello"},"index":0}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"delta":{"content":"!"},"index":0}]}

data: [DONE]
```

**Response (stream: false)**:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "choices": [{
    "message": {"role": "assistant", "content": "Hello!"},
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

**Response codes:**
| Code | Description |
|---|---|
| 200 | Successful response (or start of stream) |
| 503 | All providers unavailable (circuit open) |

**Example:**
```bash
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen:0.5b",
    "messages": [{"role": "user", "content": "What is an LLM?"}],
    "stream": true
  }'
```

---

### Provider Management

All endpoints require the **`X-Admin-Key`** header.

---

#### `POST /providers/register`

Register a new LLM provider.

**Headers:** `X-Admin-Key`, `Content-Type: application/json`

**Request body:**
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

**Response `201 Created`:**
```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "name": "openai-gpt4",
  "url": "https://api.openai.com",
  "api_key": "****sk-1",
  "models": ["gpt-4o", "gpt-4-turbo"],
  "model_alias": null,
  "token_price": 0.005,
  "rate_limit": 0,
  "priority": 1,
  "is_active": true
}
```

> `api_key` is masked in all responses — only the last 4 characters are shown.

---

#### `GET /providers`

List all registered providers.

**Response `200 OK`:** array of `ProviderResponse` objects (see above).

```bash
curl http://localhost:8000/providers \
  -H "X-Admin-Key: your-secret-admin-key"
```

---

#### `GET /providers/{provider_id}`

Get a provider by ID.

**Response `200 OK`:** `ProviderResponse` object.
**Response `404 Not Found`:** `{"detail": "Provider not found"}`

---

#### `PATCH /providers/{provider_id}`

Partially update a provider. Omitted fields are left unchanged.

**Request body** (all fields optional):
```json
{
  "is_active": false,
  "priority": 2,
  "token_price": 0.003,
  "models": ["gpt-4o"]
}
```

**Response `200 OK`:** updated `ProviderResponse`.

```bash
# Deactivate a provider
curl -X PATCH http://localhost:8000/providers/<id> \
  -H "X-Admin-Key: your-secret-admin-key" \
  -H "Content-Type: application/json" \
  -d '{"is_active": false}'
```

---

#### `DELETE /providers/{provider_id}`

Remove a provider from the registry.

**Response `204 No Content`** — successfully deleted.
**Response `404 Not Found`** — provider not found.

---

#### `GET /providers/health`

Circuit breaker state and latency metrics for every registered provider.

**Response `200 OK`:**
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

| Field | Description |
|---|---|
| `circuit_state` | `closed` — healthy; `open` — excluded from pool; `half_open` — probing after recovery window |
| `avg_latency_ms` | Exponential moving average of TTFT in milliseconds |
| `consecutive_errors` | Number of consecutive failures (circuit opens at 3) |

---

### Agent Registry

Manage A2A agents. No authentication required.

---

#### `POST /agents/register`

Register an agent with its Agent Card.

**Request body:**
```json
{
  "name": "summarizer-agent",
  "description": "Summarizes long texts using an LLM",
  "supported_methods": ["summarize", "extract_keywords"],
  "url": "http://summarizer-agent:9000",
  "metadata": {
    "version": "1.2.0",
    "max_input_tokens": 32000
  }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Unique agent name |
| `description` | string | yes | Description of the agent's capabilities |
| `supported_methods` | string[] | yes | List of supported methods / operations |
| `url` | string | no | Agent endpoint for direct calls |
| `metadata` | object | no | Arbitrary additional data |

**Response `201 Created`:**
```json
{
  "id": "a1b2c3d4-...",
  "name": "summarizer-agent",
  "description": "Summarizes long texts using an LLM",
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
    "description": "Summarizes texts",
    "supported_methods": ["summarize"]
  }'
```

---

#### `GET /agents`

List all registered agents.

**Response `200 OK`:** array of `AgentCard` objects.

```bash
curl http://localhost:8000/agents
```

---

#### `GET /agents/{agent_id}`

Get an Agent Card by ID.

**Response `200 OK`:** `AgentCard` object.
**Response `404 Not Found`:** `{"detail": "Agent '<id>' not found"}`

---

#### `PATCH /agents/{agent_id}`

Partially update an Agent Card.

**Request body** (all fields optional):
```json
{
  "supported_methods": ["summarize", "translate"],
  "metadata": {"version": "1.3.0"}
}
```

**Response `200 OK`:** updated `AgentCard`.

---

#### `DELETE /agents/{agent_id}`

Remove an agent from the registry.

**Response `204 No Content`** — successfully deleted.
**Response `404 Not Found`** — agent not found.

---

### Monitoring & Utility Endpoints

#### `GET /health`

Balancer liveness check. Used by Docker healthcheck.

**Response `200 OK`:**
```json
{"status": "ok"}
```

---

#### `GET /metrics` (port 9464)

Prometheus scrape endpoint. Returns all metrics in Prometheus text exposition format.

```bash
curl http://localhost:9464/metrics
```

---

## Routing Algorithm

For every incoming `POST /v1/chat/completions` request:

```
1. Extract model from request body
        │
        ▼
2. Load active providers from registry (Redis)
        │
        ▼
3. Filter by model name:
   - Keep providers whose models list contains the requested model
   - Providers with an empty models [] are wildcards — always included
   - If no provider matches — fall back to all active providers (warning logged)
        │
        ▼
4. Filter by circuit breaker state:
   - Exclude providers with state = OPEN
   - If all are OPEN — return 503
        │
        ▼
5. Select the group with the lowest priority value (highest priority)
        │
        ▼
6. Within the group — pick the provider with the lowest EMA-TTFT
   (new providers with no measurements get a neutral placeholder of 1.0s)
        │
        ▼
7. Optionally rewrite model → provider's model_alias
        │
        ▼
8. Proxy the request, preserving the SSE stream
```

**Circuit Breaker state transitions:**
- `CLOSED` → `OPEN`: 3 consecutive errors (5xx, timeout)
- `OPEN` → `HALF_OPEN`: after 60 seconds
- `HALF_OPEN` → `CLOSED`: one successful request
- `HALF_OPEN` → `OPEN`: one more error

**Fallback:** if no providers are registered in Redis, the static list from `settings.PROVIDERS` is used with round-robin selection.

---

## Prometheus Metrics

Scrape endpoint: `http://localhost:9464/metrics`

### Request metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `llm_platform_requests_total` | Counter | `method`, `path`, `status_code`, `provider` | Total number of requests |
| `llm_platform_request_duration_seconds` | Histogram | `method`, `path`, `provider` | Full response time (p50, p95, p99) |
| `llm_platform_cpu_usage_percent` | Gauge | — | CPU usage of the balancer process |

### LLM metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `llm_ttft_seconds` | Histogram | `provider` | Time-to-first-token in seconds |
| `llm_tpot_milliseconds` | Histogram | `provider` | Time-per-output-token in milliseconds |
| `llm_input_tokens_total` | Counter | `provider` | Cumulative input tokens processed |
| `llm_output_tokens_total` | Counter | `provider` | Cumulative output tokens generated |
| `llm_request_cost_usd_total` | Counter | `provider` | Cumulative estimated request cost in USD |

### Example PromQL queries

```promql
# p95 latency over the last 5 minutes
histogram_quantile(0.95,
  rate(llm_platform_request_duration_seconds_bucket[5m])
)

# Requests per second by provider
rate(llm_platform_requests_total[1m])

# Median TTFT per provider
histogram_quantile(0.50, rate(llm_ttft_seconds_bucket[5m]))

# Error rate
rate(llm_platform_requests_total{status_code=~"5.."}[5m])
  / rate(llm_platform_requests_total[5m])
```

---

## MLflow Tracing

MLflow UI is available at **http://localhost:5000**.

All operations are recorded in two experiments:

### Experiment `llm_calls`

Every completed LLM request creates a run named `{provider_name}_completion`.

**Tags:** `provider_id`, `provider_name`, `model`, `status`

**Metrics:**
| Metric | Description |
|---|---|
| `ttft_seconds` | Time to first token |
| `tpot_ms` | Time per output token (ms) |
| `input_tokens` | Number of input tokens |
| `output_tokens` | Number of output tokens |
| `cost_usd` | Estimated request cost |
| `total_duration_s` | Total request duration |

### Experiment `agent_operations`

Every agent registry operation (register / update / unregister) creates a run named `agent_{operation}`.

**Tags:** `operation`, `agent_id`, `agent_name`, `status`

**Metrics:**
| Metric | Description |
|---|---|
| `duration_ms` | Operation execution time |
| `success` | `1.0` = success, `0.0` = failure |

---