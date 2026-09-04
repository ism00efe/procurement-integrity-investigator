import pandas as pd

from app.risk import indicators as ind


def _case_awards(cases_df, awards_df):
    return cases_df.merge(awards_df, on="case_id", how="left")


def test_single_bidder_flags_only_lone_tenderer(synthetic_cases_df):
    results = ind.single_bidder(synthetic_cases_df)
    ids = {r.case_id for r in results}
    assert ids == {"case-1"}
    assert results[0].score == 20.0


def test_low_competition_method_weights_direct_procurement_higher(synthetic_cases_df):
    results = {r.case_id: r for r in ind.low_competition_method(synthetic_cases_df)}
    assert results["case-1"].score == 18.0  # Direct Procurement
    assert "case-2" not in results  # National Competitive Bidding is not low-competition


def test_short_tender_period_uses_population_percentile(synthetic_cases_df):
    # case-1 has a 2-day tender period, far shorter than the 29-day periods of the others.
    results = ind.short_tender_period(synthetic_cases_df)
    assert {r.case_id for r in results} == {"case-1"}


def test_price_deviation_flags_large_ratio_either_direction(synthetic_cases_df, synthetic_awards_df):
    ca = _case_awards(synthetic_cases_df, synthetic_awards_df)
    results = {r.case_id: r for r in ind.price_deviation(ca)}
    # case-1: award 1.5M vs tender 1.0M => ratio 1.5 -> flagged
    assert "case-1" in results
    # case-2: award 950k vs tender 950k => ratio 1.0 -> not flagged
    assert "case-2" not in results


def test_missing_supplier_identity_flags_blank_supplier_name(synthetic_cases_df, synthetic_awards_df):
    ca = _case_awards(synthetic_cases_df, synthetic_awards_df)
    results = ind.missing_supplier_identity(ca)
    assert {r.case_id for r in results} == {"case-3"}


def test_supplier_concentration_ignores_blank_placeholder_suppliers():
    # Regression test: awards with a missing supplier name must never be grouped
    # together as if they were the same real supplier (see SOURCE.md note on the
    # "NG-BPP-" placeholder id shared by unrelated anonymous awards).
    cases = pd.DataFrame([
        {"case_id": f"c{i}", "buyer_id": "buyer-A", "buyer_name": "Buyer A"} for i in range(6)
    ])
    awards = pd.DataFrame([
        {"case_id": f"c{i}", "award_id": f"a{i}", "supplier_id": "PLACEHOLDER",
         "supplier_name": None, "award_value_amount": 1000.0}
        for i in range(6)
    ])
    ca = cases.merge(awards, on="case_id")
    results = ind.supplier_concentration(ca)
    assert results == []


def test_supplier_concentration_flags_genuine_concentration():
    cases = pd.DataFrame([
        {"case_id": f"c{i}", "buyer_id": "buyer-A", "buyer_name": "Buyer A"} for i in range(6)
    ])
    # Same real supplier wins 5 of 6 contracts, representing >40% of value.
    supplier_ids = ["S1"] * 5 + ["S2"]
    supplier_names = ["Repeat Supplier Ltd"] * 5 + ["Other Ltd"]
    awards = pd.DataFrame([
        {"case_id": f"c{i}", "award_id": f"a{i}", "supplier_id": supplier_ids[i],
         "supplier_name": supplier_names[i], "award_value_amount": 1000.0}
        for i in range(6)
    ])
    ca = cases.merge(awards, on="case_id")
    results = ind.supplier_concentration(ca)
    assert len(results) == 5
    assert all(r.case_id != "c5" for r in results)


def test_repeated_relationship_requires_identified_supplier():
    cases = pd.DataFrame([
        {"case_id": f"c{i}", "buyer_id": "buyer-A", "buyer_name": "Buyer A"} for i in range(5)
    ])
    awards = pd.DataFrame([
        {"case_id": f"c{i}", "supplier_id": "S1", "supplier_name": "Repeat Supplier Ltd"}
        for i in range(5)
    ])
    ca = cases.merge(awards, on="case_id")
    results = ind.repeated_relationship(ca)
    assert len(results) == 5


def test_peer_price_outlier_flags_extreme_value_in_group(synthetic_cases_df):
    # Build a larger peer group where one value is a clear robust-z outlier.
    rows = []
    for i in range(8):
        rows.append({
            "case_id": f"peer-{i}", "peer_group_key": "widgets",
            "tender_value_amount": 100_000.0 + i * 1000,
        })
    rows.append({"case_id": "peer-outlier", "peer_group_key": "widgets", "tender_value_amount": 5_000_000.0})
    df = pd.DataFrame(rows)
    results = ind.peer_price_outlier(df)
    assert {r.case_id for r in results} == {"peer-outlier"}
