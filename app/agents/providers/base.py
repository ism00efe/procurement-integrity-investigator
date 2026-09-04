from abc import ABC, abstractmethod


class LLMProviderError(Exception):
    pass


class LLMNotConfiguredError(LLMProviderError):
    """Raised when a provider is used without the credentials it needs."""


class LLMProvider(ABC):
    """Vendor-agnostic chat completion interface. Business logic (tool loops,
    JSON parsing, retries at the semantic level) lives above this — a
    provider only knows how to send OpenAI-style messages to its API and
    return an OpenAI-style assistant message dict.
    """

    @abstractmethod
    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """Returns an assistant message dict: {"role": "assistant",
        "content": str | None, "tool_calls": list[dict] | None}."""
        raise NotImplementedError
