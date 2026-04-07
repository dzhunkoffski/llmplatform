"""
Provider health tracking using the Circuit Breaker pattern.

States:
  CLOSED    — normal operation; all requests go through.
  OPEN      — provider is down; requests are blocked until recovery timeout passes.
  HALF_OPEN — one probe request is allowed through to test if the provider recovered.

Latency is tracked via an Exponential Moving Average (EMA) of the time-to-first-token (TTFT).
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ── Tuning knobs ──────────────────────────────────────────────────────────────
FAILURE_THRESHOLD = 3    # consecutive errors before the circuit opens
RECOVERY_TIMEOUT  = 60.0 # seconds an OPEN circuit waits before allowing a probe
EMA_ALPHA         = 0.3  # smoothing factor for the latency EMA (0 < α ≤ 1)
# ─────────────────────────────────────────────────────────────────────────────


class CircuitState(str, Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


@dataclass
class ProviderStats:
    provider_id:        str
    state:              CircuitState   = CircuitState.CLOSED
    avg_latency:        float          = 0.0   # EMA of TTFT in seconds
    total_requests:     int            = 0
    total_errors:       int            = 0
    consecutive_errors: int            = 0
    last_failure_time:  Optional[float] = None
    last_success_time:  Optional[float] = None


class HealthTracker:
    """
    Asyncio-safe tracker for per-provider health and latency.

    Call record_success / record_failure after every upstream request,
    and is_available before routing to a provider.
    """

    def __init__(self) -> None:
        self._stats: Dict[str, ProviderStats] = {}
        self._lock = asyncio.Lock()

    def _ensure(self, provider_id: str) -> ProviderStats:
        if provider_id not in self._stats:
            self._stats[provider_id] = ProviderStats(provider_id=provider_id)
        return self._stats[provider_id]

    async def record_success(self, provider_id: str, latency: float) -> None:
        """Record a successful response and update the latency EMA."""
        async with self._lock:
            stats = self._ensure(provider_id)
            stats.total_requests     += 1
            stats.consecutive_errors  = 0
            stats.last_success_time   = time.time()

            # Seed with the first observation; use EMA thereafter
            if stats.avg_latency == 0.0:
                stats.avg_latency = latency
            else:
                stats.avg_latency = EMA_ALPHA * latency + (1 - EMA_ALPHA) * stats.avg_latency

            if stats.state in (CircuitState.OPEN, CircuitState.HALF_OPEN):
                logger.info(
                    "Provider %s recovered — circuit CLOSED (TTFT=%.2fs)",
                    provider_id, latency,
                )
                stats.state = CircuitState.CLOSED

    async def record_failure(self, provider_id: str) -> None:
        """Record a failed request (timeout, connection error, HTTP 5xx)."""
        async with self._lock:
            stats = self._ensure(provider_id)
            stats.total_requests     += 1
            stats.total_errors       += 1
            stats.consecutive_errors += 1
            stats.last_failure_time   = time.time()

            if (
                stats.state == CircuitState.CLOSED
                and stats.consecutive_errors >= FAILURE_THRESHOLD
            ):
                logger.warning(
                    "Provider %s tripped the circuit breaker after %d consecutive errors — circuit OPEN",
                    provider_id, stats.consecutive_errors,
                )
                stats.state = CircuitState.OPEN

    async def is_available(self, provider_id: str) -> bool:
        """
        Return True if the provider may receive traffic right now.

        Handles the OPEN → HALF_OPEN transition: after RECOVERY_TIMEOUT seconds
        one probe request is let through to check if the provider is back.
        """
        async with self._lock:
            if provider_id not in self._stats:
                return True  # no data yet → optimistically healthy

            stats = self._stats[provider_id]

            if stats.state == CircuitState.CLOSED:
                return True

            if stats.state == CircuitState.OPEN:
                elapsed = time.time() - (stats.last_failure_time or 0.0)
                if elapsed >= RECOVERY_TIMEOUT:
                    logger.info(
                        "Provider %s in OPEN state for %.0fs — entering HALF_OPEN for probe",
                        provider_id, elapsed,
                    )
                    stats.state = CircuitState.HALF_OPEN
                    return True
                return False

            # HALF_OPEN: let the probe through
            return True

    def get_latency(self, provider_id: str) -> float:
        """Return the EMA latency in seconds; 0.0 if no data yet."""
        stats = self._stats.get(provider_id)
        return stats.avg_latency if stats else 0.0

    def get_stats(self, provider_id: str) -> Optional[ProviderStats]:
        return self._stats.get(provider_id)

    def get_all_stats(self) -> Dict[str, ProviderStats]:
        return dict(self._stats)


# Singleton shared across the application
health_tracker = HealthTracker()
