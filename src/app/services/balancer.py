import itertools
import logging

from app.core.config import settings
from app.models.provider import ProviderConfig

logger = logging.getLogger(__name__)


class DynamicPriorityBalancer:
    """
    Selects providers using round-robin within the highest-priority group.
    Falls back to the static PROVIDERS list from config if no providers are registered.
    """

    def __init__(self) -> None:
        self._counter = 0
        self._fallback_iter = (
            itertools.cycle(settings.PROVIDERS) if settings.PROVIDERS else None
        )

    async def get_next_provider(self) -> ProviderConfig:
        from app.services.provider_registry import provider_registry

        providers = await provider_registry.list_active()

        if not providers:
            if self._fallback_iter is not None:
                url = next(self._fallback_iter)
                logger.warning(f"No registered providers — falling back to config: {url}")
                return ProviderConfig(name=url, url=url)
            raise RuntimeError("No providers available and no fallback configured")

        # Sort ascending; lowest priority number = highest precedence
        providers.sort(key=lambda p: p.priority)
        min_priority = providers[0].priority
        top = [p for p in providers if p.priority == min_priority]

        selected = top[self._counter % len(top)]
        self._counter += 1

        logger.debug(
            f"Selected provider '{selected.name}' (priority={selected.priority}, "
            f"url={selected.url}, price={selected.token_price}/1K tokens, "
            f"rate_limit={selected.rate_limit} rpm)"
        )
        return selected


balancer = DynamicPriorityBalancer()
