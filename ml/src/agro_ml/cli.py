"""Interfaz de línea de comandos (CLI) agro-ml para CPU."""
import argparse
import csv
import json
from pathlib import Path
import sys

from agro_ml.calibration.calibrator import PlattCalibrator
from agro_ml.config import ModelConfig
from agro_ml.data.partitioning import (
    seal_test_partitions,
    verify_partition_leakage,
    verify_test_partition_seal,
)
from agro_ml.evaluation.freezing import (
    TestEvaluationBlockedError,
    authorize_test_evaluation,
    freeze_release_candidate,
)
from agro_ml.evaluation.metrics import generate_evaluation_report
from agro_ml.models.architectures import CLASS_MAPPING, CPUClassifier
from agro_ml.models.provenance import BASE_ARCHITECTURES, verify_weights_digest
from agro_ml.packaging.bundle import (
    build_model_bundle,
    build_publication_policy,
    load_model_bundle,
    verify_dual_crop_coverage,
)


def cmd_train(args):
    """Refuse release operations until the real pipeline and G0/G1 exist."""
    print("ML_PIPELINE_NOT_READY: train requiere pipeline real implementado, "
          "datos admitidos y protocolo aprobado. No se generan artefactos de éxito.",
          file=sys.stderr)
    return 2


def cmd_calibrate(args):
    """Refuse release operations until the real pipeline and G0/G1 exist."""
    print("ML_PIPELINE_NOT_READY: calibrate requiere pipeline real implementado, "
          "datos admitidos y protocolo aprobado. No se generan artefactos de éxito.",
          file=sys.stderr)
    return 2


def cmd_freeze(args):
    """Refuse release operations until the real pipeline and G0/G1 exist."""
    print("ML_PIPELINE_NOT_READY: freeze requiere pipeline real implementado, "
          "datos admitidos y protocolo aprobado. No se generan artefactos de éxito.",
          file=sys.stderr)
    return 2


def cmd_evaluate(args):
    """Refuse release operations until the real pipeline and G0/G1 exist."""
    print("ML_PIPELINE_NOT_READY: evaluate requiere pipeline real implementado, "
          "datos admitidos y protocolo aprobado. No se generan artefactos de éxito.",
          file=sys.stderr)
    return 2


def cmd_package(args):
    """Refuse release operations until the real pipeline and G0/G1 exist."""
    print("ML_PIPELINE_NOT_READY: package requiere pipeline real implementado, "
          "datos admitidos y protocolo aprobado. No se generan artefactos de éxito.",
          file=sys.stderr)
    return 2


def cmd_verify(args):
    """Do not mistake readable JSON for a verified release."""
    print("ML_PIPELINE_NOT_READY: verify requiere validar esquema, pesos, "
          "checksums y evidencia G2 con un runtime real.", file=sys.stderr)
    return 2


def cmd_partition(args):
    """Verifica ausencia de fugas y genera sello de TEST/EXTERNAL."""
    manifest_path = Path(args.manifest)
    print(f"[agro-ml partition] Validando aislamiento y sellando particiones en {manifest_path}...")
    records = []
    with manifest_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            records.append(r)

    verify_partition_leakage(records)
    print("  ✓ Cero fugas en los 6 pares de particiones (TRAIN, VAL, TEST, EXTERNAL).")

    seal_out = Path(args.output_seal or "ml/manifests/test_external_seal.v1.json")
    seal = seal_test_partitions(records, seal_out)
    print(f"  ✓ TEST sellado exitosamente ({seal.test_count} muestras). Hash: {seal.test_seal[:16]}...")
    if seal.external_seal:
        print(f"  ✓ EXTERNAL sellado ({seal.external_count} muestras).")
    else:
        print("  ℹ EXTERNAL no disponible (0 muestras).")
    return 0


def cmd_verify_seal(args):
    """Verifica si la partición TEST actual coincide con el sello congelado."""
    manifest_path = Path(args.manifest)
    seal_path = Path(args.seal)
    print(f"[agro-ml verify-seal] Verificando {manifest_path} contra {seal_path}...")
    records = []
    with manifest_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            records.append(r)

    verify_test_partition_seal(records, seal_path)
    print("  ✓ Sello de TEST íntegro y verificado. Sin alteraciones detectadas.")
    return 0


