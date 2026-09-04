"""Deterministic procurement risk indicators.

Each indicator is a pure function over pandas DataFrames (loaded from DuckDB)
that returns a per-case_id score contribution plus a human-readable
explanation and evidence references. Conceptual basis: Open Contracting
Partnership's red-flag methodology, restricted to what the Nigeria BPP OCDS
dataset actually contains (see data/raw/SOURCE.md).

Evidence reference scheme:
  case:{case_id}              -> the tender-stage case record
  award:{case_id}:{award_id}  -> a specific award record
  buyer:{buyer_id}            -> aggregate buyer statistics
  supplier:{supplier_id}      -> aggregate supplier statistics
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

LOW_COMPETITION_METHODS = {
    "Direct Procurement", "Sole Source", "Emergency", "Selective Tendering",
}


@dataclass
class IndicatorResult:
    case_id: str
    indicator_id: str
    score: float
    explanation: str
    evidence_refs: list[str] = field(default_factory=list)


IndicatorTable = list[IndicatorResult]


def single_bidder(cases: pd.DataFrame) -> IndicatorTable:
    out = []
    hits = cases[cases["number_of_tenderers"] == 1]
    for _, row in hits.iterrows():
        out.append(IndicatorResult(
            case_id=row["case_id"],
            indicator_id="SINGLE_BIDDER",
            score=20.0,
            explanation="Only one tenderer participated in this competitive process.",
            evidence_refs=[f"case:{row['case_id']}"],
        ))
    return out


def low_competition_method(cases: pd.DataFrame) -> IndicatorTable:
    out = []
    hits = cases[cases["procurement_method_details"].isin(LOW_COMPETITION_METHODS)]
    for _, row in hits.iterrows():
        method = row["procurement_method_details"]
        weight = 18.0 if method in ("Sole Source", "Direct Procurement") else 12.0
        out.append(IndicatorResult(
            case_id=row["case_id"],
            indicator_id="LOW_COMPETITION_METHOD",
            score=weight,
            explanation=f'Procured via "{method}", a reduced-competition method.',
            evidence_refs=[f"case:{row['case_id']}"],
        ))
    return out


def short_tender_period(cases: pd.DataFrame) -> IndicatorTable:
    out = []
    valid = cases[cases["tender_period_days"].notna()]
    if valid.empty:
        return out
    threshold = valid["tender_period_days"].quantile(0.10)
    hits = valid[valid["tender_period_days"] <= max(threshold, 3)]
    for _, row in hits.iterrows():
        days = row["tender_period_days"]
        out.append(IndicatorResult(
            case_id=row["case_id"],
            indicator_id="SHORT_TENDER_PERIOD",
            score=15.0 if days <= 3 else 10.0,
            explanation=(
                f"Tender period was only {int(days)} day(s), in the shortest 10% of all "
                "tenders in this dataset, limiting time for competitors to bid."
            ),
            evidence_refs=[f"case:{row['case_id']}"],
        ))
    return out


def price_deviation(case_awards: pd.DataFrame) -> IndicatorTable:
    """NOTE on this dataset: in 99.94% of records, award value is exactly
    equal to the tender's own estimated value (the source system appears to
    populate both from the same underlying figure rather than recording an
    independent pre-bid estimate). A deviation here is therefore rare and,
    when it occurs, is at least as likely to reflect a data-entry error
    (e.g. a stray extra digit) as a genuine cost overrun — either way, a
    large discrepancy in the public record is worth a human look, so this
    indicator is kept but its explanation says so explicitly rather than
    implying a confident economic reading."""
    out = []
    df = case_awards.dropna(subset=["tender_value_amount", "award_value_amount", "award_id"])
    df = df[df["tender_value_amount"] > 0]
    ratio = df["award_value_amount"] / df["tender_value_amount"]
    hits = df[(ratio >= 1.5) | (ratio <= 0.5)]
    for (_, row), r in zip(hits.iterrows(), ratio.loc[hits.index]):
        pct = (r - 1) * 100
        direction = "above" if pct > 0 else "below"
        score = min(20.0, 8.0 + abs(pct) / 20.0)
        out.append(IndicatorResult(
            case_id=row["case_id"],
            indicator_id="PRICE_DEVIATION",
            score=round(score, 1),
            explanation=(
                f"Awarded value is {abs(pct):.0f}% {direction} the tender's own recorded "
                "estimate. In this dataset these two figures are almost always identical, "
                "so a gap this large is unusual and worth checking against the source "
                "record — either a genuine cost/estimate anomaly or a data-entry error."
            ),
            evidence_refs=[f"case:{row['case_id']}", f"award:{row['case_id']}:{row['award_id']}"],
        ))
    return out


def _with_identified_supplier(case_awards: pd.DataFrame) -> pd.DataFrame:
    """Rows with a genuine supplier identity. Excludes blank/placeholder
    supplier_id values (e.g. "NG-BPP-") shared across unrelated anonymous
    awards from different buyers — grouping on those would fabricate false
    same-supplier relationships."""
    df = case_awards.dropna(subset=["supplier_id", "supplier_name"])
    return df[df["supplier_name"].str.strip() != ""]


def supplier_concentration(case_awards: pd.DataFrame) -> IndicatorTable:
    out = []
    df = _with_identified_supplier(case_awards).dropna(subset=["buyer_id", "award_value_amount"])
    grouped = df.groupby(["buyer_id", "supplier_id"])["award_value_amount"].sum()
    buyer_totals = df.groupby("buyer_id")["award_value_amount"].sum()
    supplier_award_count = df.groupby(["buyer_id", "supplier_id"]).size()
    buyer_award_count = df.groupby("buyer_id").size()

    share = (grouped / buyer_totals).rename("value_share")
    count_share = (supplier_award_count / buyer_award_count).rename("count_share")

    risky_pairs = share[(share >= 0.40) & (buyer_award_count.reindex(share.index.get_level_values("buyer_id")).values >= 5)]

    for (buyer_id, supplier_id), value_share in risky_pairs.items():
        rows = df[(df["buyer_id"] == buyer_id) & (df["supplier_id"] == supplier_id)]
        supplier_name = rows["supplier_name"].dropna().iloc[0] if rows["supplier_name"].notna().any() else supplier_id
        buyer_name = rows["buyer_name"].dropna().iloc[0] if rows["buyer_name"].notna().any() else buyer_id
        n_contracts = len(rows)
        for _, row in rows.iterrows():
            out.append(IndicatorResult(
                case_id=row["case_id"],
                indicator_id="SUPPLIER_CONCENTRATION",
                score=round(min(18.0, value_share * 25), 1),
                explanation=(
                    f'Supplier "{supplier_name}" received {value_share*100:.0f}% of the '
                    f'total award value from buyer "{buyer_name}" across {n_contracts} '
                    "contracts in this dataset."
                ),
                evidence_refs=[f"buyer:{buyer_id}", f"supplier:{supplier_id}"],
            ))
    return out


def repeated_relationship(case_awards: pd.DataFrame) -> IndicatorTable:
    out = []
    df = _with_identified_supplier(case_awards).dropna(subset=["buyer_id"])
    pair_counts = df.groupby(["buyer_id", "supplier_id"]).size()
    repeated = pair_counts[pair_counts >= 5]
    for (buyer_id, supplier_id), n in repeated.items():
        rows = df[(df["buyer_id"] == buyer_id) & (df["supplier_id"] == supplier_id)]
        supplier_name = rows["supplier_name"].dropna().iloc[0] if rows["supplier_name"].notna().any() else supplier_id
        buyer_name = rows["buyer_name"].dropna().iloc[0] if rows["buyer_name"].notna().any() else buyer_id
        for _, row in rows.iterrows():
            out.append(IndicatorResult(
                case_id=row["case_id"],
                indicator_id="REPEATED_RELATIONSHIP",
                score=round(min(15.0, 3 + n), 1),
                explanation=(
                    f'Buyer "{buyer_name}" has awarded {n} separate contracts to supplier '
                    f'"{supplier_name}" in this dataset.'
                ),
                evidence_refs=[f"buyer:{buyer_id}", f"supplier:{supplier_id}"],
            ))
    return out


def missing_supplier_identity(case_awards: pd.DataFrame) -> IndicatorTable:
    out = []
    df = case_awards.dropna(subset=["award_id"])
    hits = df[df["supplier_name"].isna() | (df["supplier_name"].str.strip() == "")]
    for _, row in hits.iterrows():
        out.append(IndicatorResult(
            case_id=row["case_id"],
            indicator_id="MISSING_SUPPLIER_IDENTITY",
            score=12.0,
            explanation="The award record does not disclose the winning supplier's name.",
            evidence_refs=[f"award:{row['case_id']}:{row['award_id']}"],
        ))
    return out


def peer_price_outlier(cases: pd.DataFrame) -> IndicatorTable:
    out = []
    df = cases.dropna(subset=["peer_group_key", "tender_value_amount"])
    df = df[df["tender_value_amount"] > 0]
    groups = df.groupby("peer_group_key")
    for key, group in groups:
        if len(group) < 5:
            continue
        median = group["tender_value_amount"].median()
        mad = (group["tender_value_amount"] - median).abs().median()
        if mad == 0:
            continue
        robust_z = 0.6745 * (group["tender_value_amount"] - median) / mad
        outliers = group[robust_z.abs() >= 4.0]
        for _, row in outliers.iterrows():
            ratio = row["tender_value_amount"] / median
            # Below 1.0, "0.1x" rounds to a meaningless "0.0x" for large gaps;
            # express those as a percentage of the peer median instead.
            ratio_text = f"{ratio:.1f}x" if ratio >= 0.1 else f"only {ratio * 100:.1f}% of"
            out.append(IndicatorResult(
                case_id=row["case_id"],
                indicator_id="PEER_PRICE_OUTLIER",
                score=round(min(15.0, 6 + abs(ratio - 1) * 3), 1),
                explanation=(
                    f"Estimated value is {ratio_text} the median for {len(group)} tenders "
                    f'with similar item descriptions ("{key}").'
                ),
                evidence_refs=[f"case:{row['case_id']}"],
            ))
    return out


def buyer_award_burst(case_awards: pd.DataFrame) -> IndicatorTable:
    """Flags awards that fall inside an unusually dense burst of high-value
    awards by the same buyer within a short window, a pattern associated with
    year-end budget-flush spending or artificial contract splitting."""
    out = []
    df = case_awards.dropna(subset=["buyer_id", "award_date", "award_value_amount", "award_id"]).copy()
    if df.empty:
        return out
    df = df.sort_values(["buyer_id", "award_date"])
    high_value_threshold = df["award_value_amount"].quantile(0.75)

    for buyer_id, group in df.groupby("buyer_id"):
        high = group[group["award_value_amount"] >= high_value_threshold]
        if len(high) < 5:
            continue
        dates = high["award_date"]
        window_days = (dates.max() - dates.min()).days
        if window_days <= 0:
            continue
        density = len(high) / max(window_days, 1)
        if len(high) >= 5 and window_days <= 21:
            buyer_name = group["buyer_name"].dropna().iloc[0] if group["buyer_name"].notna().any() else buyer_id
            for _, row in high.iterrows():
                out.append(IndicatorResult(
                    case_id=row["case_id"],
                    indicator_id="BUYER_AWARD_BURST",
                    score=10.0,
                    explanation=(
                        f'Buyer "{buyer_name}" made {len(high)} high-value awards within a '
                        f"{window_days}-day window, a denser-than-typical clustering."
                    ),
                    evidence_refs=[f"buyer:{buyer_id}"],
                ))
    return out


ALL_CASE_LEVEL_INDICATORS = [single_bidder, low_competition_method, short_tender_period, peer_price_outlier]
ALL_AWARD_LEVEL_INDICATORS = [
    price_deviation, supplier_concentration, repeated_relationship,
    missing_supplier_identity, buyer_award_burst,
]
