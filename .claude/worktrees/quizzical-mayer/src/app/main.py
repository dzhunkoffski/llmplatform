import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.routes import router
from app.api.registry_routes import registry_router
from app.api.provider_routes import provider_router
from app.core.config import settings
from app.monitoring.metrics import setup_metrics
from app.monitoring.mlflow_tracker import init_mlflow
from app.services.registry import registry
from app.services.provider_registry import provider_registry

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("app.log", encoding="utf-8")
    ]
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_mlflow(settings.MLFLOW_TRACKING_URI)
    yield
    await registry.close()
    await provider_registry.close()

app = FastAPI(title="Agent Platform API Gateway", lifespan=lifespan)

app.include_router(router)
app.include_router(registry_router)
app.include_router(provider_router)
setup_metrics(app)

@app.get("/health")
async def health_check():
    return {"status": "ok"}
