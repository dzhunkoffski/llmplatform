import logging

from fastapi import APIRouter, HTTPException
from app.models.agent import AgentCard, AgentCardUpdate
from app.services.registry import registry

logger = logging.getLogger(__name__)

registry_router = APIRouter(prefix="/agents", tags=["Agent Registry"])


@registry_router.post("/register", response_model=AgentCard, status_code=201)
async def register_agent(card: AgentCard) -> AgentCard:
    """Register a new A2A agent with its Agent Card."""
    return await registry.register(card)


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
    card = await registry.update(agent_id, patch)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return card


@registry_router.delete("/{agent_id}", status_code=204)
async def unregister_agent(agent_id: str) -> None:
    """Remove an agent from the registry."""
    if not await registry.unregister(agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
