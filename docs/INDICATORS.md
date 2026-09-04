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

| Rule ID | Points | Input fields | Calculation | Rationale |
|---|---|---|---|---|
| `SINGLE_BIDDER` | 20 | `tender.numberOfTenderers` | Exactly 1 tenderer | Absence of competitive pressure on price/terms; ~44% of tender-stage records in this dataset show this. |
| `LOW_COMPETITION_METHOD` | 12–18 | `tender.procurementMethodDetails` | Method in {Direct Procurement, Sole Source, Emergency, Selective Tendering} (Sole Source/Direct Procurement weighted higher) | These methods bypass open competitive bidding by design; legitimate in genuine emergencies but also a common vector for steering awards. |
| `SHORT_TENDER_PERIOD` | 10–15 | `tender.tenderPeriod.startDate/endDate` | Duration at or below the dataset's 10th percentile (floor 3 days) | Short bidding windows can exclude potential competitors who need time to prepare a bid. |
| `PRICE_DEVIATION` | 8–20 | `tender.value.amount`, `award.value.amount` | \|award/tender − 1\| ≥ 50% | Large gaps between the buyer's own estimate and what was actually awarded merit review in either direction. |
| `SUPPLIER_CONCENTRATION` | up to 18 | `award.suppliers`, `award.value`, `buyer` | A single (identified) supplier holds ≥40% of a buyer's total award value across ≥5 of that buyer's awards | Concentrated award patterns can indicate market capture or a lack of supplier diversification, though it can also reflect a genuinely small/specialized supplier market. |
| `REPEATED_RELATIONSHIP` | up to 15 | `award.suppliers`, `buyer` | Same identified buyer–supplier pair appears in ≥5 awards | Repeat-vendor patterns are common and often benign, but warrant a look when combined with other indicators. |
| `MISSING_SUPPLIER_IDENTITY` | 12 | `award.suppliers[].name` | Award's supplier name is blank/missing | A basic transparency/disclosure gap — the public record doesn't say who was paid. |
| `PEER_PRICE_OUTLIER` | 6–15 | `tender.items[].description`/`title`, `tender.value` | Robust z-score (median/MAD) ≥ 4 within a text-normalized peer group of ≥5 tenders | Flags estimates far outside the range of similarly described tenders. **Limitation:** the dataset has no item classification codes, so grouping is by normalized free-text, a coarse proxy. |
| `BUYER_AWARD_BURST` | 10 | `award.date`, `award.value`, `buyer` | ≥5 of a buyer's top-quartile-value awards fall within a 21-day window | Dense clusters of high-value awards can indicate year-end budget-flush spending or split awards; also plausibly a legitimate batch procurement round. |

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
