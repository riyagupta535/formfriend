"""Small shared Gemini call for per-question helpers (answer checking, teaching): JSON in, JSON out, cached."""
import asyncio
import json
import os

import httpx

from .gemini_cache import get_response, put_response, response_key


async def gemini_json(system: str, request: str, *, purpose: str, thinking: str = "low",
                      max_output_tokens: int = 2048) -> str:
    """Return the model's JSON text. Raises on provider errors; callers decide how to degrade."""
    model = os.getenv("GEMINI_JUDGE_MODEL") or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    base = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    cache_key = response_key({"purpose": purpose, "model": model, "thinking": thinking, "system": system, "request": request})
    cached = get_response(cache_key)
    if cached is not None:
        return cached
    # Short per-attempt timeout: a voice agent waits at most 30 seconds for a tool result.
    async with httpx.AsyncClient(timeout=float(os.getenv("GEMINI_JUDGE_TIMEOUT_SECONDS", "8"))) as client:
        for attempt in range(3):
            response = await client.post(
                f"{base}/models/{model}:generateContent",
                headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": request}]}],
                    "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": max_output_tokens,
                                         "thinkingConfig": {"thinkingLevel": thinking}},
                },
            )
            # Overload and rate limits are usually brief; the person is waiting, so retry quickly.
            if response.status_code not in {429, 500, 503} or attempt == 2:
                break
            await asyncio.sleep(0.8 * (attempt + 1))
    response.raise_for_status()
    parts = response.json()["candidates"][0].get("content", {}).get("parts", [])
    content = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    json.loads(content)  # Only cache well-formed JSON; a bad reply should be retried next time, not replayed.
    put_response(cache_key, content)
    return content
