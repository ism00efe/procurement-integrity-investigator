import duckdb
import pandas as pd
import pytest

from app.core.config import get_settings


@pytest.fixture
def synthetic_cases_df() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "case_id": "case-1", "release_id": "r1", "release_date": pd.Timestamp("2023-01-01"),
            "buyer_id": "buyer-A", "buyer_name": "Ministry of Widgets",
            "tender_id": "t1", "tender_title": "Supply of laptops",
            "tender_description": "laptops for staff",
            "procurement_method_details": "Direct Procurement",
            "procurement_method_rationale": "urgent", "tender_status": "complete",
            "tender_value_amount": 1_000_000.0, "tender_value_currency": "NGN",
            "number_of_tenderers": 1,
            "tender_period_start": pd.Timestamp("2023-01-01"),
            "tender_period_end": pd.Timestamp("2023-01-03"),
            "tender_period_days": 2, "award_criteria": "priceOnly",
            "items_count": 1, "peer_group_key": "laptops staff",
        },
        {
            "case_id": "case-2", "release_id": "r2", "release_date": pd.Timestamp("2023-02-01"),
            "buyer_id": "buyer-A", "buyer_name": "Ministry of Widgets",
            "tender_id": "t2", "tender_title": "Supply of laptops batch 2",
            "tender_description": "laptops for staff",
            "procurement_method_details": "National Competitive Bidding",
            "procurement_method_rationale": "standard", "tender_status": "complete",
            "tender_value_amount": 950_000.0, "tender_value_currency": "NGN",
            "number_of_tenderers": 6,
            "tender_period_start": pd.Timestamp("2023-02-01"),
            "tender_period_end": pd.Timestamp("2023-03-01"),
            "tender_period_days": 29, "award_criteria": "priceOnly",
            "items_count": 1, "peer_group_key": "laptops staff",
        },
        {
            "case_id": "case-3", "release_id": "r3", "release_date": pd.Timestamp("2023-03-01"),
            "buyer_id": "buyer-A", "buyer_name": "Ministry of Widgets",
            "tender_id": "t3", "tender_title": "Supply of laptops batch 3",
            "tender_description": "laptops for staff",
            "procurement_method_details": "National Competitive Bidding",
            "procurement_method_rationale": "standard", "tender_status": "complete",
            "tender_value_amount": 20_000_000.0, "tender_value_currency": "NGN",
            "number_of_tenderers": 5,
            "tender_period_start": pd.Timestamp("2023-03-01"),
            "tender_period_end": pd.Timestamp("2023-03-30"),
            "tender_period_days": 29, "award_criteria": "priceOnly",
            "items_count": 1, "peer_group_key": "laptops staff",
        },
    ])


@pytest.fixture
def synthetic_awards_df() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "award_id": "a1", "case_id": "case-1", "award_date": pd.Timestamp("2023-01-05"),
            "award_title": "Award laptops", "award_value_amount": 1_500_000.0,
            "award_value_currency": "NGN", "award_status": "active",
            "supplier_id": "supplier-X", "supplier_name": "Acme Supplies Ltd",
            "contract_duration_days": 30,
        },
        {
            "award_id": "a2", "case_id": "case-2", "award_date": pd.Timestamp("2023-02-05"),
            "award_title": "Award laptops 2", "award_value_amount": 950_000.0,
            "award_value_currency": "NGN", "award_status": "active",
            "supplier_id": "supplier-Y", "supplier_name": "Beta Traders",
            "contract_duration_days": 30,
        },
        {
            "award_id": "a3", "case_id": "case-3", "award_date": pd.Timestamp("2023-03-05"),
            "award_title": "Award laptops 3", "award_value_amount": 20_000_000.0,
            "award_value_currency": "NGN", "award_status": "active",
            "supplier_id": None, "supplier_name": None,
            "contract_duration_days": 30,
        },
    ])


@pytest.fixture
def temp_database(tmp_path, synthetic_cases_df, synthetic_awards_df, monkeypatch):
    """Builds a fresh temp DuckDB with cases/awards/case_awards for a test,
    and points app settings at it so app.data.db.get_connection uses it."""
    db_path = tmp_path / "test.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db_path))
    get_settings.cache_clear()

    con = duckdb.connect(str(db_path))
    con.register("cases_df", synthetic_cases_df)
    con.register("awards_df", synthetic_awards_df)
    con.execute("CREATE OR REPLACE TABLE cases AS SELECT * FROM cases_df")
    con.execute("CREATE OR REPLACE TABLE awards AS SELECT * FROM awards_df")
    con.execute(
        "CREATE OR REPLACE VIEW case_awards AS "
        "SELECT c.*, a.award_id, a.award_date, a.award_value_amount, "
        "a.award_value_currency, a.award_status, a.supplier_id, a.supplier_name, "
        "a.contract_duration_days FROM cases c LEFT JOIN awards a USING (case_id)"
    )
    con.close()

    yield db_path
    get_settings.cache_clear()


@pytest.fixture
def temp_database_with_risk(temp_database):
    """Extends temp_database with case_risk/case_summary so pipeline-level code
    (which reads case_summary) can be exercised in tests."""
    import json

    con = duckdb.connect(str(temp_database))
    risk_df = pd.DataFrame([
        {
            "case_id": "case-1", "risk_score": 45.0, "risk_level": "medium",
            "indicators_json": json.dumps([
                {"id": "SINGLE_BIDDER", "score": 20.0, "explanation": "one bidder",
                 "evidence_refs": ["case:case-1"]},
            ]),
            "num_indicators": 1, "computed_at": "2023-01-01T00:00:00Z",
        },
    ])
    con.register("risk_df", risk_df)
    con.execute("CREATE OR REPLACE TABLE case_risk AS SELECT * FROM risk_df")
    con.execute(
        "CREATE OR REPLACE VIEW case_summary AS "
        "SELECT c.case_id, c.buyer_id, c.buyer_name, c.tender_title, c.tender_value_amount, "
        "c.tender_value_currency, c.procurement_method_details, c.number_of_tenderers, "
        "r.risk_score, r.risk_level, r.num_indicators, r.indicators_json "
        "FROM cases c JOIN case_risk r USING (case_id)"
    )
    con.close()
    return temp_database