def main():
    parser = argparse.ArgumentParser(prog="agro-ml", description="Herramientas reproducibles ML para AgroDiagnóstico V1")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # train
    p_train = subparsers.add_parser("train", help="Entrenar modelo en CPU")
    p_train.add_argument("--config", required=True, help="Ruta al archivo JSON de configuración")
    p_train.add_argument("--output-dir", default="ml/models", help="Directorio de salida para pesos")

    # calibrate
    p_calib = subparsers.add_parser("calibrate", help="Ajustar calibración escalar en VAL")
    p_calib.add_argument("--config", required=True, help="Ruta al archivo de configuración")
    p_calib.add_argument("--output", default="ml/models/calibration_params.json", help="Ruta de salida")

    # freeze
    p_freeze = subparsers.add_parser("freeze", help="Congelar modelo, calibración, umbrales y protocolo antes de TEST")
    p_freeze.add_argument("--config", required=True, help="Ruta al archivo de configuración")
    p_freeze.add_argument("--weights", required=True, help="Ruta al archivo de pesos")
    p_freeze.add_argument("--calibrator", help="Ruta a parámetros de calibración JSON")
    p_freeze.add_argument("--thresholds", help="Ruta a umbrales JSON")
    p_freeze.add_argument("--frozen-by", help="Responsable del congelamiento")
    p_freeze.add_argument("--output", default="ml/evaluation/candidate_freeze.v1.json", help="Ruta de salida del snapshot")

    # evaluate
    p_eval = subparsers.add_parser("evaluate", help="Evaluar modelo en TEST sellado")
    p_eval.add_argument("--config", required=True, help="Ruta al archivo de configuración")
    p_eval.add_argument("--freeze", help="Ruta al snapshot de congelamiento para control de acceso")
    p_eval.add_argument("--weights", help="Ruta al archivo de pesos actual")
    p_eval.add_argument("--calibrator", help="Ruta a parámetros de calibración actuales")
    p_eval.add_argument("--thresholds", help="Ruta a umbrales actuales")
    p_eval.add_argument("--test-manifest", help="Ruta al manifiesto TEST (opcional)")
    p_eval.add_argument("--output", default="ml/evaluation/eval_report.json", help="Ruta de reporte")

    # package
    p_pkg = subparsers.add_parser("package", help="Empaquetar bundle inmutable")
    p_pkg.add_argument("--config", required=True, help="Ruta al archivo de configuración")
    p_pkg.add_argument("--weights", required=True, help="Ruta al archivo de pesos")
    p_pkg.add_argument("--train-manifest", required=True, help="Manifiesto TRAIN")
    p_pkg.add_argument("--val-manifest", required=True, help="Manifiesto VAL")
    p_pkg.add_argument("--test-manifest", required=True, help="Manifiesto TEST")
    p_pkg.add_argument("--output", required=True, help="Ruta del bundle JSON de salida")

    # verify
    p_ver = subparsers.add_parser("verify", help="Verificar procedencia e integridad de bundle")
    p_ver.add_argument("--bundle", required=True, help="Ruta al bundle JSON")

    # partition
    p_part = subparsers.add_parser("partition", help="Verificar fugas de partición y sellar TEST")
    p_part.add_argument("--manifest", required=True, help="Ruta al CSV de particiones")
    p_part.add_argument("--output-seal", default="ml/manifests/test_external_seal.v1.json", help="Ruta de salida del sello")

    # verify-seal
    p_vseal = subparsers.add_parser("verify-seal", help="Verificar sello inmutable de TEST")
    p_vseal.add_argument("--manifest", required=True, help="Ruta al CSV de particiones")
    p_vseal.add_argument("--seal", required=True, help="Ruta al archivo de sello JSON")

    args = parser.parse_args()
    cmds = {
        "train": cmd_train,
        "calibrate": cmd_calibrate,
        "freeze": cmd_freeze,
        "evaluate": cmd_evaluate,
        "package": cmd_package,
        "verify": cmd_verify,
        "partition": cmd_partition,
        "verify-seal": cmd_verify_seal,
    }
    return cmds[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
