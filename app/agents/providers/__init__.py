from app.agents.providers.base import LLMNotConfiguredError, LLMProvider, LLMProviderError
from app.agents.providers.openrouter import OpenRouterProvider
from app.core.config import get_settings


def get_provider() -> LLMProvider:
    settings = get_settings()
    if not settings.llm_configured:
        raise LLMNotConfiguredError(
            "No LLM provider is configured. Set OPENROUTER_API_KEY in your environment "
            "or .env file to enable the AI investigation layer. The deterministic risk "
            "engine and dashboard work fully without it."
        )
    return OpenRouterProvider(
        api_key=settings.openrouter_api_key,
        model=settings.openrouter_model,
        base_url=settings.openrouter_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


__all__ = ["LLMProvider", "LLMProviderError", "LLMNotConfiguredError", "get_provider"]
