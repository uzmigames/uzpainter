"""CPU-only scoring of ring policies on the Wand v1 (item 2.7), as `padding_corpus.py` does on the
kernel probes.

The Wand's tap values are Painter's own covered texels of its r1 export (`phase1/tier1/wand-v1`),
which UzPainter's covered texels equal exactly. Each ring texel's chain (`padding_reference.py`
under a policy) runs on the channels' document operands, then is stored and written as the export
does (`src/export/encode.cpp`): BaseColor sRGB8 (operand `kSrgb8DecodeBits`, store
`kSrgb8ThresholdBits`, 16-bit codes `kOcioSrgbPng16`, as OCIO writes them), Roughness and
Metallic L8 (k / 255, `WriteUnorm` at 8 bits, times 257). Those three maps are predicted exactly.
The Height (L16F) operand cannot be recovered from its PNG 16 code, and the Normal is derived from
the Height, so for them only the texels whose chain (taps and fractions) a policy changes against
the first policy are counted, split by whether `--measured` (UzPainter's PNG 16 files of the
first policy's diagnostic measure, `test_wand_measure.py`) misses Painter there.

Stdout carries counts only; residual coordinates go to the optional private `--out` file.

    python -m tools.parity.fit.padding_wand [--policy baseline --policy baseline+patch]
        [--measured tmp/scratch/wand-ours-{map}.png]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.fit.decode import decode
from tools.parity.fit.oracle import load
from tools.parity.fit.padding_corpus import PATCHES, reference_text
from tools.parity.fit.plane_transform_diagnostic import load_module
from tools.parity.recorder.script_run import load_script_job
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import locate
from tools.parity.verdict import resolve_golden

GOLDEN_ID = "phase1/tier1/wand-v1"
MATERIAL = "11-Varinha-Madeira"
MESH_INPUT = "wand-mesh"
SIZE = 2048
ASSETS3D = Path(os.environ.get("UZP_TEST_ASSETS3D", r"E:\UzmiGames\Assets3D"))
EXACT = ("BaseColor", "Roughness", "Metallic")
CHAINED = ("Height", "Normal")
F32 = np.float32
type Codes = npt.NDArray[np.int64]
type Point = tuple[int, int]


def source_table(path: str, name: str) -> list[int]:
    """The integer table `name` of the C++ source `path` (repository relative)."""
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    body = text[text.index(name) :]
    body = body[body.index("{") + 1 : body.index("};")]
    return [int(x.rstrip("uU"), 0) for x in re.findall(r"0x[0-9A-Fa-f]+u?|\d+u?", body)]


def write_unorm(v: np.float32, bits: int) -> int:
    """arith::WriteUnorm: clamped to [0, 1], truncated to bits + 4 fractional bits, nearest code
    with ties down."""
    c = F32(min(max(float(v), 0.0), 1.0)) if v == v else F32(0.0)
    j = int(F32(c * F32(1 << (bits + 4))))
    return (j * ((1 << bits) - 1) + (1 << (bits + 3)) - 1) >> (bits + 4)


class Channel:
    """A document channel's operand of a covered 16-bit code and its written code of a padded
    operand."""

    def __init__(self, kind: str, srgb_codes: Codes | None = None) -> None:
        self.kind = kind
        if kind == "sRGB8":
            assert srgb_codes is not None
            arith = "src/evaluator/arith.cpp"
            decode_bits = np.array(source_table(arith, "kSrgb8DecodeBits[256]"), np.uint32)
            self.decoded = decode_bits.view(F32)
            thresholds = np.array(source_table(arith, "kSrgb8ThresholdBits[255]"), np.uint32)
            self.thresholds = thresholds.view(F32).astype(np.float64)
            self.codes = srgb_codes
            self.index = {int(c): k for k, c in enumerate(srgb_codes)}

    def operand(self, code: int) -> np.float32:
        if self.kind == "L8":
            if code % 257:
                raise ValueError("an L8 channel's code is not k * 257")
            return F32(float(code // 257) / 255.0)
        return F32(self.decoded[self.index[code]])

    def written(self, v: np.float32) -> int:
        if self.kind == "L8":
            return write_unorm(v, 8) * 257
        c = min(max(float(v), 0.0), 1.0) if v == v else 0.0
        return int(self.codes[int(np.searchsorted(self.thresholds, float(F32(c)), side="right"))])


def painter_maps() -> dict[str, Codes]:
    """Painter's r1 Wand maps by map name (`BaseColor`, ...), H x W x C codes."""
    resolved = resolve_golden(GOLDEN_ID)
    if resolved is None:
        raise ValueError(f"{GOLDEN_ID} is not admitted")
    golden = load(locate(), resolved.manifest_path)
    out: dict[str, Codes] = {}
    for output_id, output in sorted(golden.recordings["r1"].outputs.items()):
        if output.get("kind") == "exported_map" and output.get("texture_set") == MATERIAL:
            values = golden.map("r1", output_id).values
            out[str(output.get("map")).rsplit("_", 1)[1]] = (
                values if values.ndim == 3 else values[..., None]
            )
    return out


