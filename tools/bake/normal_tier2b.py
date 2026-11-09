"""Tier 2b comparison of the native Normal baker against Painter's goldens (phase3.2_baker-normal).

    python -m tools.bake.normal_tier2b --exe <uzp-bake-feasibility-tests.exe> [--golden NAME]...
        [--threads N] [--report FILE]

For each `tier2b/bakes/normal-*` golden of the current envelope the native baker bakes the
golden's own instruction sequence: the low mesh through the project importer, every
`BakingParameters.set` step as `--set key=value`, the `HipolyMesh` input as `--high`, the
project's normal map format and tangent-space mode (Painter's project default is `PerVertex`,
`parity/semantics/tangent-frame.json`). The command is the native driver's `bake-files`
(`tests/bake/bake_feasibility_test.cpp`).

The comparison follows `docs/architecture/14-parity-testing.md` section 4: hit/coverage first,
then the map. Painter leaves every texel without a baked value at code 0 (decision 384: no
dilation, passthrough padding), so its hit set is the set of texels with a nonzero code; the
native hit set is the texels of class `StraightHit` or `CageHit`. Maps are compared at native
depth (16-bit codes) on every texel of the image, r1 and r2. The report holds counts only: no
private value leaves the store.

A golden that leaves `RelativeScale` at Painter's default (on) measures its distances against the
bounding box, whose size metric is not established (decision 311). Such a golden is baked under
each metric the native baker names (`--box-size-metric`); the comparison stands only when both
bakes give the same map, so no metric is chosen.
"""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.decode import decode
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, locate

FAMILY = "tier2b/bakes"
GOLDENS = (
    "normal-plane",
    "normal-sphere",
    "normal-bevelled-cube",
    "normal-hemisphere-per-vertex",
    "normal-hemisphere-per-fragment",
    "normal-sphere-absolute-0-01",
    "normal-sphere-absolute-0-05",
)
CREATE = "substance_painter.project.create"
BAKING_SET = "substance_painter.baking.BakingParameters.set"
EXPORT = "substance_painter.export.export_project_textures"
PROJECT_DEFAULT_TANGENT_SPACE = "PerVertex"  # parity/semantics/tangent-frame.json
HIT_CLASSES = (1, 4)  # TexelClass::StraightHit, TexelClass::CageHit
BOX_SIZE_METRICS = ("Diagonal", "LargestExtent")

U16 = npt.NDArray[np.uint16]
Mask = npt.NDArray[np.bool_]


class ComparisonError(RuntimeError):
    """A golden or a native result cannot be compared as this tool requires."""


@dataclass(frozen=True)
class NativeResult:
    normal: U16  # (height, width, 3) raw codes, zero on texels without a value
    texel_class: npt.NDArray[np.uint8]  # (height, width)
    summary: dict[str, Any]


def manifest_path(name: str, root: Path = REPO_ROOT) -> Path:
    return manifest_root(current_envelope(root), root) / FAMILY / f"{name}.json"


def _value_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(_value_text(v) for v in value)
    return str(value)


def bake_arguments(manifest: dict[str, Any], root: Path = REPO_ROOT) -> list[str]:
    """The `bake-files` arguments of a golden's instruction sequence."""
    inputs = {item["input_id"]: root / item["path"] for item in manifest["inputs"]}
    steps = manifest["instruction_sequence"]["steps"]
    if steps[0]["call"] != CREATE:
        raise ComparisonError(f"{manifest['golden_id']}: the first step is not project.create")
    create = steps[0]["args"]
    args = ["--low", str(inputs[create["mesh"]])]
    args += ["--format", create.get("normal_map_format", "OpenGL")]
    args += ["--tangent-space", create.get("tangent_space_mode", PROJECT_DEFAULT_TANGENT_SPACE)]
    for step in steps[1:]:
        if step["call"] != BAKING_SET:
            continue
        a = step["args"]
        if "usage" in a or "texture_set" in a:
            golden = manifest["golden_id"]
            raise ComparisonError(f"{golden}: step {step['step']} is not a common set")
        if a["parameter"] == "HipolyMesh":
            args += ["--high", str(inputs[a["input"]])]
        elif "enum_label" in a:
            args += ["--set", f"{a['parameter']}={a['enum_label']}"]
        else:
            args += ["--set", f"{a['parameter']}={_value_text(a['value'])}"]
    return args


def parse_result(data: bytes) -> tuple[U16, npt.NDArray[np.uint8]]:
    """The raw Normal codes and texel classes of a `UZPBAKE4` result (`SerializeResult`)."""
    if data[:8] != b"UZPBAKE4":
        raise ComparisonError("the native result holds no Normal map (not UZPBAKE4)")
    offset = 11
    (raw_count,) = struct.unpack_from("<Q", data, offset)
    offset += 8
    raw = np.frombuffer(data, "<u2", raw_count, offset)
    offset += 2 * raw_count
    (dilated_count,) = struct.unpack_from("<Q", data, offset)
    offset += 8 + 2 * dilated_count
    width, height, _tile, _rays, _subsampling, _dilation = struct.unpack_from("<6I", data, offset)
    offset += 24
    texels = width * height
    if raw_count != 3 * texels:
        raise ComparisonError("the native Normal map does not cover the image")
    classes = np.frombuffer(data, np.uint8, texels, offset)
    return raw.reshape(height, width, 3).astype(np.uint16), classes.reshape(height, width)


