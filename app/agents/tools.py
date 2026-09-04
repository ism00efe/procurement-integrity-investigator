"""Bounded, deterministic tool interface for LLM investigators.

Every tool is a whitelisted, parameterized query against the local DuckDB
tables built by app.data.ingest — never free-form SQL. Arguments are opaque
IDs (case_id / buyer_id / supplier_id / evidence_ref) that the model can only
obtain from a case's seed context or from a prior tool result, so it cannot
probe the dataset arbitrarily.
"""
import json

from app.data.db import get_connection


def get_tender_details(case_id: str) -> dict:
    con = get_connection(read_only=True)
    row = con.execute(
        "SELECT case_id, buyer_id, buyer_name, tender_title, tender_description, "
        "procurement_method_details, procurement_method_rationale, tender_status, "
        "tender_value_amount, tender_value_currency, number_of_tenderers, "
        "tender_period_start, tender_period_end, tender_period_days, items_count "
        "FROM cases WHERE case_id = ?",
        [case_id],
    ).fetchdf()
    con.close()
    if row.empty:
        return {"error": f"no case found for case_id={case_id}"}
    record = json.loads(row.iloc[0].to_json(date_format="iso"))
    record["evidence_ref"] = f"case:{case_id}"
    return record


def get_competing_bidders(case_id: str) -> dict:
    con = get_connection(read_only=True)
    row = con.execute(
        "SELECT number_of_tenderers FROM cases WHERE case_id = ?", [case_id]
    ).fetchone()
    con.close()
    if row is None:
        return {"error": f"no case found for case_id={case_id}"}
    return {
        "case_id": case_id,
        "number_of_tenderers": row[0],
        "note": (
            "The dataset only discloses the count of tenderers, not their "
            "identities. Do not claim specific losing-bidder names or "
            "attributes beyond this count."
        ),
        "evidence_ref": f"case:{case_id}",
    }


def get_supplier_history(supplier_id: str) -> dict:
    con = get_connection(read_only=True)
    df = con.execute(
        "SELECT buyer_id, buyer_name, award_value_amount, award_date, case_id, award_id "
        "FROM case_awards WHERE supplier_id = ? AND supplier_name IS NOT NULL "
        "AND trim(supplier_name) != ''",
        [supplier_id],
    ).fetchdf()
    con.close()
    if df.empty:
        return {"error": f"no identified awards found for supplier_id={supplier_id}"}
    return {
        "supplier_id": supplier_id,
        "total_awards": int(len(df)),
        "total_value": float(df["award_value_amount"].sum(skipna=True)),
        "distinct_buyers": int(df["buyer_id"].nunique()),
        "buyers": sorted(df["buyer_name"].dropna().unique().tolist())[:20],
        "evidence_ref": f"supplier:{supplier_id}",
    }


def get_buyer_history(buyer_id: str) -> dict:
    con = get_connection(read_only=True)
    df = con.execute(
        "SELECT DISTINCT case_id, procurement_method_details, number_of_tenderers "
        "FROM cases WHERE buyer_id = ?", [buyer_id],
    ).fetchdf()
    awards_df = con.execute(
        "SELECT award_value_amount, supplier_id, supplier_name FROM case_awards "
        "WHERE buyer_id = ? AND award_value_amount IS NOT NULL", [buyer_id],
    ).fetchdf()
    con.close()
    if df.empty:
        return {"error": f"no cases found for buyer_id={buyer_id}"}
    method_counts = df["procurement_method_details"].value_counts().to_dict()
    single_bidder_share = float((df["number_of_tenderers"] == 1).mean())
    return {
        "buyer_id": buyer_id,
        "total_tenders": int(len(df)),
        "total_award_value": float(awards_df["award_value_amount"].sum(skipna=True)),
        "distinct_suppliers": int(awards_df["supplier_id"].nunique()),
        "single_bidder_share": round(single_bidder_share, 3),
        "procurement_method_breakdown": method_counts,
        "evidence_ref": f"buyer:{buyer_id}",
    }


def get_peer_price_comparison(case_id: str) -> dict:
    con = get_connection(read_only=True)
    case_row = con.execute(
        "SELECT tender_title, tender_description, tender_value_amount, peer_group_key "
        "FROM cases WHERE case_id = ?", [case_id],
    ).fetchdf()
    if case_row.empty:
        con.close()
        return {"error": f"no case found for case_id={case_id}"}
    key = case_row.iloc[0]["peer_group_key"]
    value = case_row.iloc[0]["tender_value_amount"]
    if not key:
        con.close()
        return {
            "case_id": case_id,
            "note": "No comparable peer group could be derived from this tender's item text.",
        }
    peers = con.execute(
        "SELECT tender_value_amount FROM cases WHERE peer_group_key = ? "
        "AND tender_value_amount IS NOT NULL", [key],
    ).fetchdf()
    con.close()
    if len(peers) < 3:
        return {
            "case_id": case_id,
            "peer_group_size": int(len(peers)),
            "note": "Fewer than 3 comparable tenders found; peer comparison is not reliable.",
        }
    median = float(peers["tender_value_amount"].median())
    return {
        "case_id": case_id,
        "peer_group_key": key,
        "peer_group_size": int(len(peers)),
        "this_tender_value": float(value) if value is not None else None,
        "peer_median_value": median,
        "ratio_to_peer_median": round(float(value) / median, 3) if value and median else None,
        "evidence_ref": f"case:{case_id}",
    }


