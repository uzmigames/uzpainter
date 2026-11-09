"""Tier 2b comparison of the native baker's other usages against Painter's goldens.

    python -m tools.bake.usage_tier2b --exe <uzp-bake-feasibility-tests.exe> [--golden NAME]...
        [--threads N] [--report FILE]

Every admitted `tier2b/bakes/*` golden except Normal's (`tools/bake/normal_tier2b.py`) is baked
from its own instruction sequence with the native driver's `bake-files`: the common `set` steps
as `--set Key=value`, the usage's own steps as `--set Usage:Key=value`, the enabled baker as
`--usage`. A usage setting the native baker refuses is dropped and the refusal is recorded: the
texel classes come from the primary-ray stage every usage shares (`BakeTexel`), so the hit set
still compares, the map does not. When the usage's own defaults are refused as well (AO's default
`Attenuation`), the classes are those of the same sequence baked as Normal.

The comparison follows `docs/architecture/14-parity-testing.md` section 4, hit/coverage first,
then the map, wherever the native map and Painter's export have an established relation:

- coverage: Painter leaves every texel without a baked value at 0 (no dilation, passthrough
  padding), so its value set is its nonzero texels, compared with the native hits (`StraightHit`,
  `CageHit`) and with the native covered texels (every class but `Uncovered`). Painter's
  WorldSpaceNormal and Position write a value on covered texels whose ray misses, and Thickness
  under `Relative to ray distances` on every texel; a Position value can be zero (the origin, or
  Painter's zero on a quarter of the plane). Curvature is not baked natively;
- AO: the native 16-bit codes against the PNG 16 export, every texel, once the native baker
  accepts the golden's AO settings (Painter's default `Attenuation` is refused today);
- ID: the native labels partition the hits as Painter's colours do (no colour mapping is
  inferred): texels whose label meets more than one colour, or whose colour meets more than one
  label, are counted;
- WorldSpaceNormal, Position, Thickness: no channel format or value is established (decisions
  337 and 341), so only coverage compares.

A golden with relative distances (Painter's default `RelativeScale`) is baked under both box-size
metrics and stands only when both give the same per-texel arrays (decision 311). The report holds
counts only: no private value leaves the store.
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

from tools.bake import normal_tier2b as nt
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.decode import decode
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, locate

UNCOVERED = 0  # TexelClass::Uncovered
ENABLE = "substance_painter.baking.BakingParameters.set_enabled_bakers"
NOT_BAKED = ("Curvature",)  # the CPU baker does not bake it (bake_publication.cpp)

Mask = npt.NDArray[np.bool_]


class ComparisonError(RuntimeError):
    """A golden or a native result cannot be compared as this tool requires."""


@dataclass(frozen=True)
class NativeResult:
    texel_class: npt.NDArray[np.uint8]  # (height, width)
    ao: npt.NDArray[np.uint16] | None  # (height, width) raw codes
    id_labels: npt.NDArray[np.uint16] | None  # (height, width)
    maps: bytes  # every per-texel array but the distance record (it holds the box size)


def goldens(root: Path = REPO_ROOT) -> list[str]:
    folder = manifest_root(current_envelope(root), root) / nt.FAMILY
    names = sorted(p.stem for p in folder.glob("*.json"))
    return [n for n in names if not n.startswith("normal-")]


def manifest(name: str, root: Path = REPO_ROOT) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(nt.manifest_path(name, root).read_text(encoding="utf-8"))
    return data


def usage_of(m: dict[str, Any]) -> str:
    for step in m["instruction_sequence"]["steps"]:
        if step["call"] == ENABLE:
            # Curvature from the normal map enables Normal beside it; the golden is Curvature's.
            usages = [u for u in step["args"]["usages"] if u != "Normal"]
            if len(usages) != 1:
                raise ComparisonError(f"{m['golden_id']}: expected one usage but Normal: {usages}")
            return str(usages[0])
    raise ComparisonError(f"{m['golden_id']}: no set_enabled_bakers step")


def bake_arguments(m: dict[str, Any], root: Path = REPO_ROOT) -> tuple[list[str], list[str]]:
    """The common `bake-files` arguments and the usage's own `--set Usage:Key=value` values."""
    inputs = {item["input_id"]: root / item["path"] for item in m["inputs"]}
    steps = m["instruction_sequence"]["steps"]
    if steps[0]["call"] != nt.CREATE:
        raise ComparisonError(f"{m['golden_id']}: the first step is not project.create")
    create = steps[0]["args"]
    args = ["--low", str(inputs[create["mesh"]])]
    args += ["--format", create.get("normal_map_format", "OpenGL")]
    args += ["--tangent-space", create.get("tangent_space_mode", nt.PROJECT_DEFAULT_TANGENT_SPACE)]
    usage_sets: list[str] = []
    for step in steps[1:]:
        if step["call"] != nt.BAKING_SET:
            continue
        a = step["args"]
        if "texture_set" in a:
            raise ComparisonError(f"{m['golden_id']}: step {step['step']} names a texture set")
        if a["parameter"] == "HipolyMesh":
            args += ["--high", str(inputs[a["input"]])]
            continue
        value = a["enum_label"] if "enum_label" in a else nt._value_text(a["value"])
        if "usage" in a:
            usage_sets.append(f"{a['usage']}:{a['parameter']}={value}")
        else:
            args += ["--set", f"{a['parameter']}={value}"]
    return args, usage_sets


