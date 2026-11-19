"""CLI executable entry point for Diagnosis publication policy operations.

Usage:
  # Import a policy contract in dry-run mode (default):
  python -m app.policy import --policy-file /path/to/policy.json --actor "operator@example.com" --reason "G2 Approved"

  # Apply policy import:
  python -m app.policy import --policy-file /path/to/policy.json --actor "operator@example.com" --reason "G2 Approved" --apply

  # Activate an imported policy:
  python -m app.policy activate --policy-id <UUID> --actor "operator@example.com" --reason "Release deployment" --apply

  # Retire the currently active policy:
  python -m app.policy retire --actor "operator@example.com" --reason "Emergency rollback" --apply

  # Check policy and catalog support status:
  python -m app.policy status

Security and Operational Invariants:
- Never runs via public HTTP endpoints or PATCH routes.
- Mandatory operator context (actor, reason) for all mutating operations.
- Dry-run by default; requires explicit --apply.
- Atomically audits all operations before and upon commit.
- On activation, atomically sets Problem.model_supported for approved classes and clears unsupported classes.
- On retirement, atomically resets Problem.model_supported to False for all problems.
"""
import argparse
import json
import logging
from pathlib import Path
import sys
import uuid

from app.application.policy import (
    activate_publication_policy,
    get_publication_policy_status,
    import_publication_policy,
    retire_publication_policy,
)
from app.persistence import get_sessionmaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("policy_cli")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Operational CLI for Diagnosis publication policies and catalog support."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: import
    import_parser = subparsers.add_parser("import", help="Import an immutable publication policy.")
    import_parser.add_argument(
        "--policy-file",
        type=str,
        required=True,
        help="Path to the JSON publication policy file.",
    )
    import_parser.add_argument(
        "--actor",
        type=str,
        required=True,
        help="Identifier of the operator performing the action.",
    )
    import_parser.add_argument(
        "--reason",
        type=str,
        required=True,
        help="Operational or governance justification.",
    )
    import_parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Apply changes to the database. If omitted, runs in safe dry-run mode.",
    )

    # Subcommand: activate
    activate_parser = subparsers.add_parser("activate", help="Activate an imported publication policy.")
    activate_parser.add_argument(
        "--policy-id",
        type=str,
        required=True,
        help="UUID of the policy to activate.",
    )
    activate_parser.add_argument(
        "--actor",
        type=str,
        required=True,
        help="Identifier of the operator performing the action.",
    )
    activate_parser.add_argument(
        "--reason",
        type=str,
        required=True,
        help="Operational or governance justification.",
    )
    activate_parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Apply changes to the database. If omitted, runs in safe dry-run mode.",
    )

    # Subcommand: retire
    retire_parser = subparsers.add_parser("retire", help="Retire an active publication policy.")
    retire_parser.add_argument(
        "--policy-id",
        type=str,
        default=None,
        help="Optional UUID of the policy to retire. If omitted, retires the currently active policy.",
    )
    retire_parser.add_argument(
        "--actor",
        type=str,
        required=True,
        help="Identifier of the operator performing the action.",
    )
    retire_parser.add_argument(
        "--reason",
        type=str,
        required=True,
        help="Operational or governance justification.",
    )
    retire_parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Apply changes to the database. If omitted, runs in safe dry-run mode.",
    )

    # Subcommand: status
    subparsers.add_parser("status", help="Show current active policy and catalog support status.")

    args = parser.parse_args()

    session_maker = get_sessionmaker()

    try:
        if args.command == "import":
            path = Path(args.policy_file)
            if not path.is_file():
                logger.error("Policy file not found: %s", args.policy_file)
                return 1
            payload = json.loads(path.read_text(encoding="utf-8"))

            with session_maker() as db:
                result = import_publication_policy(
                    db=db,
                    actor=args.actor,
                    reason=args.reason,
                    policy_data=payload,
                    apply=args.apply,
                )
                print(json.dumps(result, indent=2))
                return 0

        elif args.command == "activate":
            try:
                pid = uuid.UUID(args.policy_id)
            except ValueError:
                logger.error("Invalid UUID for --policy-id: %s", args.policy_id)
                return 1

            with session_maker() as db:
                result = activate_publication_policy(
                    db=db,
                    actor=args.actor,
                    reason=args.reason,
                    policy_id=pid,
                    apply=args.apply,
                )
                print(json.dumps(result, indent=2))
                return 0

        elif args.command == "retire":
            pid = None
            if args.policy_id:
                try:
                    pid = uuid.UUID(args.policy_id)
                except ValueError:
                    logger.error("Invalid UUID for --policy-id: %s", args.policy_id)
                    return 1

            with session_maker() as db:
                result = retire_publication_policy(
                    db=db,
                    actor=args.actor,
                    reason=args.reason,
                    policy_id=pid,
                    apply=args.apply,
                )
                print(json.dumps(result, indent=2))
                return 0

        elif args.command == "status":
            with session_maker() as db:
                result = get_publication_policy_status(db=db)
                print(json.dumps(result, indent=2))
                return 0

    except Exception as ex:
        logger.error("Execution failed: %s", str(ex))
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
