"""Ad hoc analysis of the deterministic risk engine's output on the real
dataset -- indicator trigger counts, score distributions, co-occurrence,
and top-case inspection. Not part of the application; a validation tool.
"""
import json
from collections import Counter

import numpy as np

from app.data.db import get_connection

con = get_connection(read_only=True)
df = con.execute("SELECT case_id, risk_score, risk_level, indicators_json FROM case_risk").fetchdf()
con.close()

df["indicators"] = df["indicators_json"].apply(json.loads)

print("=" * 70)
print("SCORE DISTRIBUTION")
print("=" * 70)
scores = df["risk_score"].values
nonzero = scores[scores > 0]
print(f"Total cases: {len(scores)}")
print(f"Cases with score > 0: {len(nonzero)} ({100*len(nonzero)/len(scores):.1f}%)")
for p in [50, 75, 90, 95, 99, 99.5, 100]:
    print(f"  p{p}: {np.percentile(scores, p):.1f}")
print(f"Risk level counts: {df['risk_level'].value_counts().to_dict()}")

print()
print("=" * 70)
print("INDICATOR TRIGGER COUNTS AND SCORE STATS")
print("=" * 70)
indicator_scores = {}
indicator_counts = Counter()
for inds in df["indicators"]:
    for ind in inds:
        indicator_counts[ind["id"]] += 1
        indicator_scores.setdefault(ind["id"], []).append(ind["score"])

for ind_id, count in indicator_counts.most_common():
    s = np.array(indicator_scores[ind_id])
    print(f"{ind_id:28s} n={count:6d} ({100*count/len(df):5.1f}%)  "
          f"score min={s.min():.1f} median={np.median(s):.1f} max={s.max():.1f}")

print()
print("=" * 70)
print("NUMBER OF DISTINCT INDICATORS PER CASE (among cases with >=1)")
print("=" * 70)
n_ind = df["indicators"].apply(len)
n_ind_nonzero = n_ind[n_ind > 0]
print(Counter(n_ind_nonzero).most_common())

print()
print("=" * 70)
print("SINGLE-INDICATOR-ONLY CASES: how high can score get from ONE indicator?")
print("=" * 70)
single = df[n_ind == 1]
print(f"{len(single)} cases triggered by exactly one indicator")
print(f"  score distribution: min={single['risk_score'].min()}, "
      f"median={single['risk_score'].median()}, max={single['risk_score'].max()}")
print("  breakdown by which indicator:")
single_ind_id = single["indicators"].apply(lambda x: x[0]["id"])
print(single_ind_id.value_counts().to_dict())

print()
print("=" * 70)
print("TOP 20 HIGHEST-RISK CASES")
print("=" * 70)
top20 = df.sort_values("risk_score", ascending=False).head(20)
for _, row in top20.iterrows():
    ids = [i["id"] for i in row["indicators"]]
    print(f"{row['risk_score']:6.1f}  {row['case_id']:35s}  n_ind={len(ids):2d}  {ids}")

print()
print("=" * 70)
print("INDICATOR CO-OCCURRENCE IN TOP 100 CASES")
print("=" * 70)
top100 = df.sort_values("risk_score", ascending=False).head(100)
pair_counts = Counter()
for inds in top100["indicators"]:
    ids = sorted(i["id"] for i in inds)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            pair_counts[(ids[i], ids[j])] += 1
for pair, count in pair_counts.most_common(15):
    print(f"  {count:3d}x  {pair[0]} + {pair[1]}")
