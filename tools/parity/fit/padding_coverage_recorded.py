"""Island coverage rules scored against Painter's recorded coverage.

Task `phase3.1_export-island-padding` item 2.1, decision 401.

A kernel-code probe (decision 266) records every covered texel's own source: a texel is covered
when all 24 components of the first `infinite` export of r1 equal its sources bit for bit. This
scores three rules against that truth on every texel of each admitted kernel probe named:

- `281`: decision 281's coverage (`padding_coverage.coverage_281`; an on-edge centre is covered);
- `ndc`: `padding_coverage.py`'s float32 device-coordinate vertices, decision 281's edge test;
- `ndc-top-left`: the same vertices; an on-edge centre is covered only for an edge with dy < 0, or
  a horizontal one with dx < 0 (rows top first, the triangle wound to a positive area); adopted by
  decision 408 as `tools/parity/coverage.py`'s `coverage`.

    python -m tools.parity.fit.padding_coverage_recorded <probe> [<probe> ...]

`<probe>` is a manifest path under the current envelope's manifests (for example
`semantics/export-padding-fold-tie`). Counts only: no coordinate leaves the private store.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.coverage import Mask, Triangles, coverage, obj_materials, obj_triangles
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.decode import decode
from tools.parity.fit.padding_coverage import coverage_281, ndc_coverage, recorded_meshes
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, locate

EXPORT = "substance_painter.export.export_project_textures"
SET_SOURCE = "substance_painter.layerstack.FillLayerNode.set_source"


def top_left_coverage(triangles: Triangles, width: int, height: int) -> Mask:
    """The covered texels (rows top first) under the `ndc-top-left` rule: decision 408's
    `coverage`."""
    return coverage(triangles, width, height)


def recorded_coverage(manifest: dict[str, Any], store: OracleStore) -> npt.NDArray[np.bool_]:
    """Texels whose 24 r1 `infinite` components (first such export) equal their sources."""
    refs = {r["record_id"]: r["sha256"] for r in manifest["private_records"]}
    steps = {s["step"]: s for s in manifest["instruction_sequence"]["steps"]}
    paths = {row["input_id"]: row.get("path") for row in manifest["inputs"]}
    step = min(
        s["step"]
        for s in steps.values()
        if s["call"] == EXPORT and s["args"].get("padding") == "infinite"
    )
    golden = json.loads(store.load(refs["golden-record"]) or b"{}")
    covered: npt.NDArray[np.bool_] | None = None
    for output in golden["recordings"][0]["outputs"]:
        settings = output.get("export_settings", {})
        if output["kind"] != "exported_map" or settings.get("step") != step:
            continue
        channel = output["map"].capitalize()
        source_step = next(
            s
            for s in steps.values()
            if s["call"] == SET_SOURCE and s["args"].get("channel") == channel
        )
        source_input = steps[source_step["args"]["resource_step"]]["args"]["input"]
        source = decode((REPO_ROOT / paths[source_input]).read_bytes()).values[..., :3]
        data = store.load(output["blob"]["sha256"])
        if data is None:
            raise ValueError(f"{output['output_id']}: blob unavailable")
        recorded = decode(data).values[..., :3]
        equal = np.all(
            recorded.astype(np.float32).view(np.uint32)
            == source.astype(np.float32).view(np.uint32),
            axis=-1,
        )
        covered = equal if covered is None else covered & equal
    if covered is None:
        raise ValueError("no infinite export in r1")
    return covered


def score(rule: Mask, truth: npt.NDArray[np.bool_]) -> tuple[int, int, int]:
    """(texels covered, covered but padding in Painter, padding but covered in Painter)."""
    return int(rule.sum()), int((rule & ~truth).sum()), int((~rule & truth).sum())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("probe", nargs="+")
    args = parser.parse_args(argv)
    store = locate()
    if store is None:
        print("oracle_unavailable: no private oracle store on this machine", file=sys.stderr)
        return 1
    root = manifest_root(current_envelope())
    meshes = {golden: (mesh, sizes) for golden, mesh, sizes in recorded_meshes()}
    for probe in args.probe:
        manifest = json.loads((root / "tier0" / f"{probe}.json").read_text(encoding="utf-8"))
        mesh, sizes = meshes[manifest["golden_id"]]
        (size,) = sizes
        (material,) = obj_materials(Path(mesh))
        triangles = obj_triangles(Path(mesh), material)
        truth = recorded_coverage(manifest, store)
        print(f"{probe}: recorded covered {int(truth.sum())}")
        for name, rule in (
            ("281", coverage_281(triangles, size, size)),
            ("ndc", ndc_coverage(triangles, size, size)),
            ("ndc-top-left", top_left_coverage(triangles, size, size)),
        ):
            covered, extra, missing = score(rule, truth)
            print(f"  {name:<13} covered {covered} too-many {extra} too-few {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
