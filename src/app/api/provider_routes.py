from fastapi import APIRouter, Depends, HTTPException, Header, status

from app.core.config import settings
from app.models.provider import ProviderConfig, ProviderUpdate, ProviderResponse, ProviderHealthStatus
from app.services.provider_registry import provider_registry


def verify_admin_key(x_admin_key: str = Header(..., description="Admin key for provider management")):
    if x_admin_key != settings.ADMIN_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin key")


provider_router = APIRouter(
    prefix="/providers",
    tags=["providers"],
    dependencies=[Depends(verify_admin_key)],
)


@provider_router.post("/register", response_model=ProviderResponse, status_code=status.HTTP_201_CREATED)
async def register_provider(provider: ProviderConfig):
    saved = await provider_registry.register(provider)
    return ProviderResponse.from_config(saved)


@provider_router.get("", response_model=list[ProviderResponse])
async def list_providers():
    providers = await provider_registry.list_all()
    return [ProviderResponse.from_config(p) for p in providers]


@provider_router.get("/health", response_model=list[ProviderHealthStatus])
async def providers_health():
    """
    Return runtime health for every registered provider:
    circuit-breaker state, average latency (EMA of TTFT), and error counters.
    """
    from app.services.health_tracker import health_tracker

    providers = await provider_registry.list_all()
    result: list[ProviderHealthStatus] = []

    for p in providers:
        stats = health_tracker.get_stats(p.id)
        result.append(
            ProviderHealthStatus(
                id=p.id,
                name=p.name,
                url=p.url,
                circuit_state=stats.state.value if stats else "closed",
                avg_latency_ms=round((stats.avg_latency if stats else 0.0) * 1000, 2),
                total_requests=stats.total_requests if stats else 0,
                total_errors=stats.total_errors if stats else 0,
                consecutive_errors=stats.consecutive_errors if stats else 0,
                last_failure_time=stats.last_failure_time if stats else None,
                last_success_time=stats.last_success_time if stats else None,
            )
        )

    return result


@provider_router.get("/{provider_id}", response_model=ProviderResponse)
async def get_provider(provider_id: str):
    provider = await provider_registry.get(provider_id)
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    return ProviderResponse.from_config(provider)


@provider_router.patch("/{provider_id}", response_model=ProviderResponse)
async def update_provider(provider_id: str, patch: ProviderUpdate):
    provider = await provider_registry.update(provider_id, patch)
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    return ProviderResponse.from_config(provider)


@provider_router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_provider(provider_id: str):
    deleted = await provider_registry.unregister(provider_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
