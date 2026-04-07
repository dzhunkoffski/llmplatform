import json
import logging
import time
from typing import Optional, AsyncGenerator

import httpx

from app.monitoring.metrics import record_llm_metrics
from app.monitoring.mlflow_tracker import log_llm_call

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
    provider_name: str = "unknown",
    token_price: float = 0.0,
    mlflow_tracking_uri: str = "http://mlflow:5000",
) -> AsyncGenerator[bytes, None]:
    """
    Stream a chat-completion request to an upstream provider.

    Beyond proxying the stream, this function:
      - Records TTFT / circuit-breaker health via HealthTracker.
      - Parses SSE chunks to extract token-usage (prompt_tokens,
        completion_tokens) from the provider's usage field; falls back to
        counting content delta chunks when usage is absent.
      - Computes TPOT = (total_time − TTFT) / output_tokens  (ms/token).
      - Calculates cost = (input + output) × token_price / 1 000  (USD/1K tokens).
      - Emits all metrics to Prometheus and logs a run to MLflow after the
        stream is fully consumed.
    """
    from app.services.health_tracker import health_tracker

    # ── Parse request for model name + rough input-token estimate ────────────
    model = "unknown"
    estimated_input_tokens = 0
    try:
        req_obj = json.loads(body)
        model = req_obj.get("model", "unknown")
        messages = req_obj.get("messages", [])
        char_count = sum(
            len(m.get("content", "")) for m in messages
            if isinstance(m.get("content"), str)
        )
        estimated_input_tokens = max(1, char_count // 4)   # ≈ 4 chars / token
    except Exception:
        pass

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    timeout = httpx.Timeout(
        connect=CONNECT_TIMEOUT,
        read=READ_TIMEOUT,
        write=WRITE_TIMEOUT,
        pool=5.0,
    )

    # ── Tracking state ────────────────────────────────────────────────────────
    start        = time.perf_counter()
    ttft_s       = 0.0
    first_chunk  = True
    success      = False

    # SSE parsing state
    sse_buffer   = ""
    input_tokens  = estimated_input_tokens
    output_tokens = 0

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
                    return

                async for chunk in response.aiter_bytes():
                    now = time.perf_counter()

                    # ── TTFT ─────────────────────────────────────────────────
                    if first_chunk:
                        ttft_s = now - start
                        logger.debug("Provider %s TTFT=%.3fs", provider_id, ttft_s)
                        if provider_id:
                            await health_tracker.record_success(provider_id, ttft_s)
                        first_chunk = False
                        success = True

                    # ── SSE parsing for token counts ──────────────────────────
                    try:
                        sse_buffer += chunk.decode("utf-8", errors="replace")
                        while "\n" in sse_buffer:
                            line, sse_buffer = sse_buffer.split("\n", 1)
                            line = line.strip()
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                continue
                            obj = json.loads(data_str)
                            usage = obj.get("usage")
                            if usage:
                                # Authoritative counts from provider
                                input_tokens  = usage.get("prompt_tokens",     input_tokens)
                                output_tokens = usage.get("completion_tokens", output_tokens)
                            else:
                                for choice in obj.get("choices", []):
                                    if choice.get("delta", {}).get("content"):
                                        output_tokens += 1  # fallback: 1 chunk ≈ 1 token
                    except Exception:
                        pass  # parsing is best-effort; never drop the chunk

                    yield chunk

    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.error("Provider %s unreachable: %s", provider_id, exc)
        if provider_id:
            await health_tracker.record_failure(provider_id)
        raise

    finally:
        # ── Post-stream metrics (runs even when the client disconnects) ───────
        if not first_chunk:   # at least one chunk was received
            end           = time.perf_counter()
            total_s       = end - start
            generation_s  = max(total_s - ttft_s, 0.0)
            tpot_ms       = (generation_s / output_tokens * 1000) if output_tokens > 0 else 0.0
            cost_usd      = (input_tokens + output_tokens) * token_price / 1_000

            logger.debug(
                "Provider %s | TTFT=%.3fs TPOT=%.1fms "
                "in=%d out=%d cost=$%.6f",
                provider_id, ttft_s, tpot_ms,
                input_tokens, output_tokens, cost_usd,
            )

            # Prometheus (synchronous, fast)
            record_llm_metrics(
                provider_name=provider_name,
                ttft_s=ttft_s,
                tpot_ms=tpot_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            )

            # MLflow (runs in thread pool — non-blocking)
            await log_llm_call(
                tracking_uri=mlflow_tracking_uri,
                provider_id=provider_id or "unknown",
                provider_name=provider_name,
                model=model,
                ttft_s=ttft_s,
                tpot_ms=tpot_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                total_duration_s=total_s,
                success=success,
            )
