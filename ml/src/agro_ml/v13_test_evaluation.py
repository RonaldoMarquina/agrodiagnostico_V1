"""Fixed, untuned scoring of the sealed v1.3.2 TEST outputs."""

import math
import statistics

from agro_ml.v13_metrics import DISEASES, HEALTHY, OTHER, TARGETS, evaluate, probabilities


EXPECTED_TEST = {DISEASES[0]: (80, 20), DISEASES[1]: (80, 20), HEALTHY: (32, 8), OTHER: (80, 20)}


def _check(observed, limit, operator):
    return {"observed": observed, "limit": limit, "operator": operator,
            "passed": observed is not None and
            (observed >= limit if operator == ">=" else observed <= limit)}


def score_test(rows, logits, latencies_ms, protocol, *, temperature, threshold, route,
               healthy_gate, max_rss_mb):
    """Score one complete TEST snapshot; never search weights, routes or thresholds."""
    if protocol.get("protocol_version") != "1.3.2" or \
            not (len(rows) == len(logits) == len(latencies_ms) == 272) or \
            any(not math.isfinite(value) or value < 0 for value in latencies_ms) or \
            not math.isfinite(max_rss_mb) or max_rss_mb <= 0:
        raise ValueError("Incomplete or invalid sealed TEST inputs")
    for code, (photos, groups) in EXPECTED_TEST.items():
        selected = [row for row in rows if row.get("stratum_code") == code]
        if len(selected) != photos or len({row.get("split_group") for row in selected}) != groups or \
                any(not row.get("split_group") or not row.get("image_id") for row in selected):
            raise ValueError(f"Sealed TEST stratum incomplete: {code}")
    if len({row["image_id"] for row in rows}) != 272 or \
            any(row.get("split") != "TEST" for row in rows):
        raise ValueError("Duplicate or non-TEST image")
    report = evaluate(rows, logits, temperature, threshold, route, healthy_gate)
    predictions = report.pop("predictions")
    report["split"] = "TEST"
    confusion = {code: {outcome: 0 for outcome in (*DISEASES, "NO_CONCLUYENTE")}
                 for code in (*TARGETS, OTHER)}
    groups = {}
    correct_argmax_abstained = {code: 0 for code in DISEASES}
    for row, pred, raw_logits in zip(rows, predictions, logits):
        truth, outcome = row["stratum_code"], pred["published_class"] or "NO_CONCLUYENTE"
        confusion[truth][outcome] += 1
        group = groups.setdefault(row["split_group"],
                                  {"stratum_code": truth, "photos": 0, "published": 0,
                                   "abstained": 0, "correct_published": 0})
        if group["stratum_code"] != truth:
            raise ValueError("One leaf group has multiple strata")
        group["photos"] += 1
        group["published"] += pred["published_class"] is not None
        group["abstained"] += pred["published_class"] is None
        group["correct_published"] += pred["published_class"] == truth and truth in DISEASES
        if truth in DISEASES and pred["published_class"] is None and \
                max(range(3), key=lambda index: raw_logits[index]) == DISEASES.index(truth):
            correct_argmax_abstained[truth] += 1
    report["confusion_with_abstention"] = confusion
    report["groups"] = {key: groups[key] for key in sorted(groups)}
    report["group_counts"] = {code: len({row["split_group"] for row in rows
                                         if row["stratum_code"] == code}) for code in (*TARGETS, OTHER)}
    report["correct_candidate_abstained"] = correct_argmax_abstained
    report["abstained_positive_count"] = sum(report["counts"][code]["abstained"] for code in DISEASES)
    for code in DISEASES:
        item = report["per_class"][code]
        item["recall_counts"] = {"numerator": item["tp"], "denominator": item["support"]}
        item["precision_counts"] = {"numerator": item["tp"], "denominator": item["tp"] + item["fp"]}
        item["f1_counts"] = {"numerator": 2 * item["tp"],
                             "denominator": 2 * item["tp"] + item["fp"] + item["fn"]}
        item["false_negative_due_to_abstention"] = report["counts"][code]["abstained"]
    potato = [(row, probabilities(values, temperature)) for row, values in zip(rows, logits)
              if row["stratum_code"] in TARGETS]
    brier_sum = sum(sum((p[index] - int(TARGETS[index] == row["stratum_code"])) ** 2
                        for index in range(3)) for row, p in potato)
    report["brier_technical_potato"] = {"sum": brier_sum, "denominator": len(potato),
                                        "mean": brier_sum / len(potato)}
    timings = sorted(latencies_ms)
    report["cpu_latency"] = {"scope": "TEST_DECODE_PREPROCESS_MODEL_DECISION_CPU_NOT_FULL_FLOW",
                             "count": len(timings), "median_ms": statistics.median(timings),
                             "p95_ms": timings[math.ceil(.95 * len(timings)) - 1],
                             "maximum_ms": max(timings), "max_rss_mb": max_rss_mb}
    limits = protocol["metrics_thresholds"]
    budget = protocol["compute_budget_cpu"]
    healthy = report["counts"][HEALTHY]
    other = report["counts"][OTHER]
    checks = {
        "macro_f1_test": _check(report["macro_f1"], limits["macro_f1_test_min"], ">="),
        "coverage": _check(report["coverage"]["rate"], limits["selective_coverage_min"], ">="),
        "selective_error": _check(report["selective_error"]["rate"], limits["selective_error_max"], "<="),
        "healthy_visible_blight_count": _check(healthy["accepted"],
                                                limits["potato_healthy_test_max_visible_blight_count"], "<="),
        "healthy_no_concluyente_count": _check(healthy["abstained"],
                                               limits["potato_healthy_test_min_no_concluyente_count"], ">="),
        "healthy_negative_acceptance": _check(healthy["accepted"] / healthy["photos"],
                                               limits["negative_acceptance_per_stratum_max"], "<="),
        "other_crop_fpr": _check(other["accepted"] / other["photos"],
                                 limits["negative_fpr_other_crop_max"], "<="),
        "other_crop_rejection": _check(other["abstained"] / other["photos"],
                                       limits["negative_rejection_other_crop_min"], ">="),
        "other_crop_negative_acceptance": _check(other["accepted"] / other["photos"],
                                                  limits["negative_acceptance_per_stratum_max"], "<="),
        "calibration_ece": _check(report["ece_technical_potato"], limits["calibration_ece_max"], "<="),
        "cpu_median_ms": _check(report["cpu_latency"]["median_ms"], budget["latency_median_ms_max"], "<="),
        "cpu_p95_ms": _check(report["cpu_latency"]["p95_ms"], budget["latency_p95_ms_max"], "<="),
        "cpu_max_ms": _check(report["cpu_latency"]["maximum_ms"], budget["latency_hard_limit_ms"], "<="),
        "cpu_peak_rss_mb": _check(max_rss_mb, budget["max_rss_mb"], "<="),
    }
    for code in DISEASES:
        checks[f"recall_{code}"] = _check(report["per_class"][code]["recall"],
                                            limits["class_recall_test_min"], ">=")
        checks[f"f1_{code}"] = _check(report["per_class"][code]["f1"],
                                        limits["class_f1_test_min"], ">=")
    report["g0_checks"] = checks
    report["g0_numeric_pass"] = all(value["passed"] for value in checks.values())
    report["external"] = {"status": "NOT_AVAILABLE"}
    report["full_flow_latency"] = {"status": "NOT_MEASURED"}
    report["g2_approval"] = None
    return report, predictions
