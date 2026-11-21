"""Inventario privado del lote color de PlantVillage antes de la admisión G1."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import re
from pathlib import Path
import zipfile

from agro_ml.data.grouping import compute_dhash, DEFAULT_HAMMING_THRESHOLD
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REV = "9e97599868962bd0079b8db4b7f1efa9185fa1e7"
PIN = {
    "README.md": "9fbe34695a3f05583f47345e5174383226ecee9e7af9e21d979307771b2362fb",
    "data.zip": "fba30c6a7965e49be94b47a62f8aff6cfb1c35c27f475f22092b56db41745e84",
    "color_train.txt": "c43e0205b321d1c929116f5df1842348ac1e5c4861306e081416785d3c439dbd",
    "leaf-map.json": "3b4b253683c6911744959a3870a92509b1faa1ee34e9f8585e21d0fe6337a25b",
}
NEG = "Tomato___healthy"


def leaf_for(path, leaf_map):
    label = path.parent.name
    key = path.name.split("___")[-1].split("copy")[0].lower()
    key = key.replace(".jpg", "").replace(".png", "").strip()
    hits = set(leaf_map.get(key, []))
    matching = sorted(x for x in hits if re.fullmatch(re.escape(label) + r":::[0-9]+(?:\.0)?", x))
    return matching[0] if len(matching) == 1 else ""


def write_csv(path, header, rows):
    with path.open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def prepare(src, out):
    for name, expected in PIN.items():
        with (src / name).open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != expected:
                raise ValueError(f"Revisión o bytes incompatibles: {name}")
    mappings = json.loads((ROOT / "ml/manifests/label-mappings.v2.json").read_text())
    codes = {m["source_label"]: m["class_code"] for m in mappings["mappings"]
             if m["source"] == "plantvillage" and m["status"] != "UNMAPPED"}
    if len(codes) != 7:
        raise ValueError("Se requieren las siete etiquetas")
    codes[NEG] = "OTHER_CROP"
    leaf_map = json.loads((src / "leaf-map.json").read_text())
    paths = sorted((src / "color_train.txt").read_text().splitlines())
    out.mkdir(mode=0o700)
    images = out / "images"
    images.mkdir()
    (out / "rights.md").write_bytes((src / "README.md").read_bytes())
    rows, peers = [], []
    dhashes = []
    with zipfile.ZipFile(src / "data.zip") as archive:
        for name in paths:
            p = Path(name)
            if len(p.parts) != 4 or p.parts[:2] != ("raw", "color") or p.parent.name not in codes:
                continue
            raw = archive.read(name)
            digest = hashlib.sha256(raw).hexdigest()
            file = images / (digest + p.suffix.lower())
            file.write_bytes(raw)
            leaf = leaf_for(p, leaf_map)
            reason = "" if leaf else "LEAF_ID_UNRESOLVED"
            try:
                with Image.open(file) as im:
                    im.load()
                dhash = compute_dhash(file)
            except (OSError, ValueError):
                reason = "DECODE_ERROR"
                dhash = None
            rows.append(dict(source_revision=REV, path=name, sha256=digest, relative_path="images/"+file.name,
                             proof_path="rights.md", license="CC-BY-SA-3.0", source_label=p.parent.name,
                             candidate=codes[p.parent.name], leaf_id=leaf, split="", exclusion=reason,
                             label_review="SOURCE_LABEL_ONLY"))
            dhashes.append(dhash)
    # Compare even unresolved rows so their duplicates cannot silently cross into a split.
    same = defaultdict(list)
    for i, row in enumerate(rows):
        same[row["sha256"]].append(i)
    for copies in same.values():
        if len(copies) < 2:
            continue
        compatible = len({(rows[i]["leaf_id"],rows[i]["candidate"]) for i in copies}) == 1
        for i in copies[1:] if compatible else copies:
            rows[i]["exclusion"] = "EXACT_DUPLICATE" if compatible else "CONFLICTING_DUPLICATE"
    for i, a in enumerate(dhashes):
        if a is None:
            continue
        for j in range(i):
            b = dhashes[j]
            if b is None or rows[i]["sha256"] == rows[j]["sha256"]:
                continue
            distance = (a ^ b).bit_count()
            if distance <= DEFAULT_HAMMING_THRESHOLD and (
                not rows[i]["leaf_id"] or rows[i]["leaf_id"] != rows[j]["leaf_id"]
            ):
                peers.append(dict(a=rows[i]["path"], b=rows[j]["path"], distance=distance))
                for row in (rows[i], rows[j]):
                    row["exclusion"] = row["exclusion"] or "VISUAL_MATCH_PENDING"
    # Fixed group assignment by class; no pixels are accessed after this step.
    groups = defaultdict(set)
    for row in rows:
        if not row["exclusion"]:
            groups[row["candidate"]].add(row["leaf_id"])
    splits = {}
    for leaves in groups.values():
        ordered = sorted(leaves, key=lambda x: hashlib.sha256(x.encode()).digest())
        for i, leaf in enumerate(ordered):
            splits[leaf] = "TEST" if i < len(leaves)*15//100 else (
                "VAL" if i < len(leaves)*35//100 else "TRAIN")
    for row in rows:
        if not row["exclusion"]:
            row["split"] = splits[row["leaf_id"]]
    header = list(rows[0])
    for name, subset in (("positives", [r for r in rows if r["candidate"] != "OTHER_CROP"]),
                         ("negatives", [r for r in rows if r["candidate"] == "OTHER_CROP"]),
                         ("excluded", [r for r in rows if r["exclusion"]])):
        write_csv(out / (name+".csv"), header, subset)
    write_csv(out / "visual-pairs.csv", ["a","b","distance"], peers)
    summary = {}
    for code in codes.values():
        subset = [r for r in rows if r["candidate"] == code]
        summary[code] = {"inventoried": len(subset), "excluded": dict(Counter(
            r["exclusion"] for r in subset if r["exclusion"])), "partitions": {}}
        for split in ("TRAIN","VAL","TEST"):
            keep = [r for r in subset if r["split"] == split]
            summary[code]["partitions"][split] = [len(keep), len({r["leaf_id"] for r in keep})]
    evidence = dict(revision=REV, inputs_sha256=PIN, source_train_paths=len(paths),
                    scope="CANDIDATE_ONLY", partition_units=["images","distinct_publisher_leaf_ids"],
                    visual_pairs=len(peers), exact_redundant_paths=sum(len(v)-1 for v in same.values()),
                    csv_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob("*.csv"))},
                    classes=summary)
    (out / "summary.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("new_output_dir", type=Path)
    args = parser.parse_args()
    prepare(args.source, args.new_output_dir)
