"""Registro y verificación de procedencia y licencias de arquitecturas base."""
import hashlib
from pathlib import Path
from typing import Dict, Optional

BASE_ARCHITECTURES = {
    "mobilenet_v3_small": {
        "name": "MobileNetV3-Small",
        "license": "PENDING_REVIEW",
        "authors": "Howard et al. (Google Research)",
        "source": "https://download.pytorch.org/models/mobilenet_v3_small-047dc642.pth",
        "expected_sha256": None,
        "description": "Arquitectura ligera optimizada para inferencia eficiente en CPU móvil y servidor."
    },
    "resnet18": {
        "name": "ResNet-18",
        "license": "PENDING_REVIEW",
        "authors": "He et al.",
        "source": "https://download.pytorch.org/models/resnet18-f37072fd.pth",
        "expected_sha256": None,
        "description": "Arquitectura residual convolucional clásica para comparación de línea base en CPU."
    }
}


def verify_weights_digest(weights_path: str | Path, expected_sha256: Optional[str] = None) -> str:
    """Verifica que el archivo binario de pesos coincida exactamente con el digest SHA-256."""
    path = Path(weights_path)
    if not path.is_file():
        raise FileNotFoundError(f"Archivo de pesos no encontrado: {path}")

    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    digest = h.hexdigest()

    if expected_sha256 and digest.lower() != expected_sha256.lower():
        raise ValueError(
            f"Digest SHA-256 de pesos no coincide: obtenido {digest}, esperado {expected_sha256}"
        )
    return digest
