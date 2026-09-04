from typing import Literal

from pydantic import BaseModel, Field, field_validator

RiskLevel = Literal["low", "medium", "high"]

BANNED_PHRASES = (
    "is corrupt", "is corruption", "confirms corruption", "guilty",
    "bribery occurred", "was bribed", "committed fraud", "is fraudulent",
)


def _reject_conclusory_language(value: str) -> str:
    lowered = value.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            raise ValueError(
                f"claim uses conclusory language ('{phrase}'); restate as a risk "
                "indicator requiring review, not a finding of wrongdoing"
            )
    return value


class Finding(BaseModel):
    claim: str
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel
    benign_explanation: str = ""

    @field_validator("claim")
    @classmethod
    def claim_not_conclusory(cls, v: str) -> str:
        return _reject_conclusory_language(v)


class InvestigatorOutput(BaseModel):
    investigator: str
    case_id: str
    summary: str
    findings: list[Finding] = Field(default_factory=list)

    @field_validator("summary")
    @classmethod
    def summary_not_conclusory(cls, v: str) -> str:
        return _reject_conclusory_language(v)


class VerifiedFinding(BaseModel):
    finding: Finding
    investigator: str
    verification_status: Literal["verified", "downgraded", "rejected"]
    verification_notes: str


class CaseReport(BaseModel):
    case_id: str
    overall_risk_level: RiskLevel
    deterministic_risk_score: float
    key_findings: list[VerifiedFinding]
    conflicting_evidence: str
    benign_explanations: str
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_follow_up: str
    source_record_refs: list[str]
    narrative: str

    @field_validator("narrative")
    @classmethod
    def narrative_not_conclusory(cls, v: str) -> str:
        return _reject_conclusory_language(v)
