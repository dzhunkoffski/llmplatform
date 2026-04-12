import os
from typing import List

from dotenv import load_dotenv

load_dotenv()


class Settings:
    PROVIDERS: List[str] = ["http://provider-1:11434", "http://provider-2:11434"]
    REDIS_URL: str = "redis://redis:6379"
    ADMIN_KEY: str = os.getenv("ADMIN_KEY", "admin")
    MLFLOW_TRACKING_URI: str = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")


settings = Settings()
