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

def setup_metrics(app: FastAPI):
    # [ ]: replace hardcoded port with config
    start_http_server(port=9464)
    logger.info("Prometheus metrics server started on port 9464")

    @app.middleware("http")
    async def monitor_requests(request: Request, call_next):
        # Игнорируем health-checks и сами метрики, чтобы не засорять статистику
        if request.url.path in ["/health", "/metrics"]:
            return await call_next(request)

        method = request.method
        path = request.url.path
        
        # Начинаем отсчёт времени
        start_time = time.time()
        
        # Обновляем метрику CPU перед обработкой запроса
        CPU_USAGE.set(psutil.cpu_percent(interval=None))
        
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as e:
            status_code = 500
            raise e
        finally:
            # Запрос завершен. Вычисляем длительность.
            duration = time.time() - start_time
            
            # Получаем имя провайдера, которое Middleware routes.py положил в request.scope
            # (нам нужно немного обновить routes.py, см. Шаг 3)
            provider_name = request.scope.get("chosen_provider", "unknown")

            # Записываем метрики
            REQUESTS_COUNTER.labels(
                method=method, 
                path=path, 
                status_code=status_code, 
                provider=provider_name
            ).inc()
            
            # Длительность пишем только для успешных или LLM-ошибок (4xx), не для падений прокси
            if status_code != 500:
                REQUEST_DURATION.labels(
                    method=method, 
                    path=path, 
                    provider=provider_name
                ).observe(duration)

        return response