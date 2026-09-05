"""Re-run deterministic verification over already-cached investigations.

Verification is decoupled from the LLM: it reads the investigators' stored
findings and re-derives their numbers from DuckDB. So when the verifier's
rules change, archived investigations can be re-checked offline -- no API
key, no network, no model spend, and the same inputs always produce the same
verdicts.

    .venv\\Scripts\\python -m scripts.reverify_cached          # rewrite in place
    .venv\\Scripts\\python -m scripts.reverify_cached --dry-run  # report only

Note: this refreshes `verification` and the statuses carried in
`report.key_findings`. The report's `narrative` prose was written by the LLM
during the original run and is left untouched -- re-run
`python -m app.services.pipeline` if you need the narrative regenerated
against the new verdicts too.
"""
import argparse
import collections
import json
from pathlib import Path

from app.agents.schemas import InvestigatorOutput
from app.core.config import get_settings
from app.verification.verifier import verify_all

STATUS_ORDER = ("verified", "downgraded", "rejected")


def _tally(records: list[dict]) -> str:
    counts = collections.Counter(r["verification_status"] for r in records)
    return ", ".join(f"{counts.get(s, 0)} {s}" for s in STATUS_ORDER)


def reverify_file(path: Path, dry_run: bool = False) -> bool:
    """Re-verify one cached investigation. Returns True if anything changed."""
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_outputs = data.get("investigator_outputs") or []
    if not raw_outputs:
        print(f"  {path.name}: no investigator output cached, skipping")
        return False

    outputs = [InvestigatorOutput.model_validate(o) for o in raw_outputs]
    fresh = [vf.model_dump() for vf in verify_all(outputs)]
    before = data.get("verification") or []

    if before == fresh:
        print(f"  {path.name}: unchanged ({_tally(fresh)})")
        return False

    print(f"  {path.name}:\n      was  {_tally(before) if before else 'no verification cached'}"
          f"\n      now  {_tally(fresh)}")
    if dry_run:
        return True

    data["verification"] = fresh
    # The report embeds the verified findings it was built from; refresh their
    # statuses so the dashboard's conclusion panel agrees with the verify panel.
    by_claim = {vf["finding"]["claim"]: vf for vf in fresh}
    report = data.get("report") or {}
    report["key_findings"] = [
        by_claim.get(kf["finding"]["claim"], kf) for kf in report.get("key_findings", [])
    ]
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without rewriting files")
    args = parser.parse_args()

    directory = Path(get_settings().investigations_dir)
    files = sorted(directory.glob("*.json"))
    if not files:
        print(f"No cached investigations found in {directory}")
        return

    print(f"Re-verifying {len(files)} cached investigation(s) in {directory}")
    changed = sum(reverify_file(p, args.dry_run) for p in files)
    verb = "would be updated" if args.dry_run else "updated"
    print(f"{changed} of {len(files)} {verb}.")


if __name__ == "__main__":
    main()
