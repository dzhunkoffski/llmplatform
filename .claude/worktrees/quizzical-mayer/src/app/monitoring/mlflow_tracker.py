"""
MLflow tracking integration for LLM calls and Agent operations.

Each LLM streaming request is logged as a run in the 'llm_calls' experiment.
Each Agent registry operation is logged as a run in the 'agent_operations' experiment.

All MLflow I/O runs in a thread pool so it never blocks the async event loop.
Failures are caught and logged as warnings — MLflow is non-critical.
"""

import asyncio
import logging

import mlflow

logger = logging.getLogger(__name__)

LLM_EXPERIMENT   = "llm_calls"
AGENT_EXPERIMENT = "agent_operations"


def init_mlflow(tracking_uri: str) -> None:
    try:
        mlflow.set_tracking_uri(tracking_uri)
        for name in (LLM_EXPERIMENT, AGENT_EXPERIMENT):
            if mlflow.get_experiment_by_name(name) is None:
                mlflow.create_experiment(name)
        logger.info("MLflow initialised — tracking URI: %s", tracking_uri)
    except Exception as exc:
        logger.warning("MLflow init failed (tracking disabled): %s", exc)


# ── LLM call tracing ─────────────────────────────────────────────────────────

def _log_llm_run(
    tracking_uri: str,
    provider_id: str,
    provider_name: str,
    model: str,
    ttft_s: float,
    tpot_ms: float,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    total_duration_s: float,
    success: bool,
) -> None:
    try:
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(LLM_EXPERIMENT)
        with mlflow.start_run(run_name=f"{provider_name}_completion"):
            mlflow.set_tags({
                "provider_id":   provider_id,
                "provider_name": provider_name,
                "model":         model,
                "status":        "success" if success else "error",
            })
            mlflow.log_metrics({
                "ttft_seconds":     ttft_s,
                "tpot_ms":          tpot_ms,
                "input_tokens":     float(input_tokens),
                "output_tokens":    float(output_tokens),
                "cost_usd":         cost_usd,
                "total_duration_s": total_duration_s,
            })
    except Exception as exc:
        logger.warning("MLflow LLM run logging failed: %s", exc)


async def log_llm_call(
    tracking_uri: str,
    provider_id: str,
    provider_name: str,
    model: str,
    ttft_s: float,
    tpot_ms: float,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    total_duration_s: float,
    success: bool = True,
) -> None:
    await asyncio.to_thread(
        _log_llm_run,
        tracking_uri,
        provider_id, provider_name, model,
        ttft_s, tpot_ms,
        input_tokens, output_tokens,
        cost_usd, total_duration_s,
        success,
    )


# ── Agent operation tracing ───────────────────────────────────────────────────

def _log_agent_run(
    tracking_uri: str,
    operation: str,
    agent_id: str,
    agent_name: str,
    duration_ms: float,
    success: bool,
) -> None:
    try:
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(AGENT_EXPERIMENT)
        with mlflow.start_run(run_name=f"agent_{operation}"):
            mlflow.set_tags({
                "operation":  operation,
                "agent_id":   agent_id,
                "agent_name": agent_name,
                "status":     "success" if success else "error",
            })
            mlflow.log_metrics({
                "duration_ms": duration_ms,
                "success":     1.0 if success else 0.0,
            })
    except Exception as exc:
        logger.warning("MLflow agent run logging failed: %s", exc)


async def log_agent_operation(
    tracking_uri: str,
    operation: str,
    agent_id: str,
    agent_name: str,
    duration_ms: float,
    success: bool = True,
) -> None:
    await asyncio.to_thread(
        _log_agent_run,
        tracking_uri,
        operation, agent_id, agent_name,
        duration_ms, success,
    )
