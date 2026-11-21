"""Review package and safe publication through the existing admin API."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.publish_pilot_guidance import load_guidance, publish


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "docs/catalog/pilot-potato-guidance.v1.json"


class TestPilotGuidance(unittest.TestCase):
    def test_exact_scope_review_sources_and_general_content(self):
        package, digest = load_guidance(PACKAGE)
        self.assertEqual(len(digest), 64)
        self.assertEqual({row["problem_code"] for row in package["recommendations"]},
                         {"POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT"})
        self.assertEqual(package["reviewed_by"], "Responsable del proyecto AgroDiagnostico V1")
        for row in package["recommendations"]:
            text = " ".join([row["summary"], *row["cultural_practices"],
                             *row["preventive_measures"]]).lower()
            for term in ("orientación visual", "confirme", "otras plantas cercanas",
                         "evolucionan", "semilla sana", "residuos vegetales",
                         "rotación", "malezas", "riego", "herramientas", "senasa"):
                self.assertIn(term, text)
            self.assertNotIn("fungicida", text)
        late = next(row for row in package["recommendations"]
                    if row["problem_code"] == "POTATO_LATE_BLIGHT")
        text = " ".join(late["cultural_practices"] + late["preventive_measures"])
        for term in ("manejo integrado", "variedades", "consulta técnica temprana"):
            self.assertIn(term, text)

    def test_rejects_chemical_instructions_and_unreviewed_package(self):
        package = json.loads(PACKAGE.read_text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guidance.json"
            package["recommendations"][0]["summary"] += " Aplicar fungicida X."
            path.write_text(json.dumps(package), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "GUIDANCE_TREATMENT_NOT_ALLOWED"):
                load_guidance(path)
            package["recommendations"][0]["summary"] = "Orientación visual."
            package["review_reference"] = ""
            path.write_text(json.dumps(package), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "GUIDANCE_REVIEW_MISSING"):
                load_guidance(path)

    def test_dry_run_never_posts_and_apply_uses_admin_api(self):
        package, _ = load_guidance(PACKAGE)
        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "token"
            token_file.write_text("private-test-token", encoding="utf-8")
            token_file.chmod(0o600)
            calls = []

            def fake_request(_base, path, _token, payload=None):
                calls.append((path, payload))
                if payload is None:
                    return 200, {"items": []}
                return 201, {**payload, "version": 1}

            with patch("scripts.publish_pilot_guidance._request", side_effect=fake_request):
                dry = publish("http://127.0.0.1:8080", token_file, package, False)
                self.assertEqual([row["action"] for row in dry], ["DRY_RUN", "DRY_RUN"])
                self.assertTrue(all(payload is None for _path, payload in calls))
                calls.clear()
                applied = publish("http://127.0.0.1:8080", token_file, package, True)
                self.assertEqual([row["action"] for row in applied], ["CREATED", "CREATED"])
                self.assertEqual(sum(payload is not None for _path, payload in calls), 2)
