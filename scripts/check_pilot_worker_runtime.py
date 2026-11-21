"""Exercise the approved CPU adapter with synthetic pixels, without consuming jobs."""

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

import httpx
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/ai_inference"))

from app.worker import create_configured_inference_adapter  # noqa: E402
from app.worker import InferenceWorker  # noqa: E402
from app.domain.models import Base, InferenceInbox, InferenceOutbox, InferenceResult  # noqa: E402
from app.infrastructure.auth import InternalTokenSigner, generate_worker_keypair  # noqa: E402


class ProbeChannel:
    def __init__(self):
        self.acks = []
        self.nacks = []

    def basic_ack(self, delivery_tag):
        self.acks.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue=False):
        self.nacks.append((delivery_tag, requeue))


class ProbeHttp:
    def __init__(self, pixels: bytes, lease_token: uuid.UUID):
        self.pixels = pixels
        self.lease_token = lease_token
        self.claims = 0
        self.renewals = 0

    def post(self, url, **kwargs):
        if url.endswith("/lease/renew"):
            self.renewals += 1
        else:
            self.claims += 1
        return httpx.Response(200, json={"lease_token": str(self.lease_token)})

    def get(self, url, **kwargs):
        return httpx.Response(200, content=self.pixels)


def main() -> int:
    if os.environ.get("INFERENCE_MODE") != "real":
        raise RuntimeError("Explicit real mode required for this isolated check")
    adapter = create_configured_inference_adapter()
    image = Image.new("RGB", (224, 224), (92, 146, 75))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    diagnosis_id = uuid.uuid4()
    rejected = adapter.run_inference(diagnosis_id, stream.getvalue(), identified_crop="MAIZE")
    assert rejected["reason_code"] == "UNSUPPORTED_CROP" and rejected["model_id"] is None
    bad = adapter.run_inference(diagnosis_id, b"bad image", identified_crop="POTATO")
    assert bad["reason_code"] == "BAD_IMAGE" and bad["model_id"] is None
    result = adapter.run_inference(diagnosis_id, stream.getvalue(), identified_crop="POTATO")
    assert result["outcome"] in {"PREDICTION", "ABSTENTION"}
    assert result["class_code"] in {None, "POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT"}
    assert result["model_version"] == "0.1.0-pilot"
    with tempfile.TemporaryDirectory() as temporary:
        engine = create_engine(f"sqlite:///{Path(temporary) / 'worker.sqlite'}")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine)
        private_key, _ = generate_worker_keypair()
        signer = InternalTokenSigner(private_key_pem=private_key, kid="probe-key",
                                     instance_id="probe-worker")
        lease_token = uuid.uuid4()
        http = ProbeHttp(stream.getvalue(), lease_token)
        worker = InferenceWorker(
            session_factory, "http://diagnosis.invalid", signer,
            http_client=http, local_lease_seconds=20, heartbeat_seconds=.5,
            inference_adapter=adapter)
        event_id = uuid.uuid4()
        event = {
            "event_id": str(event_id), "event_type": "DiagnosisRequested",
            "schema_version": 2, "occurred_at": "2026-11-20T12:00:00Z",
            "correlation_id": str(uuid.uuid4()),
            "payload": {"diagnosis_id": str(diagnosis_id), "owner_id": str(uuid.uuid4()),
                        "object_key": f"diagnoses/{diagnosis_id}/original.png",
                        "identified_crop": "POTATO"},
        }
        body = json.dumps(event).encode("utf-8")
        channel = ProbeChannel()
        assert worker.process_message(channel, 1, body, "diagnosis.requested.v2")
        assert worker.process_message(channel, 2, body, "diagnosis.requested.v2")
        assert channel.acks == [1, 2] and not channel.nacks
        assert http.claims == 1 and http.renewals >= 1
        with session_factory() as session:
            assert len(session.scalars(select(InferenceResult)).all()) == 1
            assert len(session.scalars(select(InferenceInbox)).all()) == 1
            assert len(session.scalars(select(InferenceOutbox)).all()) == 1
        engine.dispose()
    print({"scope": "SYNTHETIC_RUNTIME_CHECK_NOT_AGRONOMIC_EVIDENCE",
           "result": result["outcome"], "class_code": result["class_code"],
           "reason_code": result["reason_code"], "inference_ms": result["inference_ms"],
           "renewals": http.renewals, "logical_results": 1, "redelivery_acknowledged": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
