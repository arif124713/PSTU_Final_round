import httpx

from app.config import settings


async def chat_completion(messages: list[dict], tools: list[dict] | None = None, tool_choice: str | None = None) -> dict:
    """Thin wrapper around DeepSeek's OpenAI-compatible chat completions endpoint."""
    payload = {
        "model": settings.deepseek_model,
        "messages": messages,
        "max_tokens": settings.deepseek_max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{settings.deepseek_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()
