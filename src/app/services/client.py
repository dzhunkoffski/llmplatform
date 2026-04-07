import logging
import time
from typing import Optional, AsyncGenerator

import httpx

logger = logging.getLogger(__name__)

# Timeouts (seconds)
CONNECT_TIMEOUT = 10.0   # max time to establish a TCP connection
READ_TIMEOUT    = 120.0  # max time between two consecutive stream chunks
WRITE_TIMEOUT   = 30.0


async def fetch_stream(
    url: str,
    body: bytes,
    api_key: Optional[str] = None,
    provider_id: Optional[str] = None,
) -> AsyncGenerator[bytes, None]:
    """
    Stream a chat-completion request to an upstream provider.

    Reports success / failure to the HealthTracker so that the circuit breaker
    and latency EMA stay up to date:
      - Success is recorded when the **first chunk** arrives (TTFT).
      - Failure is recorded on connection errors, timeouts, or HTTP 5xx.
    """
    from app.services.health_tracker import health_tracker

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    timeout = httpx.Timeout(
        connect=CONNECT_TIMEOUT,
        read=READ_TIMEOUT,
        write=WRITE_TIMEOUT,
        pool=5.0,
    )

    start = time.perf_counter()
    first_chunk = True

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{url}/v1/chat/completions",
                content=body,
                headers=headers,
            ) as response:
                if response.status_code >= 500:
                    logger.warning(
                        "Provider %s returned HTTP %d — recording failure",
                        provider_id, response.status_code,
                    )
                    if provider_id:
                        await health_tracker.record_failure(provider_id)
                    return  # stop the generator; StreamingResponse sends an empty body

                async for chunk in response.aiter_bytes():
                    if first_chunk:
                        ttft = time.perf_counter() - start
                        logger.debug("Provider %s TTFT=%.2fs", provider_id, ttft)
                        if provider_id:
                            await health_tracker.record_success(provider_id, ttft)
                        first_chunk = False
                    yield chunk

    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.error("Provider %s unreachable: %s", provider_id, exc)
        if provider_id:
            await health_tracker.record_failure(provider_id)
        raise
