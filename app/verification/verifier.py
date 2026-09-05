"""Deterministic verification of LLM-generated findings.

The LLM's text is never treated as authoritative. For every finding we:
  1. confirm every cited evidence_ref resolves to a real record,
  2. re-derive any numerical claim we can recognize (counts, percentages,
     multipliers, tenderer counts) directly from the database, and
  3. reject or downgrade the claim if the recomputed value materially
     disagrees with what was claimed.

"verified" is deliberately a narrow status: it means step (2) actually ran
and the recomputed value matched. Confirming that a claim's citations point
at real records (step 1) is a necessary check, not verification of the claim
itself -- an LLM can cite a perfectly real record and still describe it
wrongly. So a claim carrying no recomputable numeric assertion ends at
"downgraded", not "verified", however well-cited it is.

The resulting statuses:
  verified    a numeric assertion was re-derived from the database and matched
  downgraded  not independently checkable -- either no recomputable numeric
              assertion was present, or one was but the recomputation was
              unavailable, or the claim cited no evidence at all
  rejected    a cited record does not exist, or a re-derived value materially
              disagrees with what was claimed

Downgraded findings still reach the final report (they are not assumed
false); they are simply never presented as independently confirmed.
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
PRICE_PCT_TOLERANCE = 15.0


def _ref_ids(refs: list[str], scheme: str) -> list[str]:
    return [r.split(":", 1)[1] for r in refs if r.startswith(scheme + ":")]


def _award_refs(refs: list[str]) -> list[tuple[str, str]]:
    """Parses 'award:{case_id}:{award_id}' refs into (case_id, award_id) pairs."""
    out = []
    for r in refs:
        if not r.startswith("award:"):
            continue
        case_id, sep, award_id = r[len("award:"):].partition(":")
        if sep:
            out.append((case_id, award_id))
    return out


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


def _check_bare_contract_count(claim: str, buyer_ids: list[str], supplier_ids: list[str]) -> _Check | None:
    """Catches plain count claims like 'awarded 12 contracts' that don't use
    the 'N of M' phrasing _check_count_of_total looks for. Callers must only
    invoke this when _check_count_of_total already found no match, so a claim
    like '8 of the buyer's last 10 contracts' isn't double-interpreted (this
    regex alone would misread the trailing '10 contracts' as the claim)."""
    m = re.search(r"(\d+)\s+(?:separate\s+|identified\s+)?contracts?\b", claim, re.IGNORECASE)
    if not (m and buyer_ids and supplier_ids):
        return None
    claimed = int(m.group(1))
    related = get_related_contracts(buyer_ids[0], supplier_ids[0])
    actual = related.get("contract_count")
    if actual is None:
        return _Check("downgraded", "Could not independently recompute the cited contract count.")
    if actual != claimed:
        return _Check(
            "rejected",
            f"Claimed {claimed} contract(s); recalculated {actual} identified contract(s) "
            "between this buyer and supplier.",
        )
    return _Check("verified", f"Recalculated contract count ({actual}) matches claim.")


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


def _recompute_price_deviation_pct(case_id: str, award_id: str | None) -> float | None:
    con = get_connection(read_only=True)
    if award_id:
        row = con.execute(
            "SELECT tender_value_amount, award_value_amount FROM case_awards "
            "WHERE case_id = ? AND award_id = ?", [case_id, award_id],
        ).fetchone()
    else:
        row = con.execute(
            "SELECT tender_value_amount, award_value_amount FROM case_awards "
            "WHERE case_id = ? AND award_value_amount IS NOT NULL LIMIT 1", [case_id],
        ).fetchone()
    con.close()
    if not row or not row[0] or row[1] is None:
        return None
    return (row[1] / row[0] - 1) * 100


def _check_price_deviation_percentage(
    claim: str, case_ids: list[str], award_refs: list[tuple[str, str]],
) -> _Check | None:
    """Catches claims like '9900% above the tender's own estimated value' —
    distinct from _check_percentage (buyer/supplier value-share claims),
    which requires buyer+supplier refs this claim shape won't have."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(above|below|higher|lower|over|under)", claim, re.IGNORECASE)
    if not (m and case_ids):
        return None
    claimed_pct = float(m.group(1))
    if m.group(2).lower() in ("below", "lower", "under"):
        claimed_pct = -claimed_pct
    case_id = case_ids[0]
    award_id = next((a for c, a in award_refs if c == case_id), None)
    actual_pct = _recompute_price_deviation_pct(case_id, award_id)
    if actual_pct is None:
        return _Check("downgraded", "Could not independently recompute the cited price deviation percentage.")
    tolerance = max(PRICE_PCT_TOLERANCE, 0.15 * abs(claimed_pct))
    if abs(actual_pct - claimed_pct) > tolerance:
        return _Check(
            "rejected",
            f"Claimed {claimed_pct:.0f}% deviation from the tender estimate; recalculated "
            f"award/tender deviation is {actual_pct:.0f}%.",
        )
    return _Check(
        "verified",
        f"Recalculated award/tender deviation ({actual_pct:.0f}%) matches claimed {claimed_pct:.0f}%.",
    )


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
    award_refs = _award_refs(refs)

    count_of_total_check = _check_count_of_total(finding.claim, buyer_ids, supplier_ids)
    checks = [
        count_of_total_check,
        # Only tried if the "N of M" phrasing didn't match, so a claim like
        # "8 of the buyer's last 10 contracts" isn't reinterpreted using just
        # the trailing "10 contracts" fragment.
        _check_bare_contract_count(finding.claim, buyer_ids, supplier_ids) if count_of_total_check is None else None,
        _check_percentage(finding.claim, buyer_ids, supplier_ids),
        _check_price_deviation_percentage(finding.claim, case_ids, award_refs),
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
        finding=finding, investigator=investigator, verification_status="downgraded",
        verification_notes=(
            "States no recomputable number, so the claim itself was never independently "
            "checked — only that the records it cites are real."
        ),
    )


def verify_all(investigator_outputs: list[InvestigatorOutput]) -> list[VerifiedFinding]:
    results = []
    for output in investigator_outputs:
        for finding in output.findings:
            results.append(verify_finding(finding, output.investigator))
    return results
