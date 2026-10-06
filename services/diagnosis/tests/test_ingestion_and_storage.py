"""Unit and integration tests for image ingestion, S3 adapter, idempotency, intent reconciliation, and image retrieval."""
import datetime
import io
import time
import unittest
import uuid
from typing import Dict, List, Optional, Tuple

import jwt
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.application.reconcile import reconcile_upload_intents
from app.domain.image import MAX_FILE_BYTES, MAX_TRANSPORT_BYTES
from app.domain.models import Base, Diagnosis, IdempotencyKey, ImageUploadIntent
from app.infrastructure.tokens import (
    TokenVerifier,
    generate_ed25519_keypair,
    set_token_verifier,
)
from app.main import app as main_app
from app.storage import (
    ObjectNotFoundError,
    S3StorageAdapter,
    StorageError,
    StorageUnavailableError,
    set_storage_adapter,
)
from tests.client import TestClient


class MemoryStorageAdapter(S3StorageAdapter):
    def __init__(self):
        super().__init__(bucket="test-bucket")
        self.objects: Dict[str, Tuple[bytes, str]] = {}
        self.fail_put = False
        self.fail_delete = False
        self.fail_get = False

    def put_object(self, key: str, body: bytes, content_type: str) -> None:
        if self.fail_put:
            raise StorageUnavailableError("Simulated S3 put failure")
        self.objects[key] = (body, content_type)

    def get_object(self, key: str) -> Tuple[bytes, str]:
        if self.fail_get:
            raise StorageUnavailableError("Simulated S3 get failure")
        if key not in self.objects:
            raise ObjectNotFoundError(f"Key {key} not found")
        return self.objects[key]

    def delete_object(self, key: str) -> None:
        if self.fail_delete:
            raise StorageError("Simulated S3 delete failure")
        self.objects.pop(key, None)

    def object_exists(self, key: str) -> bool:
        return key in self.objects


def make_multipart_body(
    fields: Optional[Dict[str, str]] = None,
    files: Optional[List[Tuple[str, str, bytes, str]]] = None,
    boundary: str = "----WebKitFormBoundary7MA4YWxkTrZu0gW",
) -> Tuple[bytes, str]:
    body = bytearray()
    if fields:
        for k, v in fields.items():
            body.extend(f"--{boundary}\r\n".encode("latin1"))
            body.extend(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("latin1"))
            body.extend(v.encode("utf-8"))
            body.extend(b"\r\n")
    if files:
        for field_name, filename, file_bytes, content_type in files:
            body.extend(f"--{boundary}\r\n".encode("latin1"))
            body.extend(
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode("latin1")
            )
            body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("latin1"))
            body.extend(file_bytes)
            body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("latin1"))
    content_type_header = f"multipart/form-data; boundary={boundary}"
    return bytes(body), content_type_header


def make_test_jpeg(width: int = 50, height: int = 50, color: str = "green") -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def make_test_png(width: int = 50, height: int = 50, color: str = "blue") -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_test_webp(width: int = 50, height: int = 50, color: str = "red") -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    return buf.getvalue()


