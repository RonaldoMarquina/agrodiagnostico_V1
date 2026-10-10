"""Diagnosis Outbox and DLQ Descriptor Publisher process.

Runs decoupled outbox publication loop for Diagnosis service:
- Claims batches using short transactions (FOR UPDATE SKIP LOCKED).
- Delivers events to RabbitMQ with publisher confirms and mandatory=True.
- Publishes pending DLQ quarantine descriptors.
- Provides graceful shutdown on SIGTERM/SIGINT.
- Manages readiness marker file at /tmp/diagnosis_publisher_ready.
"""
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import signal
import sys
import time

import pika

from app.infrastructure.outbox import publish_pending_outbox_batches
from app.infrastructure.quarantine import publish_pending_quarantine_descriptors
from app.persistence import get_sessionmaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("diagnosis_publisher")

READY_FILE = Path("/tmp/diagnosis_publisher_ready")


def read_secret(path_env: str, fallback_file: str = "") -> str:
    path_val = os.environ.get(path_env, fallback_file)
    if path_val and Path(path_val).is_file():
        return Path(path_val).read_text().strip()
    return os.environ.get(path_env.replace("_FILE", ""), "")


def main() -> int:
    running = True

    def sig_handler(signum, frame):
        nonlocal running
        logger.info("Received signal %d; initiating graceful shutdown...", signum)
        running = False

    signal.signal(signal.SIGTERM, sig_handler)
    signal.signal(signal.SIGINT, sig_handler)

    rabbit_host = os.environ.get("RABBITMQ_HOST", "rabbitmq")
    rabbit_user = os.environ.get("RABBITMQ_USER", "rabbit_diagnosis")
    rabbit_pw = read_secret("RABBITMQ_PASSWORD_FILE", "/run/secrets/rabbit_diagnosis_password")

    poll_interval = float(os.environ.get("PUBLISHER_POLL_INTERVAL_SECONDS", "1.0"))
    batch_size = int(os.environ.get("PUBLISHER_BATCH_SIZE", "20"))

    logger.info("Starting Diagnosis Outbox Publisher (host=%s, user=%s)...", rabbit_host, rabbit_user)

    READY_FILE.touch()

    try:
        while running:
            try:
                db = get_sessionmaker()()
                # 1. Publish standard business outbox events
                published = publish_pending_outbox_batches(
                    db=db,
                    batch_size=batch_size,
                    host=rabbit_host,
                    user=rabbit_user,
                    password=rabbit_pw,
                )

                # 2. Publish pending quarantine DLQ descriptors if any exist
                try:
                    credentials = pika.PlainCredentials(rabbit_user, rabbit_pw) if rabbit_pw else None
                    params = pika.ConnectionParameters(
                        host=rabbit_host,
                        credentials=credentials,
                        connection_attempts=3,
                        retry_delay=1.0,
                    )
                    with pika.BlockingConnection(params) as conn:
                        ch = conn.channel()
                        ch.confirm_delivery()
                        publish_pending_quarantine_descriptors(
                            session=db,
                            channel=ch,
                            batch_size=batch_size,
                        )
                except Exception as dlq_err:
                    logger.debug("Quarantine descriptor publish check skipped or broker idle: %s", dlq_err)

                if published == 0:
                    time.sleep(poll_interval)
            except Exception as loop_err:
                logger.error("Error in publisher loop: %s; sleeping before retry", loop_err)
                time.sleep(min(poll_interval * 2, 5.0))
            finally:
                if "db" in locals():
                    db.close()
    finally:
        if READY_FILE.exists():
            try:
                READY_FILE.unlink()
            except OSError:
                pass
        logger.info("Diagnosis Outbox Publisher stopped cleanly.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

