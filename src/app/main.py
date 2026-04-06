import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.routes import router
from app.api.registry_routes import registry_router
from app.monitoring.metrics import setup_metrics
from app.services.registry import registry

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("app.log", encoding="utf-8")
    ]
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await registry.close()

app = FastAPI(title="Agent Platform API Gateway", lifespan=lifespan)

app.include_router(router)
app.include_router(registry_router)
setup_metrics(app)

@app.get("/health")
async def health_check():
    return {"status": "ok"}
