"""
SmartBalancer — model-aware, latency-based, health-aware provider selection.

Selection algorithm
-------------------
1. Load all active providers from the registry.
2. If a model name is provided, filter to providers that explicitly serve that
   model (providers with an empty `models` list are treated as wildcards and
   are included in every pool).  If the model-filtered pool is empty, fall back
   to all active providers so existing deployments without model declarations
   continue to work (logged as a warning).
3. Filter out providers whose circuit is OPEN (via HealthTracker.is_available).
4. If *all* remaining providers are unavailable, raise RuntimeError(503).
5. Among healthy providers, keep only the highest-priority group
   (lowest `priority` number).
6. Within that group, pick the provider with the lowest latency EMA.
   Providers with no latency data yet are treated as having a neutral
   placeholder latency (UNKNOWN_LATENCY) so they get a fair chance.
7. If no providers are registered at all, fall back to the static list
   in settings.PROVIDERS (round-robin).
"""

import logging

from app.core.config import settings
from app.models.provider import ProviderConfig

logger = logging.getLogger(__name__)

# Latency assigned to providers that have never been measured yet.
# Set it lower than typical observed latency so new providers get a
# chance to prove themselves before being pushed to the back of the queue.
UNKNOWN_LATENCY = 1.0   # seconds


class SmartBalancer:
    """Routes requests using circuit-breaker health state and latency EMA."""

    def __init__(self) -> None:
        self._fallback_urls: list[str] = settings.PROVIDERS or []
        self._fallback_index: int = 0

    async def get_next_provider(self, model: str | None = None) -> ProviderConfig:
        from app.services.provider_registry import provider_registry
        from app.services.health_tracker import health_tracker

        providers = await provider_registry.list_active()

        if not providers:
            return self._fallback_provider()

        # ── 1. Filter by requested model name ─────────────────────────────────
        if model:
            # Providers with an empty `models` list are wildcards (serve any model).
            model_pool = [
                p for p in providers
                if not p.models or model in p.models
            ]
            if not model_pool:
                logger.warning(
                    "No provider declares support for model '%s' — "
                    "falling back to all active providers",
                    model,
                )
                model_pool = providers
            else:
                logger.debug(
                    "Model '%s' matched %d provider(s): %s",
                    model,
                    len(model_pool),
                    [p.name for p in model_pool],
                )
            providers = model_pool

        # ── 2. Filter by circuit-breaker state ────────────────────────────────
        available = [
            p for p in providers
            if await health_tracker.is_available(p.id)
        ]

        if not available:
            # All circuits are open — pick the one that has been down the longest
            # (most likely to recover soonest) and try it as a last resort.
            logger.warning(
                "All %d provider(s) are circuit-OPEN — attempting least-recently-failed",
                len(providers),
            )
            providers.sort(
                key=lambda p: (health_tracker.get_stats(p.id) or _NullStats).last_failure_time or 0.0
            )
            raise RuntimeError(
                f"All {len(providers)} provider(s) are temporarily unavailable "
                "(circuit open). Retry after the recovery window."
            )

        # ── 3. Keep only the top-priority group ───────────────────────────────
        available.sort(key=lambda p: p.priority)
        min_priority = available[0].priority
        top_group = [p for p in available if p.priority == min_priority]

        # ── 4. Pick the fastest within the group ──────────────────────────────
        def latency_key(p: ProviderConfig) -> float:
            lat = health_tracker.get_latency(p.id)
            return lat if lat > 0.0 else UNKNOWN_LATENCY

        selected = min(top_group, key=latency_key)

        logger.debug(
            "Selected provider '%s' | priority=%d | latency=%.2fs | url=%s",
            selected.name,
            selected.priority,
            health_tracker.get_latency(selected.id),
            selected.url,
        )
        return selected

    def _fallback_provider(self) -> ProviderConfig:
        if not self._fallback_urls:
            raise RuntimeError("No providers registered and no fallback configured in settings.")
        url = self._fallback_urls[self._fallback_index % len(self._fallback_urls)]
        self._fallback_index += 1
        logger.warning("No registered providers — falling back to config: %s", url)
        return ProviderConfig(name=url, url=url)


class _NullStats:
    """Sentinel used when a provider has no HealthTracker entry yet."""
    last_failure_time = 0.0


balancer = SmartBalancer()
