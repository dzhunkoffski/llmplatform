from typing import List

class Settings:
    PROVIDERS: List[str] = [
        "http://provider-1:11434",
        "http://provider-2:11434"
    ]
    REDIS_URL: str = "redis://redis:6379"

settings = Settings()