def get_related_contracts(buyer_id: str, supplier_id: str) -> dict:
    con = get_connection(read_only=True)
    df = con.execute(
        "SELECT case_id, award_id, award_date, award_value_amount, tender_title "
        "FROM case_awards WHERE buyer_id = ? AND supplier_id = ? "
        "AND supplier_name IS NOT NULL AND trim(supplier_name) != '' "
        "ORDER BY award_date", [buyer_id, supplier_id],
    ).fetchdf()
    con.close()
    if df.empty:
        return {"error": "no identified contracts found for this buyer-supplier pair"}
    records = json.loads(df.to_json(orient="records", date_format="iso"))
    return {
        "buyer_id": buyer_id,
        "supplier_id": supplier_id,
        "contract_count": len(records),
        "contracts": records[:25],
        "evidence_refs": [f"award:{r['case_id']}:{r['award_id']}" for r in records[:25]],
    }


def get_evidence_record(evidence_ref: str) -> dict:
    try:
        scheme, rest = evidence_ref.split(":", 1)
    except ValueError:
        return {"error": f"malformed evidence_ref: {evidence_ref}"}

    if scheme == "case":
        return get_tender_details(rest)
    if scheme == "award":
        case_id, _, award_id = rest.partition(":")
        con = get_connection(read_only=True)
        row = con.execute(
            "SELECT * FROM case_awards WHERE case_id = ? AND award_id = ?",
            [case_id, award_id],
        ).fetchdf()
        con.close()
        if row.empty:
            return {"error": f"no award found for {evidence_ref}"}
        return json.loads(row.iloc[0].to_json(date_format="iso"))
    if scheme == "buyer":
        return get_buyer_history(rest)
    if scheme == "supplier":
        return get_supplier_history(rest)
    return {"error": f"unknown evidence scheme: {scheme}"}


TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "get_tender_details",
            "description": "Get the full tender-stage details for a procurement case.",
            "parameters": {
                "type": "object",
                "properties": {"case_id": {"type": "string"}},
                "required": ["case_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_competing_bidders",
            "description": "Get the number of tenderers that participated in a case's bidding process.",
            "parameters": {
                "type": "object",
                "properties": {"case_id": {"type": "string"}},
                "required": ["case_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_supplier_history",
            "description": "Get aggregate award history (count, total value, distinct buyers) for a supplier.",
            "parameters": {
                "type": "object",
                "properties": {"supplier_id": {"type": "string"}},
                "required": ["supplier_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_buyer_history",
            "description": "Get aggregate procurement history for a buyer (tender count, methods used, supplier diversity).",
            "parameters": {
                "type": "object",
                "properties": {"buyer_id": {"type": "string"}},
                "required": ["buyer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_peer_price_comparison",
            "description": "Compare a tender's estimated value against the median of similar tenders (grouped by item text).",
            "parameters": {
                "type": "object",
                "properties": {"case_id": {"type": "string"}},
                "required": ["case_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_related_contracts",
            "description": "List all contracts awarded by a specific buyer to a specific supplier.",
            "parameters": {
                "type": "object",
                "properties": {
                    "buyer_id": {"type": "string"},
                    "supplier_id": {"type": "string"},
                },
                "required": ["buyer_id", "supplier_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_evidence_record",
            "description": "Fetch the raw underlying record for an evidence reference (e.g. 'case:...', 'award:...:...', 'buyer:...', 'supplier:...').",
            "parameters": {
                "type": "object",
                "properties": {"evidence_ref": {"type": "string"}},
                "required": ["evidence_ref"],
            },
        },
    },
]

_DISPATCH = {
    "get_tender_details": lambda args: get_tender_details(args["case_id"]),
    "get_competing_bidders": lambda args: get_competing_bidders(args["case_id"]),
    "get_supplier_history": lambda args: get_supplier_history(args["supplier_id"]),
    "get_buyer_history": lambda args: get_buyer_history(args["buyer_id"]),
    "get_peer_price_comparison": lambda args: get_peer_price_comparison(args["case_id"]),
    "get_related_contracts": lambda args: get_related_contracts(args["buyer_id"], args["supplier_id"]),
    "get_evidence_record": lambda args: get_evidence_record(args["evidence_ref"]),
}


def dispatch_tool(name: str, arguments: dict) -> dict:
    fn = _DISPATCH.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return fn(arguments)
    except Exception as exc:  # noqa: BLE001 - surfaced to the model as a tool error, not raised
        return {"error": f"tool execution failed: {exc}"}
