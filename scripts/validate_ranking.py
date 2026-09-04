"""Validation analysis: does the deterministic weighted risk score add value
over a trivial single-bidder baseline?

Not part of the application; a one-off validation tool for the hackathon
write-up. Run: .venv\\Scripts\\python -m scripts.validate_ranking
"""
import json
from collections import Counter

import numpy as np
import pandas as pd

from app.data.db import get_connection

con = get_connection(read_only=True)
cases = con.execute(
    "SELECT case_id, buyer_id, buyer_name, tender_value_amount, tender_value_currency, "
    "procurement_method_details, number_of_tenderers FROM cases"
).fetchdf()
risk = con.execute(
    "SELECT case_id, risk_score, risk_level, indicators_json, num_indicators FROM case_risk"
).fetchdf()
awards = con.execute(
    "SELECT case_id, supplier_id, supplier_name FROM case_awards"
).fetchdf()
con.close()

df = cases.merge(risk, on="case_id", how="left")
df["indicators"] = df["indicators_json"].apply(json.loads)
df["indicator_ids"] = df["indicators"].apply(lambda inds: [i["id"] for i in inds])

# Primary (identified) supplier per case, for supplier-diversity comparison.
awards_id = awards.dropna(subset=["supplier_id", "supplier_name"])
awards_id = awards_id[awards_id["supplier_name"].str.strip() != ""]
primary_supplier = awards_id.groupby("case_id")["supplier_id"].first()
df["primary_supplier_id"] = df["case_id"].map(primary_supplier)


def profile(subset: pd.DataFrame, label: str, n: int) -> dict:
    top = subset.head(n)
    n_ind = top["indicator_ids"].apply(len)
    all_ind_ids = [i for lst in top["indicator_ids"] for i in lst]
    return {
        "label": label,
        "n": len(top),
        "avg_indicators_per_case": round(n_ind.mean(), 2),
        "pct_with_3plus_indicators": round(100 * (n_ind >= 3).mean(), 1),
        "pct_with_1_indicator_only": round(100 * (n_ind == 1).mean(), 1),
        "distinct_indicator_types_used": len(set(all_ind_ids)),
        "indicator_type_counts": dict(Counter(all_ind_ids).most_common()),
        "median_risk_score": round(top["risk_score"].median(), 1),
        "risk_score_range": (top["risk_score"].min(), top["risk_score"].max()),
        "distinct_buyers": top["buyer_id"].nunique(),
        "top_buyer_share_pct": round(
            100 * top["buyer_id"].value_counts().iloc[0] / len(top), 1
        ) if len(top) else 0,
        "distinct_suppliers": top["primary_supplier_id"].nunique(),
        "distinct_procurement_methods": top["procurement_method_details"].nunique(),
        "median_contract_value": round(top["tender_value_amount"].median(), 0)
        if top["tender_value_amount"].notna().any() else None,
        "total_contract_value": round(top["tender_value_amount"].sum(), 0)
        if top["tender_value_amount"].notna().any() else None,
        "pct_single_bidder": round(100 * (top["number_of_tenderers"] == 1).mean(), 1),
    }


our_ranking = df.sort_values(["risk_score", "case_id"], ascending=[False, True])

# Baseline: rank using ONLY numberOfTenderers == 1. This is a binary filter,
# not a score, so it cannot order cases within the filtered set on its own.
# We break ties by contract value (largest first) -- the one piece of
# information a human would naturally reach for to prioritize among an
# undifferentiated pile of single-bidder cases, and NOT one of our own risk
# indicators. This is the most charitable, realistic version of the baseline.
baseline_pool = df[df["number_of_tenderers"] == 1]
baseline_ranking = baseline_pool.sort_values(
    ["tender_value_amount", "case_id"], ascending=[False, True]
)

