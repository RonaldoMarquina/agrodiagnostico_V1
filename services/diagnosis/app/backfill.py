"""CLI executable entry point for backfilling legacy PENDIENTE diagnoses.

Usage:
  python -m app.backfill [--apply] [--batch-size N] [--ids ID1,ID2]

Default mode is safe dry-run. Requires --apply to commit mutations.
"""
import argparse
import json
import logging
import sys
import uuid

from app.application.backfill import run_backfill
from app.persistence import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_cli")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill legacy PENDIENTE diagnoses with DiagnosisRequested v2 outbox events.")
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Apply mutations and commit outbox events. If omitted, runs in safe dry-run mode.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Maximum number of candidate diagnoses to process in one run (default: 50).",
    )
    parser.add_argument(
        "--ids",
        type=str,
        default=None,
        help="Optional comma-separated list of diagnosis UUIDs to target.",
    )

    args = parser.parse_args()

    target_ids = None
    if args.ids:
        try:
            target_ids = [uuid.UUID(i.strip()) for i in args.ids.split(",") if i.strip()]
        except ValueError as exc:
            logger.error("Invalid UUID in --ids list: %s", exc)
            return 1

    mode_str = "APPLY" if args.apply else "DRY-RUN"
    logger.info("Starting backfill in %s mode (batch_size=%d)...", mode_str, args.batch_size)

    try:
        db = next(get_db())
        result = run_backfill(
            db=db,
            apply=args.apply,
            ids=target_ids,
            batch_size=args.batch_size,
        )

        summary = {
            "mode": mode_str,
            "scanned": result.scanned,
            "candidates": result.candidates,
            "tombstones": result.tombstones,
            "applied": result.applied,
            "skipped_not_pending": result.skipped_not_pending,
        }
        print(json.dumps(summary, indent=2))
        return 0
    except Exception as exc:
        logger.error("Backfill failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