def parse_result(data: bytes) -> NativeResult:
    """The texel classes and the AO and ID maps of a canonical result (`SerializeResult`)."""
    offset = 8
    if data[:8] == b"UZPBAKE4":
        offset = 11
        (count,) = struct.unpack_from("<Q", data, offset)
        offset += 8 + 2 * count
        (count,) = struct.unpack_from("<Q", data, offset)
        offset += 8 + 2 * count
    elif data[:8] != b"UZPBAKE3":
        raise ComparisonError("not a canonical bake result")
    width, height, _tile, rays, _subsampling, _dilation = struct.unpack_from("<6I", data, offset)
    offset += 24
    texels = width * height
    # AO's maps exist when rays are cast; the class arrays always.
    ao_texels = texels if rays else 0
    start = offset
    offset += 2 * ao_texels  # dilated AO (equal to the raw codes at DilationWidth 0)
    ao = np.frombuffer(data, "<u2", ao_texels, offset) if ao_texels else None
    offset += 2 * ao_texels
    classes = np.frombuffer(data, np.uint8, texels, offset)
    offset += 3 * texels + 4 * ao_texels  # classes, coverage, sub-sample hits, ray counts
    offset += 15 * 8 + 8  # class/sub-sample/ray counts, dilated texels
    maps = data[start:offset]
    offset += 8 + 3 + 8 + 16  # the distance record
    maps += data[offset:]
    id_labels = None
    while offset < len(data):
        tag = data[offset : offset + 4]
        offset += 4
        if tag == b"IDM1":
            (count,) = struct.unpack_from("<Q", data, offset)
            id_labels = np.frombuffer(data, "<u2", count, offset + 8).reshape(height, width)
            break
        if tag not in (b"WSN1", b"POS1", b"OPA1", b"HGT1", b"THK1"):
            raise ComparisonError(f"unexpected section {tag!r} at {offset - 4}")
        break  # one usage per bake: the other sections hold no map this tool compares
    return NativeResult(
        classes.reshape(height, width),
        None if ao is None else ao.reshape(height, width).astype(np.uint16),
        id_labels,
        maps,
    )


def bake(
    exe: Path, args: list[str], usage: str, out: Path, threads: int, metric: str | None
) -> tuple[NativeResult | None, str | None]:
    """The native result, or None and the refusal when the baker refuses the request."""
    command = [str(exe), "bake-files", *args, "--usage", usage, "--out", str(out)]
    if threads:
        command += ["--threads", str(threads)]
    if metric is not None:
        command += ["--box-size-metric", metric]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)
    if proc.returncode != 0:
        return None, proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "failed"
    return parse_result(out.read_bytes()), None


def golden_map(store: OracleStore, m: dict[str, Any]) -> dict[str, npt.NDArray[np.int64]]:
    """Each recording's PNG 16 export, by recording (`r1`, `r2`), as (height, width, channels)."""
    png_step = next(
        s["step"]
        for s in m["instruction_sequence"]["steps"]
        if s["call"] == nt.EXPORT and s["args"].get("file_format") == "png"
    )
    maps: dict[str, npt.NDArray[np.int64]] = {}
    for record in m["private_records"]:
        rid = record["record_id"]
        if record["kind"] != "exported_map" or not rid.endswith(f"-step{png_step}"):
            continue
        data = store.load(record["sha256"], record.get("size_bytes"))
        if data is None:
            raise ComparisonError(f"oracle_unavailable: {rid}")
        decoded = decode(data)
        if not decoded.integer or decoded.bits != 16:
            raise ComparisonError(f"{rid} is not a 16-bit PNG")
        maps[rid.split("-", 1)[0]] = decoded.values.astype(np.int64)
    if sorted(maps) != ["r1", "r2"]:
        raise ComparisonError(f"{m['golden_id']}: expected r1 and r2, found {sorted(maps)}")
    return maps


def _count(mask: Mask) -> int:
    return int(np.count_nonzero(mask))


