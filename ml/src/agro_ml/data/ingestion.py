"""Módulo de ingestión segura de imágenes desde fuentes admitidas.

Aplica validación de límites de archivo, resolución segura de rutas contra traversal,
verificación de decodificación y cálculo de hash SHA-256 sobre bytes crudos.
Los descartes se registran en una lista de cuarentena con motivo y timestamp.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore


MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB
MIN_FILE_SIZE_BYTES = 100  # Archivos vacíos o ínfimos no son fotos válidas
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


class IngestionError(Exception):
    """Error base de ingestión."""
    pass


class PathTraversalError(IngestionError):
    """Intento de path traversal o escape del directorio raíz."""
    pass


class UnadmittedSourceError(IngestionError):
    """Fuente no admitida o con licencia no verificada."""
    pass


class InvalidImageBytesError(IngestionError):
    """Bytes corruptos, truncados o no decodificables."""
    pass


@dataclass
class QuarantineRecord:
    file_path: str
    source: str
    reason_code: str
    reason_detail: str
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sha256: Optional[str] = None
    file_size_bytes: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IngestedImageRecord:
    image_id: str
    sha256: str
    crop_code: str
    class_code: str
    source: str
    license: str
    capture_context: str
    label_quality: str
    split_group: str
    file_path: str
    width: int
    height: int
    format: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ImageIngestionService:
    def __init__(
        self,
        sources_doc: Optional[Dict[str, Any]] = None,
        label_mappings_doc: Optional[Dict[str, Any]] = None,
        taxonomy_doc: Optional[Dict[str, Any]] = None,
        max_file_size: int = MAX_FILE_SIZE_BYTES,
    ):
        self.sources_doc = sources_doc or {}
        self.label_mappings_doc = label_mappings_doc or {}
        self.taxonomy_doc = taxonomy_doc or {}
        self.max_file_size = max_file_size
        self.quarantine: List[QuarantineRecord] = []

        # Construir conjuntos de fuentes admitidas y mapeos
        self.eligible_sources: Dict[str, Dict[str, Any]] = {}
        self._load_eligible_sources()
        self.mappings_by_source_label: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._load_label_mappings()

    def _load_eligible_sources(self) -> None:
        sources_list = self.sources_doc.get("sources", [])
        for src in sources_list:
            sid = src.get("source_id")
            eligibility = src.get("eligibility")
            lic = src.get("license", {})
            status = lic.get("status")
            if eligibility == "ELIGIBLE" and status in ("VERIFIED_FOR_PROJECT", "SYNTHETIC_ONLY"):
                self.eligible_sources[sid] = src

    def _load_label_mappings(self) -> None:
        mappings_list = self.label_mappings_doc.get("mappings", [])
        for m in mappings_list:
            src = m.get("source")
            slabel = m.get("source_label")
            status = m.get("status")
            if src and slabel and status == "APPROVED":
                self.mappings_by_source_label[(src, slabel)] = m

    def check_path_safe(self, base_dir: Path, relative_path: str) -> Path:
        """Verifica que relative_path no escape de base_dir."""
        base_dir = base_dir.resolve()
        candidate = (base_dir / relative_path).resolve()
        try:
            if not candidate.is_relative_to(base_dir):
                raise PathTraversalError(
                    f"Ruta insegura: '{relative_path}' escapa del directorio base '{base_dir}'"
                )
        except AttributeError:
            # Fallback para Python < 3.9 (aunque usamos 3.12)
            if not str(candidate).startswith(str(base_dir)):
                raise PathTraversalError(
                    f"Ruta insegura: '{relative_path}' escapa del directorio base '{base_dir}'"
                )
        return candidate

    def ingest_single_image(
        self,
        base_dir: Path,
        relative_path: str,
        source: str,
        source_label: str,
        split_group: Optional[str] = None,
    ) -> Optional[IngestedImageRecord]:
        """Ingiere una imagen validando ruta, bytes, decodificación y mapeo.

        Si falla por alguna razón recuperable (corrupta, traversal, fuente no elegible,
        sin mapeo), registra en cuarentena y retorna None.
        """
        # 1. Validar fuente elegible
        if source not in self.eligible_sources:
            reason = f"Fuente '{source}' no es elegible o no tiene licencia verificada"
            self.quarantine.append(
                QuarantineRecord(
                    file_path=relative_path,
                    source=source,
                    reason_code="UNADMITTED_SOURCE",
                    reason_detail=reason,
                )
            )
            return None

        # 2. Validar seguridad de ruta
        try:
            safe_file_path = self.check_path_safe(base_dir, relative_path)
        except PathTraversalError as e:
            self.quarantine.append(
                QuarantineRecord(
                    file_path=relative_path,
                    source=source,
                    reason_code="PATH_TRAVERSAL_ATTEMPT",
                    reason_detail=str(e),
                )
            )
            return None

        if not safe_file_path.is_file():
            self.quarantine.append(
                QuarantineRecord(
                    file_path=relative_path,
                    source=source,
                    reason_code="FILE_NOT_FOUND",
                    reason_detail=f"Archivo no existe: {safe_file_path}",
                )
            )
            return None

        # 3. Validar extensión permitida
        if safe_file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
            self.quarantine.append(
                QuarantineRecord(
                    file_path=relative_path,
                    source=source,
                    reason_code="UNSUPPORTED_EXTENSION",
                    reason_detail=f"Extensión no permitida: {safe_file_path.suffix}",
                )
            )
            return None

        # 4. Validar tamaño de bytes
        file_size = safe_file_path.stat().st_size
        if file_size < MIN_FILE_SIZE_BYTES or file_size > self.max_file_size:
            self.quarantine.append(
                QuarantineRecord(
                    file_path=relative_path,
                    source=source,
                    reason_code="FILE_SIZE_LIMIT",
                    reason_detail=f"Tamaño de archivo fuera de límites: {file_size} bytes (min: {MIN_FILE_SIZE_BYTES}, max: {self.max_file_size})",
                    file_size_bytes=file_size,
                )
            )
            return None

        # 5. Leer bytes y calcular SHA-256
        raw_bytes = safe_file_path.read_bytes()
        digest = hashlib.sha256(raw_bytes).hexdigest().lower()

        # 6. Decodificar y verificar imagen
        if Image is None:
            raise IngestionError("Pillow (PIL) no está disponible en el entorno")

        try:
            with Image.open(safe_file_path) as img:
                img.verify()
            # Segunda apertura para obtener dimensiones y modo reales tras verify()
            with Image.open(safe_file_path) as img:
                width, height = img.size
                img_format = img.format or "UNKNOWN"
                if width <= 0 or height <= 0:
                    raise ValueError(f"Dimensiones inválidas: {width}x{height}")
                # Forzar carga de píxeles para detectar truncamientos
                img.load()
        except Exception as e:
            self.quarantine.append(
                QuarantineRecord(
                    file_path=relative_path,
                    source=source,
                    reason_code="DECODE_ERROR",
                    reason_detail=f"Fallo al decodificar imagen: {e}",
                    sha256=digest,
                    file_size_bytes=file_size,
                )
            )
            return None

        # 7. Validar mapeo de etiqueta
        mapping_key = (source, source_label)
        if mapping_key not in self.mappings_by_source_label:
            self.quarantine.append(
                QuarantineRecord(
                    file_path=relative_path,
                    source=source,
                    reason_code="UNMAPPED_LABEL",
                    reason_detail=f"Etiqueta '{source_label}' de fuente '{source}' no tiene mapeo aprobado",
                    sha256=digest,
                    file_size_bytes=file_size,
                )
            )
            return None

        mapping = self.mappings_by_source_label[mapping_key]
        class_code = mapping["class_code"]
        crop_code = "POTATO" if class_code.startswith("POTATO_") else "MAIZE"
        source_info = self.eligible_sources[source]
        license_id = source_info.get("license", {}).get("identifier", "UNKNOWN")
        capture_context = source_info.get("capture_context", "CONTROLLED_LEAF")

        # split_group por defecto si no se especificó: prefijo o nombre de archivo
        group = split_group or f"{source}_{safe_file_path.stem}"

        # image_id: identificador determinista y opaco
        image_id = f"{source}_{digest[:16]}"

        return IngestedImageRecord(
            image_id=image_id,
            sha256=digest,
            crop_code=crop_code,
            class_code=class_code,
            source=source,
            license=license_id,
            capture_context=capture_context,
            label_quality="REVIEWED",
            split_group=group,
            file_path=str(safe_file_path),
            width=width,
            height=height,
            format=img_format,
        )

    def export_quarantine(self, output_path: Path) -> None:
        """Exporta el registro de cuarentena a formato JSON estructurado."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        records = [r.to_dict() for r in self.quarantine]
        doc = {
            "schema_version": 2,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "quarantined_total": len(records),
            "records": records,
        }
        output_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
