"""VAL-only visible-decision metrics for the three-target potato candidate."""

import math

DISEASES = ("POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT")
HEALTHY = "POTATO_HEALTHY"
OTHER = "OTHER_CROP"
TARGETS = DISEASES + (HEALTHY,)


def probabilities(logits, temperature):
    if len(logits) != 3 or not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("Invalid technical logits or temperature")
    values = [float(value) / temperature for value in logits]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("Nonfinite technical logit")
    peak = max(values)
    exponents = [math.exp(value - peak) for value in values]
    total = sum(exponents)
    return [value / total for value in exponents]


def visible_decision(probs, threshold, route, healthy_gate=None):
    if len(probs) != 3 or any(not math.isfinite(x) or x < 0 or x > 1 for x in probs) or \
            abs(sum(probs) - 1) > 1e-4 or not 0 <= threshold <= 1:
        raise ValueError("Invalid probabilities or threshold")
    candidate = max(range(3), key=lambda index: probs[index])
    if candidate == 2 or probs[candidate] < threshold:
        return None
    if route == "HEALTHY_GATE":
        if healthy_gate is None or not 0 <= healthy_gate <= 1:
            raise ValueError("Invalid healthy gate")
        if probs[2] > healthy_gate:
            return None
    elif route != "ARGMAX_CONFIDENCE":
        raise ValueError("Unknown rejection route")
    return candidate


def evaluate(rows, logits, temperature, threshold, route, healthy_gate=None):
    if len(rows) != len(logits) or not rows:
        raise ValueError("Missing VAL scores")
    probabilities_by_row = [probabilities(values, temperature) for values in logits]
    decisions = [visible_decision(p, threshold, route, healthy_gate) for p in probabilities_by_row]
    counts = {code: {"photos": 0, "accepted": 0, "correct": 0, "abstained": 0}
              for code in (*TARGETS, OTHER)}
    for row, decision in zip(rows, decisions):
        code = row["stratum_code"]
        if code not in counts:
            raise ValueError("Unknown VAL stratum")
        bucket = counts[code]
        bucket["photos"] += 1
        bucket["accepted"] += decision is not None
        bucket["abstained"] += decision is None
        if code in DISEASES:
            bucket["correct"] += decision == DISEASES.index(code)
    per_class = {}
    positive_total = sum(counts[code]["photos"] for code in DISEASES)
    accepted_positive = sum(counts[code]["accepted"] for code in DISEASES)
    correct_positive = sum(counts[code]["correct"] for code in DISEASES)
    for index, code in enumerate(DISEASES):
        tp = counts[code]["correct"]
        fp = sum(1 for row, decision in zip(rows, decisions) if decision == index and row["stratum_code"] != code)
        fn = counts[code]["photos"] - tp
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / counts[code]["photos"] if counts[code]["photos"] else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[code] = {"tp": tp, "fp": fp, "fn": fn, "support": counts[code]["photos"],
                           "precision": precision, "recall": recall, "f1": f1}
    ece_total = 0.0
    calibration_rows = [(p, row) for p, row in zip(probabilities_by_row, rows) if row["stratum_code"] in TARGETS]
    for bin_index in range(10):
        bin_items = [(max(p), int(TARGETS[max(range(3), key=lambda i: p[i])] == row["stratum_code"]))
                     for p, row in calibration_rows if min(9, int(max(p) * 10)) == bin_index]
        if bin_items:
            ece_total += len(bin_items) / len(calibration_rows) * abs(
                sum(x for x, _ in bin_items) / len(bin_items) - sum(y for _, y in bin_items) / len(bin_items))
    return {"split": "VAL", "route": route, "threshold": threshold,
            "healthy_gate": healthy_gate if route == "HEALTHY_GATE" else None,
            "temperature": temperature, "counts": counts, "per_class": per_class,
            "macro_f1": sum(item["f1"] for item in per_class.values()) / 2,
            "coverage": {"numerator": accepted_positive, "denominator": positive_total,
                         "rate": accepted_positive / positive_total if positive_total else None},
            "selective_error": {"numerator": accepted_positive - correct_positive,
                                "denominator": accepted_positive,
                                "rate": (accepted_positive - correct_positive) / accepted_positive
                                if accepted_positive else None},
            "ece_technical_potato": ece_total,
            "predictions": [{"image_id": row["image_id"], "stratum_code": row["stratum_code"],
                             "split_group": row["split_group"],
                             "published_class": DISEASES[decision] if decision is not None else None,
                             "visible_state": "COMPLETADO" if decision is not None else "NO_CONCLUYENTE",
                             "probabilities": p}
                            for row, decision, p in zip(rows, decisions, probabilities_by_row)]}


def val_gate(report, protocol):
    limits = protocol["metrics_thresholds"]
    counts = report["counts"]
    healthy, other = counts[HEALTHY], counts[OTHER]
    healthy_max = math.floor(healthy["photos"] * limits["potato_healthy_test_visible_blight_rate_max"])
    healthy_min = math.ceil(healthy["photos"] * limits["potato_healthy_test_no_concluyente_rate_min"])
    conditions = {
        "macro_f1_val": report["macro_f1"] >= limits["macro_f1_val_min"],
        "recall_each_disease": all(item["recall"] >= limits["class_recall_test_min"]
                                   for item in report["per_class"].values()),
        "coverage": report["coverage"]["rate"] is not None and
                    report["coverage"]["rate"] >= limits["selective_coverage_min"],
        "selective_error": report["selective_error"]["rate"] is not None and
                           report["selective_error"]["rate"] <= limits["selective_error_max"],
        "healthy_visible_blight": healthy["photos"] > 0 and healthy["accepted"] <= healthy_max,
        "healthy_no_concluyente": healthy["photos"] > 0 and healthy["abstained"] >= healthy_min,
        "other_crop_fpr": other["photos"] > 0 and
                          other["accepted"] / other["photos"] <= limits["negative_fpr_other_crop_max"],
        "other_crop_rejection": other["photos"] > 0 and
                                other["abstained"] / other["photos"] >= limits["negative_rejection_other_crop_min"],
        "calibration_ece": report["ece_technical_potato"] <= limits["calibration_ece_max"],
    }
    return {"passed": all(conditions.values()), "conditions": conditions,
            "healthy_val_allowed_accepted": healthy_max, "healthy_val_required_no_concluyente": healthy_min}
