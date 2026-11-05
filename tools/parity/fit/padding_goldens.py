"""CPU-only scoring of the `infinite` padding reference on the recorded islanded goldens
(`phase3.1_export-island-padding` item 2.1).

Every `infinite` OpenEXR 32f map of `GOLDENS`, r1 and r2, is padded by
`tests/export/padding_reference.py` (under a policy, as `padding_corpus.py` names them) from
Painter's own covered texels of that file, then compared with the file bit for bit on every texel.

- **Operands and store** (decision 274, `src/export/encode.cpp` `DocumentValue`): a ring texel's
  chain runs on the covered texels' values, which an OpenEXR 32f export writes unchanged as the
  document's operands; the result is stored as the document channel stores it and read back
  (`src/evaluator/cpu_store.cpp` `StoreValue`, `OperandOf`). Each component's document format is
  the coarsest of sRGB8, UNORM8, UNORM16, half and float32 whose operands hold every covered
  value of that component (`detect`), printed with the counts.
- **Virtual normals** (`Normal_OpenGL`, `Normal_DirectX`) are padded by decision 287's rule
  (`island_normal`), the measure export's; their covered island-edge texels are item 2.2's.
- **Classes.** Covered (kept), ring (an uncovered texel with a covered 8-neighbour, x wrapping)
  and gutter (decision 197's jump flood). A gutter miss is `own` when the flood over Painter's own
  ring values misses it too; every other gutter miss is inherited from a ring miss.

Stdout carries counts only; residual coordinates go to the optional private `--out` file, never
into the repository. No capture, fitting or admission.

    python -m tools.parity.fit.padding_goldens [--policy baseline] [--golden export-padding]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import types
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.oracle import Golden, load
from tools.parity.fit.padding_corpus import PATCHES, reference_text, ring_points
from tools.parity.fit.padding_wand import source_table, write_unorm
from tools.parity.fit.plane_transform_diagnostic import load_module
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import locate

# Item 2.1's recorded islanded goldens (tier0/semantics), in decision 220's table order.
GOLDENS = (
    "export-padding",
    "export-padding-bevelled-cube",
    "export-padding-sphere",
    "export-padding-seam-256",
    "export-padding-seam-1024",
    "export-padding-seam-field-256",
    "export-padding-seam-field-1024",
    "export-padding-seam-ramp-1024",
)
MESHES = REPO_ROOT / "parity" / "fixtures" / "tier0-semantics" / "meshes"
VIRTUAL_NORMALS = ("Normal_OpenGL", "Normal_DirectX")
F32 = np.float32
type Mask = npt.NDArray[np.bool_]
type Image = npt.NDArray[np.float32]


# ── The document stores (src/evaluator/arith.cpp, cpu_store.cpp) ───────────────────────────────


def half_toward_zero(v: np.float32) -> np.float32:
    """arith::HalfTowardZero, read back as a float (finite values)."""
    h = np.float16(v)
    if abs(float(h)) > abs(float(v)):
        h = np.nextafter(h, np.float16(0.0))
    return F32(h)


class Format:
    """A document channel format: whether a value is one of its operands (`holds`), and a value
    stored in it and read back (`value`)."""

    def __init__(
        self,
        name: str,
        holds: Callable[[np.float32], bool],
        value: Callable[[np.float32], np.float32],
    ) -> None:
        self.name, self.holds, self.value = name, holds, value


def _unorm(bits: int) -> Format:
    m = (1 << bits) - 1

    def holds(v: np.float32) -> bool:
        k = round(float(v) * m)
        return 0 <= k <= m and F32(k / m) == v

    def value(v: np.float32) -> np.float32:
        return F32(write_unorm(v, bits) / m)

    return Format(f"UNORM{bits}", holds, value)


def formats() -> list[Format]:
    """sRGB8, UNORM8, UNORM16, half and float32, coarsest first."""
    arith = "src/evaluator/arith.cpp"
    decoded = np.array(source_table(arith, "kSrgb8DecodeBits[256]"), np.uint32).view(F32)
    thresholds = (
        np.array(source_table(arith, "kSrgb8ThresholdBits[255]"), np.uint32)
        .view(F32)
        .astype(np.float64)
    )
    srgb = {int(b) for b in decoded.view(np.uint32)}

    def srgb_value(v: np.float32) -> np.float32:
        c = min(max(float(v), 0.0), 1.0) if v == v else 0.0
        return F32(decoded[int(np.searchsorted(thresholds, float(F32(c)), side="right"))])

    return [
        Format("sRGB8", lambda v: int(np.array([v], F32).view(np.uint32)[0]) in srgb, srgb_value),
        _unorm(8),
        _unorm(16),
        Format("half", lambda v: bool(F32(np.float16(v)) == v), half_toward_zero),
        Format("float32", lambda v: True, F32),
    ]


# Painter's channel formats by recorder name (`Stack.add_channel`), and the project's defaults
# for the channels these goldens fill without adding them.
CHANNEL_FORMATS = {
    "L8": "UNORM8",
    "RGB8": "UNORM8",
    "sRGB8": "sRGB8",
    "L16": "UNORM16",
    "RGB16": "UNORM16",
    "L16F": "half",
    "RGB16F": "half",
    "L32F": "float32",
    "RGB32F": "float32",
}
DEFAULT_CHANNELS = {
    "basecolor": "sRGB8",
    "height": "L16F",
    "specularroughness": "L8",
    "roughness": "L8",
    "metallic": "L8",
}


def channel_formats(golden: Golden) -> dict[str, str]:
    """Map name (`basecolor`, `user0`, ...) -> its document format's name."""
    named = dict(DEFAULT_CHANNELS)
    for step in golden.manifest["instruction_sequence"]["steps"]:
        if step["call"].endswith("Stack.add_channel"):
            named[str(step["args"]["channel"]).lower()] = str(step["args"]["format"])
    return {k: CHANNEL_FORMATS[v] for k, v in named.items()}


