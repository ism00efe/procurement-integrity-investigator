"""One-shot setup: ingest the raw dataset and run the deterministic risk engine.
Run this after downloading data/raw/nigeria_bpp_full.jsonl(.gz) and before
starting the API server. Does not call the LLM layer.
"""
import json

from app.data.ingest import build_database
from app.risk.engine import persist_risk_results, run_risk_engine

if __name__ == "__main__":
    ingest_stats = build_database()
    print("Ingested:", json.dumps(ingest_stats, indent=2))

    case_risks = run_risk_engine()
    persist_risk_results(case_risks)
    scored = [cr for cr in case_risks.values() if cr.risk_score > 0]
    print("Risk engine:", json.dumps({
        "total_cases_analyzed": len(case_risks),
        "cases_with_indicators": len(scored),
        "high_risk_cases": sum(1 for cr in scored if cr.risk_score >= 60),
        "medium_risk_cases": sum(1 for cr in scored if 30 <= cr.risk_score < 60),
    }, indent=2))
