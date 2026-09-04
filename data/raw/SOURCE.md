# Data source

- **Dataset:** Nigeria: Bureau of Public Procurement (BPP) — Nigeria Open Contracting Portal (NOCOPO)
- **Registry page:** https://data.open-contracting.org/en/publication/64
- **Bulk download URL used:** https://data.open-contracting.org/en/publication/64/download?name=full.jsonl.gz
- **Format:** OCDS compiled releases, JSON Lines, gzip-compressed
- **Downloaded on:** 2026-09-04
- **File:** `nigeria_bpp_full.jsonl.gz` (14,032,702 bytes compressed; 225,539,269 bytes uncompressed; 98,866 records)
- **Coverage:** 2021-05-03 to 2026-07-29
- **License:** http://nocopo.bpp.gov.ng/license

## Notes from inspection

- Of 98,866 top-level records, only 17,623 have reached the `tender` stage (the rest are `planning`-only budget line items with no procurement activity yet). The risk engine operates on the 17,623 tender-stage records.
- `tender.procurementMethod` is constant (`"open"`) across the dataset and carries no signal. `tender.procurementMethodDetails` (e.g. National Competitive Bidding, Selective Tendering, Direct Procurement, Sole Source, Emergency) is the useful method field.
- `tender.minValue` is identical to `tender.value` in 100% of records — it is not a genuine estimate range and is not used as an independent field.
- `tender.numberOfTenderers` is populated for all tender-stage records; ~44% show exactly 1 tenderer.
- `tender.tenderPeriod` (start/end dates) is present for ~52% of tender-stage records.
- No item/product classification codes are present — only free-text item descriptions and tender titles. Peer price comparisons use normalized-text grouping, not category codes.
- Many `award.suppliers` entries carry only an `id` with a blank/missing `name` — used as a transparency/disclosure indicator rather than discarded.
