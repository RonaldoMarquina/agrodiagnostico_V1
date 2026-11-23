"""Compara candidatos v1.4.0 usando únicamente sus expedientes VAL.

No abre imágenes ni conoce el manifiesto protegido. Solo autoriza congelamiento
cuando un candidato satisface todas las condiciones VAL registradas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml/src"))

from agro_ml.v14_training import selection_rank


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Objeto JSON inválido: {path.name}")
    return value


def candidate(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    experiment = read_json(root / "experiment.json")
    report = read_json(root / "val-report.json")
    config = read_json(root / "candidate-config.json")
    if experiment.get("status") != "VAL_ONLY_CANDIDATE_NOT_FROZEN_NOT_G2" or \
            experiment.get("protected_external_partition_accessed") is not False:
        raise ValueError(f"Candidato no es exclusivamente VAL: {root.name}")
    if report.get("split") != "VAL" or config.get("protocol_version") != "1.4.0":
        raise ValueError(f"Reporte o configuración incompatible: {root.name}")
    files = {
        "weights_sha256": root / "weights.safetensors",
        "candidate_config_sha256": root / "candidate-config.json",
        "val_report_sha256": root / "val-report.json",
        "val_predictions_sha256": root / "val-predictions.jsonl",
        "train_manifest_sha256": root / "train-manifest.jsonl",
        "val_manifest_sha256": root / "val-manifest.jsonl",
    }
    expected = experiment.get("hashes", {})
    for field, path in files.items():
        if sha256(path) != expected.get(field):
            raise ValueError(f"Hash cambió: {root.name}/{path.name}")
    return experiment, report, config


def summarize(experiment: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategy_id": experiment["strategy_id"],
        "selected_epoch": report["selected_epoch"],
        "weights_sha256": experiment["hashes"]["weights_sha256"],
        "configuration_sha256": experiment["hashes"]["candidate_config_sha256"],
        "val_report_sha256": experiment["hashes"]["val_report_sha256"],
        "macro_f1": report["macro_f1"],
        "recall": {code: item["recall"] for code, item in report["per_class"].items()},
        "coverage": report["coverage"],
        "selective_error": report["selective_error"],
        "healthy": report["counts"]["POTATO_HEALTHY"],
        "other_crop": report["counts"]["OTHER_CROP"],
        "ece": report["ece_technical_potato"],
        "route": report["route"],
        "threshold": report["threshold"],
        "temperature": report["temperature"],
        "visible_confusion_matrix": report["visible_confusion_matrix"],
        "cpu_latency": report["cpu_latency"],
        "training_peak_rss_mb": experiment["runtime"]["peak_rss_mb"],
        "training_seconds": experiment["runtime"]["total_seconds"],
        "val_selection": report["val_selection"],
    }


def run(weighted_root: Path, balanced_root: Path, output: Path) -> None:
    if output.exists():
        raise FileExistsError(output)
    loaded = [candidate(weighted_root), candidate(balanced_root)]
    experiments = [item[0] for item in loaded]
    reports = [item[1] for item in loaded]
    configs = [item[2] for item in loaded]
    if experiments[0]["hashes"]["train_manifest_sha256"] != experiments[1]["hashes"]["train_manifest_sha256"] or \
            experiments[0]["hashes"]["val_manifest_sha256"] != experiments[1]["hashes"]["val_manifest_sha256"] or \
            configs[0]["preprocessing"] != configs[1]["preprocessing"] or \
            configs[0]["seed"] != configs[1]["seed"]:
        raise ValueError("Los candidatos no son comparables bajo el mismo experimento")
    leader_index = max(range(2), key=lambda index: selection_rank(reports[index]))
    eligible = [index for index, report in enumerate(reports)
                if report["val_selection"]["passed"]]
    comparison = {
        "schema_version": 1,
        "protocol_version": "1.4.0",
        "selection_source": "PLANTVILLAGE_VAL_ONLY",
        "protected_external_partition_accessed": False,
        "same_seed": configs[0]["seed"],
        "same_train_manifest_sha256": experiments[0]["hashes"]["train_manifest_sha256"],
        "same_val_manifest_sha256": experiments[0]["hashes"]["val_manifest_sha256"],
        "same_preprocessing": configs[0]["preprocessing"],
        "candidates": [summarize(experiment, report)
                       for experiment, report in zip(experiments, reports)],
        "relative_leader": experiments[leader_index]["strategy_id"],
        "eligible_candidate_count": len(eligible),
        "freeze_decision": "ELIGIBLE_FOR_FREEZE" if eligible else "BLOCKED_NO_CANDIDATE_PASSES_VAL",
        "frozen_bundle_created": False,
        "blocking_conditions": {
            experiments[index]["strategy_id"]: [name for name, passed in
                                                  reports[index]["val_selection"]["conditions"].items()
                                                  if not passed]
            for index in range(2)
        },
    }
    output.write_text(json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": comparison["freeze_decision"],
        "relative_leader": comparison["relative_leader"],
        "comparison_sha256": sha256(output),
    }, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weighted", type=Path, required=True)
    parser.add_argument("--balanced", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.weighted, args.balanced, args.output)


if __name__ == "__main__":
    main()
