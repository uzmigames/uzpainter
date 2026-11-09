"""Candidate fits of Painter's Normal bake residue (phase3.2_baker-normal, task notes section 11).

    python -m tools.bake.normal_fit --exe <uzp-bake-feasibility-tests.exe> [--work DIR]

The native driver dumps each golden's low parts as the baker receives them (`bake-files
--dump-low`: positions, normals, UVs, indices and per-corner MikkTSpace tangents). This tool
recomputes the Normal map of the hemisphere and sphere goldens in numpy under named candidate
rules and counts, per candidate, the texels whose three codes equal Painter's. It prints counts
only; no private value leaves the store.

Candidates:
- the texel samples: `inclusive` (the texel centre's exact UV barycentrics, edges included, the
  lowest triangle first) or `decision-408` (the snapped texel-space triangle and its top-left
  rule, as the native baker samples);
- the arithmetic of the frame and of the inverse transform: float32 (the native baker's order)
  or float64.

The hemisphere's high is faceted, so a texel's high normal is its facet's: the facet is found by a
double-precision ray from the native distances. Texels whose ray meets a facet edge exactly (a
tie Painter breaks differently) are counted apart. The sphere is baked low as high; its candidates
take the high normal at the sample itself, as Painter's map does not depend on the ray
(`normal-sphere` equals `normal-sphere-absolute-0-01` and `-0-05`).
"""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.bake import normal_tier2b as nt
from tools.parity.coverage import snapped
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import locate

F32, F64 = np.float32, np.float64
Array = npt.NDArray[Any]
SIZE = 512


def read_low_dump(data: bytes) -> list[dict[str, Array]]:
    """The `UZPLOW1` dump of `bake-files --dump-low`."""
    if data[:7] != b"UZPLOW1":
        raise ValueError("not a UZPLOW1 dump")
    offset = 7

    def count() -> int:
        nonlocal offset
        (value,) = struct.unpack_from("<Q", data, offset)
        offset += 8
        return int(value)

    def array(dtype: str, width: int) -> Array:
        nonlocal offset
        n = count()
        out = np.frombuffer(data, dtype, n * width, offset).reshape(n, width)
        offset += np.dtype(dtype).itemsize * n * width
        return out

    parts = []
    for _ in range(count()):
        n = count()
        name = data[offset : offset + n].decode("utf-8")
        offset += n
        pos, nor, uv = array("<f4", 3), array("<f4", 3), array("<f4", 2)
        idx = array("<u4", 1)[:, 0].reshape(-1, 3)
        tan = array("<f4", 4).reshape(-1, 3, 4)
        parts.append(
            {"name": np.array(name), "pos": pos, "nor": nor, "uv": uv, "idx": idx, "tan": tan}
        )
    return parts


def _cross2(a: Array, b: Array, px: Array, py: Array) -> Array:
    result: Array = (b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0])
    return result


def samples(part: dict[str, Array], rule: str) -> tuple[Array, Array]:
    """Per texel the sampled triangle (-1: none) and its barycentric weights (float64)."""
    tri_of = np.full((SIZE, SIZE), -1, np.int64)
    weights = np.zeros((SIZE, SIZE, 3))
    uv = part["uv"][part["idx"]].astype(F64)
    if rule == "decision-408":
        corners = snapped(uv, SIZE, SIZE)
    else:
        corners = np.stack([uv[..., 0] * SIZE, (1.0 - uv[..., 1]) * SIZE], -1)
    for t, p in enumerate(corners):
        area = float(_cross2(p[0], p[1], p[2][0], p[2][1]))
        if area == 0.0:
            continue
        x0 = int(max(0, np.floor(p[:, 0].min()) - 1))
        x1 = int(min(SIZE - 1, np.floor(p[:, 0].max()) + 1))
        y0 = int(max(0, np.floor(p[:, 1].min()) - 1))
        y1 = int(min(SIZE - 1, np.floor(p[:, 1].max()) + 1))
        px = (np.arange(x0, x1 + 1) + 0.5)[None, :]
        py = (np.arange(y0, y1 + 1) + 0.5)[:, None]
        e = [_cross2(p[1], p[2], px, py), _cross2(p[2], p[0], px, py), _cross2(p[0], p[1], px, py)]
        sign = 1.0 if area > 0 else -1.0
        inside = np.ones(np.broadcast_shapes(px.shape, py.shape), bool)
        for k, (f, to) in enumerate(((1, 2), (2, 0), (0, 1))):
            w = sign * e[k]
            if rule == "decision-408":
                dx, dy = sign * (p[to][0] - p[f][0]), sign * (p[to][1] - p[f][1])
                tie = bool(dy < 0 or (dy == 0 and dx < 0))
                inside &= (w > 0) | ((w == 0) & tie)
            else:
                inside &= w >= 0
        window = tri_of[y0 : y1 + 1, x0 : x1 + 1]
        take = inside & (window < 0)
        window[take] = t
        weights[y0 : y1 + 1, x0 : x1 + 1][take] = np.stack([x / area for x in e], -1)[take]
    return tri_of, weights


