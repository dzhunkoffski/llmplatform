import logging

from fastapi import FastAPI
from app.api.routes import router
from app.monitoring.metrics import setup_metrics

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("app.log", encoding="utf-8")
    ]
)

app = FastAPI(title="Agent Platform API Gateway")

app.include_router(router)
setup_metrics(app)

@app.get("/health")
async def health_check():
    return {"status": "ok"}
