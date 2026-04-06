from fastapi import APIRouter, Depends, HTTPException, Header, status

from app.core.config import settings
from app.models.provider import ProviderConfig, ProviderUpdate, ProviderResponse
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