def _cross(a: Array, b: Array) -> Array:
    return np.stack(
        [
            a[..., 1] * b[..., 2] - a[..., 2] * b[..., 1],
            a[..., 2] * b[..., 0] - a[..., 0] * b[..., 2],
            a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0],
        ],
        -1,
    )


def _dot(a: Array, b: Array) -> Array:
    result: Array = a[..., 0] * b[..., 0] + a[..., 1] * b[..., 1] + a[..., 2] * b[..., 2]
    return result


def _blend(values: Array, w: Array, dtype: Any) -> Array:
    v, w = values.astype(dtype), w.astype(dtype)
    result: Array = v[:, 0] * w[:, 0:1] + v[:, 1] * w[:, 1:2] + v[:, 2] * w[:, 2:3]
    return result


def _normalize(v: Array, dtype: Any) -> Array:
    v = v.astype(dtype)
    result: Array = v * (dtype(1) / np.sqrt(_dot(v, v)))[..., None]
    return result


def encode(x: Array) -> Array:
    """The native float32 encoding (`06-baking.md` section 3.2)."""
    e = np.clip(x.astype(F32) * F32(0.5) + F32(0.5), F32(0), F32(1))
    result: Array = np.floor(e * F32(65535) + F32(0.5)).astype(np.int64)
    return result


def tangent_codes(
    part: dict[str, Array], tri: Array, w: Array, h: Array, mode: str, dtype: Any
) -> Array:
    """Codes of `h` in the interpolated frame (PerVertex or PerFragment), inverse transform."""
    normals = part["nor"][part["idx"][tri]]
    tangents = part["tan"][tri]
    t, s = tangents[..., :3], tangents[..., 3]
    wf = w.astype(F32)
    v_t, v_n = _blend(t, wf, dtype), _blend(normals, wf, dtype)
    if mode == "PerVertex":
        corner_b = _cross(normals.astype(dtype), t.astype(dtype)) * s.astype(dtype)[..., None]
        v_b = _blend(corner_b, wf, dtype)
    else:
        sign = _blend(s[..., None], wf, dtype)[..., 0]
        v_b = _cross(v_n, v_t) * np.where(sign < 0, -1, 1).astype(dtype)[..., None]
    r0, r1, r2 = _cross(v_b, v_n), _cross(v_n, v_t), _cross(v_t, v_b)
    orient = np.where(_dot(v_t, r0) < 0, -1, 1).astype(dtype)[:, None]
    hd = h.astype(dtype)
    v = _normalize(np.stack([_dot(hd, r0), _dot(hd, r1), _dot(hd, r2)], -1) * orient, dtype)
    return np.stack([encode(v[:, k]) for k in range(3)], -1)


