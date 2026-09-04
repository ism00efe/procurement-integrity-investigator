"""Transparent aggregation of indicator results into a single 0-100 risk score
per case. No hidden weighting: the overall score is simply the sum of each
triggered indicator's point contribution (deduplicated per indicator per
case by taking its strongest instance), capped at 100 so a case can't exceed
the scale. This keeps "why did this case score 91/100?" answerable by listing
the contributing indicators, in contrast to an opaque model-derived score.
"""
from dataclasses import dataclass

from app.risk.indicators import IndicatorResult

MAX_SCORE = 100.0


@dataclass
class CaseRisk:
    case_id: str
    risk_score: float
    indicators: list[IndicatorResult]

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "risk_score": self.risk_score,
            "indicators": [
                {
                    "id": ind.indicator_id,
                    "score": ind.score,
                    "explanation": ind.explanation,
                    "evidence_refs": ind.evidence_refs,
                }
                for ind in self.indicators
            ],
        }


def aggregate(all_indicator_results: list[IndicatorResult]) -> dict[str, CaseRisk]:
    by_case: dict[str, dict[str, IndicatorResult]] = {}
    for result in all_indicator_results:
        bucket = by_case.setdefault(result.case_id, {})
        existing = bucket.get(result.indicator_id)
        if existing is None or result.score > existing.score:
            bucket[result.indicator_id] = result

    case_risks: dict[str, CaseRisk] = {}
    for case_id, indicators_by_id in by_case.items():
        indicators = sorted(indicators_by_id.values(), key=lambda r: -r.score)
        raw_score = sum(ind.score for ind in indicators)
        case_risks[case_id] = CaseRisk(
            case_id=case_id,
            risk_score=round(min(raw_score, MAX_SCORE), 1),
            indicators=indicators,
        )
    return case_risks


def risk_level(score: float) -> str:
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"
