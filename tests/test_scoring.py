from app.risk.indicators import IndicatorResult
from app.risk.scoring import aggregate, risk_level


def test_aggregate_sums_distinct_indicators_and_dedupes_same_indicator():
    results = [
        IndicatorResult("case-1", "SINGLE_BIDDER", 20.0, "one bidder", ["case:case-1"]),
        IndicatorResult("case-1", "SHORT_TENDER_PERIOD", 15.0, "short period", ["case:case-1"]),
        # A second, weaker SINGLE_BIDDER-style hit for the same case/indicator should not
        # be double-counted -- only the strongest instance per indicator is kept.
        IndicatorResult("case-1", "SINGLE_BIDDER", 5.0, "duplicate weaker hit", ["case:case-1"]),
    ]
    aggregated = aggregate(results)
    case = aggregated["case-1"]
    assert case.risk_score == 35.0
    assert len(case.indicators) == 2


def test_aggregate_caps_score_at_100():
    results = [
        IndicatorResult("case-1", f"IND_{i}", 30.0, "x", []) for i in range(5)
    ]
    aggregated = aggregate(results)
    assert aggregated["case-1"].risk_score == 100.0


def test_risk_level_thresholds():
    assert risk_level(0) == "low"
    assert risk_level(29.9) == "low"
    assert risk_level(30) == "medium"
    assert risk_level(59.9) == "medium"
    assert risk_level(60) == "high"
    assert risk_level(100) == "high"
