import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from app.services.balancer import balancer
from app.services.client import fetch_stream

import urllib.parse

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/v1/chat/completions")
async def balance_and_proxy(request: Request):
    selected_node = balancer.get_next_provider()
    provider_name = urllib.parse.urlparse(selected_node).hostname
    request.scope["chosen_provider"] = provider_name

    logger.info(f"Request routes to: {selected_node} ({provider_name})")
    
    request_body = await request.body()
    
    return StreamingResponse(
        fetch_stream(selected_node, request_body),
        media_type="text/event-stream"
    )
