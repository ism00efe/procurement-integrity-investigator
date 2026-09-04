"""Parses the raw OCDS JSONL dataset into normalized DuckDB tables.

Only records that have reached the `tender` stage are loaded into `cases` /
`awards` — records without a tender are budget-planning entries with no
procurement activity to analyze (see data/raw/SOURCE.md).
"""
import gzip
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.core.config import get_settings
from app.data.db import get_connection
from app.data.normalize import peer_group_key


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iter_records(path: str):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_raw_records(path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    case_rows = []
    award_rows = []

    for rec in _iter_records(path):
        tender = rec.get("tender")
        if not tender:
            continue

        case_id = rec["ocid"]
        buyer = rec.get("buyer") or {}
        tender_value = (tender.get("value") or {})
        tender_period = tender.get("tenderPeriod") or {}
        start = _parse_dt(tender_period.get("startDate"))
        end = _parse_dt(tender_period.get("endDate"))
        tender_period_days = (end - start).days if start and end else None

        items = tender.get("items") or []
        item_texts = " ".join(
            it.get("description", "") for it in items if it.get("description")
        )
        group_source = item_texts or tender.get("title") or ""

        case_rows.append({
            "case_id": case_id,
            "release_id": rec.get("id"),
            "release_date": _parse_dt(rec.get("date")),
            "buyer_id": buyer.get("id"),
            "buyer_name": (buyer.get("name") or "").strip() or None,
            "tender_id": tender.get("id"),
            "tender_title": tender.get("title"),
            "tender_description": tender.get("description"),
            "procurement_method_details": tender.get("procurementMethodDetails"),
            "procurement_method_rationale": tender.get("procurementMethodRationale"),
            "tender_status": tender.get("status"),
            "tender_value_amount": tender_value.get("amount"),
            "tender_value_currency": tender_value.get("currency"),
            "number_of_tenderers": tender.get("numberOfTenderers"),
            "tender_period_start": start,
            "tender_period_end": end,
            "tender_period_days": tender_period_days,
            "award_criteria": tender.get("awardCriteria"),
            "items_count": len(items),
            "peer_group_key": peer_group_key(group_source),
        })

        for award in (rec.get("awards") or []):
            award_value = award.get("value") or {}
            contract_period = award.get("contractPeriod") or {}
            suppliers = award.get("suppliers") or [{}]
            for supplier in suppliers:
                award_rows.append({
                    "award_id": award.get("id"),
                    "case_id": case_id,
                    "award_date": _parse_dt(award.get("date")),
                    "award_title": award.get("title"),
                    "award_value_amount": award_value.get("amount"),
                    "award_value_currency": award_value.get("currency"),
                    "award_status": award.get("status"),
                    "supplier_id": supplier.get("id"),
                    "supplier_name": (supplier.get("name") or "").strip() or None,
                    "contract_duration_days": contract_period.get("durationInDays"),
                })

    cases_df = pd.DataFrame(case_rows)
    awards_df = pd.DataFrame(award_rows)
    return cases_df, awards_df


def build_database(raw_path: str | None = None) -> dict:
    settings = get_settings()
    raw_path = raw_path or settings.raw_dataset_path
    path = Path(raw_path)
    if not path.exists():
        gz_path = path.with_suffix(path.suffix + ".gz")
        if gz_path.exists():
            with gzip.open(gz_path, "rb") as src, open(path, "wb") as dst:
                shutil.copyfileobj(src, dst)
        else:
            raise FileNotFoundError(
                f"Raw dataset not found at {raw_path} (or {gz_path}). Download the "
                "Nigeria BPP OCDS dataset (All time JSON) from "
                "https://data.open-contracting.org/en/publication/64 and place it "
                "at data/raw/nigeria_bpp_full.jsonl.gz, or set RAW_DATASET_PATH."
            )

    cases_df, awards_df = load_raw_records(raw_path)

    con = get_connection()
    con.register("cases_df", cases_df)
    con.register("awards_df", awards_df)
    con.execute("CREATE OR REPLACE TABLE cases AS SELECT * FROM cases_df")
    con.execute("CREATE OR REPLACE TABLE awards AS SELECT * FROM awards_df")
    con.execute("CREATE OR REPLACE VIEW case_awards AS "
                "SELECT c.*, a.award_id, a.award_date, a.award_value_amount, "
                "a.award_value_currency, a.award_status, a.supplier_id, a.supplier_name, "
                "a.contract_duration_days "
                "FROM cases c LEFT JOIN awards a USING (case_id)")
    con.close()

    return {
        "cases": len(cases_df),
        "awards": len(awards_df),
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        "source": raw_path,
    }


if __name__ == "__main__":
    stats = build_database()
    print(json.dumps(stats, indent=2))