def faceted_high(path: Path) -> tuple[Array, Array]:
    """Corner positions (float32 values in double) and the facet normal of each triangle."""
    v: list[list[float]] = []
    vn: list[list[float]] = []
    faces: list[list[list[int]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == "v":
            v.append([float(F32(x)) for x in p[1:4]])
        elif p[0] == "vn":
            vn.append([float(F32(x)) for x in p[1:4]])
        elif p[0] == "f":
            faces.append([[int(c) if c else 0 for c in q.split("/")] for q in p[1:4]])
    corners = np.array([[v[c[0] - 1] for c in f] for f in faces], F64)
    facet = np.array([vn[f[0][2] - 1] for f in faces], F64)
    return corners, facet


def facet_hits(origin: Array, direction: Array, corners: Array, tmax: float) -> tuple[Array, Array]:
    """First front facet of each ray (double, edges included) and whether another facet ties."""
    best_t = np.full(len(origin), np.inf)
    best = np.full(len(origin), -1)
    margin = np.full(len(origin), np.inf)
    for k, (a, b, c) in enumerate(corners):
        e1, e2 = b - a, c - a
        pv = np.cross(direction, e2)
        det = pv @ e1
        tv = origin - a
        u = (tv * pv).sum(1) / det
        qv = np.cross(tv, e1)
        vv = (direction * qv).sum(1) / det
        t = (qv @ e2) / det
        front = direction @ np.cross(e1, e2) < 0
        ok = (u >= 0) & (vv >= 0) & (u + vv <= 1) & (t >= 0) & (t <= tmax) & front & (t < best_t)
        best_t[ok], best[ok] = t[ok], k
        margin[ok] = np.minimum(np.minimum(u, vv), 1 - u - vv)[ok]
    return best, margin <= 1e-12


def dump_low(exe: Path, manifest: dict[str, Any], work: Path) -> list[dict[str, Array]]:
    dump = work / f"normal-fit-{Path(str(manifest['golden_id'])).name}.low"
    out = work / f"normal-fit-{Path(str(manifest['golden_id'])).name}.bin"
    args = [str(exe), "bake-files", *nt.bake_arguments(manifest), "--out", str(out)]
    args += ["--dump-low", str(dump)]
    if nt.relative_distances(manifest):
        args += ["--box-size-metric", "Diagonal"]
    subprocess.run(args, capture_output=True, check=True, timeout=600)
    return read_low_dump(dump.read_bytes())


def hemisphere(exe: Path, name: str, mode: str, work: Path) -> dict[str, Any]:
    store = locate()
    if store is None:
        raise SystemExit("oracle_unavailable")
    manifest = json.loads(nt.manifest_path(name).read_text(encoding="utf-8"))
    gold = nt.golden_maps(store, manifest)["r1"].astype(np.int64)
    part = dump_low(exe, manifest, work)[0]
    high = REPO_ROOT / next(i["path"] for i in manifest["inputs"] if i["input_id"].endswith("high"))
    corners, facet = faceted_high(high)
    out: dict[str, Any] = {"golden": name}
    for rule in ("inclusive", "decision-408"):
        tri_of, weights = samples(part, rule)
        sel = (tri_of >= 0) & (gold != 0).any(-1)
        tri, w, g = tri_of[sel], weights[sel], gold[sel]
        pos = part["pos"][part["idx"][tri]].astype(F64)
        p = (pos * w[..., None]).sum(1)
        n = (part["nor"][part["idx"][tri]].astype(F64) * w[..., None]).sum(1)
        n /= np.linalg.norm(n, axis=1)[:, None]
        hit, tie = facet_hits(p + 0.02 * n, -n, corners, 0.04)
        h = _normalize(facet[hit], F64).astype(F32)
        for name_, dtype in (("float32", F32), ("float64", F64)):
            codes = tangent_codes(part, tri, w, h, mode, dtype)
            d = np.abs(codes - g).max(-1)
            out[f"{rule}/{name_}"] = {
                "exact": int((d == 0).sum()),
                "one_code": int((d == 1).sum()),
                "other": int((d > 1).sum()),
                "facet_edge_ties": int(tie.sum()),
                "texels": len(g),
            }
    return out


def sphere(exe: Path, work: Path) -> dict[str, Any]:
    store = locate()
    if store is None:
        raise SystemExit("oracle_unavailable")
    manifest = json.loads(nt.manifest_path("normal-sphere").read_text(encoding="utf-8"))
    gold = nt.golden_maps(store, manifest)["r1"].astype(np.int64)
    part = dump_low(exe, manifest, work)[0]
    out: dict[str, Any] = {"golden": "normal-sphere"}
    for rule in ("inclusive", "decision-408"):
        tri_of, weights = samples(part, rule)
        sel = tri_of >= 0
        tri, w, g = tri_of[sel], weights[sel], gold[sel]
        normals = part["nor"][part["idx"][tri]]
        curved = np.abs(normals[:, 0, 2] - 1) > 1e-6  # the sphere, not its flat ground
        for name_, dtype in (("float32", F32), ("float64", F64)):
            h = _normalize(_blend(normals, w.astype(F32), dtype), dtype)
            codes = tangent_codes(part, tri, w, h, "PerVertex", dtype)
            out[f"{rule}/{name_}"] = {
                "red_equal": int((codes[curved, 0] == g[curved, 0]).sum()),
                "green_equal": int((codes[curved, 1] == g[curved, 1]).sum()),
                "sphere_texels": int(curved.sum()),
            }
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.bake.normal_fit")
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--work", type=Path, default=REPO_ROOT / "tmp" / "scratch")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    report = [
        hemisphere(args.exe, "normal-hemisphere-per-vertex", "PerVertex", args.work),
        hemisphere(args.exe, "normal-hemisphere-per-fragment", "PerFragment", args.work),
        sphere(args.exe, args.work),
    ]
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