def detect(
    values: Image, covered: Mask, table: list[Format], named: str | None = None
) -> list[Format]:
    """Per component, the format `named` (which must hold every covered value), or without a name
    the coarsest format whose operands hold every covered value."""
    out = []
    for c in range(values.shape[-1]):
        distinct = np.unique(values[..., c][covered])
        fits = [f for f in table if all(f.holds(F32(v)) for v in distinct)]
        if named is None:
            out.append(fits[0])
        elif named in {f.name for f in fits}:
            out.append(next(f for f in fits if f.name == named))
        else:
            raise ValueError(f"a covered value is not a {named} operand")
    return out


# ── The reference and the goldens ───────────────────────────────────────────────────────────────


def reference(policy: str) -> Any:
    """The reference module under `policy`: `baseline` (the working tree) or `git:<revision>`,
    then `+`-joined `padding_corpus.PATCHES`."""
    base, *patches = policy.split("+")
    if base != "baseline" and not base.startswith("git:"):
        raise ValueError(f"unknown reference {base}")
    if policy == "baseline":
        return load_module(REPO_ROOT / "tests/export/padding_reference.py", "ref_goldens")
    text = reference_text(None if base == "baseline" else base[4:])
    for name in patches:
        for old, new in PATCHES[name]:
            if text.count(old) != 1:
                raise ValueError(f"patch {name} does not apply")
            text = text.replace(old, new)
    module = types.ModuleType("ref_goldens_patched")
    exec(compile(text, f"padding_reference@{policy}", "exec"), module.__dict__)
    return module


def mesh_of(golden: Golden) -> Path:
    for step in golden.manifest["instruction_sequence"]["steps"]:
        if step["call"].endswith("project.create"):
            return MESHES / f"{step['args']['mesh']}.obj"
    raise ValueError(f"{golden.golden_id}: no project.create step")


def infinite_exr32(golden: Golden) -> list[tuple[str, str, str]]:
    """(recording, output id, map) of every `infinite` OpenEXR 32f map, r1 then r2."""
    steps = {s["step"]: s["args"] for s in golden.manifest["instruction_sequence"]["steps"]}
    out = []
    for recording in sorted(golden.recordings):
        for oid, o in sorted(golden.recordings[recording].outputs.items()):
            if o["kind"] != "exported_map":
                continue
            fmt = o["storage_format"]
            if (
                steps[o["export_settings"]["step"]].get("padding") == "infinite"
                and fmt["container"] == "exr"
                and fmt["bits_per_channel"] == 32
            ):
                out.append((recording, oid, str(o["map"])))
    return out


def ring_mask(covered: Mask) -> Mask:
    """The uncovered texels with a covered 8-neighbour (x wrapping)."""
    ring = np.zeros_like(covered)
    for x, y in ring_points(covered):
        ring[y, x] = True
    return ring


def differs(a: Image, b: Image) -> Mask:
    result: Mask = np.any(a.view(np.uint32) != b.view(np.uint32), axis=-1)
    return result


