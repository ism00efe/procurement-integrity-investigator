"""Deterministic verification of LLM-generated findings.

The LLM's text is never treated as authoritative. For every finding we:
  1. confirm every cited evidence_ref resolves to a real record,
  2. re-derive any numerical claim we can recognize (counts, percentages,
     multipliers, tenderer counts) directly from the database, and
  3. reject or downgrade the claim if the recomputed value materially
     disagrees with what was claimed.

Claims with no recognizable/recomputable numeric assertion are left at
"verified" on the strength of (1) alone, with that limitation stated
explicitly in the notes rather than silently upgraded to full confidence.
"""
import re
from dataclasses import dataclass

from app.agents.schemas import Finding, InvestigatorOutput, VerifiedFinding
from app.agents.tools import (
    get_buyer_history,
    get_competing_bidders,
    get_evidence_record,
    get_peer_price_comparison,
    get_related_contracts,
)
from app.data.db import get_connection

PCT_TOLERANCE = 8.0
RATIO_TOLERANCE = 0.35
COUNT_TOLERANCE = 0


def _ref_ids(refs: list[str], scheme: str) -> list[str]:
    return [r.split(":", 1)[1] for r in refs if r.startswith(scheme + ":")]


def _recompute_supplier_share_pct(buyer_id: str, supplier_id: str) -> float | None:
    con = get_connection(read_only=True)
    row = con.execute(
        "SELECT "
        "  SUM(CASE WHEN supplier_id = ? THEN award_value_amount ELSE 0 END) AS supplier_total, "
        "  SUM(award_value_amount) AS buyer_total "
        "FROM case_awards WHERE buyer_id = ? AND award_value_amount IS NOT NULL "
        "AND supplier_name IS NOT NULL AND trim(supplier_name) != ''",
        [supplier_id, buyer_id],
    ).fetchone()
    con.close()
    if not row or not row[1]:
        return None
    return 100.0 * (row[0] or 0) / row[1]


@dataclass
class _Check:
    status: str
    note: str


def _check_evidence_exists(refs: list[str]) -> _Check | None:
    if not refs:
        return _Check("downgraded", "No evidence references were cited for this claim.")
    missing = [r for r in refs if "error" in get_evidence_record(r)]
    if missing:
        return _Check(
            "rejected",
            f"Evidence reference(s) do not resolve to real records: {missing}.",
        )
    return None


def _check_count_of_total(claim: str, buyer_ids: list[str], supplier_ids: list[str]) -> _Check | None:
    m = re.search(
        r"(\d+)\s+(?:of|out of)\s+(?:the\s+)?(?:buyer'?s?\s+)?(?:last\s+)?(\d+)",
        claim, re.IGNORECASE,
    )
    if not (m and buyer_ids and supplier_ids):
        return None
    claimed_n, claimed_m = int(m.group(1)), int(m.group(2))
    related = get_related_contracts(buyer_ids[0], supplier_ids[0])
    actual_n = related.get("contract_count", 0)
    buyer_hist = get_buyer_history(buyer_ids[0])
    actual_m = buyer_hist.get("total_tenders")
    n_off = abs(actual_n - claimed_n) > COUNT_TOLERANCE
    m_off = actual_m is not None and abs(actual_m - claimed_m) > max(2, round(0.25 * claimed_m))
    if n_off or m_off:
        return _Check(
            "rejected",
            f"Claimed {claimed_n} of {claimed_m}; recalculated {actual_n} identified "
            f"contracts against {actual_m} total buyer tenders on record.",
        )
    return _Check("verified", f"Recalculated count matches claim: {actual_n} of {actual_m}.")


