import asyncio

import pytest

from app.agents.investigators import run_investigator
from app.agents.providers import LLMNotConfiguredError, get_provider
from app.agents.providers.base import LLMProvider, LLMProviderError
from app.agents.providers.openrouter import OpenRouterProvider
from app.core.config import get_settings


def test_get_provider_raises_when_no_api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(LLMNotConfiguredError):
        get_provider()
    get_settings.cache_clear()


def test_get_provider_returns_openrouter_when_key_present(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key")
    get_settings.cache_clear()
    provider = get_provider()
    assert isinstance(provider, OpenRouterProvider)
    get_settings.cache_clear()


class _AlwaysFailsProvider(LLMProvider):
    async def chat(self, messages, tools=None):
        raise LLMProviderError("simulated upstream failure")


def test_investigator_handles_failed_llm_call_gracefully():
    provider = _AlwaysFailsProvider()
    semaphore = asyncio.Semaphore(1)
    spec = {"id": "procedure", "role": "Procurement / Procedure Analyst", "focus": "test"}
    case_seed = {"case_id": "case-1", "risk_score": 10.0}

    output = asyncio.run(run_investigator(provider, semaphore, spec, case_seed))

    assert output.case_id == "case-1"
    assert output.findings == []
    assert "failed" in output.summary.lower()
