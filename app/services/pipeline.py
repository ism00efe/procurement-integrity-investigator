import asyncio
import json
import logging
from pathlib import Path

from app.agents.investigators import investigate_case
from app.agents.providers import LLMNotConfiguredError, get_provider
from app.agents.schemas import CaseReport
from app.core.config import get_settings
from app.data.db import get_connection
from app.risk.engine import top_n_cases
from app.services.synthesis import synthesize_case_report
from app.verification.verifier import verify_all

logger = logging.getLogger(__name__)


def _case_seed(case_id: str) -> dict:
    con = get_connection(read_only=True)
    row = con.execute(
        "SELECT case_id, buyer_id, buyer_name, tender_title, tender_value_amount, "
        "tender_value_currency, procurement_method_details, number_of_tenderers, "
        "risk_score, risk_level, indicators_json "
        "FROM case_summary WHERE case_id = ?", [case_id],
    ).fetchdf()
    con.close()
    if row.empty:
        raise ValueError(f"case_id not found in case_summary: {case_id}")
    rec = json.loads(row.iloc[0].to_json())
    rec["indicators"] = json.loads(rec.pop("indicators_json"))
    return rec


def _investigations_path(case_id: str) -> Path:
    settings = get_settings()
    directory = Path(settings.investigations_dir)
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = case_id.replace("/", "_")
    return directory / f"{safe_name}.json"


def load_cached_report(case_id: str) -> dict | None:
    path = _investigations_path(case_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


async def investigate_and_report(case_id: str, semaphore: asyncio.Semaphore | None = None) -> dict:
    case_seed = _case_seed(case_id)

    try:
        provider = get_provider()
    except LLMNotConfiguredError as exc:
        logger.info("LLM not configured, returning deterministic-only report for %s", case_id)
        report = await synthesize_case_report(
            provider=None, case_id=case_id,
            deterministic_score=case_seed["risk_score"],
            verified_findings=[], rejected_findings=[],
        )
        result = {
            "case": case_seed, "investigator_outputs": [], "report": report.model_dump(),
            "llm_status": f"not_configured: {exc}",
        }
        _investigations_path(case_id).write_text(json.dumps(result, indent=2, default=str))
        return result

    settings = get_settings()
    sem = semaphore or asyncio.Semaphore(settings.llm_max_concurrency)

    outputs = await investigate_case(provider, sem, case_seed)
    verified = verify_all(outputs)
    rejected = [vf for vf in verified if vf.verification_status == "rejected"]

    report = await synthesize_case_report(
        provider=provider, case_id=case_id,
        deterministic_score=case_seed["risk_score"],
        verified_findings=verified, rejected_findings=rejected,
    )

    result = {
        "case": case_seed,
        "investigator_outputs": [o.model_dump() for o in outputs],
        "verification": [vf.model_dump() for vf in verified],
        "report": report.model_dump(),
        "llm_status": "ok",
    }
    _investigations_path(case_id).write_text(json.dumps(result, indent=2, default=str))
    return result


async def investigate_top_n(n: int | None = None) -> list[dict]:
    settings = get_settings()
    n = n or settings.top_n_cases
    case_ids = top_n_cases(n)
    semaphore = asyncio.Semaphore(settings.llm_max_concurrency)
    results = []
    for case_id in case_ids:
        try:
            results.append(await investigate_and_report(case_id, semaphore))
        except Exception:  # noqa: BLE001
            logger.exception("Investigation failed for case %s", case_id)
    return results


if __name__ == "__main__":
    import sys

    n_arg = int(sys.argv[1]) if len(sys.argv) > 1 else None
    outcomes = asyncio.run(investigate_top_n(n_arg))
    print(json.dumps({"investigated": len(outcomes)}, indent=2))
