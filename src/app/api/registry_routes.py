import logging
import time

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.models.agent import AgentCard, AgentCardUpdate
from app.monitoring.mlflow_tracker import log_agent_operation
from app.services.registry import registry

logger = logging.getLogger(__name__)

registry_router = APIRouter(prefix="/agents", tags=["Agent Registry"])


@registry_router.post("/register", response_model=AgentCard, status_code=201)
async def register_agent(card: AgentCard) -> AgentCard:
    """Register a new A2A agent with its Agent Card."""
    t0 = time.perf_counter()
    result = await registry.register(card)
    duration_ms = (time.perf_counter() - t0) * 1000
    await log_agent_operation(
        tracking_uri=settings.MLFLOW_TRACKING_URI,
        operation="register",
        agent_id=str(result.id),
        agent_name=result.name,
        duration_ms=duration_ms,
        success=True,
    )
    return result


@registry_router.get("", response_model=list[AgentCard])
async def list_agents() -> list[AgentCard]:
    """Return all registered Agent Cards."""
    return await registry.list_all()


@registry_router.get("/{agent_id}", response_model=AgentCard)
async def get_agent(agent_id: str) -> AgentCard:
    """Return the Agent Card for a specific agent."""
    card = await registry.get(agent_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return card


@registry_router.patch("/{agent_id}", response_model=AgentCard)
async def update_agent(agent_id: str, patch: AgentCardUpdate) -> AgentCard:
    """Partially update a registered Agent Card."""
    t0 = time.perf_counter()
    card = await registry.update(agent_id, patch)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    duration_ms = (time.perf_counter() - t0) * 1000
    await log_agent_operation(
        tracking_uri=settings.MLFLOW_TRACKING_URI,
        operation="update",
        agent_id=str(card.id),
        agent_name=card.name,
        duration_ms=duration_ms,
        success=True,
    )
    return card


@registry_router.delete("/{agent_id}", status_code=204)
async def unregister_agent(agent_id: str) -> None:
    """Remove an agent from the registry."""
    t0 = time.perf_counter()
    removed = await registry.unregister(agent_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    duration_ms = (time.perf_counter() - t0) * 1000
    await log_agent_operation(
        tracking_uri=settings.MLFLOW_TRACKING_URI,
        operation="unregister",
        agent_id=agent_id,
        agent_name="",
        duration_ms=duration_ms,
        success=True,
    )
