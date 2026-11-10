"""Public parameter semantics of the inventoried grunges (`phase3.2_proc-grunge-families` 2.2).

Every case of the diagnostic goldens (`goldens.py`) sets the grunge's seed, so the recorder reads
the source back through the documented `properties.Property` getters (the `set_parameters`
readback, `GeneratorEffectNode.get_source` applied to the mask's fill effect). This module reads
those private readbacks from the admitted golden records in the store and publishes only what
`05-procedural-content.md` §3 names as public parameter semantics, with the generator
discovery's rules (`tools.parity.proc_generators.discovery`): per parameter its name, label,
widget type, default, range, enum labels and values and visibility; per grunge its resource URL
and the counts of presets, image inputs and outputs. No description text, no preset content,
no pixel.

    python -m tools.parity.proc_grunges.discovery

Writes `docs/analysis/proc-grunge-families/02-parameter-discovery.md`.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from typing import Any

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.proc_generators.discovery import cell, count, parameter
from tools.parity.proc_grunges.goldens import recorded
from tools.parity.proc_grunges.requests import FAMILY, GRUNGE_URLS
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, locate

OUTPUT = REPO_ROOT / "docs" / "analysis" / "proc-grunge-families" / "02-parameter-discovery.md"
READBACK = "substance_painter.layerstack.GeneratorEffectNode.get_source"
# A case that sets no parameter has only the `set_source` readback: value, label and widget type.
SOURCE_READBACK = "substance_painter.layerstack.FillEffectNode.get_source"


def golden_record(store: OracleStore, name: str) -> tuple[dict[str, Any], str]:
    path = manifest_root(current_envelope(REPO_ROOT), REPO_ROOT) / FAMILY / f"{name}.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    (record,) = [r for r in manifest["private_records"] if r["record_id"] == "golden-record"]
    data = store.load(record["sha256"], record["size_bytes"])
    if data is None:
        raise ValueError(f"{name}: golden record unavailable")
    return json.loads(data), record["sha256"]


def descriptions(store: OracleStore) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    """The first r1 readback of each grunge's source, and the golden records' SHA-256."""
    found: dict[str, Mapping[str, Any]] = {}
    hashes: list[str] = []
    for golden in recorded():
        record, sha = golden_record(store, golden.name)
        hashes.append(sha)
        outputs = record["recordings"][0]["outputs"]
        readbacks = {
            o["args"]["node_step"]: o["value"]
            for o in outputs
            if o.get("call") == READBACK and isinstance(o.get("value"), dict)
        }
        fallback = {
            o["args"]["node_step"]: from_source_readback(o["value"])
            for o in outputs
            if o.get("call") == SOURCE_READBACK and "substance_properties" in o.get("value", {})
        }
        for asset, step in record_steps(golden.name):
            if step in readbacks and "partial" in found.get(asset, {"partial": True}):
                found[asset] = readbacks[step]  # a full description replaces a partial one
            elif asset not in found and step in fallback:
                found[asset] = fallback[step]
    return found, hashes


def from_source_readback(value: Mapping[str, Any]) -> dict[str, Any]:
    """A `set_source` readback in the shape of a full description: each parameter's value as its
    default, its label and widget type; no range, no port counts (`partial`)."""
    properties = {
        name: {
            "label": entry.get("label"),
            "widget_type": entry.get("widget_type"),
            "properties": {"defaultValue": entry.get("value")},
        }
        for name, entry in value["substance_properties"].items()
    }
    return {"properties": properties, "partial": {"properties": True}}


def record_steps(name: str) -> list[tuple[str, int]]:
    """(asset, fill-effect step) of each case, from the request's own steps."""
    path = manifest_root(current_envelope(REPO_ROOT), REPO_ROOT) / FAMILY / f"{name}.json"
    steps = json.loads(path.read_text(encoding="utf-8"))["instruction_sequence"]["steps"]
    by_url = {url: asset for asset, url in GRUNGE_URLS.items()}
    return [
        (by_url[s["args"]["resource"]], s["args"]["node_step"])
        for s in steps
        if s["call"].endswith("FillEffectNode.set_source") and "resource" in s["args"]
    ]


def markdown(found: Mapping[str, Mapping[str, Any]], hashes: list[str]) -> str:
    digest = hashlib.sha256("".join(sorted(hashes)).encode("ascii")).hexdigest()
    lines = [
        "# Grunge parameters (phase3.2_proc-grunge-families item 2.2)",
        "",
        "Discovered through the documented `properties.Property` getters (approved source "
        "A-PYDOC): the recorder's readback of each grunge source after its seed was set, in the "
        "diagnostic goldens of `tools/parity/proc_grunges/goldens.py` (Painter "
        "`12.2.0+js-api.1.1.20`, Legacy colour management). The readbacks are private (golden "
        f"records in the owner's store; SHA-256 of their sorted hashes `{digest}`). Generated by "
        "`python -m tools.parity.proc_grunges.discovery`; do not edit by hand.",
        "",
        "Published here, as `05-procedural-content.md` §3 allows: parameter names, labels, widget "
        "types, default values, ranges (`min`/`max`), enum labels and values, visibility, the "
        "resource URL and the counts of presets, image inputs and outputs. No description text, "
        "no preset content, no pixel.",
        "",
        "| UzPainter asset | Resource | Presets | Image inputs | Outputs |",
        "|---|---|---|---|---|",
    ]
    for asset in GRUNGE_URLS:
        source = found.get(asset, {})
        lines.append(
            f"| `grunge/{asset}` | `{GRUNGE_URLS[asset]}` | {cell(count(source.get('presets')))} | "
            f"{cell(count(source.get('image_inputs')))} | "
            f"{cell(count(source.get('image_outputs')))} |"
        )
    for asset in GRUNGE_URLS:
        lines += ["", f"## `grunge/{asset}`", ""]
        found_source = found.get(asset)
        if found_source is None:
            lines.append("No readback.")
            continue
        source = found_source
        if "partial" in source:
            lines += [
                "No case set a parameter of this grunge, so only the `set_source` readback "
                "describes it: the default is the value read, and no range was read.",
                "",
            ]
        lines += [
            "| Parameter | Label | Widget | Default | Min | Max | Enum | Visible |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for name, described in sorted(source.get("properties", {}).items()):
            entry = parameter(described)
            lines.append(
                f"| `{name}` | {cell(entry.get('label'))} | {cell(entry.get('widget_type'))} | "
                f"{cell(entry.get('default'))} | {cell(entry.get('min'))} | "
                f"{cell(entry.get('max'))} | {cell(entry.get('enum'))} | "
                f"{cell(entry.get('visible'))} |"
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    store = locate()
    if store is None:
        print("no private store on this machine", file=sys.stderr)
        return 2
    found, hashes = descriptions(store)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(markdown(found, hashes), encoding="utf-8", newline="\n")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
