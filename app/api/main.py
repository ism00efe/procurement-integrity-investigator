import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agents.providers import LLMNotConfiguredError
from app.core.config import get_settings
from app.data.db import get_connection
from app.services.pipeline import investigate_and_report, load_cached_report

app = FastAPI(title="Procurement Integrity Investigator")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


def _row_indicators(indicators_json: str) -> list[dict]:
    return json.loads(indicators_json)


def _diversify_by_buyer(rows: list[dict], per_buyer_cap: int = 3) -> list[dict]:
    """Presentation-only reordering of an already risk_score-sorted list.

    Validation on the real dataset showed the top of the raw ranking is
    dominated by one buyer's batch of near-duplicate contracts (e.g. 15 of
    the top 20 cases from a single COVID-19 emergency procurement round) --
    a genuine, legitimate concentration (see scripts/validate_ranking.py),
    not a scoring bug. Repeating that near-identical case 15 times at the
    top of a paginated dashboard is still a poor showcase of the system's
    range, so this pushes a buyer's cases past `per_buyer_cap` to the end of
    the list instead of dropping them. It never changes risk_score or the
    stored ranking -- only the order this endpoint returns.
    """
    counts: dict[str, int] = {}
    primary, overflow = [], []
    for row in rows:
        buyer = row.get("buyer") or row.get("buyer_name") or row.get("case_id")
        if counts.get(buyer, 0) < per_buyer_cap:
            primary.append(row)
            counts[buyer] = counts.get(buyer, 0) + 1
        else:
            overflow.append(row)
    return primary + overflow


@app.get("/")
def index():
    return FileResponse(str(WEB_DIR / "templates" / "index.html"))


@app.get("/api/health")
def health():
    settings = get_settings()
    con = get_connection(read_only=True)
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    finally:
        con.close()
    return {
        "llm_configured": settings.llm_configured,
        "llm_model": settings.openrouter_model if settings.llm_configured else None,
        "database_ready": {"cases", "case_risk"}.issubset(tables),
    }


@app.get("/api/summary")
def summary():
    con = get_connection(read_only=True)
    try:
        total = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        risky = con.execute("SELECT COUNT(*) FROM case_risk WHERE risk_score > 0").fetchone()[0]
        high = con.execute("SELECT COUNT(*) FROM case_risk WHERE risk_level = 'high'").fetchone()[0]
        medium = con.execute("SELECT COUNT(*) FROM case_risk WHERE risk_level = 'medium'").fetchone()[0]
        buyers = con.execute("SELECT COUNT(DISTINCT buyer_id) FROM cases").fetchone()[0]
        suppliers = con.execute(
            "SELECT COUNT(DISTINCT supplier_id) FROM case_awards WHERE supplier_name IS NOT NULL "
            "AND trim(supplier_name) != ''"
        ).fetchone()[0]
    finally:
        con.close()
    return {
        "total_procurements_analyzed": total,
        "risky_procurements_detected": risky,
        "high_risk_cases": high,
        "medium_risk_cases": medium,
        "distinct_buyers": buyers,
        "distinct_suppliers": suppliers,
    }