def relative_distances(manifest: dict[str, Any]) -> bool:
    """Whether the golden's detail distances are relative to the bounding box (the default)."""
    for step in manifest["instruction_sequence"]["steps"]:
        if step["call"] == BAKING_SET and step["args"].get("parameter") == "RelativeScale":
            return bool(step["args"]["value"])
    return True


def bake(
    exe: Path, manifest: dict[str, Any], out: Path, threads: int = 0, metric: str | None = None
) -> NativeResult:
    command = [str(exe), "bake-files", *bake_arguments(manifest), "--out", str(out)]
    if threads:
        command += ["--threads", str(threads)]
    if metric is not None:
        command += ["--box-size-metric", metric]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    if proc.returncode != 0:
        raise ComparisonError(f"bake-files failed ({proc.returncode}): {proc.stderr.strip()}")
    normal, classes = parse_result(out.read_bytes())
    return NativeResult(normal, classes, json.loads(proc.stdout))


def golden_maps(store: OracleStore, manifest: dict[str, Any]) -> dict[str, U16]:
    """Each recording's PNG 16 export of the Normal map, by recording (`r1`, `r2`)."""
    png_step = next(
        (
            s["step"]
            for s in manifest["instruction_sequence"]["steps"]
            if s["call"] == EXPORT and s["args"].get("file_format") == "png"
        ),
        None,
    )
    if png_step is None:
        raise ComparisonError(f"{manifest['golden_id']}: no PNG export step")
    maps: dict[str, U16] = {}
    by_hash: dict[str, U16] = {}  # identical recordings are decoded once
    for record in manifest["private_records"]:
        rid = record["record_id"]
        if record["kind"] != "exported_map" or not rid.endswith(f"-step{png_step}"):
            continue
        if record["sha256"] not in by_hash:
            data = store.load(record["sha256"], record.get("size_bytes"))
            if data is None:
                raise ComparisonError(f"oracle_unavailable: {rid}")
            decoded = decode(data)
            if not decoded.integer or decoded.bits != 16 or decoded.values.shape[-1] != 3:
                raise ComparisonError(f"{rid} is not an RGB16 PNG")
            by_hash[record["sha256"]] = decoded.values.astype(np.uint16)
        maps[rid.split("-", 1)[0]] = by_hash[record["sha256"]]
    if sorted(maps) != ["r1", "r2"]:
        raise ComparisonError(f"{manifest['golden_id']}: expected r1 and r2, found {sorted(maps)}")
    return maps


def _count(mask: Mask | np.bool_) -> int:
    return int(np.count_nonzero(mask))


def coverage(oracle: U16, native: NativeResult) -> dict[str, int]:
    painter_hit = (oracle != 0).any(axis=-1)
    native_hit = np.isin(native.texel_class, HIT_CLASSES)
    return {
        "painter_hit": _count(painter_hit),
        "native_hit": _count(native_hit),
        "both": _count(painter_hit & native_hit),
        "painter_only": _count(painter_hit & ~native_hit),
        "native_only": _count(native_hit & ~painter_hit),
    }


def map_difference(oracle: U16, candidate: U16) -> dict[str, Any]:
    delta = np.abs(oracle.astype(np.int64) - candidate.astype(np.int64))
    texels = delta.any(axis=-1)
    return {
        "differing_components": _count(delta != 0),
        "differing_texels": _count(texels),
        "components_per_channel": [_count(delta[..., c] != 0) for c in range(3)],
        "max_abs": int(delta.max()),
        "exact": bool(not texels.any()),
    }


def compare(
    store: OracleStore, exe: Path, name: str, out: Path, threads: int = 0
) -> dict[str, Any]:
    manifest = json.loads(manifest_path(name).read_text(encoding="utf-8"))
    oracle = golden_maps(store, manifest)
    entry: dict[str, Any] = {
        "golden_id": manifest["golden_id"],
        "oracle_stable": bool(np.array_equal(oracle["r1"], oracle["r2"])),
    }
    if relative_distances(manifest):
        bakes = [bake(exe, manifest, out, threads, metric) for metric in BOX_SIZE_METRICS]
        native = bakes[0]
        entry["box_size_metric_independent"] = all(
            np.array_equal(b.normal, native.normal)
            and np.array_equal(b.texel_class, native.texel_class)
            for b in bakes[1:]
        )
    else:
        native = bake(exe, manifest, out, threads)
    entry["native_texels"] = native.summary["texels"]
    entry["native_identity"] = {k: native.summary[k] for k in ("embree_version", "isa", "tasking")}
    for recording, codes in oracle.items():
        cov = coverage(codes, native)
        diff = map_difference(codes, native.normal)
        entry[recording] = {"coverage": cov, "map": diff}
    entry["exact"] = entry.get("box_size_metric_independent", True) and all(
        entry[r]["map"]["exact"] for r in oracle
    )
    return entry


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.bake.normal_tier2b")
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--golden", action="append", choices=GOLDENS)
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--work", type=Path, default=REPO_ROOT / "tmp" / "scratch")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    store = locate()
    if store is None:
        print("oracle_unavailable: no private store on this machine", file=sys.stderr)
        return 2
    report = []
    for name in args.golden or GOLDENS:
        out = args.work / f"normal-tier2b-{name}.bin"
        report.append(compare(store, args.exe, name, out, args.threads))
    text = json.dumps(report, indent=2) + "\n"
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if all(e["exact"] for e in report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
