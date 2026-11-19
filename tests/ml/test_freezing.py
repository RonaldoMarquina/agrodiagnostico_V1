"""Pruebas unitarias para congelamiento de candidato y control de acceso previo a TEST."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from agro_ml.evaluation.freezing import (
    FrozenCandidateTamperedError,
    TestEvaluationBlockedError,
    authorize_test_evaluation,
    freeze_release_candidate,
    verify_frozen_candidate,
)


class TestCandidateFreezing(unittest.TestCase):
    def setUp(self):
        self.calib_params = {
            "POTATO_EARLY_BLIGHT": {"slope": 1.25, "intercept": -0.15},
            "MAIZE_COMMON_RUST": {"slope": 1.15, "intercept": -0.12},
        }
        self.thresholds = {
            "POTATO_EARLY_BLIGHT": 0.70,
            "MAIZE_COMMON_RUST": 0.65,
        }
        self.protocol_ver = "1.0.0"

    def test_freeze_and_verify_candidate_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            weights_file = base / "weights.json"
            weights_file.write_text('{"weights": [0.1, 0.2]}', encoding="utf-8")
            snap_file = base / "freeze_snapshot.json"

            snapshot = freeze_release_candidate(
                model_id="test-model",
                model_version="1.0.0",
                dataset_version="2.0.0",
                architecture="mobilenet_v3_small",
                weights_path=weights_file,
                calibration_params=self.calib_params,
                thresholds=self.thresholds,
                protocol_version=self.protocol_ver,
                frozen_by="Ronald Omar",
                output_freeze_path=snap_file,
            )

            self.assertTrue(snap_file.is_file())
            self.assertEqual(snapshot.status, "LOCKED_BEFORE_TEST")
            self.assertEqual(len(snapshot.freeze_digest), 64)

            # Verificación positiva y autorización
            authorized = authorize_test_evaluation(
                snapshot_path=snap_file,
                current_weights_path=weights_file,
                current_calibration_params=self.calib_params,
                current_thresholds=self.thresholds,
                current_protocol_version=self.protocol_ver,
            )
            self.assertTrue(authorized)

    def test_tamper_detection_on_weights_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            weights_file = base / "weights.json"
            weights_file.write_text('{"weights": [0.1, 0.2]}', encoding="utf-8")
            snap_file = base / "freeze_snapshot.json"

            freeze_release_candidate(
                model_id="test-model",
                model_version="1.0.0",
                dataset_version="2.0.0",
                architecture="mobilenet_v3_small",
                weights_path=weights_file,
                calibration_params=self.calib_params,
                thresholds=self.thresholds,
                protocol_version=self.protocol_ver,
                frozen_by="Ronald Omar",
                output_freeze_path=snap_file,
            )

            # Modificar los pesos después del congelamiento
            weights_file.write_text('{"weights": [0.1, 0.25]}', encoding="utf-8")

            with self.assertRaises(TestEvaluationBlockedError):
                authorize_test_evaluation(
                    snapshot_path=snap_file,
                    current_weights_path=weights_file,
                    current_calibration_params=self.calib_params,
                    current_thresholds=self.thresholds,
                    current_protocol_version=self.protocol_ver,
                )

    def test_tamper_detection_on_calibration_or_threshold_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            weights_file = base / "weights.json"
            weights_file.write_text('{"weights": [0.1, 0.2]}', encoding="utf-8")
            snap_file = base / "freeze_snapshot.json"

            freeze_release_candidate(
                model_id="test-model",
                model_version="1.0.0",
                dataset_version="2.0.0",
                architecture="mobilenet_v3_small",
                weights_path=weights_file,
                calibration_params=self.calib_params,
                thresholds=self.thresholds,
                protocol_version=self.protocol_ver,
                frozen_by="Ronald Omar",
                output_freeze_path=snap_file,
            )

            # Caso A: Modificar calibración
            bad_calib = copy.deepcopy(self.calib_params)
            bad_calib["POTATO_EARLY_BLIGHT"]["slope"] = 1.30
            with self.assertRaises(TestEvaluationBlockedError):
                authorize_test_evaluation(
                    snapshot_path=snap_file,
                    current_weights_path=weights_file,
                    current_calibration_params=bad_calib,
                    current_thresholds=self.thresholds,
                    current_protocol_version=self.protocol_ver,
                )

            # Caso B: Modificar umbrales
            bad_thresh = copy.deepcopy(self.thresholds)
            bad_thresh["POTATO_EARLY_BLIGHT"] = 0.60
            with self.assertRaises(TestEvaluationBlockedError):
                authorize_test_evaluation(
                    snapshot_path=snap_file,
                    current_weights_path=weights_file,
                    current_calibration_params=self.calib_params,
                    current_thresholds=bad_thresh,
                    current_protocol_version=self.protocol_ver,
                )


if __name__ == "__main__":
    unittest.main()
