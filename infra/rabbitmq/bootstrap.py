"""Idempotent privileged bootstrap for RabbitMQ topology, queues, and restricted users.

Never imported or mounted in application APIs.
"""
import base64
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Dict, Optional
import urllib.error
import urllib.request

import pika

logger = logging.getLogger("rabbit_bootstrap")

EXCHANGE_NAME = "agrodiagnostico.events"

QUEUES_AND_BINDINGS = [
    {
        "queue": "ai_inference.diagnosis-requested.v1",
        "routing_key": "diagnosis.requested.v1",
    },
    {
        "queue": "ai_inference.diagnosis-requested.v1.dlq",
        "routing_key": "diagnosis.requested.v1.dlq",
    },
    {
        "queue": "ai_inference.diagnosis-requested.v2",
        "routing_key": "diagnosis.requested.v2",
    },
    {
        "queue": "ai_inference.diagnosis-requested.v2.dlq",
        "routing_key": "diagnosis.requested.v2.dlq",
    },
    {
        "queue": "diagnosis.diagnosis-analyzed.v1",
        "routing_key": "diagnosis.analyzed.v1",
    },
    {
        "queue": "diagnosis.diagnosis-analyzed.v1.dlq",
        "routing_key": "diagnosis.analyzed.v1.dlq",
    },
    {
        "queue": "notification.diagnosis-finished.v1",
        "routing_key": "diagnosis.finished.v1",
    },
    {
        "queue": "notification.diagnosis-finished.v1.dlq",
        "routing_key": "diagnosis.finished.v1.dlq",
    },
]

SERVICE_PERMISSIONS = {
    "rabbit_diagnosis": {
        "secret": "rabbit_diagnosis_password",
        "configure": "^$",
        "write": r"^(agrodiagnostico\.events)$",
        "read": r"^(diagnosis\.diagnosis-analyzed\.v1|diagnosis\.diagnosis-analyzed\.v1\.dlq)$",
    },
    "rabbit_ai_inference": {
        "secret": "rabbit_ai_inference_password",
        "configure": "^$",
        "write": r"^(agrodiagnostico\.events)$",
        "read": r"^(ai_inference\.diagnosis-requested\.v1|ai_inference\.diagnosis-requested\.v1\.dlq|ai_inference\.diagnosis-requested\.v2|ai_inference\.diagnosis-requested\.v2\.dlq)$",
    },
    "rabbit_notification": {
        "secret": "rabbit_notification_password",
        "configure": "^$",
        "write": "^$",
        "read": r"^(notification\.diagnosis-finished\.v1|notification\.diagnosis-finished\.v1\.dlq)$",
    },
}


def read_secret(name: str) -> str:
    """Read secret from container /run/secrets or local fallback."""
    for base in [Path("/run/secrets"), Path(".local/persistence")]:
        candidate = base / name
        if candidate.is_file():
            val = candidate.read_text().strip()
            if val:
                return val
    raise ValueError(f"Secret not found or empty: {name}")


def mgmt_request(
    mgmt_url: str,
    path: str,
    method: str = "GET",
    data: Optional[dict] = None,
    auth_header: Optional[str] = None,
) -> dict:
    """Execute authenticated HTTP request to RabbitMQ Management API."""
    url = f"{mgmt_url}{path}"
    req = urllib.request.Request(url, method=method)
    if auth_header:
        req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/json")
    
    body_bytes = json.dumps(data).encode("utf-8") if data is not None else None
    with urllib.request.urlopen(req, data=body_bytes, timeout=10) as resp:
        content = resp.read()
        if content:
            return json.loads(content.decode("utf-8"))
        return {}


