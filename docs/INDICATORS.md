# Deterministic risk indicators

Conceptual basis: the Open Contracting Partnership's procurement red-flag
methodology, restricted to what is actually computable from the Nigeria BPP
OCDS dataset (see [`data/raw/SOURCE.md`](../data/raw/SOURCE.md)). Implemented
in [`app/risk/indicators.py`](../app/risk/indicators.py).

Every indicator returns, per triggered case: an `id`, a `score` (point
contribution), a human-readable `explanation`, and `evidence_refs` (opaque
IDs resolvable via `get_evidence_record`). Scores are combined by
[`app/risk/scoring.py`](../app/risk/scoring.py): the strongest instance of
each indicator per case is kept, then all distinct indicator scores for a
case are summed and capped at 100. No indicator's weight is hidden — the
overall score is always fully explained by the list of triggered indicators.

| Rule ID | Points | Input fields | Calculation | Rationale | Real-data coverage |
|---|---|---|---|---|---|
| `SINGLE_BIDDER` | 20 | `tender.numberOfTenderers` | Exactly 1 tenderer | Absence of competitive pressure on price/terms. | 7,726 cases (43.8%) |
| `LOW_COMPETITION_METHOD` | 12–18 | `tender.procurementMethodDetails` | Method in {Direct Procurement, Sole Source, Emergency, Selective Tendering} (Sole Source/Direct Procurement weighted higher) | These methods bypass open competitive bidding by design; legitimate in genuine emergencies but also a common vector for steering awards. | 5,363 cases (30.4%) |
| `SHORT_TENDER_PERIOD` | 10–15 | `tender.tenderPeriod.startDate/endDate` | Duration at or below the dataset's 10th percentile (floor 3 days) | Short bidding windows can exclude potential competitors who need time to prepare a bid. | 1,118 cases (6.3%) |
| `REPEATED_RELATIONSHIP` | up to 15 | `award.suppliers`, `buyer` | Same identified buyer–supplier pair appears in ≥5 awards | Repeat-vendor patterns are common and often benign, but warrant a look when combined with other indicators. | 1,887 cases (10.7%) |
| `MISSING_SUPPLIER_IDENTITY` | 12 | `award.suppliers[].name` | Award's supplier name is blank/missing | A basic transparency/disclosure gap — the public record doesn't say who was paid. | 1,019 cases (5.8%) |
| `SUPPLIER_CONCENTRATION` | up to 18 | `award.suppliers`, `award.value`, `buyer` | A single (identified) supplier holds ≥40% of a buyer's total award value across ≥5 of that buyer's awards | Concentrated award patterns can indicate market capture or a lack of supplier diversification, though it can also reflect a genuinely small/specialized supplier market. | 131 cases (0.7%) |
| `PEER_PRICE_OUTLIER` | 6–15 | `tender.items[].description`/`title`, `tender.value` | Robust z-score (median/MAD) ≥ 4 within a text-normalized peer group of ≥5 tenders | Flags estimates far outside the range of similarly described tenders. **Limitation:** the dataset has no item classification codes, so grouping is by normalized free-text, a coarse proxy. | 108 cases (0.6%) |
| `BUYER_AWARD_BURST` | 10 | `award.date`, `award.value`, `buyer` | ≥5 of a buyer's top-quartile-value awards fall within a 21-day window | Dense clusters of high-value awards can indicate year-end budget-flush spending or split awards; also plausibly a legitimate batch procurement round. Spot-checked on real data: fires on genuinely varied contract types (boreholes, classrooms, training, solar equipment) from the same buyer in tight windows, not on noise. | 22 cases (0.1%) |
| `PRICE_DEVIATION` | 8–20 | `tender.value.amount`, `award.value.amount` | \|award/tender − 1\| ≥ 50% | Large gaps between the buyer's own estimate and what was actually awarded merit review in either direction. **Validated limitation:** in this dataset, award value equals the tender's own recorded estimate in 99.94% of records (17,137 of 17,148) — the source system appears to populate both from the same underlying figure rather than an independent pre-bid estimate, so this indicator has almost no room to fire. It triggers on exactly 1 case in the full dataset, and inspection of that case shows 11 of its 18 award records recording *exactly* 100× the tender value (a near-certain data-entry error — likely two stray digits — rather than a priced-in cost overrun). The indicator is kept (a discrepancy this large is worth a human's attention regardless of cause, and the explanation text now says so explicitly) but should not be relied on as a general-purpose price-inflation detector for this dataset. | 1 case (0.006%) |

Note: percentages are of the 17,623 tender-stage cases; a case can trigger more than one indicator, so columns don't sum to 100%.

## Indicators considered but not implemented

- **Values clustered just below a procurement-method threshold** — would
  require Nigeria's exact BPP threshold schedule as an external reference
  table; out of scope for this MVP but a natural extension once threshold
  values are sourced.
- **Peer price comparison by product category** — no classification codes
  exist in the source data; addressed instead with the coarser
  `PEER_PRICE_OUTLIER` text-grouping indicator above.
- **Bidder-identity-based patterns** (e.g. shared addresses/directors between
  "competing" bidders) — the dataset discloses only the *count* of tenderers,
  never their identities, so this cannot be computed.
