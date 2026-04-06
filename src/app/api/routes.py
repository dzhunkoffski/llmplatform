import json
import logging
import urllib.parse

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from app.services.balancer import balancer
from app.services.client import fetch_stream

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/v1/chat/completions")
async def balance_and_proxy(request: Request):
    provider = await balancer.get_next_provider()
    provider_name = urllib.parse.urlparse(provider.url).hostname
    request.scope["chosen_provider"] = provider_name

    logger.info(f"Request routed to: {provider.url} ({provider_name})")

    request_body = await request.body()

    if provider.model_alias:
        body = json.loads(request_body)
        original_model = body.get("model")
        body["model"] = provider.model_alias
        request_body = json.dumps(body).encode()
        logger.debug(f"Rewrote model '{original_model}' → '{provider.model_alias}' for {provider.name}")

    return StreamingResponse(
        fetch_stream(provider.url, request_body, provider.api_key),
        media_type="text/event-stream"
    )
