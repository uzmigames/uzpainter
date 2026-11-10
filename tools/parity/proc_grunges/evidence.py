"""Separating evidence of the grunge diagnostic goldens (item 2.4), numbers only.

    python -m tools.parity.proc_grunges.evidence

Reads the admitted diagnostic goldens of `goldens.py` from the private store and prints, per
grunge, statistics that say what kind of function Painter's output is. No texel value, image or
readback leaves the store; the printed numbers are counts, fractions and maxima:

- `r1_r2_differing`: texels where the two recordings of a case differ.
- `seed`: seed 1 against seed 2 at 1024: the texels they differ on, the largest difference,
  and the best cyclic translation of seed 2 onto seed 1 (from the phase correlation peak) with
  the texels that translation leaves different. A seed that only moves a fixed texture is a
  translation with nothing left.
- `levels`: the number of distinct values at seed 1, 1024, and how many of them lie on the
  8-bit and 16-bit grids (k / 255, k / 65535).
- `resolution`: seed 1 at 2048 against seed 1 at 1024: the texels where the 1024 output differs
  from each 2 x 2 sample of the 2048 one and from their mean. A resolution-independent texture
  sampled at texel centres would make one of them small.
- `wrap`: the largest difference across the left/right and top/bottom borders against the largest
  difference between neighbouring texels inside: a texture that tiles keeps its border step in
  the inside range.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.decode import decode_exr
from tools.parity.proc_grunges.goldens import recorded
from tools.parity.proc_grunges.requests import FAMILY, Golden
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, locate

Floats = npt.NDArray[np.float32]
DEFAULT_SEED = -1  # the case left the seed at the source's default (or the source has none)


def records(golden: Golden) -> dict[str, Mapping[str, Any]]:
    path = manifest_root(current_envelope(REPO_ROOT), REPO_ROOT) / FAMILY / f"{golden.name}.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return {record["record_id"]: record for record in manifest["private_records"]}


def user_record(found: Mapping[str, Mapping[str, Any]], run: str, k: int) -> Mapping[str, Any]:
    matches = [
        r for rid, r in found.items() if rid.startswith(f"{run}-") and rid.endswith(f"-user{k}")
    ]
    if len(matches) != 1:
        raise ValueError(f"{run} user{k}: {len(matches)} records")
    return matches[0]


def exr(store: OracleStore, record: Mapping[str, Any]) -> Floats:
    data = store.load(record["sha256"], record["size_bytes"])
    if data is None:
        raise ValueError(f"{record['record_id']}: oracle unavailable")
    values = np.asarray(decode_exr(data).values, dtype=np.float32)
    return values[..., 0] if values.ndim == 3 else values


def load(store: OracleStore) -> tuple[dict[tuple[str, int, int], Floats], dict[str, int]]:
    images: dict[tuple[str, int, int], Floats] = {}
    unstable: dict[str, int] = {}
    for golden in recorded():
        found = records(golden)
        for k, case in enumerate(golden.cases):
            r1 = exr(store, user_record(found, "r1", k))
            r2 = exr(store, user_record(found, "r2", k))
            seed = DEFAULT_SEED if case.seed is None else case.seed
            images[(case.asset, golden.resolution, seed)] = r1
            unstable[case.asset] = unstable.get(case.asset, 0) + int((r1 != r2).sum())
    return images, unstable


def best_translation(a: Floats, b: Floats) -> tuple[int, int, int]:
    """The cyclic shift (dy, dx) of b that best matches a (phase correlation), and the texels
    that shift leaves different."""
    fa = np.fft.rfft2(a - a.mean())
    fb = np.fft.rfft2(b - b.mean())
    cross = fa * np.conj(fb)
    cross /= np.maximum(np.abs(cross), 1e-30)
    surface = np.fft.irfft2(cross, s=a.shape)
    dy, dx = np.unravel_index(int(np.argmax(surface)), surface.shape)
    shifted = np.roll(b, (int(dy), int(dx)), axis=(0, 1))
    return int(dy), int(dx), int((shifted != a).sum())


def on_grid(values: Floats, levels: int) -> int:
    scaled = values.astype(np.float64) * levels
    return int((np.abs(scaled - np.round(scaled)) < 1e-6).sum())


def wrap(image: Floats) -> dict[str, float]:
    inside = max(
        float(np.abs(np.diff(image, axis=0)).max()), float(np.abs(np.diff(image, axis=1)).max())
    )
    border = max(
        float(np.abs(image[0] - image[-1]).max()), float(np.abs(image[:, 0] - image[:, -1]).max())
    )
    return {"inside_max_step": inside, "border_max_step": border}


def seed_effect(a: Floats, b: Floats) -> dict[str, Any]:
    dy, dx, left = best_translation(a, b)
    return {
        "differing": int((a != b).sum()),
        "max_abs": float(np.abs(a - b).max()),
        "best_translation": [dy, dx],
        "differing_after_translation": left,
    }


def asset_evidence(images: Mapping[tuple[str, int, int], Floats], asset: str) -> dict[str, Any]:
    base_seed = 1 if (asset, 1024, 1) in images else DEFAULT_SEED
    base, high = images[(asset, 1024, base_seed)], images[(asset, 2048, base_seed)]
    seeds: dict[str, Any] = {}
    if (asset, 1024, 2) in images:
        seeds["seed_1_vs_2"] = seed_effect(base, images[(asset, 1024, 2)])
    if base_seed == 1 and (asset, 1024, DEFAULT_SEED) in images:
        seeds["default_vs_1"] = seed_effect(images[(asset, 1024, DEFAULT_SEED)], base)
    distinct = np.unique(base)
    samples = {
        f"sample_{oy}{ox}": int((high[oy::2, ox::2] != base).sum())
        for oy in (0, 1)
        for ox in (0, 1)
    }
    mean = (high[0::2, 0::2] + high[0::2, 1::2] + high[1::2, 0::2] + high[1::2, 1::2]) / 4
    return {
        "has_seed": base_seed == 1,
        "texels_1024": int(base.size),
        "range": [float(base.min()), float(base.max())],
        "mean": float(base.mean()),
        "seed": seeds,
        "levels": {
            "distinct": int(distinct.size),
            "on_8bit_grid": on_grid(distinct, 255),
            "on_16bit_grid": on_grid(distinct, 65535),
        },
        "resolution": {
            **samples,
            "mean_2x2_max_abs": float(np.abs(mean - base).max()),
            "mean_2x2_mean_abs": float(np.abs(mean - base).mean()),
        },
        "wrap_1024": wrap(base),
    }


def main() -> int:
    store = locate()
    if store is None:
        print("no private store on this machine", file=sys.stderr)
        return 2
    images, unstable = load(store)
    assets = sorted({asset for asset, _, _ in images})
    report = {
        asset: {"r1_r2_differing": unstable[asset], **asset_evidence(images, asset)}
        for asset in assets
    }
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
