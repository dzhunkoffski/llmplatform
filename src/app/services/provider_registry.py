import logging
from typing import List

import redis.asyncio as aioredis

from app.models.provider import ProviderConfig, ProviderUpdate
from app.core.config import settings

logger = logging.getLogger(__name__)


class ProviderRegistry:
    def __init__(self) -> None:
        self._redis: aioredis.Redis = aioredis.from_url(
            settings.REDIS_URL, decode_responses=True
        )

    async def register(self, provider: ProviderConfig) -> ProviderConfig:
        await self._redis.set(f"provider:{provider.id}", provider.model_dump_json())
        logger.info(f"Registered provider: {provider.id} ({provider.name}) at {provider.url}")
        return provider

    async def get(self, provider_id: str) -> ProviderConfig | None:
        data = await self._redis.get(f"provider:{provider_id}")
        return ProviderConfig.model_validate_json(data) if data else None

    async def list_all(self) -> List[ProviderConfig]:
        keys = await self._redis.keys("provider:*")
        if not keys:
            return []
        values = await self._redis.mget(*keys)
        return [ProviderConfig.model_validate_json(v) for v in values if v]

    async def list_active(self) -> List[ProviderConfig]:
        all_providers = await self.list_all()
        return [p for p in all_providers if p.is_active]

    async def update(self, provider_id: str, patch: ProviderUpdate) -> ProviderConfig | None:
        provider = await self.get(provider_id)
        if provider is None:
            return None
        updated = provider.model_copy(
            update={k: v for k, v in patch.model_dump().items() if v is not None}
        )
        await self._redis.set(f"provider:{provider_id}", updated.model_dump_json())
        logger.info(f"Updated provider: {provider_id}")
        return updated

    async def unregister(self, provider_id: str) -> bool:
        deleted = await self._redis.delete(f"provider:{provider_id}")
        if deleted:
            logger.info(f"Unregistered provider: {provider_id}")
        return deleted > 0

    async def close(self) -> None:
        await self._redis.aclose()


provider_registry = ProviderRegistry()
