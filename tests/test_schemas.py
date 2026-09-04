import pytest
from pydantic import ValidationError

from app.agents.schemas import Finding, InvestigatorOutput


def test_finding_rejects_conclusory_corruption_language():
    with pytest.raises(ValidationError):
        Finding(
            claim="This buyer is corrupt.",
            evidence_refs=["case:c1"], confidence=0.9, risk_level="high",
        )


def test_finding_accepts_hedged_risk_language():
    f = Finding(
        claim="This case shows a risk indicator requiring review.",
        evidence_refs=["case:c1"], confidence=0.6, risk_level="medium",
    )
    assert f.risk_level == "medium"


def test_investigator_output_summary_also_checked():
    with pytest.raises(ValidationError):
        InvestigatorOutput(
            investigator="procedure", case_id="c1",
            summary="We confirmed this supplier committed fraud.", findings=[],
        )


def test_confidence_bounds_enforced():
    with pytest.raises(ValidationError):
        Finding(claim="ok", evidence_refs=[], confidence=1.5, risk_level="low")
