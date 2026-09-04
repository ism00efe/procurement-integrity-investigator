from app.agents.schemas import Finding
from app.verification.verifier import verify_finding


def test_count_of_total_claim_rejected_when_recalculation_disagrees(temp_database):
    # Mirrors the architecture's canonical example: LLM claims "8 of 10" but the
    # database only shows 1 identified contract out of 3 total buyer tenders.
    finding = Finding(
        claim="This supplier won 8 of the buyer's last 10 contracts.",
        evidence_refs=["buyer:buyer-A", "supplier:supplier-X"],
        confidence=0.9, risk_level="high",
    )
    result = verify_finding(finding, "supplier")
    assert result.verification_status == "rejected"
    assert "recalculated" in result.verification_notes.lower()


def test_percentage_claim_verified_when_close_to_actual(temp_database):
    # supplier-X's true share of buyer-A's *identified-supplier* award value is
    # 1,500,000 / (1,500,000 + 950,000) = ~61.2% (case-3's blank-supplier award
    # is excluded from both numerator and denominator).
    finding = Finding(
        claim="This supplier received about 61% of the buyer's total award value.",
        evidence_refs=["buyer:buyer-A", "supplier:supplier-X"],
        confidence=0.6, risk_level="medium",
    )
    result = verify_finding(finding, "supplier")
    assert result.verification_status == "verified"


def test_percentage_claim_rejected_when_far_from_actual(temp_database):
    finding = Finding(
        claim="This supplier received 10% of the buyer's total award value.",
        evidence_refs=["buyer:buyer-A", "supplier:supplier-X"],
        confidence=0.9, risk_level="high",
    )
    result = verify_finding(finding, "supplier")
    assert result.verification_status == "rejected"


def test_nonexistent_evidence_ref_is_rejected(temp_database):
    finding = Finding(
        claim="Some claim about a case.",
        evidence_refs=["case:does-not-exist"],
        confidence=0.5, risk_level="medium",
    )
    result = verify_finding(finding, "procedure")
    assert result.verification_status == "rejected"
    assert "does not resolve" in result.verification_notes.lower() or "do not resolve" in result.verification_notes.lower()


def test_claim_with_no_evidence_refs_is_downgraded(temp_database):
    finding = Finding(claim="Something unusual here.", evidence_refs=[], confidence=0.4, risk_level="low")
    result = verify_finding(finding, "procedure")
    assert result.verification_status == "downgraded"


def test_price_deviation_percentage_verified_when_matching(temp_database):
    # case-1: tender 1,000,000 vs award a1 1,500,000 -> true deviation is +50%.
    finding = Finding(
        claim="Awarded value is 50% above the tender's own estimated value.",
        evidence_refs=["case:case-1", "award:case-1:a1"],
        confidence=0.8, risk_level="high",
    )
    result = verify_finding(finding, "price")
    assert result.verification_status == "verified"


def test_price_deviation_percentage_rejected_when_fabricated(temp_database):
    # Regression test: this claim shape ("X% above the tender's own estimated
    # value") previously slipped past every numeric check (the multiplier
    # check only recognizes "Nx" phrasing, and the percentage check requires
    # buyer+supplier refs this claim doesn't have) and fell through to the
    # weak evidence-existence-only "verified" fallback.
    finding = Finding(
        claim="Awarded value is 9900% above the tender's own estimated value.",
        evidence_refs=["case:case-1", "award:case-1:a1"],
        confidence=0.85, risk_level="high",
    )
    result = verify_finding(finding, "price")
    assert result.verification_status == "rejected"
    assert "recalculated" in result.verification_notes.lower()


def test_bare_contract_count_verified_when_matching(temp_database):
    # buyer-A/supplier-X share exactly 1 identified contract (case-1/a1).
    finding = Finding(
        claim="The supplier has been awarded 1 contract from the same buyer.",
        evidence_refs=["buyer:buyer-A", "supplier:supplier-X"],
        confidence=0.7, risk_level="medium",
    )
    result = verify_finding(finding, "supplier")
    assert result.verification_status == "verified"


def test_bare_contract_count_rejected_when_fabricated(temp_database):
    finding = Finding(
        claim="The supplier has been awarded 12 contracts from the same buyer.",
        evidence_refs=["buyer:buyer-A", "supplier:supplier-X"],
        confidence=0.7, risk_level="high",
    )
    result = verify_finding(finding, "supplier")
    assert result.verification_status == "rejected"


def test_n_of_m_phrasing_is_not_reinterpreted_by_bare_count_check(temp_database):
    # The trailing "10 contracts" must not be picked up by the bare-count
    # check once _check_count_of_total has already matched "8 of ... 10".
    finding = Finding(
        claim="This supplier won 8 of the buyer's last 10 contracts.",
        evidence_refs=["buyer:buyer-A", "supplier:supplier-X"],
        confidence=0.9, risk_level="high",
    )
    result = verify_finding(finding, "supplier")
    # Still rejected (actual is 1 of 3), but for the count-of-total reason,
    # not a conflicting/duplicate bare-count reason.
    assert result.verification_status == "rejected"
    assert "of" in result.verification_notes.lower()


def test_qualitative_claim_with_valid_evidence_is_verified(temp_database):
    finding = Finding(
        claim="Only one tenderer participated in this process.",
        evidence_refs=["case:case-1"], confidence=0.8, risk_level="high",
    )
    result = verify_finding(finding, "procedure")
    assert result.verification_status == "verified"
