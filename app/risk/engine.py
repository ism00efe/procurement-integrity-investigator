import json
from datetime import datetime, timezone

import pandas as pd

from app.data.db import get_connection
from app.risk import indicators as ind
from app.risk.scoring import CaseRisk, aggregate, risk_level


def run_risk_engine() -> dict[str, CaseRisk]:
    con = get_connection()
    cases = con.execute("SELECT * FROM cases").fetchdf()
    case_awards = con.execute("SELECT * FROM case_awards").fetchdf()
    con.close()

    all_results: list[ind.IndicatorResult] = []
    for fn in ind.ALL_CASE_LEVEL_INDICATORS:
        all_results.extend(fn(cases))
    for fn in ind.ALL_AWARD_LEVEL_INDICATORS:
        all_results.extend(fn(case_awards))

    case_risks = aggregate(all_results)

    # Cases with a tender but no triggered indicators still get a zero-risk row
    # so ranking/coverage stats reflect the full analyzed population.
    for case_id in cases["case_id"]:
        if case_id not in case_risks:
            case_risks[case_id] = CaseRisk(case_id=case_id, risk_score=0.0, indicators=[])

    return case_risks


def persist_risk_results(case_risks: dict[str, CaseRisk]) -> None:
    rows = []
    for case_id, cr in case_risks.items():
        rows.append({
            "case_id": case_id,
            "risk_score": cr.risk_score,
            "risk_level": risk_level(cr.risk_score),
            "indicators_json": json.dumps([
                {
                    "id": i.indicator_id, "score": i.score,
                    "explanation": i.explanation, "evidence_refs": i.evidence_refs,
                }
                for i in cr.indicators
            ]),
            "num_indicators": len(cr.indicators),
            "computed_at": datetime.now(timezone.utc).isoformat(),
        })
    df = pd.DataFrame(rows)
    con = get_connection()
    con.register("risk_df", df)
    con.execute("CREATE OR REPLACE TABLE case_risk AS SELECT * FROM risk_df")
    con.execute(
        "CREATE OR REPLACE VIEW case_summary AS "
        "SELECT c.case_id, c.buyer_id, c.buyer_name, c.tender_title, c.tender_value_amount, "
        "c.tender_value_currency, c.procurement_method_details, c.number_of_tenderers, "
        "r.risk_score, r.risk_level, r.num_indicators, r.indicators_json "
        "FROM cases c JOIN case_risk r USING (case_id)"
    )
    con.close()


def top_n_cases(n: int) -> list[str]:
    con = get_connection(read_only=True)
    rows = con.execute(
        "SELECT case_id FROM case_risk ORDER BY risk_score DESC, case_id LIMIT ?", [n]
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


if __name__ == "__main__":
    results = run_risk_engine()
    persist_risk_results(results)
    scored = [cr for cr in results.values() if cr.risk_score > 0]
    print(json.dumps({
        "total_cases_analyzed": len(results),
        "cases_with_indicators": len(scored),
        "high_risk_cases (>=60)": sum(1 for cr in scored if cr.risk_score >= 60),
        "medium_risk_cases (30-59)": sum(1 for cr in scored if 30 <= cr.risk_score < 60),
    }, indent=2))
