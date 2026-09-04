import asyncio

from app.services.pipeline import investigate_and_report


def test_investigate_and_report_falls_back_when_llm_not_configured(
    temp_database_with_risk, monkeypatch, tmp_path,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("INVESTIGATIONS_DIR", str(tmp_path / "investigations"))
    from app.core.config import get_settings
    get_settings.cache_clear()

    result = asyncio.run(investigate_and_report("case-1"))

    assert result["llm_status"].startswith("not_configured")
    assert result["investigator_outputs"] == []
    # The deterministic risk result must still be present even without an LLM.
    assert result["report"]["deterministic_risk_score"] == 45.0
    assert result["report"]["overall_risk_level"] == "medium"

    get_settings.cache_clear()
