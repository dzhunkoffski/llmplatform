import json
import logging
import urllib.parse

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.services.balancer import balancer
from app.services.client import fetch_stream

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/v1/chat/completions")
async def balance_and_proxy(request: Request):
    request_body = await request.body()

    # Extract model name early so the balancer can route to the right provider.
    try:
        body_json = json.loads(request_body)
        requested_model: str | None = body_json.get("model")
    except (json.JSONDecodeError, AttributeError):
        body_json = None
        requested_model = None

    try:
        provider = await balancer.get_next_provider(model=requested_model)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    provider_name = urllib.parse.urlparse(provider.url).hostname or provider.name
    request.scope["chosen_provider"] = provider_name

    logger.info(
        "Request routed to: %s (%s) | model=%s",
        provider.url, provider_name, requested_model,
    )

    if provider.model_alias:
        if body_json is None:
            body_json = json.loads(request_body)
        original_model = body_json.get("model")
        body_json["model"] = provider.model_alias
        request_body = json.dumps(body_json).encode()
        logger.debug(
            "Rewrote model '%s' → '%s' for %s",
            original_model, provider.model_alias, provider.name,
        )

    return StreamingResponse(
        fetch_stream(
            url=provider.url,
            body=request_body,
            api_key=provider.api_key,
            provider_id=provider.id,
            provider_name=provider_name,
            token_price=provider.token_price,
            mlflow_tracking_uri=settings.MLFLOW_TRACKING_URI,
        ),
        media_type="text/event-stream",
    )
