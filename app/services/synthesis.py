import json
import logging

from app.agents.providers.base import LLMProvider, LLMProviderError
from app.agents.schemas import CaseReport, VerifiedFinding
from app.risk.scoring import risk_level

logger = logging.getLogger(__name__)

SYNTHESIS_SYSTEM_PROMPT = """You write the final human-readable summary of a procurement
integrity review for oversight staff. You are given ONLY findings that have already passed
independent deterministic verification against the source database — you must not introduce
any new factual claim, number, or entity that isn't present in what you were given.

You must never state that corruption, fraud, or bribery occurred or is confirmed. Use
"requires review", "risk indicator", "unusual pattern", or "insufficient evidence".

Respond with ONLY a JSON object of this shape, no prose outside it:
{"narrative": "2-4 sentence human-readable summary", "conflicting_evidence": "string, or "
 ""'None identified.' if none", "benign_explanations": "string synthesizing plausible "
 "innocent explanations", "recommended_follow_up": "concrete next step(s) for a human "
 "reviewer", "confidence": 0.0-1.0}
"""


def _fallback_narrative(verified: list[VerifiedFinding], score: float) -> dict:
    if not verified:
        claims = "No investigator claims passed verification."
    else:
        claims = " ".join(f"- {vf.finding.claim}" for vf in verified[:5])
    return {
        "narrative": (
            f"Deterministic analysis assigned a risk score of {score}/100. {claims} "
            "This is an automatically generated fallback summary because the LLM "
            "synthesis step was unavailable; deterministic evidence above is still valid."
        ),
        "conflicting_evidence": "Not assessed (LLM synthesis unavailable).",
        "benign_explanations": " ".join(
            f"- {vf.finding.benign_explanation}" for vf in verified if vf.finding.benign_explanation
        ) or "Not assessed (LLM synthesis unavailable).",
        "recommended_follow_up": "Review the deterministic indicators and verified findings below manually.",
        "confidence": 0.3,
    }


async def synthesize_case_report(
    provider: LLMProvider | None,
    case_id: str,
    deterministic_score: float,
    verified_findings: list[VerifiedFinding],
    rejected_findings: list[VerifiedFinding],
) -> CaseReport:
    accepted = [vf for vf in verified_findings if vf.verification_status in ("verified", "downgraded")]
    source_refs = sorted({ref for vf in accepted for ref in vf.finding.evidence_refs})

    if provider is None:
        parts = _fallback_narrative(accepted, deterministic_score)
    else:
        evidence_text = json.dumps(
            [
                {
                    "investigator": vf.investigator,
                    "claim": vf.finding.claim,
                    "risk_level": vf.finding.risk_level,
                    "confidence": vf.finding.confidence,
                    "benign_explanation": vf.finding.benign_explanation,
                    "verification_status": vf.verification_status,
                    "verification_notes": vf.verification_notes,
                }
                for vf in accepted
            ],
            indent=2,
        )
        rejected_text = json.dumps(
            [
                {"investigator": vf.investigator, "claim": vf.finding.claim,
                 "why_rejected": vf.verification_notes}
                for vf in rejected_findings
            ],
            indent=2,
        )
        user = (
            f"Case {case_id}. Deterministic risk score: {deterministic_score}/100.\n\n"
            f"Verified/downgraded findings you may summarize:\n{evidence_text}\n\n"
            f"Findings that FAILED verification (do not use as evidence, but you may note "
            f"that an AI claim was rejected by verification):\n{rejected_text}"
        )
        messages = [
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        try:
            message = await provider.chat(messages, tools=None)
            text = (message.get("content") or "").strip()
            if text.startswith("```"):
                text = text.strip("`")
                text = text.split("\n", 1)[1] if "\n" in text else text
            parts = json.loads(text)
        except (LLMProviderError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("Synthesis LLM call failed for %s, using fallback: %s", case_id, exc)
            parts = _fallback_narrative(accepted, deterministic_score)

    return CaseReport(
        case_id=case_id,
        overall_risk_level=risk_level(deterministic_score),
        deterministic_risk_score=deterministic_score,
        key_findings=accepted,
        conflicting_evidence=parts.get("conflicting_evidence", "None identified."),
        benign_explanations=parts.get("benign_explanations", ""),
        confidence=float(parts.get("confidence", 0.3)),
        recommended_follow_up=parts.get("recommended_follow_up", "Manual review recommended."),
        source_record_refs=source_refs,
        narrative=parts.get("narrative", ""),
    )
