"""Compare the pinned publisher metadata generator to the positive candidate inventory (offline)."""
import argparse
import ast
from collections import Counter, defaultdict
import csv
import hashlib
import json
import os
from pathlib import Path

PINS = {
    "plant_village.py": "872c207c874ad96e3a2e470299abf67e82b15c66e23f9e4e5b1ed784c69567d8",
    "leaf-map.json": "3b4b253683c6911744959a3870a92509b1faa1ee34e9f8585e21d0fe6337a25b",
    "color_train.txt": "c43e0205b321d1c929116f5df1842348ac1e5c4861306e081416785d3c439dbd",
    "batch-v1/positives.csv": "4109b54502970432ba75356e60a45b999039c392556fa1c469ba2502b6c60b4c",
}


def audit(root):
    for name, digest in PINS.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Entrada distinta de la revisión auditada: {name}")

    # Execute only the pinned metadata method. It constructs image paths as strings.
    # Importing the publisher's dataset builder would enable unrelated download hooks.
    loader = ast.parse((root / "plant_village.py").read_text())
    method = next(n for n in ast.walk(loader)
                  if isinstance(n, ast.FunctionDef) and n.name == "_generate_examples")
    namespace = {"os": os, "json": json}
    exec(compile(ast.Module([method], []), "pinned_metadata_method", "exec"), namespace)
    examples = namespace["_generate_examples"](None, "", root / "color_train.txt", root / "leaf-map.json")
    mapping = json.loads((root / "leaf-map.json").read_text())
    with (root / "batch-v1/positives.csv").open(newline="") as f:
        inventory = {r["path"]: r for r in csv.DictReader(f)}
    counts = defaultdict(Counter)
    distinct = defaultdict(set)
    for _, example in examples:
        row = inventory.pop(example["image_path"], None)
        if row is None:
            continue
        code = row["candidate"]
        leaf = example["leaf_id"]
        distinct[code].add(leaf)
        counts[code]["rows"] += 1
        if example["label"] != row["source_label"]:
            raise ValueError("Etiqueta publicada y carpeta del inventario divergen")
        if leaf.startswith("fallback_"):
            key = leaf.removeprefix("fallback_").lower().strip()
            counts[code]["fallback"] += 1
            counts[code]["missing_map_key"] += int(key not in mapping)
            if row["leaf_id"] or row["split"]:
                raise ValueError("Fallback utilizado como hoja o particionado")
        elif leaf == row["leaf_id"] and leaf.split(":::")[0] == example["label"]:
            counts[code]["source_matches_inventory"] += 1
        else:
            raise ValueError("Resultado del cargador incompatible con el inventario")
    if inventory:
        raise ValueError("Hay rutas del inventario que no aparecen en TRAIN del editor")
    for code, values in distinct.items():
        counts[code]["distinct_loader_values"] = len(values)
    prefixes = {v.split(":::")[0] for vals in mapping.values() for v in vals}
    return {"map_keys": len(mapping), "map_namespaces": sorted(prefixes), "classes": counts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    print(json.dumps(audit(parser.parse_args().source), indent=2, sort_keys=True))