def _check_percentage(claim: str, buyer_ids: list[str], supplier_ids: list[str]) -> _Check | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", claim)
    if not (m and buyer_ids and supplier_ids):
        return None
    claimed_pct = float(m.group(1))
    actual_pct = _recompute_supplier_share_pct(buyer_ids[0], supplier_ids[0])
    if actual_pct is None:
        return _Check("downgraded", "Could not independently recompute the cited percentage.")
    if abs(actual_pct - claimed_pct) > PCT_TOLERANCE:
        return _Check(
            "rejected",
            f"Claimed {claimed_pct:.0f}%; recalculated supplier value share is "
            f"{actual_pct:.0f}% of buyer's total award value.",
        )
    return _Check("verified", f"Recalculated share ({actual_pct:.0f}%) matches claimed {claimed_pct:.0f}%.")


def _check_multiplier(claim: str, case_ids: list[str]) -> _Check | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*x\b", claim, re.IGNORECASE)
    if not (m and case_ids):
        return None
    claimed_ratio = float(m.group(1))
    comparison = get_peer_price_comparison(case_ids[0])
    actual_ratio = comparison.get("ratio_to_peer_median")
    if actual_ratio is None:
        return _Check("downgraded", "Could not independently recompute the cited price ratio.")
    if abs(actual_ratio - claimed_ratio) > RATIO_TOLERANCE:
        return _Check(
            "rejected",
            f"Claimed {claimed_ratio}x peer median; recalculated ratio is {actual_ratio}x.",
        )
    return _Check("verified", f"Recalculated ratio ({actual_ratio}x) matches claimed {claimed_ratio}x.")


def _check_tenderer_count(claim: str, case_ids: list[str]) -> _Check | None:
    m = re.search(r"(\d+)\s+tendere", claim, re.IGNORECASE)
    if not (m and case_ids):
        return None
    claimed = int(m.group(1))
    actual = get_competing_bidders(case_ids[0]).get("number_of_tenderers")
    if actual is None:
        return None
    if actual != claimed:
        return _Check(
            "rejected", f"Claimed {claimed} tenderer(s); dataset records {actual}.",
        )
    return _Check("verified", f"Recalculated tenderer count ({actual}) matches claim.")


def verify_finding(finding: Finding, investigator: str) -> VerifiedFinding:
    refs = finding.evidence_refs
    existence_issue = _check_evidence_exists(refs)
    if existence_issue and existence_issue.status == "rejected":
        return VerifiedFinding(
            finding=finding, investigator=investigator,
            verification_status="rejected", verification_notes=existence_issue.note,
        )

    buyer_ids = _ref_ids(refs, "buyer")
    supplier_ids = _ref_ids(refs, "supplier")
    case_ids = _ref_ids(refs, "case")

    checks = [
        _check_count_of_total(finding.claim, buyer_ids, supplier_ids),
        _check_percentage(finding.claim, buyer_ids, supplier_ids),
        _check_multiplier(finding.claim, case_ids),
        _check_tenderer_count(finding.claim, case_ids),
    ]
    numeric_checks = [c for c in checks if c is not None]

    if any(c.status == "rejected" for c in numeric_checks):
        rejected = [c for c in numeric_checks if c.status == "rejected"]
        return VerifiedFinding(
            finding=finding, investigator=investigator, verification_status="rejected",
            verification_notes=" ".join(c.note for c in rejected),
        )
    if numeric_checks:
        notes = " ".join(c.note for c in numeric_checks)
        status = "downgraded" if any(c.status == "downgraded" for c in numeric_checks) else "verified"
        return VerifiedFinding(
            finding=finding, investigator=investigator, verification_status=status,
            verification_notes=notes,
        )

    if existence_issue:  # no refs cited at all
        return VerifiedFinding(
            finding=finding, investigator=investigator,
            verification_status="downgraded", verification_notes=existence_issue.note,
        )

    return VerifiedFinding(
        finding=finding, investigator=investigator, verification_status="verified",
        verification_notes=(
            "All cited evidence references resolve to real records. No specific numeric "
            "assertion in this claim could be independently recalculated; the qualitative "
            "claim is accepted on the strength of the underlying evidence alone."
        ),
    )


def verify_all(investigator_outputs: list[InvestigatorOutput]) -> list[VerifiedFinding]:
    results = []
    for output in investigator_outputs:
        for finding in output.findings:
            results.append(verify_finding(finding, output.investigator))
    return results
