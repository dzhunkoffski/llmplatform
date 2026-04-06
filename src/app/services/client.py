import httpx
from typing import Optional

async def fetch_stream(url: str, body: bytes, api_key: Optional[str] = None):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", f"{url}/v1/chat/completions", content=body, headers=headers) as response:
            async for chunk in response.aiter_bytes():
                yield chunk