def score(name: str, policy: str) -> dict[str, Any]:
    """Per map (recording, output): texels differing by class, the formats, and r1/r2 stability."""
    store = locate()
    if store is None:
        raise ValueError("store unavailable")
    root = manifest_root(current_envelope()) / "tier0" / "semantics"
    golden = load(store, root / f"{name}.json")
    ref = reference(policy)
    table = formats()
    named = channel_formats(golden)
    outputs = infinite_exr32(golden)
    if not outputs:
        raise ValueError(f"{name}: no infinite OpenEXR 32f map")
    first = golden.map(outputs[0][0], outputs[0][1]).values
    height, width = first.shape[:2]
    material = str(golden.output(outputs[0][0], outputs[0][1])["texture_set"]).split("/")[0]
    ring = ref.Ring(mesh_of(golden), material, width, height)
    covered: Mask = ring.owner >= 0
    rings = ring_mask(covered)
    gutter = ~covered & ~rings
    chains = []
    for x, y, cands, taps in ring.texels():
        chosen = cands[:taps]
        chains.append((x, y, [t for _, _, t in chosen], ring.chain_fractions(x, y, chosen)))
    seed = covered | rings
    rows: list[dict[str, Any]] = []
    misses: dict[str, list[list[int]]] = {}
    painter_by_output: dict[str, Image] = {}
    for recording, oid, map_name in outputs:
        decoded = golden.map(recording, oid).values
        painter: Image = (decoded if decoded.ndim == 3 else decoded[..., None]).astype(F32)
        painter_by_output[f"{recording}/{oid}"] = painter
        if map_name in VIRTUAL_NORMALS:
            predicted: Image = ref.island_normal(painter, covered)
            kinds = ["normal"]
        else:
            stores = detect(painter, covered, table, named.get(map_name.lower()))
            kinds = [f.name for f in stores]
            out = painter.copy()
            for x, y, taps, t in chains:
                for c, fmt in enumerate(stores):
                    m = ref.chain([painter[ty, tx, c] for tx, ty in taps], t, True)
                    out[y, x, c] = fmt.value(m)
            predicted = ref.flood(out, seed)
        bad = differs(predicted, painter)
        own_flood = differs(ref.flood(painter.copy(), seed), painter) & gutter
        rows.append(
            {
                "recording": recording,
                "output": oid,
                "map": map_name,
                "formats": kinds,
                "covered": int(covered.sum()),
                "ring": int(rings.sum()),
                "gutter": int(gutter.sum()),
                "covered_differing": int((bad & covered).sum()),
                "ring_differing": int((bad & rings).sum()),
                "gutter_differing": int((bad & gutter).sum()),
                "gutter_own": int(own_flood.sum()),
                "exact": not bool(bad.any()),
            }
        )
        ys, xs = np.nonzero(bad & rings)
        misses[f"{recording}/{oid}"] = [[int(x), int(y)] for x, y in zip(xs, ys, strict=True)]
    stable = {}
    for key, values in painter_by_output.items():
        recording, oid = key.split("/", 1)
        if recording == "r1" and f"r2/{oid}" in painter_by_output:
            stable[oid] = not bool(differs(values, painter_by_output[f"r2/{oid}"]).any())
    return {
        "golden": name,
        "size": [width, height],
        "maps": rows,
        "r1_equals_r2": stable,
        "ring_misses": misses,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--policy", default="baseline")
    parser.add_argument("--golden", action="append", choices=GOLDENS)
    parser.add_argument("--out", type=Path, help="private JSON file for residual coordinates")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 4))
    args = parser.parse_args(argv)
    names = tuple(args.golden or GOLDENS)
    with ProcessPoolExecutor(max_workers=min(args.jobs, len(names))) as pool:
        results = list(pool.map(score, names, [args.policy] * len(names)))
    keys = ("ring_differing", "gutter_differing", "gutter_own", "covered_differing")
    total = dict.fromkeys(keys, 0)
    for result in results:
        stable = result["r1_equals_r2"]
        print(
            f"{result['golden']} {result['size'][0]}x{result['size'][1]} "
            f"r1=r2 {sum(stable.values())}/{len(stable)}"
        )
        for row in result["maps"]:
            print(
                f"  {row['recording']} {row['output']:<40} {'/'.join(row['formats']):<24} "
                f"ring {row['ring_differing']:>6}/{row['ring']:<6} gutter "
                f"{row['gutter_differing']:>8}/{row['gutter']:<8} (own {row['gutter_own']}) "
                f"covered {row['covered_differing']}"
            )
            for key in keys:
                total[key] += row[key]
    print("total", json.dumps(total))
    if args.out is not None:
        args.out.write_text(json.dumps(results), encoding="utf-8")
    exact = all(row["exact"] for result in results for row in result["maps"])
    print("exact on every texel" if exact else "not exact")
    return 0 if exact else 1


if __name__ == "__main__":
    sys.exit(main())
