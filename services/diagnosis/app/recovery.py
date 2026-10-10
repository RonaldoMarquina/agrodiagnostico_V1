"""Diagnosis Lease Recovery daemon process.

Periodically scans for expired diagnosis leases in PROCESANDO status and:
- Respects minimum wait windows (5s for attempt 1, 15s for attempts 2/3).
- Emits single next-generation DiagnosisRequested v2 if attempts remain.
- Transitions to FALLIDO / PROCESSING_TIMEOUT and emits DiagnosisFinished v1
  if budget (3 attempts) or global deadline (300s) is exhausted.
- Provides graceful shutdown on SIGTERM/SIGINT.
- Manages readiness marker file at /tmp/diagnosis_recovery_ready.
"""
import logging
import os
from pathlib import Path
import signal
import sys
import time

from app.application.lease_recovery import recover_expired_leases
from app.infrastructure.lease_config import get_lease_policy
from app.persistence import get_sessionmaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("diagnosis_recovery")

READY_FILE = Path("/tmp/diagnosis_recovery_ready")


def main() -> int:
    running = True

    def sig_handler(signum, frame):
        nonlocal running
        logger.info("Received signal %d; initiating graceful shutdown...", signum)
        running = False

    signal.signal(signal.SIGTERM, sig_handler)
    signal.signal(signal.SIGINT, sig_handler)

    try:
        policy = get_lease_policy()
    except Exception as exc:
        logger.error("Invalid lease configuration; recovery daemon cannot start: %s", exc)
        return 1

    poll_interval = float(os.environ.get("RECOVERY_POLL_INTERVAL_SECONDS", "1.0"))

    logger.info(
        "Starting Diagnosis Lease Recovery daemon (poll_interval=%.1fs, max_attempts=%d, deadline=%ds)...",
        poll_interval,
        policy.max_attempt_count,
        policy.processing_deadline_seconds,
    )

    READY_FILE.touch()

    try:
        while running:
            try:
                db = get_sessionmaker()()
                actions = recover_expired_leases(
                    session=db,
                    policy=policy,
                )
                if actions:
                    logger.info(
                        "Recovery cycle complete: %d diagnoses processed.",
                        len(actions),
                    )
            except Exception as loop_err:
                logger.error("Error in lease recovery loop: %s", loop_err)

            finally:
                if "db" in locals():
                    db.close()
            time.sleep(poll_interval)
    finally:
        if READY_FILE.exists():
            try:
                READY_FILE.unlink()
            except OSError:
                pass
        logger.info("Diagnosis Lease Recovery daemon stopped cleanly.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

