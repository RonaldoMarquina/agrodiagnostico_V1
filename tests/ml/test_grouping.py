"""Pruebas unitarias para detección de duplicados, candidatos visuales y linaje de grupos."""
import io
import json
from pathlib import Path
import tempfile
import unittest

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    Image = None  # type: ignore
    HAS_PIL = False

from agro_ml.data.grouping import (
    compute_dhash,
    hamming_distance,
    DisjointSet,
    GroupLineageBuilder,
)


def make_test_image(pattern: str, size=(64, 64)):
    """Crea una imagen sintética PIL según un patrón simple."""
    img = Image.new("RGB", size)
    pixels = img.load()
    w, h = size
    for y in range(h):
        for x in range(w):
            if pattern == "horizontal_gradient":
                val = int(255 * (x / w))
                pixels[x, y] = (val, val, val)
            elif pattern == "vertical_gradient":
                val = int(255 * (y / h))
                pixels[x, y] = (val, val, val)
            elif pattern == "reversed_gradient":
                val = 255 - int(255 * (x / w))
                pixels[x, y] = (val, val, val)
            elif pattern == "checkerboard":
                val = 255 if ((x // 8) + (y // 8)) % 2 == 0 else 0
                pixels[x, y] = (val, val, val)
            elif pattern == "uniform_light":
                pixels[x, y] = (200, 200, 200)
            elif pattern == "uniform_dark":
                pixels[x, y] = (30, 30, 30)
            else:
                pixels[x, y] = (128, 128, 128)
    return img


@unittest.skipUnless(HAS_PIL, "Pillow (PIL) no disponible en este entorno")
class TestGroupingAndDuplicates(unittest.TestCase):
    def test_disjoint_set_union_find(self):
        ds = DisjointSet()
        ds.union("a", "b")
        ds.union("b", "c")
        ds.union("d", "e")

        self.assertEqual(ds.find("a"), ds.find("c"))
        self.assertEqual(ds.find("a"), ds.find("b"))
        self.assertEqual(ds.find("d"), ds.find("e"))
        self.assertNotEqual(ds.find("a"), ds.find("d"))

    def test_dhash_and_hamming_distance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            img1_path = base / "grad1.png"
            img2_path = base / "grad2.png"
            img3_path = base / "vert.png"

            # grad1 y grad2 son casi idénticas (grad2 con leve ruido)
            im1 = make_test_image("horizontal_gradient")
            im1.save(img1_path)

            im2 = make_test_image("horizontal_gradient")
            # Leve perturbación
            pix2 = im2.load()
            pix2[10, 10] = (255, 255, 255)
            im2.save(img2_path)

            # grad3 es gradiente inverso (muy diferente)
            im3 = make_test_image("reversed_gradient")
            im3.save(img3_path)

            h1 = compute_dhash(img1_path)
            h2 = compute_dhash(img2_path)
            h3 = compute_dhash(img3_path)

            dist_similar = hamming_distance(h1, h2)
            dist_different = hamming_distance(h1, h3)

            self.assertLessEqual(dist_similar, 2)
            self.assertGreater(dist_different, 10)

    def test_exact_duplicates_across_sources_share_group(self):
        builder = GroupLineageBuilder()
        builder.register_image(
            image_id="pv_001",
            sha256="hash_exact_match_12345",
            source="plantvillage",
        )
        builder.register_image(
            image_id="pdoc_999",
            sha256="hash_exact_match_12345",
            source="plantdoc",
        )
        builder.register_image(
            image_id="pv_002",
            sha256="different_hash_67890",
            source="plantvillage",
        )

        groups = builder.compute_split_groups()
        self.assertEqual(groups["pv_001"], groups["pdoc_999"])
        self.assertNotEqual(groups["pv_001"], groups["pv_002"])
        self.assertEqual(len(builder.exact_duplicate_pairs), 1)

    def test_metadata_plant_session_grouping(self):
        builder = GroupLineageBuilder()
        builder.register_image(
            image_id="img_a",
            sha256="hash_a",
            source="plantvillage",
            source_plant_id="plant_42",
        )
        builder.register_image(
            image_id="img_b",
            sha256="hash_b",
            source="plantvillage",
            source_plant_id="plant_42",
        )
        builder.register_image(
            image_id="img_c",
            sha256="hash_c",
            source="plantvillage",
            source_plant_id="plant_99",
        )

        groups = builder.compute_split_groups()
        self.assertEqual(groups["img_a"], groups["img_b"])
        self.assertNotEqual(groups["img_a"], groups["img_c"])

    def test_visual_near_duplicates_grouped(self):
        builder = GroupLineageBuilder(hamming_threshold=4)
        # dhash con distancia 2
        hash_base = 0b1010101010101010
        hash_near = 0b1010101010101001  # 1 bit de diferencia

        builder.register_image(
            image_id="img_v1",
            sha256="hash_v1",
            source="plantvillage",
            dhash_value=hash_base,
        )
        builder.register_image(
            image_id="img_v2",
            sha256="hash_v2",
            source="plantvillage",
            dhash_value=hash_near,
        )

        groups = builder.compute_split_groups()
        self.assertEqual(groups["img_v1"], groups["img_v2"])
        self.assertEqual(len(builder.visual_candidate_pairs), 1)

    def test_cross_source_near_duplicate_uncertainty_warning(self):
        builder = GroupLineageBuilder(hamming_threshold=4)
        hash_base = 0b1111000011110000
        hash_near = 0b1111000011110001

        builder.register_image(
            image_id="pv_cross",
            sha256="hash_pv",
            source="plantvillage",
            dhash_value=hash_base,
        )
        builder.register_image(
            image_id="pdoc_cross",
            sha256="hash_pdoc",
            source="plantdoc",
            dhash_value=hash_near,
        )

        groups = builder.compute_split_groups()
        self.assertEqual(groups["pv_cross"], groups["pdoc_cross"])
        self.assertTrue(any("Alerta: Casi duplicado visual entre fuentes distintas" in w for w in builder.uncertainty_warnings))

    def test_conservative_fallback_by_source(self):
        builder = GroupLineageBuilder()
        builder.register_image(
            image_id="unknown_1",
            sha256="h1",
            source="field_source_x",
        )
        builder.register_image(
            image_id="unknown_2",
            sha256="h2",
            source="field_source_x",
        )
        builder.register_image(
            image_id="other_source_1",
            sha256="h3",
            source="field_source_y",
        )

        groups = builder.compute_split_groups(conservative_by_source_fallback=True)
        self.assertEqual(groups["unknown_1"], groups["unknown_2"])
        self.assertNotEqual(groups["unknown_1"], groups["other_source_1"])

    def test_export_report_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_file = Path(temp_dir) / "duplicates_report.json"
            builder = GroupLineageBuilder()
            builder.register_image("i1", "hash_same", "pv")
            builder.register_image("i2", "hash_same", "pdoc")
            builder.export_report_json(out_file)

            self.assertTrue(out_file.is_file())
            data = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], 2)
            self.assertEqual(data["report"]["total_images"], 2)
            self.assertEqual(data["report"]["exact_duplicate_pairs"], 1)


if __name__ == "__main__":
    unittest.main()
