from typing import Optional
from pydantic import BaseModel, Field
import uuid


class ProviderHealthStatus(BaseModel):
    """Runtime health snapshot for a single provider."""
    id: str
    name: str
    url: str
    circuit_state: str          # closed / open / half_open
    avg_latency_ms: float       # EMA of time-to-first-token in milliseconds
    total_requests: int
    total_errors: int
    consecutive_errors: int
    last_failure_time: Optional[float] = None   # Unix timestamp
    last_success_time: Optional[float] = None   # Unix timestamp


class ProviderConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    url: str
    api_key: Optional[str] = Field(default=None, description="Bearer token for external providers")
    model_alias: Optional[str] = Field(default=None, description="Rewrite the model field before forwarding to this provider")
    token_price: float = Field(default=0.0, description="Price per 1K tokens in USD")
    rate_limit: int = Field(default=0, description="Max requests per minute (0 = unlimited)")
    priority: int = Field(default=1, description="Lower value = higher priority")
    is_active: bool = True


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    api_key: Optional[str] = None
    model_alias: Optional[str] = None
    token_price: Optional[float] = None
    rate_limit: Optional[int] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


class ProviderResponse(BaseModel):
    """ProviderConfig safe for API responses — api_key is masked."""
    id: str
    name: str
    url: str
    api_key: Optional[str]
    model_alias: Optional[str]
    token_price: float
    rate_limit: int
    priority: int
    is_active: bool

    @classmethod
    def from_config(cls, config: ProviderConfig) -> "ProviderResponse":
        masked = f"****{config.api_key[-4:]}" if config.api_key else None
        return cls(**config.model_dump(exclude={"api_key"}), api_key=masked)
