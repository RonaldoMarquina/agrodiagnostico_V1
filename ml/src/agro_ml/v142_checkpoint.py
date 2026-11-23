"""Adquisición y validación offline del checkpoint oficial usado por v1.4.2."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import tempfile
from typing import Any
import urllib.error
import urllib.request

import torch
from torchvision.models import mobilenet_v3_small


OFFICIAL_URL = "https://download.pytorch.org/models/mobilenet_v3_small-047dcff4.pth"
OFFICIAL_FILENAME = "mobilenet_v3_small-047dcff4.pth"
EXPECTED_SIZE = 10_306_551
EXPECTED_SHA256 = "047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f"
WEIGHT_ENUM = "MobileNet_V3_Small_Weights.IMAGENET1K_V1"


class V142CheckpointError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise V142CheckpointError(message)


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_download_identity(requested_url: str, final_url: str, filename: str) -> None:
    _require(requested_url == OFFICIAL_URL, "solo se permite la URL oficial fijada")
    _require(final_url == OFFICIAL_URL, "redirección o URL final no admitida")
    _require(filename == OFFICIAL_FILENAME, "nombre de checkpoint no admitido")


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        raise V142CheckpointError(f"redirección HTTP rechazada: {code}")


def official_opener() -> urllib.request.OpenerDirector:
    context = ssl.create_default_context()
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context), _RejectRedirects())


def validate_checkpoint_file(path: Path, *, expected_sha256: str = EXPECTED_SHA256,
                             expected_size: int = EXPECTED_SIZE) -> Mapping[str, torch.Tensor]:
    _require(path.is_file(), "checkpoint oficial no montado")
    _require(path.name == OFFICIAL_FILENAME, "nombre de checkpoint alterado")
    _require(path.stat().st_size == expected_size, "tamaño de checkpoint alterado o parcial")
    _require(sha256_file(path) == expected_sha256, "SHA-256 del checkpoint no coincide")
    try:
        state = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as exc:
        raise V142CheckpointError("checkpoint no es un state_dict seguro weights_only") from exc
    _require(isinstance(state, Mapping) and bool(state), "state_dict vacío o inválido")
    _require(all(isinstance(key, str) and isinstance(value, torch.Tensor)
                 for key, value in state.items()), "state_dict contiene objetos no tensoriales")
    _require(all(bool(torch.isfinite(value).all()) for value in state.values()),
             "state_dict contiene tensores no finitos")
    expected = mobilenet_v3_small(weights=None).state_dict()
    _require(set(state) == set(expected), "backbone o clasificador ImageNet incompleto")
    _require(all(tuple(state[key].shape) == tuple(value.shape)
                 for key, value in expected.items()), "dimensión de tensor incompatible")
    return state


def validate_registry(registry: Mapping[str, Any], checkpoint: Path) -> None:
    _require(registry.get("requested_url") == OFFICIAL_URL and
             registry.get("final_url") == OFFICIAL_URL, "URL registrada inválida")
    _require(registry.get("filename") == OFFICIAL_FILENAME, "archivo registrado inválido")
    _require(registry.get("size_bytes") == EXPECTED_SIZE and
             registry.get("sha256") == EXPECTED_SHA256, "identidad registrada inválida")
    _require(registry.get("torchvision_version") == "0.29.2+cpu" and
             registry.get("weight_enum") == WEIGHT_ENUM, "versión o enum no fijados")
    _require(registry.get("use_scope") ==
             "ACADEMIC_RESEARCH_EDUCATION_NON_COMMERCIAL_ONLY", "alcance de uso inválido")
    _require(registry.get("redistribution_authorized") is False,
             "el expediente no debe autorizar redistribución")
    validate_checkpoint_file(checkpoint)


def acquire_checkpoint(output_root: Path, terms_path: Path, *, opener: Any | None = None,
                       acquired_at: str | None = None) -> dict[str, Any]:
    """Descarga una vez desde la URL fijada, verifica y materializa expediente privado."""
    _require(not output_root.exists(), "la raíz privada de destino ya existe")
    _require(terms_path.is_file(), "registro de condiciones ausente")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".mobilenet-v142-", suffix=".partial", dir=output_root.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    client = opener or official_opener()
    validated_temporary = temporary
    try:
        request = urllib.request.Request(OFFICIAL_URL, headers={"User-Agent": "AgroDiagnostico-v1.4.2"})
        with client.open(request, timeout=120) as response:
            status = getattr(response, "status", response.getcode())
            _require(status == 200, f"respuesta HTTP inesperada: {status}")
            final_url = response.geturl()
            validate_download_identity(OFFICIAL_URL, final_url, OFFICIAL_FILENAME)
            header = response.headers.get("Content-Length")
            _require(header is None or int(header) == EXPECTED_SIZE,
                     "Content-Length no coincide con el checkpoint fijado")
            digest = hashlib.sha256()
            size = 0
            with temporary.open("wb") as stream:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    size += len(block)
                    _require(size <= EXPECTED_SIZE, "descarga excede el tamaño fijado")
                    digest.update(block)
                    stream.write(block)
                stream.flush()
                os.fsync(stream.fileno())
        _require(size == EXPECTED_SIZE, "descarga parcial")
        _require(digest.hexdigest() == EXPECTED_SHA256, "SHA-256 descargado no coincide")
        validated_temporary = _temporary_as_official(temporary)
        validate_checkpoint_file(validated_temporary)
        output_root.mkdir(mode=0o700)
        checkpoint = output_root / OFFICIAL_FILENAME
        os.replace(validated_temporary, checkpoint)
        shutil.copyfile(terms_path, output_root / "terms.md")
        record = {
            "schema_version": 1,
            "cycle_version": "1.4.2",
            "requested_url": OFFICIAL_URL,
            "final_url": OFFICIAL_URL,
            "filename": OFFICIAL_FILENAME,
            "size_bytes": size,
            "sha256": digest.hexdigest(),
            "acquired_at": acquired_at or datetime.now(timezone.utc).isoformat(),
            "tls_verification": "PYTHON_DEFAULT_SSL_CONTEXT",
            "redirect_policy": "REJECT_ALL",
            "torch_version": torch.__version__,
            "torchvision_version": __import__("torchvision").__version__,
            "weight_enum": WEIGHT_ENUM,
            "reference_transforms": "resize 256, center crop 224, RGB, ImageNet mean/std",
            "provider_metrics": {"parameters": 2542856, "acc_at_1": 67.668, "acc_at_5": 87.402},
            "code_license": "TorchVision BSD-3-Clause",
            "checkpoint_license": "NOT_ASSERTED_AS_BSD",
            "imagenet_terms": "research/education non-commercial; image copyrights not conveyed",
            "use_scope": "ACADEMIC_RESEARCH_EDUCATION_NON_COMMERCIAL_ONLY",
            "redistribution_authorized": False,
        }
        (output_root / "provenance.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        validate_registry(record, checkpoint)
        checkpoint.chmod(0o440)
        (output_root / "provenance.json").chmod(0o440)
        (output_root / "terms.md").chmod(0o440)
        output_root.chmod(0o550)
        return record
    except Exception:
        for candidate in {temporary, validated_temporary}:
            if candidate.exists():
                candidate.unlink()
        if output_root.exists():
            shutil.rmtree(output_root)
        raise


def _temporary_as_official(temporary: Path) -> Path:
    """Renombra el temporal solo localmente para aplicar también la regla de nombre."""
    official = temporary.with_name(OFFICIAL_FILENAME)
    _require(not official.exists(), "checkpoint oficial ya presente en la raíz destino")
    os.replace(temporary, official)
    return official
