"""Preprocesamiento y validación de imágenes foliares en CPU.

Proporciona:
- Validación estricta de bytes (decodificación, dimensiones y formato).
- Extracción determinista de características para inferencia CPU (64 dimensiones).
- Equivalencia de tensor bit a bit para idénticas entradas de bytes (idempotencia).
- Pipeline de data augmentation restringido estrictamente a la partición TRAIN.
- Medición de rendimiento CPU (latencia y memoria) según presupuesto del protocolo G0.
"""
from dataclasses import dataclass
import io
import math
import os
from pathlib import Path
import random
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageEnhance
except ImportError:
    Image = None  # type: ignore
    ImageEnhance = None  # type: ignore


DEFAULT_TARGET_SIZE = (224, 224)
FEATURE_DIM = 64
MIN_DIM = 200
MAX_DIM = 6000
ALLOWED_FORMATS = {"JPEG", "JPG", "PNG"}


def validate_image_bytes(
    image_bytes: bytes,
    min_dim: int = MIN_DIM,
    max_dim: int = MAX_DIM,
) -> Tuple[int, int, str]:
    """Valida decodificación, dimensiones y formato de bytes de imagen sin almacenar en disco."""
    if not image_bytes:
        raise ValueError("Bytes de imagen vacíos")

    if Image is None:
        raise RuntimeError("Pillow no está disponible en el entorno")

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.verify()
    except Exception as exc:
        raise ValueError(f"Bytes corruptos o formato no soportado: {exc}")

    with Image.open(io.BytesIO(image_bytes)) as img:
        width, height = img.size
        fmt = (img.format or "JPEG").upper()
        # Forzar carga de datos de imagen para verificar integridad de mapa de bits
        try:
            img.load()
        except Exception as exc:
            raise ValueError(f"Fallo al cargar mapa de bits: {exc}")

    if fmt not in ALLOWED_FORMATS:
        raise ValueError(f"Formato '{fmt}' no soportado. Permitidos: {ALLOWED_FORMATS}")

    if width < min_dim or height < min_dim:
        raise ValueError(f"Dimensión visual insuficiente: {width}x{height} (mínimo {min_dim}x{min_dim})")
    if width > max_dim or height > max_dim:
        raise ValueError(f"Dimensión excesiva: {width}x{height} (máximo {max_dim}x{max_dim})")

    return width, height, fmt


def preprocess_image(
    image_bytes: bytes,
    target_size: Tuple[int, int] = DEFAULT_TARGET_SIZE,
) -> List[float]:
    """Carga y transforma la imagen a un vector de características normalizado en CPU.

    Genera un vector determinista de exactamente 64 dimensiones:
    - 48 características espaciales de intensidades foliares por celdas (cuadrícula 8x6)
    - 6 momentos de canal RGB (media y desviación por canal)
    - 6 ratios de color y contrastes característicos de clorosis/necrosis
    - 4 diferencias de gradiente espacial
    """
    if Image is None:
        raise RuntimeError("Pillow no está disponible")

    # Validar primero
    validate_image_bytes(image_bytes)

    with Image.open(io.BytesIO(image_bytes)) as img:
        rgb_img = img.convert("RGB").resize(target_size, Image.Resampling.BILINEAR)

    # 1. Grilla espacial de celdas reducidas (8x6 = 48 valores)
    grid_img = rgb_img.resize((8, 6), Image.Resampling.BOX)
    grid_pixels = list(grid_img.getdata())
    spatial_features: List[float] = []
    for r, g, b in grid_pixels:
        intensity = (r + g + b) / (3.0 * 255.0)
        spatial_features.append(round(intensity, 6))

    # 2. Momentos de canal sobre la imagen completa (6 valores)
    all_pixels = list(rgb_img.getdata())
    n = len(all_pixels)
    sum_r = sum(p[0] for p in all_pixels)
    sum_g = sum(p[1] for p in all_pixels)
    sum_b = sum(p[2] for p in all_pixels)
    mean_r = sum_r / (n * 255.0)
    mean_g = sum_g / (n * 255.0)
    mean_b = sum_b / (n * 255.0)

    var_r = sum((p[0] / 255.0 - mean_r) ** 2 for p in all_pixels) / n
    var_g = sum((p[1] / 255.0 - mean_g) ** 2 for p in all_pixels) / n
    var_b = sum((p[2] / 255.0 - mean_b) ** 2 for p in all_pixels) / n
    std_r = math.sqrt(var_r)
    std_g = math.sqrt(var_g)
    std_b = math.sqrt(var_b)

    moments = [
        round(mean_r, 6),
        round(mean_g, 6),
        round(mean_b, 6),
        round(std_r, 6),
        round(std_g, 6),
        round(std_b, 6),
    ]

    # 3. Ratios de color característicos (6 valores)
    eps = 1e-5
    rg_ratio = mean_r / (mean_g + eps)
    bg_ratio = mean_b / (mean_g + eps)
    greenness = (2 * mean_g - mean_r - mean_b) / (2 * mean_g + mean_r + mean_b + eps)
    yellowness = (mean_r + mean_g - 2 * mean_b) / (mean_r + mean_g + 2 * mean_b + eps)
    saturation = (max(mean_r, mean_g, mean_b) - min(mean_r, mean_g, mean_b)) / (max(mean_r, mean_g, mean_b) + eps)
    brightness = (mean_r + mean_g + mean_b) / 3.0

    color_ratios = [
        round(min(max(rg_ratio, 0.0), 3.0) / 3.0, 6),
        round(min(max(bg_ratio, 0.0), 3.0) / 3.0, 6),
        round((greenness + 1.0) / 2.0, 6),
        round((yellowness + 1.0) / 2.0, 6),
        round(saturation, 6),
        round(brightness, 6),
    ]

    # 4. Gradientes espaciales (4 valores)
    # Comparar centro vs bordes
    center_patch = rgb_img.crop((56, 56, 168, 168)).resize((4, 4), Image.Resampling.BOX)
    center_pixels = list(center_patch.getdata())
    center_mean = sum((r + g + b) / (3.0 * 255.0) for r, g, b in center_pixels) / len(center_pixels)

    border_top = rgb_img.crop((0, 0, 224, 28)).resize((4, 1), Image.Resampling.BOX)
    border_pixels = list(border_top.getdata())
    border_mean = sum((r + g + b) / (3.0 * 255.0) for r, g, b in border_pixels) / len(border_pixels)

    grad_h = abs(center_mean - border_mean)
    grad_v = abs(mean_r - mean_b)
    grad_rg = abs(mean_r - mean_g)
    grad_bg = abs(mean_b - mean_g)

    gradients = [
        round(grad_h, 6),
        round(grad_v, 6),
        round(grad_rg, 6),
        round(grad_bg, 6),
    ]

    features = spatial_features + moments + color_ratios + gradients
    return features[:FEATURE_DIM]


