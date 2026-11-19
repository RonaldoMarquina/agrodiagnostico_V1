"""Component checks with JSON fixtures and mocked AMQP; not G2/G3 acceptance."""
import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ci_support import redact

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ml_integrated_acceptance")


def run_integrated_tests(python_bin: str) -> Dict[str, Any]:
    """Ejecuta la suite de pruebas unitarias de aceptación integrada y captura resultados."""
    cmd = [
        python_bin,
        "-m",
        "unittest",
        "services/diagnosis/tests/test_ml_integrated_acceptance.py",
        "-v",
    ]
    logger.info("Ejecutando suite de aceptación integrada: %s", " ".join(cmd))
    start_time = time.monotonic()
    env = dict(os.environ, PYTHONPATH=f"{ROOT}/services/diagnosis:{ROOT}/services/ai_inference:{ROOT}/ml/src")
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env)
    elapsed = time.monotonic() - start_time

    output = proc.stdout + "\n" + proc.stderr
    sanitized_output = redact(output)

    success = (proc.returncode == 0)
    logger.info("Suite finalizada con exit code %d (duración: %.2fs)", proc.returncode, elapsed)

    # Extraer métricas del benchmark impresas en la salida
    benchmark_metrics: Dict[str, Any] = {}
    for line in sanitized_output.splitlines():
        line_clean = line.strip()
        if line_clean.startswith("Latencia P95:"):
            parts = line_clean.split(":")
            if len(parts) >= 2:
                benchmark_metrics["p95_latency_ms"] = parts[1].split()[0]
        elif line_clean.startswith("Latencia Media:"):
            parts = line_clean.split(":")
            if len(parts) >= 2:
                benchmark_metrics["mean_latency_ms"] = parts[1].split()[0]
        elif line_clean.startswith("Memoria Pico RSS:"):
            parts = line_clean.split(":")
            if len(parts) >= 2:
                benchmark_metrics["peak_memory_rss_mb"] = parts[1].split()[0]

    return {
        "success": success,
        "exit_code": proc.returncode,
        "duration_seconds": round(elapsed, 3),
        "benchmark_metrics": benchmark_metrics,
        "sanitized_output": sanitized_output,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-report",
        type=Path,
        default=ROOT / ".local/evidence/ml_integrated_acceptance.json",
        help="Ruta de destino para el reporte JSON de evidencia saneado.",
    )
    parser.add_argument("--verbose", action="store_true", help="Mostrar salida completa en consola.")
    args = parser.parse_args()

    python_bin = "python3"
    venv_python = ROOT / "services/diagnosis/.venv/bin/python"
    if venv_python.exists() and os.access(venv_python, os.X_OK):
        python_bin = str(venv_python)

    logger.info("Iniciando Verificación de Aceptación Integrada y Benchmark CPU (Tareas 9.1 y 9.2)...")
    res = run_integrated_tests(python_bin)

    if args.verbose or not res["success"]:
        print("\n--- SALIDA DE PRUEBAS INTEGRIDAD ---\n")
        print(res["sanitized_output"])
        print("\n------------------------------------\n")

    report_data = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "protocol_stage": "TECHNICAL_FIXTURE_CHECKS",
        "status": "PASSED" if res["success"] else "FAILED",
        "g2_approved": False,
        "g3_approved": False,
        "limitations": ["JSON linear fixtures, not MobileNet/ResNet", "Mocked AMQP, not real broker E2E", "No approved dataset or agronomic review"],
        "fixture_benchmark": res["benchmark_metrics"],
        "execution": {"exit_code": res["exit_code"], "duration_seconds": res["duration_seconds"], "python_interpreter": python_bin},
    }

    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(json.dumps(report_data, indent=2) + "\n", encoding="utf-8")
    logger.info("Reporte de evidencia guardado en: %s", args.output_report)

    if res["success"]:
        logger.info("PASS: comprobaciones técnicas con fixtures; G2/G3 pendientes.")
        return 0
    else:
        logger.error("FAIL: Una o más pruebas de aceptación integrada o benchmark fallaron.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
