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


def cmd_smoke_train(args):
    """Entrena y recarga pesos tensoriales reales con fixtures geométricos."""
    from agro_ml.smoke import run_cpu_smoke
    try:
        report = run_cpu_smoke(Path(args.config), args.architecture, Path(args.output_dir))
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"CPU_SMOKE_FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


def cmd_smoke_infer(args):
    """Infiere únicamente sobre un fixture generado, nunca sobre fotos de usuario."""
    from agro_ml.smoke import fixture_image, infer_fixture_checkpoint
    try:
        label = None if args.fixture_label == "OTHER" else int(args.fixture_label)
        result = infer_fixture_checkpoint(Path(args.checkpoint), fixture_image(label, variant=1))
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        print(f"CPU_SMOKE_FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "TECHNICAL_FIXTURE_ONLY", "prediction": result}, sort_keys=True))
    return 0


def cmd_smoke_compare(args):
    """Compara ambos modelos exclusivamente sobre VAL_FIXTURE."""
    from agro_ml.smoke import compare_fixture_models
    try:
        report = compare_fixture_models(Path(args.joint), Path(args.hierarchical))
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        print(f"CPU_SMOKE_FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


def cmd_smoke_evaluate(args):
    """Genera reporte técnico sobre VAL_FIXTURE; no abre TEST."""
    from agro_ml.smoke import evaluate_fixture_checkpoint
    try:
        report = evaluate_fixture_checkpoint(Path(args.checkpoint))
        with Path(args.output).open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        print(f"CPU_SMOKE_FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


def cmd_smoke_package(args):
    """Empaqueta un fixture técnico aparte del contrato de release G2."""
    from agro_ml.smoke import package_fixture_checkpoint
    try:
        report = package_fixture_checkpoint(Path(args.checkpoint), Path(args.evaluation), Path(args.output))
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        print(f"CPU_SMOKE_FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


def cmd_cpu_train(args):
    """Entrena candidato CPU local; jamás lo convierte en release G2."""
    from agro_ml.cpu_candidate import train
    try:
        result = train(Path(args.config), Path(args.manifest), Path(args.images_root), Path(args.output_dir))
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        print(f"CPU_CANDIDATE_FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


def cmd_cpu_fixture_data(args):
    """Prepara datos gráficos locales sin fotos de terceros."""
    from agro_ml.cpu_candidate import write_fixture_manifests
    try:
        result = write_fixture_manifests(Path(args.output_dir))
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"CPU_CANDIDATE_FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


def cmd_cpu_evaluate_val(args):
    """Evalúa candidato solo en VAL explícita; jamás abre TEST."""
    from agro_ml.cpu_candidate import evaluate_val
    try:
        result = evaluate_val(Path(args.checkpoint), Path(args.train_manifest),
                              Path(args.val_manifest), Path(args.images_root), Path(args.output))
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        print(f"CPU_CANDIDATE_FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


def cmd_cpu_package_candidate(args):
    """Empaqueta candidato con reporte VAL; no cumple model-bundle G2."""
    from agro_ml.cpu_candidate import package_candidate
    try:
        result = package_candidate(Path(args.checkpoint), Path(args.evaluation), Path(args.output),
                                   Path(args.train_manifest), Path(args.val_manifest), Path(args.images_root))
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        print(f"CPU_CANDIDATE_FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


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

    p_smoke = subparsers.add_parser("smoke-train", help="Entrenamiento e inferencia CPU con fixtures, sin G0/G2")
    p_smoke.add_argument("--config", default="ml/configs/cpu-smoke.v1.json")
    p_smoke.add_argument("--architecture", required=True, choices=("mobilenet_v3_small", "resnet18_hierarchical"))
    p_smoke.add_argument("--output-dir", required=True)

    p_smoke_infer = subparsers.add_parser("smoke-infer", help="Inferencia sobre fixture gráfico, sin diagnóstico")
    p_smoke_infer.add_argument("--checkpoint", required=True)
    p_smoke_infer.add_argument("--fixture-label", required=True,
                               choices=tuple(str(index) for index in range(7)) + ("OTHER",))

    p_smoke_compare = subparsers.add_parser("smoke-compare", help="Comparación VAL_FIXTURE, sin selección de release")
    p_smoke_compare.add_argument("--joint", required=True, help="Checkpoint del clasificador conjunto")
    p_smoke_compare.add_argument("--hierarchical", required=True, help="Checkpoint de la alternativa jerárquica")

    p_smoke_evaluate = subparsers.add_parser("smoke-evaluate", help="Reporte VAL_FIXTURE, sin TEST ni G2")
    p_smoke_evaluate.add_argument("--checkpoint", required=True)
    p_smoke_evaluate.add_argument("--output", required=True)

    p_smoke_package = subparsers.add_parser("smoke-package", help="Archivo técnico FIXTURE_ONLY, no bundle G2")
    p_smoke_package.add_argument("--checkpoint", required=True)
    p_smoke_package.add_argument("--evaluation", required=True)
    p_smoke_package.add_argument("--output", required=True)

    p_cpu_train = subparsers.add_parser("cpu-train", help="Candidato CPU local desde manifiesto explícito")
    p_cpu_train.add_argument("--config", required=True)
    p_cpu_train.add_argument("--manifest", required=True, help="Manifiesto TRAIN local JSON")
    p_cpu_train.add_argument("--images-root", required=True, help="Raíz privada de imágenes locales")
    p_cpu_train.add_argument("--output-dir", required=True)

    p_cpu_fixture = subparsers.add_parser("cpu-fixture-data", help="Genera manifiestos e imágenes gráficas FIXTURE_ONLY")
    p_cpu_fixture.add_argument("--output-dir", required=True)

    p_cpu_eval = subparsers.add_parser("cpu-evaluate-val", help="Reporte de candidato solo en VAL")
    p_cpu_eval.add_argument("--checkpoint", required=True)
    p_cpu_eval.add_argument("--train-manifest", required=True)
    p_cpu_eval.add_argument("--val-manifest", required=True)
    p_cpu_eval.add_argument("--images-root", required=True)
    p_cpu_eval.add_argument("--output", required=True)

    p_cpu_package = subparsers.add_parser("cpu-package-candidate", help="Paquete de candidato sin aprobación G2")
    p_cpu_package.add_argument("--checkpoint", required=True)
    p_cpu_package.add_argument("--evaluation", required=True)
    p_cpu_package.add_argument("--train-manifest", required=True)
    p_cpu_package.add_argument("--val-manifest", required=True)
    p_cpu_package.add_argument("--images-root", required=True)
    p_cpu_package.add_argument("--output", required=True)

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
        "smoke-train": cmd_smoke_train,
        "smoke-infer": cmd_smoke_infer,
        "smoke-compare": cmd_smoke_compare,
        "smoke-evaluate": cmd_smoke_evaluate,
        "smoke-package": cmd_smoke_package,
        "cpu-train": cmd_cpu_train,
        "cpu-fixture-data": cmd_cpu_fixture_data,
        "cpu-evaluate-val": cmd_cpu_evaluate_val,
        "cpu-package-candidate": cmd_cpu_package_candidate,
        "partition": cmd_partition,
        "verify-seal": cmd_verify_seal,
    }
    return cmds[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
