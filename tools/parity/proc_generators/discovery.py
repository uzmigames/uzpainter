"""Public parameter semantics of the mesh-map generators (`phase3.2_proc-generator-families` 2.1).

`python -m tools.parity.recorder.generator_survey` describes every starter-asset generator through
the documented `Property` API into a private file. This module publishes from it only what
`05-procedural-content.md` §3 names as public parameter semantics: per parameter its name, label,
widget type, default value, range (`min`/`max`, the editor's `editorMin`/`editorMax`, `step`),
enum labels and values, and visibility; per generator its resource URL and the counts of presets,
image inputs and outputs. Descriptions and status tips (Adobe's prose) are not copied. The
survey's SHA-256 and Painter build are the provenance.

    python -m tools.parity.proc_generators.discovery <private survey.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tools.parity.schemas import REPO_ROOT

SCHEMA = "uzpainter/proc-generator-parameters/1"
OUTPUT = REPO_ROOT / "parity" / "semantics" / "proc-generator-parameters.json"
# UzPainter family id -> the generator's GUI name in Painter (05 §3 compatibility alias).
FAMILIES: dict[str, str] = {
    "mask-builder": "Mask Builder - Legacy",
    "mask-editor": "Mask Editor",
    "edge-wear": "Metal Edge Wear",
    "dirt": "Dirt",
    "curvature": "Curvature",
    "position": "Position",
    "world-normal": "World Space Normals",
    "occlusion": "Ambient Occlusion",
}
# `Property.properties()` keys that are parameter semantics (ranges, defaults, enum values).
METADATA = {
    "defaultValue": "default",
    "min": "min",
    "max": "max",
    "editorMin": "editor_min",
    "editorMax": "editor_max",
    "step": "step",
    "visible": "visible",
}


def parameter(described: Mapping[str, Any]) -> dict[str, Any]:
    metadata = described.get("properties") or {}
    entry: dict[str, Any] = {
        "label": described.get("label"),
        "widget_type": described.get("widget_type"),
    }
    for key, name in METADATA.items():
        if key in metadata:
            entry[name] = metadata[key]
    enum = described.get("enum_value") or {}
    if enum:
        entry["enum"] = dict(sorted(enum.items(), key=lambda item: item[1]))
    if "raised" in described:
        entry["raised"] = sorted(described["raised"])
    return entry


def count(value: Any) -> int | None:
    return len(value) if isinstance(value, list) else None


def generator(row: Mapping[str, Any]) -> dict[str, Any]:
    if "raised" in row:
        return {"resource_url": row["url"], "raised": row["raised"]}
    source = row["source"]
    return {
        "resource_url": source["resource_url"],
        "presets": count(source.get("presets")),
        "image_inputs": count(source.get("image_inputs")),
        "image_outputs": count(source.get("image_outputs")),
        "parameters": {
            name: parameter(described) for name, described in sorted(source["properties"].items())
        },
    }


def publish(survey_bytes: bytes, families: Mapping[str, str] = FAMILIES) -> dict[str, Any]:
    survey = json.loads(survey_bytes)
    by_name: dict[str, list[Mapping[str, Any]]] = {}
    for row in survey["rows"]:
        by_name.setdefault(row["gui_name"], []).append(row)
    generators: dict[str, Any] = {}
    for family, name in families.items():
        rows = by_name.get(name, [])
        if len(rows) != 1:
            raise ValueError(f"{family}: {len(rows)} surveyed generators named {name!r}")
        generators[family] = {"painter_name": name, **generator(rows[0])}
    return {
        "schema": SCHEMA,
        "task": "phase3.2_proc-generator-families",
        "provenance": {
            "interface": "substance_painter_documented_python_api (properties.Property getters)",
            "survey_sha256": hashlib.sha256(survey_bytes).hexdigest(),
            "survey_schema": survey["schema"],
            "query": survey["query"],
            "painter_build": survey["painter_build"],
            "published": "names, labels, widget types, defaults, ranges, enum labels and values,"
            " visibility, resource URLs and port counts; no description text, no pixel",
        },
        "generators": generators,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.proc_generators.discovery")
    parser.add_argument("survey", type=Path, help="the private generator survey")
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    document = publish(args.survey.read_bytes())
    args.out.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