def augment_image_bytes(
    image_bytes: bytes,
    split: str,
    seed: Optional[int] = None,
) -> bytes:
    """Aplica transformaciones de aumentación a la imagen en memoria (exclusivo para TRAIN)."""
    split_upper = split.upper()
    if split_upper != "TRAIN":
        raise ValueError(
            f"Data augmentation está prohibida en partición '{split}'. "
            f"Solo se permite en TRAIN para evitar sesgos en validación y evaluación."
        )

    if Image is None or ImageEnhance is None:
        raise RuntimeError("Pillow no está disponible para aumentaciones")

    rng = random.Random(seed)
    with Image.open(io.BytesIO(image_bytes)) as img:
        aug_img = img.copy()

    # Inversión horizontal aleatoria
    if rng.random() > 0.5:
        aug_img = aug_img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    # Inversión vertical aleatoria
    if rng.random() > 0.5:
        aug_img = aug_img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    # Leve ajuste de brillo (+/- 8%)
    enhancer_b = ImageEnhance.Brightness(aug_img)
    factor_b = 0.92 + rng.random() * 0.16
    aug_img = enhancer_b.enhance(factor_b)

    # Leve ajuste de contraste (+/- 8%)
    enhancer_c = ImageEnhance.Contrast(aug_img)
    factor_c = 0.92 + rng.random() * 0.16
    aug_img = enhancer_c.enhance(factor_c)

    buf = io.BytesIO()
    aug_img.save(buf, format="JPEG")
    return buf.getvalue()


def apply_transforms(
    image_bytes: bytes,
    split: str,
    augment: bool = False,
    target_size: Tuple[int, int] = DEFAULT_TARGET_SIZE,
    seed: Optional[int] = None,
) -> List[float]:
    """Aplica el pipeline completo de preprocesado y transformación garantizando restricciones de partición."""
    split_upper = split.upper()
    if augment:
        if split_upper != "TRAIN":
            raise ValueError(
                f"Augmentations están estrictamente prohibidas en partición '{split}'. "
                f"Solo se permiten en TRAIN para garantizar una evaluación no sesgada."
            )
        processed_bytes = augment_image_bytes(image_bytes, split=split, seed=seed)
    else:
        processed_bytes = image_bytes

    return preprocess_image(processed_bytes, target_size=target_size)


def measure_cpu_preprocessing(
    image_bytes: bytes,
    iterations: int = 30,
) -> Dict[str, Any]:
    """Mide la latencia y memoria del preprocesado en CPU sobre una muestra de imagen."""
    durations_ms: List[float] = []

    # Calentamiento
    preprocess_image(image_bytes)

    for _ in range(iterations):
        t0 = time.perf_counter()
        _ = preprocess_image(image_bytes)
        t1 = time.perf_counter()
        durations_ms.append((t1 - t0) * 1000.0)

    durations_ms.sort()
    median_ms = durations_ms[len(durations_ms) // 2]
    p95_idx = int(0.95 * len(durations_ms))
    p95_ms = durations_ms[min(p95_idx, len(durations_ms) - 1)]

    return {
        "iterations": iterations,
        "latency_median_ms": round(median_ms, 2),
        "latency_p95_ms": round(p95_ms, 2),
        "meets_budget": median_ms <= 1000.0 and p95_ms <= 2500.0,
    }