def wand_mesh() -> Path:
    """The Wand's OBJ, the golden's pinned `wand-mesh` input."""
    resolved = resolve_golden(GOLDEN_ID)
    assert resolved is not None
    return Path(load_script_job(resolved.manifest_path, ASSETS3D).inputs[MESH_INPUT].file)


def reference(policy: str) -> Any:
    """The reference under `policy`: `baseline` or `git:<revision>`, then `+`-joined PATCHES of
    `padding_corpus`."""
    base, *patches = policy.split("+")
    if base == "baseline" and not patches:
        return load_module(REPO_ROOT / "tests/export/padding_reference.py", "wand_ref")
    if base != "baseline" and not base.startswith("git:"):
        raise ValueError(f"unknown reference {base}")
    text = reference_text(None if base == "baseline" else base[4:])
    for name in patches:
        for old, new in PATCHES[name]:
            if text.count(old) != 1:
                raise ValueError(f"patch {name} does not apply")
            text = text.replace(old, new)
    module = types.ModuleType(f"wand_ref_{abs(hash(policy))}")
    exec(compile(text, f"padding_reference@{policy}", "exec"), module.__dict__)
    return module


def chains(policy: str, mesh: Path) -> tuple[Any, dict[Point, tuple[list[Point], list[float]]]]:
    """Each ring texel's chain under `policy`: its tap texels and fractions."""
    ref = reference(policy)
    ring = ref.Ring(mesh, MATERIAL, SIZE, SIZE)
    out: dict[Point, tuple[list[Point], list[float]]] = {}
    for x, y, candidates, count in ring.texels():
        taps = candidates[:count]
        fractions = ring.chain_fractions(x, y, taps)
        out[(x, y)] = ([c[2] for c in taps], [float(t) for t in fractions])
    return ref, out


def score(policies: tuple[str, ...], measured: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    painter = painter_maps()
    srgb = np.array(source_table("src/export/encode.cpp", "kOcioSrgbPng16[256]"), np.int64)
    if not set(np.unique(painter["BaseColor"]).tolist()) <= set(srgb.tolist()):
        raise ValueError("a covered BaseColor code is not an OCIO sRGB8 code")
    kinds = {
        "BaseColor": Channel("sRGB8", srgb),
        "Roughness": Channel("L8"),
        "Metallic": Channel("L8"),
    }
    ours: dict[str, Codes] = {}
    if measured is not None:
        for name in CHAINED:
            values = decode(Path(measured.format(map=name)).read_bytes()).values
            ours[name] = values if values.ndim == 3 else values[..., None]
    mesh = wand_mesh()
    counts: dict[str, Any] = {}
    private: dict[str, Any] = {}
    first: dict[Point, tuple[list[Point], list[float]]] | None = None
    first_misses: dict[str, set[Point]] = {}
    for policy in policies:
        ref, ring = chains(policy, mesh)
        misses: dict[str, set[Point]] = {}
        for name in EXACT:
            channel, codes = kinds[name], painter[name]
            missed: set[Point] = set()
            for (x, y), (taps, fractions) in ring.items():
                t = [F32(f) for f in fractions]
                for c in range(codes.shape[-1]):
                    operands = [channel.operand(int(codes[ty, tx, c])) for tx, ty in taps]
                    if channel.written(ref.chain(operands, t)) != int(codes[y, x, c]):
                        missed.add((x, y))
                        break
            misses[name] = missed
        row: dict[str, Any] = {name: len(misses[name]) for name in EXACT}
        union = set().union(*misses.values())
        row["union_exact"] = len(union)
        if first is None:
            first, first_misses = ring, misses
            if ours:
                for name in CHAINED:
                    differs = np.any(ours[name] != painter[name], axis=-1)
                    row[f"{name}_measured"] = sum(1 for x, y in ring if differs[y, x])
        else:
            if set(ring) != set(first):
                raise ValueError("ring population differs")
            for name in EXACT:
                row[f"{name}_fixed"] = len(first_misses[name] - misses[name])
                row[f"{name}_new"] = len(misses[name] - first_misses[name])
            changed = {p for p in ring if ring[p] != first[p]}
            row["chains_changed"] = len(changed)
            for name in CHAINED:
                if ours:
                    differs = np.any(ours[name] != painter[name], axis=-1)
                    hit = sum(1 for x, y in changed if differs[y, x])
                    row[f"{name}_changed_at_miss"] = hit
                    row[f"{name}_changed_at_match"] = len(changed) - hit
            private[f"{policy}:changed"] = sorted(changed)
        counts[policy] = row
        private[policy] = {name: sorted(m) for name, m in misses.items()}
    return counts, private


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", action="append")
    parser.add_argument(
        "--measured", help="UzPainter's PNG 16 files of the first policy, with {map} in the path"
    )
    parser.add_argument("--out", type=Path, help="private JSON file for residual coordinates")
    args = parser.parse_args(argv)
    counts, private = score(tuple(args.policy or ("baseline",)), args.measured)
    for policy, row in counts.items():
        print(json.dumps({"policy": policy, **row}, sort_keys=True), flush=True)
    if args.out is not None:
        args.out.write_text(json.dumps(private), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
