"""CLI executable entry point for operational replay and explicit message reconstruction.

Usage:
  # Replay a valid event by event-id (dry-run by default):
  python -m app.replay --actor "operator@example.com" --reason "Incident 42" --event-id <UUID> [--apply]

  # Replay by diagnosis-id:
  python -m app.replay --actor "operator@example.com" --reason "Retry delivery" --diagnosis-id <UUID> [--apply]

  # Explicitly reconstruct an invalid quarantined message with a new valid Requested event:
  python -m app.replay --actor "operator@example.com" --reason "Fixed bug" --reconstruct-quarantine-id <UUID> [--apply]

Security and Operational Invariants:
- Never runs via public HTTP endpoints.
- Demands actor and reason context; denies execution if omitted.
- Audits before any database mutation.
- Strictly preserves event_id and envelope for valid replays (no payload tampering).
- Prohibits blind replay of raw quarantined bytes.
"""
import argparse
import json
import logging
import sys
import uuid

from app.application.replay import replay_outbox_event, reconstruct_quarantined_message
from app.persistence import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("replay_cli")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Operational replay and reconstruction tool for Diagnosis outbox events."
    )
    parser.add_argument(
        "--actor",
        type=str,
        required=True,
        help="Identifier of the operator performing the action (mandatory).",
    )
    parser.add_argument(
        "--reason",
        type=str,
        required=True,
        help="Operational reason or incident ticket for this replay (mandatory).",
    )
    parser.add_argument(
        "--event-id",
        type=str,
        default=None,
        help="UUID of the specific outbox event to replay.",
    )
    parser.add_argument(
        "--diagnosis-id",
        type=str,
        default=None,
        help="UUID of the diagnosis whose latest event to replay.",
    )
    parser.add_argument(
        "--reconstruct-quarantine-id",
        type=str,
        default=None,
        help="UUID of a quarantine message entry to explicitly reconstruct for a PENDIENTE diagnosis.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Apply changes to the database. If omitted, runs in safe dry-run mode.",
    )

    args = parser.parse_args()

    if not args.actor.strip():
        logger.error("Execution denied: --actor cannot be blank.")
        return 1

    if not args.reason.strip():
        logger.error("Execution denied: --reason cannot be blank.")
        return 1

    event_id = None
    if args.event_id:
        try:
            event_id = uuid.UUID(args.event_id)
        except ValueError:
            logger.error("Invalid UUID for --event-id: %s", args.event_id)
            return 1

    diagnosis_id = None
    if args.diagnosis_id:
        try:
            diagnosis_id = uuid.UUID(args.diagnosis_id)
        except ValueError:
            logger.error("Invalid UUID for --diagnosis-id: %s", args.diagnosis_id)
            return 1

    quarantine_id = None
    if args.reconstruct_quarantine_id:
        try:
            quarantine_id = uuid.UUID(args.reconstruct_quarantine_id)
        except ValueError:
            logger.error("Invalid UUID for --reconstruct-quarantine-id: %s", args.reconstruct_quarantine_id)
            return 1

    if not event_id and not diagnosis_id and not quarantine_id:
        logger.error("Execution denied: One of --event-id, --diagnosis-id, or --reconstruct-quarantine-id is required.")
        return 1

    mode_str = "APPLY" if args.apply else "DRY-RUN"
    logger.info("Starting operational action in %s mode (actor=%s)...", mode_str, args.actor)

    try:
        db = next(get_db())
        if quarantine_id:
            result = reconstruct_quarantined_message(
                db=db,
                actor=args.actor,
                reason=args.reason,
                quarantine_id=quarantine_id,
                apply=args.apply,
            )
        else:
            result = replay_outbox_event(
                db=db,
                actor=args.actor,
                reason=args.reason,
                event_id=event_id,
                diagnosis_id=diagnosis_id,
                apply=args.apply,
            )

        output = {
            "mode": mode_str,
            "action": result.action,
            "status": result.status,
            "event_id": str(result.event_id),
            "diagnosis_id": str(result.diagnosis_id) if result.diagnosis_id else None,
            "details": result.details,
        }
        print(json.dumps(output, indent=2))
        return 0
    except Exception as exc:
        logger.error("Replay operation failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

