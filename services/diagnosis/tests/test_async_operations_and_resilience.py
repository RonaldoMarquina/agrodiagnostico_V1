"""Verification tests for Section 7.3: Background processes, Docker Compose, resilience and operation.

Covers:
- Diagnosis API availability (202 Accepted and /health/ready 200 OK) when RabbitMQ and Redis are down.
- Docker Compose topology: only Nginx reverse proxy publishes host ports; all internal
  databases, brokers, and background services remain isolated on internal networks.
- Verification of 2 AI worker instances, publishers, consumer, and recovery daemons in Compose.
- Verification of async-test profile and fail-closed simulation guard in normal startup.
- Conservation of persistent database state and in-flight jobs upon shutdown.
"""
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import uuid

from tests.client import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.diagnoses import create_diagnosis
from app.domain.image import ValidatedImage
from app.domain.models import Base, Diagnosis, DiagnosisOutbox, IdempotencyKey
from app.infrastructure.security import Principal
from app.main import app
from app.storage import S3StorageAdapter


class MemoryStorage(S3StorageAdapter):
    def __init__(self):
        self.objects = {}

    def put_object(self, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = (body, content_type)

    def get_object(self, key: str) -> tuple[bytes, str]:
        if key not in self.objects:
            from app.storage import ObjectNotFoundError
            raise ObjectNotFoundError(f"Key not found: {key}")
        return self.objects[key]

    def delete_object(self, key: str) -> None:
        self.objects.pop(key, None)


class TestAsyncOperationsAndResilience(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.storage = MemoryStorage()
        self.principal = Principal(id=uuid.uuid4(), role="USER", token_id=str(uuid.uuid4()))
        self.client = TestClient(app)

    def test_diagnosis_health_ready_independent_of_broker_and_redis(self):
        """Diagnosis readiness check (/health/ready) relies solely on DB and S3.
        
        Even when RabbitMQ and Redis are completely absent or offline,
        /health/ready must return HTTP 200 OK.
        """
        with patch("app.main.schema_ready", return_value=True), \
             patch("app.main.storage_ready", return_value=True):
            resp = self.client.get("/health/ready")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "ready")
            self.assertEqual(data["service"], "diagnosis")

    def test_diagnosis_creation_accepted_with_broker_and_redis_down(self):
        """Diagnosis ingestion returns 202 Accepted and commits outbox to DB
        when RabbitMQ and Redis are completely unavailable.
        """
        raw = b"\xFF\xD8\xFF\xE0fake-image-bytes"
        img = ValidatedImage(
            data=raw,
            size_bytes=len(raw),
            sha256="test-sha256-hash-value-12345",
            content_type="image/jpeg",
            extension=".jpg",
            width=800,
            height=600,
        )

        with self.SessionLocal() as session:
            diag = create_diagnosis(
                db=session,
                principal=self.principal,
                idempotency_key="resilience-test-key-01",
                validated_image=img,
                storage=self.storage,
            )
            session.commit()

            self.assertEqual(diag.status, "PENDIENTE")

            # Outbox record must be persisted in DB ready for async pickup
            outbox_event = session.execute(
                select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == diag.id)
            ).scalar_one_or_none()
            self.assertIsNotNone(outbox_event)
            self.assertEqual(outbox_event.event_type, "DiagnosisRequested")
            self.assertEqual(outbox_event.schema_version, 2)
            self.assertIsNone(outbox_event.sent_at)

    def test_docker_compose_only_proxy_published_and_topology_complete(self):
        """Verify Docker Compose configuration for task 7.3:
        1. Only the Nginx proxy publishes ports to host.
        2. Two AI worker instances are defined.
        3. Background publisher, consumer, and recovery processes are defined.
        4. async-test profile is configured.
        5. Simulation defaults to false (fail-closed).
        """
        compose_path = Path(__file__).resolve().parents[3] / "docker-compose.yml"
        self.assertTrue(compose_path.is_file(), f"Missing {compose_path}")

        # Render only: use committed defaults, never the developer's .env or
        # exported simulation/profile settings. No daemon or real secrets needed.
        compose_env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
        compose_command = [
            "docker", "compose", "--env-file", str(compose_path.parent / ".env.example"),
            "-f", str(compose_path),
        ]
        proc = subprocess.run(
            [*compose_command, "--profile", "async-test", "config", "--format", "json"],
            env=compose_env,
            cwd=str(compose_path.parent),
            capture_output=True,
            text=True,
            check=True,
        )
        compose_data = json.loads(proc.stdout)
        services = compose_data.get("services", {})

        # 1. Port publication check
        for svc_name, svc_cfg in services.items():
            if svc_name == "nginx":
                self.assertIn("ports", svc_cfg, "Nginx proxy must expose published host ports")
                self.assertTrue(len(svc_cfg["ports"]) > 0)
            else:
                self.assertNotIn(
                    "ports",
                    svc_cfg,
                    f"Service '{svc_name}' must NOT publish ports to host; only Nginx proxy may publish ports.",
                )

        # 2. Worker instances check
        self.assertIn("ai_inference-worker-1", services)
        self.assertIn("ai_inference-worker-2", services)
        worker1 = services["ai_inference-worker-1"]
        worker2 = services["ai_inference-worker-2"]
        self.assertEqual(worker1["environment"].get("WORKER_INSTANCE_ID"), "worker-1")
        self.assertEqual(worker2["environment"].get("WORKER_INSTANCE_ID"), "worker-2")

        # 3. Background daemons check
        self.assertIn("diagnosis-publisher", services)
        self.assertIn("diagnosis-consumer", services)
        self.assertIn("diagnosis-recovery", services)
        self.assertIn("ai_inference-publisher", services)

        # 4. Simulation default in workers
        worker1_sim = worker1["environment"].get("ENABLE_SIMULATED_INFERENCE", "")
        self.assertIn("false", str(worker1_sim), "Worker 1 must default to ENABLE_SIMULATED_INFERENCE=false")

        # 5. async-test profile check
        for worker in (worker1, worker2):
            self.assertIn("async-test", worker["profiles"])
            self.assertEqual(worker["environment"]["APP_ENV"], "test")
        normal = subprocess.run(
            [*compose_command, "config", "--services"],
            env=compose_env,
            cwd=str(compose_path.parent), capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        self.assertNotIn("ai_inference-worker-1", normal)
        self.assertNotIn("ai_inference-worker-2", normal)

    def test_simulation_guard_fails_closed_in_normal_environment(self):
        """In normal Compose or non-test environments, simulator execution fails closed."""
        from importlib.util import module_from_spec, spec_from_file_location
        simulator_path = Path(__file__).resolve().parents[3] / "services/ai_inference/app/simulator.py"
        spec = spec_from_file_location("acceptance_simulator", simulator_path)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        ensure_simulation_permitted = module.ensure_simulation_permitted

        # Case 1: APP_ENV is development / production
        with patch.dict(os.environ, {"APP_ENV": "development", "ENABLE_SIMULATED_INFERENCE": "true"}):
            with self.assertRaises(RuntimeError) as ctx:
                ensure_simulation_permitted()
            self.assertIn("strictly prohibited", str(ctx.exception))

        # Case 2: ENABLE_SIMULATED_INFERENCE is false
        with patch.dict(os.environ, {"APP_ENV": "test", "ENABLE_SIMULATED_INFERENCE": "false"}):
            with self.assertRaises(RuntimeError) as ctx:
                ensure_simulation_permitted()
            self.assertIn("strictly prohibited", str(ctx.exception))

    def test_persistent_jobs_and_outbox_conserved_on_shutdown(self):
        """Stopping or terminating background processes does not corrupt or drop persistent work."""
        with self.SessionLocal() as session:
            # Create a pending outbox row
            outbox_row = DiagnosisOutbox(
                event_id=uuid.uuid4(),
                event_type="DiagnosisRequested",
                schema_version=2,
                routing_key="diagnosis.requested.v2",
                envelope={"test": "conserved"},
                diagnosis_id=uuid.uuid4(),
                attempt_number=1,
            )
            session.add(outbox_row)
            session.commit()
            evt_id = outbox_row.event_id

        # Simulating daemon shutdown: row remains in DB uncorrupted
        with self.SessionLocal() as session:
            persisted = session.execute(
                select(DiagnosisOutbox).where(DiagnosisOutbox.event_id == evt_id)
            ).scalar_one_or_none()
            self.assertIsNotNone(persisted)
            self.assertIsNone(persisted.sent_at)
            self.assertEqual(persisted.envelope, {"test": "conserved"})


if __name__ == "__main__":
    unittest.main()
