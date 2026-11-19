"""Detección de duplicados exactos, candidatos visuales y asignación global de split_group.

Implementa:
- Detección de duplicados exactos por hash de bytes SHA-256.
- Detección de casi duplicados visuales mediante hashing perceptual (dHash) y distancia Hamming.
- Constructor de linaje y agrupamiento global (Union-Find) que unifica duplicados, candidatos visuales y metadatos de planta/sesión.
- Agrupamiento conservador por fuente/lote ante falta de identificadores finos.
- Reporte detallado de incertidumbre y candidatos visuales sin declarar independencia automática.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore


DHASH_SIZE = 8
DEFAULT_HAMMING_THRESHOLD = 6


def compute_dhash(image_path: Path, hash_size: int = DHASH_SIZE) -> int:
    """Calcula el hash de diferencia (dHash) de 64 bits para una imagen."""
    if Image is None:
        raise RuntimeError("Pillow no está disponible para cálculo de dHash")

    with Image.open(image_path) as img:
        # Convertir a escala de grises y redimensionar a (hash_size + 1, hash_size)
        gray = img.convert("L").resize(
            (hash_size + 1, hash_size),
            resample=Image.Resampling.BILINEAR if hasattr(Image, "Resampling") else Image.BILINEAR,  # type: ignore
        )
        pixels = list(gray.getdata())

    diff_bits = 0
    width = hash_size + 1
    for row in range(hash_size):
        row_offset = row * width
        for col in range(hash_size):
            left_pixel = pixels[row_offset + col]
            right_pixel = pixels[row_offset + col + 1]
            diff_bits = (diff_bits << 1) | (1 if left_pixel > right_pixel else 0)

    return diff_bits


def hamming_distance(hash1: int, hash2: int) -> int:
    """Calcula la distancia de Hamming (número de bits diferentes) entre dos hashes."""
    return bin(hash1 ^ hash2).count("1")


class DisjointSet:
    """Estructura de conjuntos disjuntos (Union-Find) con compresión de camino."""
    def __init__(self):
        self.parent: Dict[str, str] = {}
        self.rank: Dict[str, int] = {}

    def find(self, item: str) -> str:
        if item not in self.parent:
            self.parent[item] = item
            self.rank[item] = 0
            return item
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, item1: str, item2: str) -> None:
        root1 = self.find(item1)
        root2 = self.find(item2)
        if root1 == root2:
            return
        if self.rank[root1] < self.rank[root2]:
            self.parent[root1] = root2
        elif self.rank[root1] > self.rank[root2]:
            self.parent[root2] = root1
        else:
            self.parent[root2] = root1
            self.rank[root1] += 1


@dataclass
class DuplicatePair:
    image_id_a: str
    image_id_b: str
    source_a: str
    source_b: str
    duplicate_type: str  # EXACT_SHA256, VISUAL_NEAR_DUPLICATE, METADATA_SESSION
    similarity_score: float  # 1.0 para exacto, 1.0 - (dist / 64) para visual
    hamming_distance: Optional[int] = None
    note: str = ""


@dataclass
class GroupingReport:
    total_images: int
    total_groups: int
    exact_duplicate_pairs: int
    visual_candidate_pairs: int
    uncertainty_warnings: List[str]
    clusters_larger_than_one: int
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GroupLineageBuilder:
    def __init__(self, hamming_threshold: int = DEFAULT_HAMMING_THRESHOLD):
        self.hamming_threshold = hamming_threshold
        self.ds = DisjointSet()
        self.images_metadata: Dict[str, Dict[str, Any]] = {}
        self.exact_duplicate_pairs: List[DuplicatePair] = []
        self.visual_candidate_pairs: List[DuplicatePair] = []
        self.uncertainty_warnings: List[str] = []

    def register_image(
        self,
        image_id: str,
        sha256: str,
        source: str,
        file_path: Optional[str] = None,
        source_plant_id: Optional[str] = None,
        session_id: Optional[str] = None,
        dhash_value: Optional[int] = None,
    ) -> None:
        """Registra una imagen con sus atributos para deduplicación y linaje."""
        self.ds.find(image_id)  # inicializa en disjoint set
        self.images_metadata[image_id] = {
            "image_id": image_id,
            "sha256": sha256,
            "source": source,
            "file_path": file_path,
            "source_plant_id": source_plant_id,
            "session_id": session_id,
            "dhash": dhash_value,
        }

    def detect_exact_duplicates(self) -> None:
        """Agrupa imágenes con idéntico SHA-256."""
        by_hash: Dict[str, List[str]] = {}
        for img_id, meta in self.images_metadata.items():
            h = meta["sha256"]
            by_hash.setdefault(h, []).append(img_id)

        for h, group in by_hash.items():
            if len(group) > 1:
                first = group[0]
                for other in group[1:]:
                    self.ds.union(first, other)
                    self.exact_duplicate_pairs.append(
                        DuplicatePair(
                            image_id_a=first,
                            image_id_b=other,
                            source_a=self.images_metadata[first]["source"],
                            source_b=self.images_metadata[other]["source"],
                            duplicate_type="EXACT_SHA256",
                            similarity_score=1.0,
                            hamming_distance=0,
                            note=f"Coincidencia exacta de bytes SHA-256: {h[:16]}...",
                        )
                    )

    def detect_metadata_groups(self) -> None:
        """Agrupa imágenes de la misma planta, sesión o lote reportado."""
        by_plant: Dict[Tuple[str, str], List[str]] = {}
        by_session: Dict[Tuple[str, str], List[str]] = {}

        for img_id, meta in self.images_metadata.items():
            src = meta["source"]
            plant = meta.get("source_plant_id")
            sess = meta.get("session_id")
            if plant:
                by_plant.setdefault((src, plant), []).append(img_id)
            if sess:
                by_session.setdefault((src, sess), []).append(img_id)

        for (src, plant), group in by_plant.items():
            if len(group) > 1:
                first = group[0]
                for other in group[1:]:
                    self.ds.union(first, other)

        for (src, sess), group in by_session.items():
            if len(group) > 1:
                first = group[0]
                for other in group[1:]:
                    self.ds.union(first, other)

    def detect_visual_near_duplicates(self) -> None:
        """Compara dHashes entre imágenes para detectar casi duplicados visuales."""
        items = list(self.images_metadata.values())
        n = len(items)
        for i in range(n):
            hash_a = items[i].get("dhash")
            if hash_a is None:
                continue
            id_a = items[i]["image_id"]
            src_a = items[i]["source"]

            for j in range(i + 1, n):
                hash_b = items[j].get("dhash")
                if hash_b is None:
                    continue
                id_b = items[j]["image_id"]
                src_b = items[j]["source"]

                dist = hamming_distance(hash_a, hash_b)
                if dist <= self.hamming_threshold:
                    sim = 1.0 - (dist / 64.0)
                    self.ds.union(id_a, id_b)
                    pair = DuplicatePair(
                        image_id_a=id_a,
                        image_id_b=id_b,
                        source_a=src_a,
                        source_b=src_b,
                        duplicate_type="VISUAL_NEAR_DUPLICATE",
                        similarity_score=round(sim, 4),
                        hamming_distance=dist,
                        note=f"Distancia Hamming dHash {dist} <= {self.hamming_threshold}",
                    )
                    self.visual_candidate_pairs.append(pair)

                    if src_a != src_b:
                        self.uncertainty_warnings.append(
                            f"Alerta: Casi duplicado visual entre fuentes distintas: {id_a} ({src_a}) y {id_b} ({src_b}) con distancia {dist}. Agrupadas conservadoramente."
                        )

    def compute_split_groups(self, conservative_by_source_fallback: bool = False) -> Dict[str, str]:
        """Calcula el split_group final determinista para cada imagen.

        Si conservative_by_source_fallback=True y no hay identificadores de planta/sesión,
        agrupa todas las imágenes de la misma fuente juntas.
        """
        # Ejecutar deduplicaciones y agrupamiento
        self.detect_exact_duplicates()
        self.detect_metadata_groups()
        self.detect_visual_near_duplicates()

        # Si se solicita agrupamiento conservador por falta de metadatos
        if conservative_by_source_fallback:
            by_src: Dict[str, List[str]] = {}
            for img_id, meta in self.images_metadata.items():
                if not meta.get("source_plant_id") and not meta.get("session_id"):
                    by_src.setdefault(meta["source"], []).append(img_id)
            for src, ids in by_src.items():
                if len(ids) > 1:
                    first = ids[0]
                    for other in ids[1:]:
                        self.ds.union(first, other)
                    self.uncertainty_warnings.append(
                        f"Agrupamiento conservador por fuente aplicado a {len(ids)} imágenes de '{src}' por ausencia de metadatos de planta/sesión."
                    )

        # Mapear cada imagen a su raíz de grupo
        groups: Dict[str, str] = {}
        for img_id in self.images_metadata:
            root_id = self.ds.find(img_id)
            # El split_group determinista es grp_<root_id>
            groups[img_id] = f"grp_{root_id}"
        return groups

    def generate_report(self) -> GroupingReport:
        """Genera reporte estadístico del proceso de agrupamiento."""
        groups = self.compute_split_groups()
        by_grp: Dict[str, List[str]] = {}
        for img_id, grp in groups.items():
            by_grp.setdefault(grp, []).append(img_id)

        clusters_gt_1 = sum(1 for grp, members in by_grp.items() if len(members) > 1)

        return GroupingReport(
            total_images=len(self.images_metadata),
            total_groups=len(by_grp),
            exact_duplicate_pairs=len(self.exact_duplicate_pairs),
            visual_candidate_pairs=len(self.visual_candidate_pairs),
            uncertainty_warnings=self.uncertainty_warnings,
            clusters_larger_than_one=clusters_gt_1,
        )

    def export_report_json(self, output_path: Path) -> None:
        """Exporta el reporte de duplicados y candidatos visuales a JSON."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report = self.generate_report()
        doc = {
            "schema_version": 2,
            "report": report.to_dict(),
            "exact_duplicate_pairs": [asdict(p) for p in self.exact_duplicate_pairs],
            "visual_candidate_pairs": [asdict(p) for p in self.visual_candidate_pairs],
        }
        output_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
