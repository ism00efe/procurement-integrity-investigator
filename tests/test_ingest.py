import json

from app.data.ingest import load_raw_records

PLANNING_ONLY_RECORD = {
    "id": "rel-1", "ocid": "ocds-plan-1", "date": "2023-01-01T00:00:00Z",
    "buyer": {"id": "b1", "name": "Ministry A"},
    "planning": {"budget": {"amount": {"amount": 100.0, "currency": "NGN"}}},
}

TENDER_RECORD = {
    "id": "rel-2", "ocid": "ocds-tender-1", "date": "2023-02-01T00:00:00Z",
    "buyer": {"id": "b2", "name": "Ministry B"},
    "tender": {
        "id": "t1", "title": "Supply of chairs", "status": "complete",
        "value": {"amount": 500000.0, "currency": "NGN"},
        "numberOfTenderers": 1,
        "procurementMethodDetails": "Sole Source",
        "tenderPeriod": {"startDate": "2023-02-01T00:00:00Z", "endDate": "2023-02-03T00:00:00Z"},
        "items": [{"description": "Office chairs"}],
    },
    "awards": [
        {
            "id": "a1", "date": "2023-02-10T00:00:00Z",
            "value": {"amount": 500000.0, "currency": "NGN"}, "status": "active",
            "suppliers": [{"id": "s1", "name": "Chair Co"}],
        }
    ],
}


def test_records_without_tender_are_excluded(tmp_path):
    path = tmp_path / "raw.jsonl"
    path.write_text(
        json.dumps(PLANNING_ONLY_RECORD) + "\n" + json.dumps(TENDER_RECORD) + "\n",
        encoding="utf-8",
    )
    cases_df, awards_df = load_raw_records(str(path))
    assert list(cases_df["case_id"]) == ["ocds-tender-1"]
    assert len(awards_df) == 1


def test_tender_fields_are_correctly_extracted(tmp_path):
    path = tmp_path / "raw.jsonl"
    path.write_text(json.dumps(TENDER_RECORD) + "\n", encoding="utf-8")
    cases_df, awards_df = load_raw_records(str(path))
    row = cases_df.iloc[0]
    assert row["number_of_tenderers"] == 1
    assert row["procurement_method_details"] == "Sole Source"
    assert row["tender_period_days"] == 2
    assert row["tender_value_amount"] == 500000.0

    award = awards_df.iloc[0]
    assert award["supplier_name"] == "Chair Co"
    assert award["award_value_amount"] == 500000.0


def test_award_with_missing_supplier_name_becomes_none(tmp_path):
    record = dict(TENDER_RECORD)
    record["ocid"] = "ocds-tender-2"
    record["awards"] = [
        {"id": "a2", "value": {"amount": 1.0}, "suppliers": [{"id": "s-blank", "name": "  "}]}
    ]
    path = tmp_path / "raw.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    _, awards_df = load_raw_records(str(path))
    assert awards_df.iloc[0]["supplier_name"] is None