def coverage(painter_hit: Mask, native: NativeResult) -> dict[str, int]:
    """Painter's nonzero texels against the native hits and the native covered texels."""
    native_hit = np.isin(native.texel_class, nt.HIT_CLASSES)
    covered = native.texel_class != UNCOVERED
    return {
        "painter_hit": _count(painter_hit),
        "native_hit": _count(native_hit),
        "painter_only": _count(painter_hit & ~native_hit),
        "native_only": _count(native_hit & ~painter_hit),
        "native_covered": _count(covered),
        "painter_outside_covered": _count(painter_hit & ~covered),
        "covered_without_painter": _count(covered & ~painter_hit),
    }


def ao_difference(oracle: npt.NDArray[np.int64], ao: npt.NDArray[np.uint16]) -> dict[str, Any]:
    delta = np.abs(oracle[..., 0] - ao.astype(np.int64))
    return {
        "differing_texels": _count(delta != 0),
        "max_abs": int(delta.max()),
        "exact": bool(not delta.any()),
    }


def _many_to_one(keys: npt.NDArray[np.int64], values: npt.NDArray[np.int64]) -> int:
    """Texels whose key meets more than one value."""
    pairs = np.unique(np.stack([keys, values], axis=1), axis=0)
    multi_keys, per_key = np.unique(pairs[:, 0], return_counts=True)
    bad = multi_keys[per_key > 1]
    return _count(np.isin(keys, bad))


def id_partition(oracle: npt.NDArray[np.int64], labels: npt.NDArray[np.uint16]) -> dict[str, Any]:
    """Whether the native labels split the texels Painter colours as Painter's colours do."""
    hit = labels != 0
    colours = oracle[hit]
    colour_key = (colours[:, 0] << 32) | (colours[:, 1] << 16) | colours[:, 2]
    label = labels[hit].astype(np.int64)
    split = _many_to_one(label, colour_key)
    merged = _many_to_one(colour_key, label)
    return {
        "labels": int(np.unique(label).size),
        "colours": int(np.unique(colour_key).size),
        "label_with_several_colours": split,
        "colour_with_several_labels": merged,
        "exact": split == 0 and merged == 0,
    }


def compare(
    store: OracleStore, exe: Path, name: str, out: Path, threads: int = 0
) -> dict[str, Any]:
    m = manifest(name)
    usage = usage_of(m)
    entry: dict[str, Any] = {"golden_id": m["golden_id"], "usage": usage}
    if usage in NOT_BAKED:
        entry["native"] = "not baked: the CPU baker has no Curvature"
        return entry
    oracle = golden_map(store, m)
    entry["oracle_stable"] = bool(np.array_equal(oracle["r1"], oracle["r2"]))
    common, usage_sets = bake_arguments(m)
    args = common + [a for s in usage_sets for a in ("--set", s)]
    metrics: tuple[str | None, ...] = nt.BOX_SIZE_METRICS if nt.relative_distances(m) else (None,)
    results: list[NativeResult] = []
    refusals: list[str] = []
    for metric in metrics:
        native, refusal = bake(exe, args, usage, out, threads, metric)
        if native is None:
            # A refused usage setting: the hit set comes from the shared stage without it.
            refusals.append(f"{usage} as recorded: {refusal}")
            native, refusal = bake(exe, common, usage, out, threads, metric)
        if native is None:
            # The usage's defaults are refused too: the shared stage's classes through Normal.
            refusals.append(f"{usage} at its defaults: {refusal}")
            entry["hit_set_from"] = "Normal"
            native, refusal = bake(exe, common, "Normal", out, threads, metric)
        if native is None:
            raise ComparisonError(f"{name}: bake-files refused the common request: {refusal}")
        results.append(native)
    if refusals:
        entry["refused"] = sorted(set(refusals))
    native = results[0]
    if len(results) > 1:
        entry["box_size_metric_independent"] = all(r.maps == native.maps for r in results[1:])
    for recording, codes in oracle.items():
        part: dict[str, Any] = {}
        part["coverage"] = coverage((codes != 0).any(axis=-1), native)
        if usage == "AO" and native.ao is not None and "refused" not in entry:
            part["map"] = ao_difference(codes, native.ao)
        if usage == "ID" and native.id_labels is not None:
            part["partition"] = id_partition(codes, native.id_labels)
        entry[recording] = part
    return entry


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.bake.usage_tier2b")
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--golden", action="append")
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--work", type=Path, default=REPO_ROOT / "tmp" / "scratch")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    store = locate()
    if store is None:
        print("oracle_unavailable: no private store on this machine", file=sys.stderr)
        return 2
    report = []
    for name in args.golden or goldens():
        out = args.work / f"usage-tier2b-{name}.bin"
        report.append(compare(store, args.exe, name, out, args.threads))
        out.unlink(missing_ok=True)
    text = json.dumps(report, indent=2) + "\n"
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
