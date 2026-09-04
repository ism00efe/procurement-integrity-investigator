import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.agents.providers.base import LLMProvider, LLMProviderError


class OpenRouterProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, base_url: str, timeout: float, max_retries: int):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        payload: dict = {"model": self._model, "messages": messages, "temperature": 0.2}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/procurement-integrity-investigator",
            "X-Title": "Procurement Integrity Investigator",
        }

        @retry(
            stop=stop_after_attempt(max(1, self._max_retries + 1)),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
            reraise=True,
        )
        async def _call() -> dict:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions", json=payload, headers=headers,
                )
                resp.raise_for_status()
                return resp.json()

        try:
            data = await _call()
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(
                f"OpenRouter request failed: {exc.response.status_code} {exc.response.text[:500]}"
            ) from exc
        except httpx.TransportError as exc:
            raise LLMProviderError(f"OpenRouter request failed: {exc}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise LLMProviderError(f"OpenRouter returned no choices: {data}")
        return choices[0]["message"]