def make_animated_webp() -> bytes:
    frames = [Image.new("RGB", (20, 20), color=c) for c in ("red", "blue")]
    buf = io.BytesIO()
    frames[0].save(buf, format="WEBP", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buf.getvalue()


def make_padded_jpeg(target_bytes: int) -> bytes:
    base = make_test_jpeg(100, 100)
    header = base[:-2]
    tail = base[-2:]
    pad_needed = target_bytes - len(base)
    chunks = []
    while pad_needed > 0:
        chunk_len = min(pad_needed, 65535)
        if chunk_len < 4:
            break
        payload_len = chunk_len - 4
        chunks.append(b"\xff\xfe" + (payload_len + 2).to_bytes(2, "big") + b"A" * payload_len)
        pad_needed -= chunk_len
    return header + b"".join(chunks) + b"B" * pad_needed + tail


class TestIngestionAndStorage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.priv_pem, cls.pub_pem = generate_ed25519_keypair()
        cls.verifier = TokenVerifier(public_key_pem=cls.pub_pem)
        set_token_verifier(cls.verifier)

        # In-memory SQLite engine with StaticPool for cross-session access
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.SessionLocal = sessionmaker(bind=cls.engine)

        def override_get_db():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        main_app.dependency_overrides[get_db] = override_get_db

        cls.client = TestClient(main_app)

    @classmethod
    def tearDownClass(cls):
        set_token_verifier(None)
        set_storage_adapter(None)
        main_app.dependency_overrides.clear()

    def setUp(self):
        # Clean up database tables between tests
        with self.SessionLocal() as session:
            session.query(IdempotencyKey).delete()
            session.query(ImageUploadIntent).delete()
            session.query(Diagnosis).delete()
            session.commit()

        self.storage = MemoryStorageAdapter()
        set_storage_adapter(self.storage)

        self.user_a_id = uuid.uuid4()
        self.user_b_id = uuid.uuid4()
        self.admin_id = uuid.uuid4()

        self.token_user_a = self._create_token(sub=str(self.user_a_id), role="USER")
        self.token_user_b = self._create_token(sub=str(self.user_b_id), role="USER")
        self.token_admin = self._create_token(sub=str(self.admin_id), role="ADMIN")

    def _create_token(self, sub: str, role: str = "USER", expires_in: int = 3600) -> str:
        now = int(time.time())
        claims = {
            "sub": sub,
            "role": role,
            "iss": "agrodiagnostico-identity",
            "aud": "agrodiagnostico-api",
            "iat": now,
            "exp": now + expires_in,
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(claims, self.priv_pem, algorithm="EdDSA")

    # --- Task 4.1: Image parsing and limits ---

    def test_incomplete_multipart_does_not_persist(self):
        body, ct = make_multipart_body(files=[("image", "leaf.jpg", make_test_jpeg(), "image/jpeg")], boundary="audit")
        variants = [body[:-len(b"--audit--\r\n")], body.replace(b'; filename="leaf.jpg"', b'')]
        for body in variants:
            response = self.client.post("/api/v1/diagnoses", data=body,
                                        headers={"Authorization": f"Bearer {self.token_user_a}",
                                                 "Content-Type": ct, "Idempotency-Key": str(uuid.uuid4())})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["code"], "INVALID_REQUEST")
        with self.SessionLocal() as session:
            self.assertEqual(session.query(Diagnosis).count(), 0)
            self.assertEqual(session.query(ImageUploadIntent).count(), 0)
        self.assertEqual(self.storage.objects, {})

    def test_post_diagnoses_valid_jpeg(self):
        img_bytes = make_test_jpeg(60, 60)
        body, ct = make_multipart_body(files=[("image", "test.jpg", img_bytes, "image/jpeg")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "test-key-01",
            "Content-Type": ct,
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        self.assertEqual(resp.status_code, 202)
        data = resp.json()
        self.assertIn("id", data)
        self.assertEqual(data["status"], "PENDIENTE")
        self.assertIn("created_at", data)
        self.assertEqual(resp.headers.get("Cache-Control"), "private, no-store")
        self.assertIn("x-correlation-id", resp.headers)

        # Check DB
        with self.SessionLocal() as session:
            diag = session.get(Diagnosis, uuid.UUID(data["id"]))
            self.assertIsNotNone(diag)
            self.assertEqual(diag.owner_id, self.user_a_id)
            self.assertEqual(diag.status, "PENDIENTE")
            self.assertEqual(diag.image_content_type, "image/jpeg")
            self.assertEqual(diag.image_width, 60)
            self.assertEqual(diag.image_height, 60)

            # Check intent deleted
            intents = session.query(ImageUploadIntent).all()
            self.assertEqual(len(intents), 0)

        # Check S3
        self.assertTrue(self.storage.object_exists(diag.object_key))
        stored_bytes, stored_ct = self.storage.get_object(diag.object_key)
        self.assertEqual(stored_bytes, img_bytes)
        self.assertEqual(stored_ct, "image/jpeg")

    def test_post_diagnoses_exact_10_mib(self):
        padded_bytes = make_padded_jpeg(MAX_FILE_BYTES)
        self.assertEqual(len(padded_bytes), MAX_FILE_BYTES)

        body, ct = make_multipart_body(files=[("image", "exact.jpg", padded_bytes, "image/jpeg")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "key-exact-10mb",
            "Content-Type": ct,
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        self.assertEqual(resp.status_code, 202)
        data = resp.json()
        self.assertEqual(data["status"], "PENDIENTE")

    def test_post_diagnoses_exceeds_10_mib(self):
        # 10 MiB + 1 byte
        too_big = make_padded_jpeg(MAX_FILE_BYTES + 1)
        self.assertEqual(len(too_big), MAX_FILE_BYTES + 1)

        body, ct = make_multipart_body(files=[("image", "toolarge.jpg", too_big, "image/jpeg")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "key-too-big",
            "Content-Type": ct,
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(resp.json()["code"], "IMAGE_TOO_LARGE")

        # Verify no diagnosis and no object in S3
        with self.SessionLocal() as session:
            self.assertEqual(session.query(Diagnosis).count(), 0)
        self.assertEqual(len(self.storage.objects), 0)

    def test_post_diagnoses_misleading_content_length(self):
        too_big = make_padded_jpeg(MAX_FILE_BYTES + 1)
        body, ct = make_multipart_body(files=[("image", "toolarge.jpg", too_big, "image/jpeg")])
        # Provide small deceptive content-length header
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "key-misleading-cl",
            "Content-Type": ct,
            "Content-Length": "100",
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(resp.json()["code"], "IMAGE_TOO_LARGE")

    def test_post_diagnoses_extra_parts_rejected(self):
        img_bytes = make_test_jpeg()
        body, ct = make_multipart_body(
            fields={"crop_code": "POTATO"},
            files=[("image", "test.jpg", img_bytes, "image/jpeg")],
        )
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "key-extra-fields",
            "Content-Type": ct,
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "INVALID_REQUEST")

    def test_post_diagnoses_missing_image_rejected(self):
        img_bytes = make_test_jpeg()
        body, ct = make_multipart_body(files=[("other_field", "test.jpg", img_bytes, "image/jpeg")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "key-missing-image",
            "Content-Type": ct,
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "INVALID_REQUEST")

    def test_post_diagnoses_corrupt_image_rejected(self):
        valid = make_test_jpeg()
        corrupt = valid[:25] + b"\x00" * (len(valid) - 25)
        body, ct = make_multipart_body(files=[("image", "corrupt.jpg", corrupt, "image/jpeg")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "key-corrupt",
            "Content-Type": ct,
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "INVALID_IMAGE")

    def test_post_diagnoses_pixel_bomb_rejected(self):
        # 5000 x 5000 = 25,000,000 pixels > 24 MP
        bomb = make_test_jpeg(5000, 5000)
        body, ct = make_multipart_body(files=[("image", "bomb.jpg", bomb, "image/jpeg")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "key-pixel-bomb",
            "Content-Type": ct,
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(resp.json()["code"], "IMAGE_TOO_LARGE")

    def test_post_diagnoses_multiframe_animated_rejected(self):
        animated_webp = make_animated_webp()
        body, ct = make_multipart_body(files=[("image", "anim.webp", animated_webp, "image/webp")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "key-anim",
            "Content-Type": ct,
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "INVALID_IMAGE")

    def test_post_diagnoses_unsupported_media_type_gif(self):
        # GIF disguised as .jpg
        img = Image.new("RGB", (20, 20), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="GIF")
        body, ct = make_multipart_body(files=[("image", "fake.jpg", buf.getvalue(), "image/jpeg")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "key-gif",
            "Content-Type": ct,
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        self.assertEqual(resp.status_code, 415)
        self.assertEqual(resp.json()["code"], "UNSUPPORTED_MEDIA_TYPE")

    def test_post_diagnoses_heic_rejected_415(self):
        mock_heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 100
        body, ct = make_multipart_body(files=[("image", "photo.heic", mock_heic, "image/heic")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "key-heic",
            "Content-Type": ct,
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        self.assertEqual(resp.status_code, 415)
        self.assertEqual(resp.json()["code"], "UNSUPPORTED_MEDIA_TYPE")

    # --- Tasks 4.2 & 4.3 & 4.4: Idempotency, S3, and Durable Intent ---

    def test_idempotency_identical_replay(self):
        img_bytes = make_test_jpeg(30, 30, color="green")
        body, ct = make_multipart_body(files=[("image", "photo.jpg", img_bytes, "image/jpeg")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "replay-key-1",
            "Content-Type": ct,
        }

        # 1. First acceptance
        resp1 = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        self.assertEqual(resp1.status_code, 202)
        d1 = resp1.json()

        # 2. Replay with identical image and key
        resp2 = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        self.assertEqual(resp2.status_code, 202)
        d2 = resp2.json()

        # Same diagnosis returned
        self.assertEqual(d1["id"], d2["id"])
        self.assertEqual(d1["created_at"], d2["created_at"])
        self.assertEqual(d2["status"], "PENDIENTE")

        # Confirm only 1 diagnosis and 1 S3 object
        with self.SessionLocal() as session:
            self.assertEqual(session.query(Diagnosis).count(), 1)
        self.assertEqual(len(self.storage.objects), 1)

    def test_idempotency_content_conflict(self):
        img1 = make_test_jpeg(30, 30, color="green")
        body1, ct1 = make_multipart_body(files=[("image", "photo.jpg", img1, "image/jpeg")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "conflict-key",
            "Content-Type": ct1,
        }
        resp1 = self.client.post("/api/v1/diagnoses", data=body1, headers=headers)
        self.assertEqual(resp1.status_code, 202)

        # Same key with DIFFERENT image bytes
        img2 = make_test_png(40, 40, color="yellow")
        body2, ct2 = make_multipart_body(files=[("image", "photo.png", img2, "image/png")])
        headers["Content-Type"] = ct2

        resp2 = self.client.post("/api/v1/diagnoses", data=body2, headers=headers)
        self.assertEqual(resp2.status_code, 409)
        self.assertEqual(resp2.json()["code"], "IDEMPOTENCY_CONFLICT")

    def test_idempotency_user_isolation(self):
        img_bytes = make_test_jpeg(30, 30, color="blue")
        body, ct = make_multipart_body(files=[("image", "photo.jpg", img_bytes, "image/jpeg")])

        # User A
        headers_a = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "shared-key-name",
            "Content-Type": ct,
        }
        resp_a = self.client.post("/api/v1/diagnoses", data=body, headers=headers_a)
        self.assertEqual(resp_a.status_code, 202)
        id_a = resp_a.json()["id"]

        # User B with identical key text
        headers_b = {
            "Authorization": f"Bearer {self.token_user_b}",
            "Idempotency-Key": "shared-key-name",
            "Content-Type": ct,
        }
        resp_b = self.client.post("/api/v1/diagnoses", data=body, headers=headers_b)
        self.assertEqual(resp_b.status_code, 202)
        id_b = resp_b.json()["id"]

        self.assertNotEqual(id_a, id_b)
        with self.SessionLocal() as session:
            self.assertEqual(session.query(Diagnosis).count(), 2)

    def test_idempotency_tombstone_returns_409(self):
        img_bytes = make_test_jpeg(30, 30)
        body, ct = make_multipart_body(files=[("image", "photo.jpg", img_bytes, "image/jpeg")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "tombstone-key",
            "Content-Type": ct,
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        diag_id = resp.json()["id"]

        # Soft delete diagnosis
        with self.SessionLocal() as session:
            diag = session.get(Diagnosis, uuid.UUID(diag_id))
            diag.deleted_at = datetime.datetime.now(datetime.timezone.utc)
            session.commit()

        # Replay with same key
        resp2 = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        self.assertEqual(resp2.status_code, 409)
        self.assertEqual(resp2.json()["code"], "IDEMPOTENCY_RESOURCE_DELETED")

    def test_idempotency_expiration_allows_new_generation(self):
        img1 = make_test_jpeg(30, 30, color="red")
        body1, ct1 = make_multipart_body(files=[("image", "photo1.jpg", img1, "image/jpeg")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "expiring-key",
            "Content-Type": ct1,
        }
        resp1 = self.client.post("/api/v1/diagnoses", data=body1, headers=headers)
        id1 = resp1.json()["id"]

        # Simulate expiration
        with self.SessionLocal() as session:
            key_row = session.query(IdempotencyKey).filter_by(key="expiring-key").one()
            key_row.expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=5)
            session.commit()

        # New request with same key
        img2 = make_test_png(40, 40, color="cyan")
        body2, ct2 = make_multipart_body(files=[("image", "photo2.png", img2, "image/png")])
        headers["Content-Type"] = ct2

        resp2 = self.client.post("/api/v1/diagnoses", data=body2, headers=headers)
        self.assertEqual(resp2.status_code, 202)
        id2 = resp2.json()["id"]
        self.assertNotEqual(id1, id2)

        # Both diagnoses exist in DB
        with self.SessionLocal() as session:
            self.assertIsNotNone(session.get(Diagnosis, uuid.UUID(id1)))
            self.assertIsNotNone(session.get(Diagnosis, uuid.UUID(id2)))

    def test_s3_unavailable_returns_503(self):
        self.storage.fail_put = True
        img_bytes = make_test_jpeg()
        body, ct = make_multipart_body(files=[("image", "photo.jpg", img_bytes, "image/jpeg")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "key-s3-fail",
            "Content-Type": ct,
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["code"], "STORAGE_UNAVAILABLE")

        # Verify no diagnosis created in DB
        with self.SessionLocal() as session:
            self.assertEqual(session.query(Diagnosis).count(), 0)

    # --- Task 4.5: Reconciler ---

    def test_reconciler_cleans_orphaned_intent_and_s3_object(self):
        orphan_id = uuid.uuid4()
        object_key = f"diagnoses/{orphan_id}/original.jpg"
        self.storage.objects[object_key] = (b"orphaned bytes", "image/jpeg")

        with self.SessionLocal() as session:
            intent = ImageUploadIntent(
                diagnosis_id=orphan_id,
                object_key=object_key,
                owner_id=self.user_a_id,
                created_at=datetime.datetime.now(datetime.timezone.utc),
            )
            session.add(intent)
            session.commit()

        # Run reconciler
        with self.SessionLocal() as session:
            stats = reconcile_upload_intents(session, self.storage)
            self.assertEqual(stats["reconciled"], 1)
            self.assertEqual(stats["failed"], 0)

        # Object removed from S3 and intent removed from DB
        self.assertFalse(self.storage.object_exists(object_key))
        with self.SessionLocal() as session:
            self.assertEqual(session.query(ImageUploadIntent).count(), 0)

    def test_reconciler_preserves_referenced_diagnosis_object(self):
        # A valid diagnosis exists
        diag_id = uuid.uuid4()
        object_key = f"diagnoses/{diag_id}/original.jpg"
        self.storage.objects[object_key] = (b"valid bytes", "image/jpeg")

        with self.SessionLocal() as session:
            diag = Diagnosis(
                id=diag_id,
                owner_id=self.user_a_id,
                status="PENDIENTE",
                object_key=object_key,
                image_sha256="abc",
                image_content_type="image/jpeg",
                image_size_bytes=100,
                image_width=50,
                image_height=50,
                created_at=datetime.datetime.now(datetime.timezone.utc),
                updated_at=datetime.datetime.now(datetime.timezone.utc),
            )
            session.add(diag)
            # Leftover intent with same diagnosis_id
            intent = ImageUploadIntent(
                diagnosis_id=diag_id,
                object_key=object_key,
                owner_id=self.user_a_id,
                created_at=datetime.datetime.now(datetime.timezone.utc),
            )
            session.add(intent)
            session.commit()

        with self.SessionLocal() as session:
            stats = reconcile_upload_intents(session, self.storage)
            self.assertEqual(stats["kept_referenced"], 1)
            self.assertEqual(stats["reconciled"], 0)

        # S3 object is kept intact
        self.assertTrue(self.storage.object_exists(object_key))
        # Leftover intent is removed
        with self.SessionLocal() as session:
            self.assertEqual(session.query(ImageUploadIntent).count(), 0)

    def test_reconciler_s3_error_keeps_intent_in_db(self):
        orphan_id = uuid.uuid4()
        object_key = f"diagnoses/{orphan_id}/original.jpg"
        self.storage.objects[object_key] = (b"orphaned bytes", "image/jpeg")
        self.storage.fail_delete = True

        with self.SessionLocal() as session:
            intent = ImageUploadIntent(
                diagnosis_id=orphan_id,
                object_key=object_key,
                owner_id=self.user_a_id,
                created_at=datetime.datetime.now(datetime.timezone.utc),
            )
            session.add(intent)
            session.commit()

        with self.SessionLocal() as session:
            stats = reconcile_upload_intents(session, self.storage)
            self.assertEqual(stats["failed"], 1)

        # Intent is preserved in DB for retry
        with self.SessionLocal() as session:
            self.assertEqual(session.query(ImageUploadIntent).count(), 1)

    # --- Task 4.6: GET /api/v1/diagnoses/{id}/image ---

    def test_get_own_image_success(self):
        img_bytes = make_test_jpeg(80, 80, color="magenta")
        body, ct = make_multipart_body(files=[("image", "my.jpg", img_bytes, "image/jpeg")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "key-download-test",
            "Content-Type": ct,
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        diag_id = resp.json()["id"]

        # Download own image
        dl_resp = self.client.get(
            f"/api/v1/diagnoses/{diag_id}/image",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
        )
        self.assertEqual(dl_resp.status_code, 200)
        self.assertEqual(dl_resp.body, img_bytes)
        self.assertEqual(dl_resp.headers.get("content-type"), "image/jpeg")
        self.assertEqual(dl_resp.headers.get("cache-control"), "private, no-store")
        self.assertIn("x-correlation-id", dl_resp.headers)

    def test_get_image_foreign_user_receives_404(self):
        img_bytes = make_test_jpeg()
        body, ct = make_multipart_body(files=[("image", "my.jpg", img_bytes, "image/jpeg")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "key-foreign-test",
            "Content-Type": ct,
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        diag_id = resp.json()["id"]

        # User B requests User A's image
        dl_resp = self.client.get(
            f"/api/v1/diagnoses/{diag_id}/image",
            headers={"Authorization": f"Bearer {self.token_user_b}"},
        )
        self.assertEqual(dl_resp.status_code, 404)
        self.assertEqual(dl_resp.json()["code"], "NOT_FOUND")

    def test_get_image_admin_on_user_route_receives_404(self):
        img_bytes = make_test_jpeg()
        body, ct = make_multipart_body(files=[("image", "my.jpg", img_bytes, "image/jpeg")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "key-admin-test",
            "Content-Type": ct,
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        diag_id = resp.json()["id"]

        # Admin requests image on user route -> 404 (ownership enforced)
        dl_resp = self.client.get(
            f"/api/v1/diagnoses/{diag_id}/image",
            headers={"Authorization": f"Bearer {self.token_admin}"},
        )
        self.assertEqual(dl_resp.status_code, 404)
        self.assertEqual(dl_resp.json()["code"], "NOT_FOUND")

    def test_get_image_tombstone_receives_404(self):
        img_bytes = make_test_jpeg()
        body, ct = make_multipart_body(files=[("image", "my.jpg", img_bytes, "image/jpeg")])
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "Idempotency-Key": "key-deleted-test",
            "Content-Type": ct,
        }
        resp = self.client.post("/api/v1/diagnoses", data=body, headers=headers)
        diag_id = resp.json()["id"]

        # Soft-delete
        with self.SessionLocal() as session:
            diag = session.get(Diagnosis, uuid.UUID(diag_id))
            diag.deleted_at = datetime.datetime.now(datetime.timezone.utc)
            session.commit()

        # Request deleted image
        dl_resp = self.client.get(
            f"/api/v1/diagnoses/{diag_id}/image",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
        )
        self.assertEqual(dl_resp.status_code, 404)
        self.assertEqual(dl_resp.json()["code"], "NOT_FOUND")

    def test_get_image_nonexistent_receives_404(self):
        dl_resp = self.client.get(
            f"/api/v1/diagnoses/{uuid.uuid4()}/image",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
        )
        self.assertEqual(dl_resp.status_code, 404)
        self.assertEqual(dl_resp.json()["code"], "NOT_FOUND")

    def test_get_image_anonymous_receives_401(self):
        dl_resp = self.client.get(f"/api/v1/diagnoses/{uuid.uuid4()}/image")
        self.assertEqual(dl_resp.status_code, 401)
        self.assertEqual(dl_resp.json()["code"], "UNAUTHORIZED")


if __name__ == "__main__":
    unittest.main()
