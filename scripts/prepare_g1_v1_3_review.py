"""Prepare private, group-based visual review sheets without admitting TEST.

Selection uses only verified source leaf IDs and deterministic hashes, never
model scores. Every original image remains linked to the pinned archive SHA.
"""

from collections import defaultdict
import argparse
import csv
import hashlib
from io import BytesIO
import json
from pathlib import Path
import zipfile

from PIL import Image, ImageDraw


CLASSES = ("POTATO_HEALTHY", "POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT", "OTHER_CROP")


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare(source, resolved_registry, output):
    if output.exists():
        raise FileExistsError(output)
    rows = read_csv(resolved_registry)
    selected = []
    for code in CLASSES:
        eligible = [r for r in rows if r["class_code"] == code and r["decision"] == "PENDING" and
                    (code == "POTATO_HEALTHY" or r["source_split"] == "AUTHOR_COLOR_TEST")]
        groups = defaultdict(list)
        for row in eligible:
            if not row["leaf_id"]:
                raise ValueError("Candidate without publisher leaf ID")
            groups[row["leaf_id"]].append(row)
        ordered = sorted(groups, key=lambda leaf: digest(leaf.encode()))
        chosen = ordered if code == "POTATO_HEALTHY" else ordered[:20]
        if code != "POTATO_HEALTHY" and len(chosen) < 20:
            raise ValueError(f"Too few independent groups: {code}")
        for leaf in chosen:
            selected.extend(groups[leaf])
    output.mkdir(parents=True, mode=0o700)
    with (output / "candidates.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(selected)
    index = []
    with zipfile.ZipFile(source / "data.zip") as archive:
        for code in CLASSES:
            per_group = defaultdict(list)
            for row in selected:
                if row["class_code"] == code:
                    per_group[row["leaf_id"]].append(row)
            ordered_groups = sorted(per_group, key=lambda leaf: digest(leaf.encode()))
            for page_no, start in enumerate(range(0, len(ordered_groups), 5), 1):
                page_groups = ordered_groups[start:start + 5]
                canvas = Image.new("RGB", (1000, len(page_groups) * 220), (255, 255, 255))
                draw = ImageDraw.Draw(canvas)
                for row_no, leaf in enumerate(page_groups):
                    items = sorted(per_group[leaf], key=lambda r: r["source_path"])
                    if len(items) > 4:
                        raise ValueError(f"Contact sheet cannot show every image in group {leaf}")
                    draw.text((4, row_no * 220 + 8), leaf.split(":::")[-1], fill=(0, 0, 0))
                    for col, row in enumerate(items):
                        raw = archive.read(row["source_path"])
                        if digest(raw) != row["sha256"]:
                            raise ValueError("Original image SHA changed")
                        with Image.open(BytesIO(raw)) as image:
                            image.load()
                            thumbnail = image.copy()
                            thumbnail.thumbnail((190, 190))
                        canvas.paste(thumbnail, (200 + col * 200, row_no * 220))
                        draw.text((200 + col * 200, row_no * 220 + 191), row["sha256"][:10],
                                  fill=(0, 0, 0))
                        index.append({"class_code": code, "leaf_id": leaf, "sha256": row["sha256"],
                                      "source_path": row["source_path"],
                                      "sheet": f"{code}-page-{page_no:02d}.png"})
                canvas.save(output / f"{code}-page-{page_no:02d}.png")
    (output / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    summary = {"status": "PRIVATE_VISUAL_REVIEW_PREPARATION_ONLY", "candidate_rows": len(selected),
               "candidate_csv_sha256": digest((output / "candidates.csv").read_bytes()),
               "index_sha256": digest((output / "index.json").read_bytes()),
               "counts": {code: {"photos": sum(r["class_code"] == code for r in selected),
                                  "groups": len({r["leaf_id"] for r in selected if r["class_code"] == code})}
                          for code in CLASSES},
               "caveat": "Contact sheets are for internal quality review, not model evaluation or TEST opening."}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("resolved_registry", type=Path)
    parser.add_argument("new_output_dir", type=Path)
    args = parser.parse_args()
    prepare(args.source_dir, args.resolved_registry, args.new_output_dir)
