"""S3 Storage Adapter and readiness probe for Diagnosis service."""
import json
import logging
import os
from pathlib import Path
from typing import Optional, Tuple
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Base storage exception."""


class StorageUnavailableError(StorageError):
    """S3 endpoint is unreachable or returned server error."""


class ObjectNotFoundError(StorageError):
    """Object does not exist in bucket."""


def _build_s3_client(connect_timeout: int = 3, read_timeout: int = 5, max_attempts: int = 2):
    creds_path = os.environ.get("S3_CREDENTIALS_FILE")
    if not creds_path or not Path(creds_path).exists():
        raise StorageUnavailableError("Configuración de credenciales S3 no disponible.")

    endpoint_url = os.environ.get("S3_ENDPOINT_URL")
    region = os.environ.get("S3_REGION", "us-east-1")
    if not endpoint_url:
        raise StorageUnavailableError("S3_ENDPOINT_URL no configurado.")

    try:
        credentials = json.loads(Path(creds_path).read_text())
        access_key = credentials["access_key"]
        secret_key = credentials["secret_key"]
    except Exception as exc:
        raise StorageUnavailableError(f"Error al leer credenciales S3: {exc}")

    config = Config(
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        retries={"max_attempts": max_attempts},
        s3={"addressing_style": "path"},
    )

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=config,
    )


class S3StorageAdapter:
    def __init__(self, bucket: Optional[str] = None):
        self._bucket = bucket or os.environ.get("S3_BUCKET", "agrodiagnostico")

    @property
    def bucket(self) -> str:
        return self._bucket

    def put_object(self, key: str, body: bytes, content_type: str) -> None:
        """Write object to private S3 bucket with server-side key and content type."""
        try:
            client = _build_s3_client(connect_timeout=3, read_timeout=10, max_attempts=2)
            try:
                client.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=body,
                    ContentType=content_type,
                )
            finally:
                client.close()
        except (ClientError, EndpointConnectionError, BotoCoreError, OSError) as exc:
            logger.error("S3 put_object failed for key %s: %s", key, exc)
            raise StorageUnavailableError(f"Fallo al guardar objeto en almacenamiento.") from exc

    def get_object(self, key: str) -> Tuple[bytes, str]:
        """Read object bytes and content type from private S3 bucket."""
        try:
            client = _build_s3_client(connect_timeout=3, read_timeout=10, max_attempts=2)
            try:
                resp = client.get_object(Bucket=self._bucket, Key=key)
                content_type = resp.get("ContentType", "application/octet-stream")
                data = resp["Body"].read()
                return data, content_type
            finally:
                client.close()
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404", "NotFound"):
                raise ObjectNotFoundError(f"Objeto no encontrado: {key}") from exc
            logger.error("S3 get_object client error for key %s: %s", key, exc)
            raise StorageUnavailableError("Fallo al acceder al almacenamiento de objetos.") from exc
        except (EndpointConnectionError, BotoCoreError, OSError) as exc:
            logger.error("S3 get_object connection error for key %s: %s", key, exc)
            raise StorageUnavailableError("Fallo al acceder al almacenamiento de objetos.") from exc

    def delete_object(self, key: str) -> None:
        """Delete object from private S3 bucket. Idempotent on missing object."""
        try:
            client = _build_s3_client(connect_timeout=3, read_timeout=5, max_attempts=2)
            try:
                client.delete_object(Bucket=self._bucket, Key=key)
            finally:
                client.close()
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404", "NotFound"):
                return
            logger.error("S3 delete_object client error for key %s: %s", key, exc)
            raise StorageUnavailableError("Fallo al eliminar objeto del almacenamiento.") from exc
        except (EndpointConnectionError, BotoCoreError, OSError) as exc:
            logger.error("S3 delete_object connection error for key %s: %s", key, exc)
            raise StorageUnavailableError("Fallo al eliminar objeto del almacenamiento.") from exc

    def object_exists(self, key: str) -> bool:
        """Check if object exists without loading body."""
        try:
            client = _build_s3_client(connect_timeout=2, read_timeout=2, max_attempts=1)
            try:
                client.head_object(Bucket=self._bucket, Key=key)
                return True
            finally:
                client.close()
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404", "NotFound"):
                return False
            raise StorageUnavailableError("Fallo al consultar existencia de objeto.") from exc
        except (EndpointConnectionError, BotoCoreError, OSError) as exc:
            raise StorageUnavailableError("Fallo al consultar existencia de objeto.") from exc


_adapter_instance: Optional[S3StorageAdapter] = None


def get_storage_adapter() -> S3StorageAdapter:
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = S3StorageAdapter()
    return _adapter_instance


def set_storage_adapter(adapter: Optional[S3StorageAdapter]) -> None:
    """Setter for testing/mocking storage adapter."""
    global _adapter_instance
    _adapter_instance = adapter


def storage_ready() -> bool:
    try:
        client = _build_s3_client(connect_timeout=2, read_timeout=2, max_attempts=0)
        try:
            client.head_bucket(Bucket=os.environ.get("S3_BUCKET", "agrodiagnostico"))
        finally:
            client.close()
        return True
    except Exception:
        return False
