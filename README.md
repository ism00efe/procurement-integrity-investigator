# Procurement Integrity Investigator

An AI-assisted screening tool for African public procurement data, built for
the TNGIMPACT AI Summit '26 Hackathon (Other African Solution track).

It helps auditors, oversight bodies, and investigative journalists find
procurement cases that deserve **human review** — it never claims a company
or contract is corrupt. It surfaces risk indicators, unusual patterns, and
open questions, and every AI-generated claim is independently re-verified
against the source data before it's shown.

## How it works

```
Nigeria BPP OCDS procurement data (real, official, ~17.6k tender-stage cases)
        |
Data ingestion / normalization (DuckDB)
        |
Deterministic risk analysis (9 explainable indicators, full dataset)
        |
Transparent risk scoring (sum of triggered indicator points, capped at 100)
        |
Top-N highest-risk cases (default 20, configurable)
        |
Parallel LLM investigation (3 specialist analysts, each with bounded tools)
        |
Deterministic evidence verification (recomputes every numeric claim)
        |
Final case synthesis (verified findings only, hedged "requires review" language)
        |
Dashboard (FastAPI + vanilla JS)
```

The core principle: **cheap deterministic analysis runs over the whole
dataset; expensive LLM calls only run on a small, already-prioritized
shortlist**, and the LLM's own text is never treated as authoritative — it's
checked against the database before it reaches the report.

## Data source

Nigeria: Bureau of Public Procurement (BPP), via the Nigeria Open
Contracting Portal (NOCOPO), sourced from the [Open Contracting Data
Registry](https://data.open-contracting.org/en/publication/64). See
[`data/raw/SOURCE.md`](data/raw/SOURCE.md) for exact download details, and
[`docs/INDICATORS.md`](docs/INDICATORS.md) for how the dataset's actual
schema shaped which risk indicators were implemented.

## Setup

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt        # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS/Linux
```

If `data/raw/nigeria_bpp_full.jsonl.gz` isn't already present, download it:

```bash
curl -L -o data/raw/nigeria_bpp_full.jsonl.gz "https://data.open-contracting.org/en/publication/64/download?name=full.jsonl.gz"
```

Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY` to enable the AI
investigation layer (get one at https://openrouter.ai). **Everything else —
ingestion, the risk engine, the dashboard's case list and score
explanations — works fully without it.**

## Running it

```bash
# 1. Ingest the dataset and compute deterministic risk scores for all cases
.venv\Scripts\python -m scripts.build_all

# 2. (Optional) Pre-run AI investigation on the current top-N cases, for demo reliability
.venv\Scripts\python -m app.services.pipeline 20

# 3. Start the API + dashboard
.venv\Scripts\python -m uvicorn app.api.main:app --reload
```

Open http://127.0.0.1:8000. The case list is sorted by risk score; click a
case to see why it was flagged, and click "Run AI investigation" to trigger
the parallel LLM analysis + verification live (or instantly, if step 2 was
run ahead of time — results are cached under
`data/processed/investigations/`).

## Architecture

```
app/
  core/       settings (env-var driven, pydantic-settings)
  data/       OCDS ingestion + normalization -> DuckDB
  risk/       9 deterministic indicators + transparent scoring/ranking
  agents/     LLM provider abstraction, bounded tool interface, 3 specialist investigators
  verification/  recomputes every numeric claim from the database; rejects/downgrades mismatches
  services/   final synthesis + end-to-end pipeline orchestration
  api/        FastAPI backend
  web/        vanilla HTML/CSS/JS dashboard
```

**LLM provider abstraction** (`app/agents/providers/`): the app talks to an
`LLMProvider` interface, not a specific vendor. `OpenRouterProvider` is the
default implementation; a different provider can be added without touching
any business logic in `agents/`, `verification/`, or `services/`. Model and
provider are fully configured via environment variables
(`OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`).

**Bounded tools** (`app/agents/tools.py`): investigators can only call seven
whitelisted, parameterized functions (`get_tender_details`,
`get_supplier_history`, `get_buyer_history`, `get_competing_bidders`,
`get_peer_price_comparison`, `get_related_contracts`,
`get_evidence_record`) — never arbitrary SQL. Every tool result includes an
`evidence_ref` the model can cite, so its claims are traceable.

**Verification** (`app/verification/verifier.py`): for every LLM finding, we
confirm cited evidence exists and re-derive any recognizable numeric
assertion (counts, percentages, price ratios, tenderer counts) directly from
DuckDB. A finding is `rejected` if the recalculated number materially
disagrees, `downgraded` if it can't be independently checked, and `verified`
otherwise. The final report only draws on verified/downgraded findings;
rejected ones are kept and surfaced in the dashboard as
"✗ claim rejected by verification," not silently dropped.

**Concurrency & resilience**: the 3 investigators for a case run in
parallel (`asyncio.gather`); an `asyncio.Semaphore` bounds total concurrent
LLM calls across the run (`LLM_MAX_CONCURRENCY`); OpenRouter calls retry
with backoff (`tenacity`) on transport errors; a malformed JSON response
gets one repair attempt before falling back to an empty, clearly-labeled
result. If no API key is configured, or a call fails outright, the pipeline
still returns the full deterministic risk result — the AI layer degrades
gracefully rather than blocking the tool.

## Testing

```bash
.venv\Scripts\python -m pytest
```

Covers: ingestion/normalization (including OCDS records that never reach
tender stage), each risk indicator (including a regression test for a real
data-quality issue — awards with a blank supplier name sharing a placeholder
ID must never be treated as the same real supplier), score aggregation and
capping, the conclusory-language guard on LLM output schemas, the
provider abstraction's missing-API-key and failed-call handling, and the
verifier's numeric recalculation (including the exact "claimed 8-of-10,
actual differs" rejection scenario from the design brief). All tests run
against small synthetic fixtures — the real Nigeria dataset is used only for
the live demo, never for unit tests.

## Known limitations

- The dataset has no product/service classification codes, so peer price
  comparison groups tenders by normalized free-text item descriptions — a
  coarse proxy, documented in `docs/INDICATORS.md`.
- The dataset discloses only the *count* of tenderers per case, never their
  identities, so no indicator or investigator can reason about who the
  losing bidders were.
- `procurementMethod` is constant (`"open"`) across the whole dataset; the
  meaningful method signal is in `procurementMethodDetails` instead.
