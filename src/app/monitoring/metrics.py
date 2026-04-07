import time
import logging
import psutil
from fastapi import FastAPI, Request
from prometheus_client import start_http_server, Counter, Histogram, Gauge
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.exporter.prometheus import PrometheusMetricReader

logger = logging.getLogger(__name__)

reader = PrometheusMetricReader()
provider = MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)
meter = metrics.get_meter("llmplatform")

# ── Existing request-level metrics ────────────────────────────────────────────

REQUESTS_COUNTER = Counter(
    'llm_platform_requests_total',
    'Total number of requests to the platform',
    ['method', 'path', 'status_code', 'provider']
)

REQUEST_DURATION = Histogram(
    'llm_platform_request_duration_seconds',
    'Duration of requests in seconds',
    ['method', 'path', 'provider'],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, float("inf"))
)

CPU_USAGE = Gauge(
    'llm_platform_cpu_usage_percent',
    'Current CPU usage of the balancer process in percent'
)

# ── LLM-specific metrics ──────────────────────────────────────────────────────

LLM_TTFT = Histogram(
    'llm_ttft_seconds',
    'Time to first token (seconds) per provider',
    ['provider'],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, float("inf"))
)

LLM_TPOT = Histogram(
    'llm_tpot_milliseconds',
    'Time per output token (milliseconds) per provider',
    ['provider'],
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, float("inf"))
)

LLM_INPUT_TOKENS = Counter(
    'llm_input_tokens_total',
    'Cumulative input tokens processed per provider',
    ['provider']
)

LLM_OUTPUT_TOKENS = Counter(
    'llm_output_tokens_total',
    'Cumulative output tokens generated per provider',
    ['provider']
)

LLM_COST_USD = Counter(
    'llm_request_cost_usd_total',
    'Cumulative estimated request cost in USD per provider',
    ['provider']
)


def record_llm_metrics(
    provider_name: str,
    ttft_s: float,
    tpot_ms: float,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    """Record per-completion LLM metrics into Prometheus."""
    LLM_TTFT.labels(provider=provider_name).observe(ttft_s)
    if tpot_ms > 0:
        LLM_TPOT.labels(provider=provider_name).observe(tpot_ms)
    if input_tokens > 0:
        LLM_INPUT_TOKENS.labels(provider=provider_name).inc(input_tokens)
    if output_tokens > 0:
        LLM_OUTPUT_TOKENS.labels(provider=provider_name).inc(output_tokens)
    if cost_usd > 0:
        LLM_COST_USD.labels(provider=provider_name).inc(cost_usd)


# ── Middleware setup ──────────────────────────────────────────────────────────

def setup_metrics(app: FastAPI):
    # [ ]: replace hardcoded port with config
    start_http_server(port=9464)
    logger.info("Prometheus metrics server started on port 9464")

    @app.middleware("http")
    async def monitor_requests(request: Request, call_next):
        if request.url.path in ["/health", "/metrics"]:
            return await call_next(request)

        method = request.method
        path = request.url.path

        start_time = time.time()
        CPU_USAGE.set(psutil.cpu_percent(interval=None))

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as e:
            status_code = 500
            raise e
        finally:
            duration = time.time() - start_time
            provider_name = request.scope.get("chosen_provider", "unknown")

            REQUESTS_COUNTER.labels(
                method=method,
                path=path,
                status_code=status_code,
                provider=provider_name
            ).inc()

            if status_code != 500:
                REQUEST_DURATION.labels(
                    method=method,
                    path=path,
                    provider=provider_name
                ).observe(duration)

        return response
