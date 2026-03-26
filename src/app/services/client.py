import httpx

async def fetch_stream(url: str, body: bytes):
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", f"{url}/v1/chat/completions", content=body) as response:
            async for chunk in response.aiter_bytes():
                yield chunk