@app.get("/api/cases")
def list_cases(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    risk_level: str | None = None,
    search: str | None = None,
    diversify: bool = Query(
        False,
        description="Presentation only: cap consecutive same-buyer cases so one "
        "buyer's batch doesn't crowd the page. Does not change risk_score or ranking.",
    ),
):
    con = get_connection(read_only=True)
    try:
        clauses = ["risk_score >= ?"]
        params: list = [min_score]
        if risk_level:
            clauses.append("risk_level = ?")
            params.append(risk_level)
        if search:
            clauses.append("(lower(buyer_name) LIKE ? OR lower(tender_title) LIKE ?)")
            like = f"%{search.lower()}%"
            params.extend([like, like])
        where = " AND ".join(clauses)

        total = con.execute(f"SELECT COUNT(*) FROM case_summary WHERE {where}", params).fetchone()[0]
        # When diversifying, pull a larger score-sorted pool so the per-buyer
        # cap has enough later-ranked cases to draw on before we paginate.
        fetch_limit = min(2000, max(offset + limit * 5, 300)) if diversify else limit
        fetch_offset = 0 if diversify else offset
        rows = con.execute(
            f"SELECT case_id, buyer_name, tender_title, tender_value_amount, "
            f"tender_value_currency, procurement_method_details, number_of_tenderers, "
            f"risk_score, risk_level, num_indicators, indicators_json "
            f"FROM case_summary WHERE {where} ORDER BY risk_score DESC, case_id LIMIT ? OFFSET ?",
            [*params, fetch_limit, fetch_offset],
        ).fetchdf()
    finally:
        con.close()

    cases = []
    for _, row in rows.iterrows():
        indicators = _row_indicators(row["indicators_json"])
        cases.append({
            "case_id": row["case_id"],
            "buyer": row["buyer_name"],
            "tender_title": row["tender_title"],
            "contract_value": row["tender_value_amount"],
            "currency": row["tender_value_currency"],
            "procurement_method": row["procurement_method_details"],
            "number_of_tenderers": row["number_of_tenderers"],
            "risk_score": row["risk_score"],
            "risk_level": row["risk_level"],
            "main_indicators": [i["id"] for i in indicators[:3]],
        })

    if diversify:
        cases = _diversify_by_buyer(cases)[offset:offset + limit]

    return {"total": total, "limit": limit, "offset": offset, "diversified": diversify, "cases": cases}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    con = get_connection(read_only=True)
    try:
        row = con.execute("SELECT * FROM case_summary WHERE case_id = ?", [case_id]).fetchdf()
        awards = con.execute(
            "SELECT award_id, award_date, award_value_amount, award_value_currency, "
            "award_status, supplier_id, supplier_name FROM case_awards WHERE case_id = ?",
            [case_id],
        ).fetchdf()
        case_row = con.execute("SELECT * FROM cases WHERE case_id = ?", [case_id]).fetchdf()

        if row.empty:
            related_cases = None
        else:
            buyer_id = row.iloc[0]["buyer_id"]
            identified = awards.dropna(subset=["supplier_id", "supplier_name"])
            identified = identified[identified["supplier_name"].str.strip() != ""]
            if buyer_id and not identified.empty:
                supplier_id = identified.iloc[0]["supplier_id"]
                supplier_name = identified.iloc[0]["supplier_name"]
                siblings = con.execute(
                    "SELECT DISTINCT ca.case_id, ca.tender_title FROM case_awards ca "
                    "WHERE ca.buyer_id = ? AND ca.supplier_id = ? AND ca.case_id != ? "
                    "ORDER BY ca.case_id",
                    [buyer_id, supplier_id, case_id],
                ).fetchdf()
                related_cases = {
                    "supplier_id": supplier_id,
                    "supplier_name": supplier_name,
                    "other_case_count": len(siblings),
                    "sample_cases": siblings.head(10).to_dict(orient="records"),
                } if len(siblings) > 0 else None
            else:
                related_cases = None
    finally:
        con.close()

    if row.empty:
        raise HTTPException(404, f"case not found: {case_id}")

    rec = json.loads(row.iloc[0].to_json())
    rec["indicators"] = json.loads(rec.pop("indicators_json"))
    rec["awards"] = json.loads(awards.to_json(orient="records", date_format="iso"))
    rec["tender"] = json.loads(case_row.iloc[0].to_json(date_format="iso")) if not case_row.empty else None
    rec["related_supplier_cases"] = related_cases
    return rec


@app.get("/api/cases/{case_id}/investigation")
def get_investigation(case_id: str):
    cached = load_cached_report(case_id)
    if cached is None:
        raise HTTPException(404, "No investigation has been run for this case yet.")
    return cached


@app.post("/api/cases/{case_id}/investigate")
async def run_investigation(case_id: str):
    try:
        return await investigate_and_report(case_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
