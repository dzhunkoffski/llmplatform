import logging
from typing import List

import redis.asyncio as aioredis

from app.models.agent import AgentCard, AgentCardUpdate
from app.core.config import settings

logger = logging.getLogger(__name__)


class AgentRegistry:
    def __init__(self) -> None:
        self._redis: aioredis.Redis = aioredis.from_url(
            settings.REDIS_URL, decode_responses=True
        )

    async def register(self, card: AgentCard) -> AgentCard:
        await self._redis.set(f"agent:{card.id}", card.model_dump_json())
        logger.info(f"Registered agent: {card.id} ({card.name})")
        return card

    async def get(self, agent_id: str) -> AgentCard | None:
        data = await self._redis.get(f"agent:{agent_id}")
        return AgentCard.model_validate_json(data) if data else None

    async def list_all(self) -> List[AgentCard]:
        keys = await self._redis.keys("agent:*")
        if not keys:
            return []
        values = await self._redis.mget(*keys)
        return [AgentCard.model_validate_json(v) for v in values if v]

    async def update(self, agent_id: str, patch: AgentCardUpdate) -> AgentCard | None:
        card = await self.get(agent_id)
        if card is None:
            return None
        updated = card.model_copy(
            update={k: v for k, v in patch.model_dump().items() if v is not None}
        )
        await self._redis.set(f"agent:{agent_id}", updated.model_dump_json())
        logger.info(f"Updated agent: {agent_id}")
        return updated

    async def unregister(self, agent_id: str) -> bool:
        deleted = await self._redis.delete(f"agent:{agent_id}")
        if deleted:
            logger.info(f"Unregistered agent: {agent_id}")
        return deleted > 0

    async def close(self) -> None:
        await self._redis.aclose()


registry = AgentRegistry()
