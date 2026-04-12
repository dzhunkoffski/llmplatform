from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field
import uuid


class AgentCard(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str
    supported_methods: List[str]
    url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class AgentCardUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    supported_methods: Optional[List[str]] = None
    url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