def wait_for_rabbitmq(host: str, port: int, mgmt_port: int, admin_user: str, admin_pass: str, timeout_sec: int = 60) -> str:
    """Wait until RabbitMQ AMQP and Management API are available."""
    deadline = time.monotonic() + timeout_sec
    mgmt_url = f"http://{host}:{mgmt_port}"
    token = base64.b64encode(f"{admin_user}:{admin_pass}".encode("utf-8")).decode("utf-8")
    auth_header = f"Basic {token}"

    last_err = None
    while time.monotonic() < deadline:
        try:
            # Check management API
            mgmt_request(mgmt_url, "/api/aliveness-test/%2f", "GET", auth_header=auth_header)
            return auth_header
        except Exception as exc:
            last_err = exc
            time.sleep(1.5)
    raise RuntimeError(f"RabbitMQ unavailable before deadline ({timeout_sec}s): {last_err}")


def provision_users_and_permissions(
    host: str,
    mgmt_port: int,
    auth_header: str,
) -> None:
    """Create service users and configure least-privilege permissions via Management API."""
    mgmt_url = f"http://{host}:{mgmt_port}"

    for username, config in SERVICE_PERMISSIONS.items():
        password = read_secret(config["secret"])
        
        # 1. Create or update user
        mgmt_request(
            mgmt_url,
            f"/api/users/{username}",
            method="PUT",
            data={"password": password, "tags": ""},
            auth_header=auth_header,
        )

        # 2. Set permissions on default vhost ("/")
        mgmt_request(
            mgmt_url,
            f"/api/permissions/%2f/{username}",
            method="PUT",
            data={
                "configure": config["configure"],
                "write": config["write"],
                "read": config["read"],
            },
            auth_header=auth_header,
        )


def declare_topology_amqp(
    host: str,
    port: int,
    admin_user: str,
    admin_pass: str,
) -> None:
    """Declare durable exchange, queues, and bindings via AMQP with admin credentials."""
    credentials = pika.PlainCredentials(admin_user, admin_pass)
    parameters = pika.ConnectionParameters(
        host=host,
        port=port,
        credentials=credentials,
        socket_timeout=10,
        blocked_connection_timeout=10,
    )
    with pika.BlockingConnection(parameters) as conn:
        channel = conn.channel()

        # 1. Declare topic exchange
        channel.exchange_declare(
            exchange=EXCHANGE_NAME,
            exchange_type="topic",
            durable=True,
            auto_delete=False,
        )

        # 2. Declare durable queues and bindings
        for item in QUEUES_AND_BINDINGS:
            queue_name = item["queue"]
            routing_key = item["routing_key"]

            channel.queue_declare(
                queue=queue_name,
                durable=True,
                auto_delete=False,
                exclusive=False,
            )

            channel.queue_bind(
                queue=queue_name,
                exchange=EXCHANGE_NAME,
                routing_key=routing_key,
            )


def bootstrap_rabbitmq(
    host: Optional[str] = None,
    port: Optional[int] = None,
    mgmt_port: Optional[int] = None,
    admin_user: Optional[str] = None,
    admin_pass: Optional[str] = None,
    timeout_sec: int = 60,
) -> bool:
    """Execute full idempotent bootstrap for RabbitMQ topology and users."""
    host = host or os.environ.get("RABBIT_HOST", "rabbitmq")
    port = port or int(os.environ.get("RABBIT_PORT", "5672"))
    mgmt_port = mgmt_port or int(os.environ.get("RABBIT_MGMT_PORT", "15672"))
    admin_user = admin_user or os.environ.get("RABBIT_ADMIN_USER", "agro_local")
    admin_pass = admin_pass or read_secret("rabbit_password")

    auth_header = wait_for_rabbitmq(host, port, mgmt_port, admin_user, admin_pass, timeout_sec)
    declare_topology_amqp(host, port, admin_user, admin_pass)
    provision_users_and_permissions(host, mgmt_port, auth_header)
    return True


def main() -> int:
    try:
        bootstrap_rabbitmq()
        print("rabbit_bootstrap_ok: durable topology and restricted users provisioned")
        return 0
    except Exception as exc:
        print(f"rabbit_bootstrap_failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