print("=" * 78)
print("RANKING VALIDATION: deterministic weighted score vs. single-bidder baseline")
print("=" * 78)
print(f"\nTotal cases analyzed: {len(df)}")
print(f"Cases with number_of_tenderers == 1: {len(baseline_pool)} ({100*len(baseline_pool)/len(df):.1f}%)")
print(f"Cases with risk_score > 0: {(df['risk_score'] > 0).sum()} ({100*(df['risk_score']>0).mean():.1f}%)")

for n in (20, 100):
    print(f"\n{'-'*78}\nTOP {n} COMPARISON\n{'-'*78}")
    ours = profile(our_ranking, "our ranking", n)
    base = profile(baseline_ranking, "single-bidder baseline", n)

    rows = [
        ("Avg indicators/case", ours["avg_indicators_per_case"], base["avg_indicators_per_case"]),
        ("% with 3+ indicators", ours["pct_with_3plus_indicators"], base["pct_with_3plus_indicators"]),
        ("% with exactly 1 indicator", ours["pct_with_1_indicator_only"], base["pct_with_1_indicator_only"]),
        ("Distinct indicator types present", ours["distinct_indicator_types_used"], base["distinct_indicator_types_used"]),
        ("Median risk score", ours["median_risk_score"], base["median_risk_score"]),
        ("Risk score range", ours["risk_score_range"], base["risk_score_range"]),
        ("Distinct buyers", ours["distinct_buyers"], base["distinct_buyers"]),
        ("Top buyer's share of list (%)", ours["top_buyer_share_pct"], base["top_buyer_share_pct"]),
        ("Distinct suppliers", ours["distinct_suppliers"], base["distinct_suppliers"]),
        ("Distinct procurement methods", ours["distinct_procurement_methods"], base["distinct_procurement_methods"]),
        ("Median contract value (NGN)", ours["median_contract_value"], base["median_contract_value"]),
        ("Total contract value (NGN)", ours["total_contract_value"], base["total_contract_value"]),
        ("% single-bidder", ours["pct_single_bidder"], base["pct_single_bidder"]),
    ]
    print(f"{'Metric':38s} {'Our ranking':>18s} {'Single-bidder baseline':>24s}")
    for name, a, b in rows:
        print(f"{name:38s} {str(a):>18s} {str(b):>24s}")

    print(f"\nOur top {n} indicator mix: {ours['indicator_type_counts']}")
    print(f"Baseline top {n} indicator mix: {base['indicator_type_counts']}")

    ours_ids = set(our_ranking.head(n)["case_id"])
    base_ids = set(baseline_ranking.head(n)["case_id"])
    overlap = ours_ids & base_ids
    print(f"\nOverlap between the two top-{n} lists: {len(overlap)}/{n} cases "
          f"({100*len(overlap)/n:.0f}%)")
    print(f"Cases in our top {n} that are NOT single-bidder at all: "
          f"{(our_ranking.head(n)['number_of_tenderers'] != 1).sum()}/{n}")

print(f"\n{'-'*78}\nTOP-20 BUYER CONCENTRATION CHECK (our ranking)\n{'-'*78}")
top20 = our_ranking.head(20)
buyer_counts = top20["buyer_name"].value_counts()
print(buyer_counts.to_dict())
print(f"\nDistinct buyers in top 20: {top20['buyer_id'].nunique()} / 20 cases")
for buyer_id, group in top20.groupby("buyer_id"):
    if len(group) < 2:
        continue
    bname = group["buyer_name"].iloc[0]
    ind_sets = [set(x) for x in group["indicator_ids"]]
    common = set.intersection(*ind_sets) if ind_sets else set()
    print(f"\nBuyer '{bname}' ({len(group)} cases in top 20):")
    for _, row in group.iterrows():
        print(f"  {row['case_id']:35s} score={row['risk_score']:6.1f}  indicators={row['indicator_ids']}")
    print(f"  Indicators common to ALL of this buyer's top-20 cases: {common or '(none)'}")
