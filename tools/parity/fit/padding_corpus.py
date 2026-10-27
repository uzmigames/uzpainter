"""CPU-only scoring of ring policies over every recorded kernel padding probe (item 2.7).

Each probe's eight RGB32F kernel maps are predicted on every ring texel by the reference
(`tests/export/padding_reference.py`) under one or more frame policies and compared bit for bit
with every recorded `infinite` export. Stdout carries counts only; residual coordinates go to the
optional private `--out` file, never into the repository. No capture, fitting or admission.

    python -m tools.parity.fit.padding_corpus [--policy baseline --policy jtau] [--probe NAME]
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import sys
import types
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.fit.plane_transform_diagnostic import load_module, validate_record
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, load_oracle, locate
from tools.parity.tier0_semantics.recording_requests import kernel_bitmaps

MANIFEST_ROOT = REPO_ROOT / (
    "parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/manifests/tier0/semantics"
)
POLICIES = ("baseline",)
# Named text patches of the reference, for policies such as "baseline+snapcol" (diagnostic
# only).
PATCHES: dict[str, list[tuple[str, str]]] = {
    # A far point within WINDOW_SIDE of a window boundary is snapped onto it before the window's
    # floor (columns) and ceil (rows).
    "snapwin": [
        (
            "                col0, row0 = math.floor(fu - 0.5), math.ceil(fv - 0.5)\n",
            "                mu, mv = fu - 0.5, fv - 0.5\n"
            "                mu = round(mu) if abs(mu - round(mu)) < WINDOW_SIDE else mu\n"
            "                mv = round(mv) if abs(mv - round(mv)) < WINDOW_SIDE else mv\n"
            "                col0, row0 = math.floor(mu), math.ceil(mv)\n",
        )
    ],
    # The far point is the ring texel centre carried across the seam edge by the UV similarity
    # that maps the own edge onto the far edge, mirrored to the far triangle's inside, instead of
    # the 3D fold read back in J's UV.
    "uvwin": [
        (
            "class Ring:\n",
            """def uv_across(E, J, edge, va, vb, px, py):  # type: ignore[no-untyped-def]
    a, b = E.t[(edge + 1) % 3], E.t[(edge + 2) % 3]
    c = E.t[edge]
    a2, b2 = J.t[J.vertex.index(va)], J.t[J.vertex.index(vb)]
    c2 = J.t[3 - J.vertex.index(va) - J.vertex.index(vb)]
    ex, ey = b[0] - a[0], b[1] - a[1]
    length2 = ex * ex + ey * ey
    s = ((px - a[0]) * ex + (py - a[1]) * ey) / length2
    h = (ex * (py - a[1]) - ey * (px - a[0])) / length2
    hc = ex * (c[1] - a[1]) - ey * (c[0] - a[0])
    fx, fy = b2[0] - a2[0], b2[1] - a2[1]
    hc2 = fx * (c2[1] - a2[1]) - fy * (c2[0] - a2[0])
    h2 = -h * math.copysign(1.0, hc) * math.copysign(1.0, hc2)
    return (a2[0] + s * fx - h2 * fy, a2[1] + s * fy + h2 * fx)


class Ring:
""",
        ),
        (
            "                fu, fv = J.texel_of(fold(hinge(E, J, va, vb), q))\n",
            "                fu, fv = uv_across(E, J, edge, va, vb, x + 0.5, y + 0.5)\n",
        ),
    ],
    "snapcol": [
        (
            "                col0, row0 = math.floor(fu - 0.5), math.ceil(fv - 0.5)\n",
            "                mu = fu - 0.5\n"
            "                mu = round(mu) if abs(mu - round(mu)) < WINDOW_SIDE else mu\n"
            "                col0, row0 = math.floor(mu), math.ceil(fv - 0.5)\n",
        )
    ],
    "snaprow": [
        (
            "                col0, row0 = math.floor(fu - 0.5), math.ceil(fv - 0.5)\n",
            "                mv = fv - 0.5\n"
            "                mv = round(mv) if abs(mv - round(mv)) < WINDOW_SIDE else mv\n"
            "                col0, row0 = math.floor(fu - 0.5), math.ceil(mv)\n",
        )
    ],
}
STEPS = {45: "infinite", 46: "infinite", 47: "passthrough", 48: "passthrough"}
type Image = npt.NDArray[np.float32]
type Point = tuple[int, int]


def probes() -> list[str]:
    """The kernel probes: every padding manifest whose inputs are the eight kernel maps."""
    out = []
    for path in sorted(MANIFEST_ROOT.glob("export-padding-*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if any(row["input_id"].startswith("kernel-onehot-a-") for row in manifest["inputs"]):
            out.append(path.stem.removeprefix("export-padding-"))
    return out


def image(path: Path, size: int) -> Image:
    """An RGB32F OpenEXR of `size` x `size` texels, rows top first."""
    import OpenEXR

    with OpenEXR.File(str(path), separate_channels=True) as exr:
        channels = exr.channels()
        if set(channels) != {"R", "G", "B"}:
            raise ValueError("expected RGB channels")
        planes = [channels[c].pixels for c in "RGB"]
        if any(p.dtype != np.float32 or p.shape != (size, size) for p in planes):
            raise ValueError("expected RGB32F at the probe's resolution")
        result = np.stack(planes, axis=-1)
    if not np.isfinite(result).all():
        raise ValueError("nonfinite samples")
    return result


def material_of(manifest: dict[str, Any]) -> str:
    names = {
        word
        for word in json.dumps(manifest["instruction_sequence"]).replace('"', " ").split()
        if word.startswith("uzp_")
    }
    if len(names) != 1:
        raise ValueError("expected one material")
    return names.pop()


def reference_text(revision: str | None) -> str:
    """The reference's source, as in the working tree or at a git `revision`."""
    if revision is None:
        return (REPO_ROOT / "tests/export/padding_reference.py").read_text("utf-8")
    shown = subprocess.run(
        ["git", "show", f"{revision}:tests/export/padding_reference.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    return shown.stdout.decode("utf-8")


def ring_points(covered: npt.NDArray[np.bool_]) -> list[Point]:
    """The uncovered texels with a covered 8-neighbour (x wrapped, as `Ring.texels`)."""
    near = np.zeros_like(covered)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            shifted = np.roll(covered, (dy, dx), axis=(0, 1))
            if dy == 1:
                shifted[0, :] = False
            elif dy == -1:
                shifted[-1, :] = False
            near |= shifted
    ys, xs = np.nonzero(near & ~covered)
    return [(int(x), int(y)) for y, x in zip(ys, xs, strict=True)]


def exports(
    record: dict[str, Any],
    material: str,
    source: Image,
    covered: npt.NDArray[np.bool_],
    points: list[Point],
    store: OracleStore,
) -> dict[Any, Image]:
    """(recording, step) -> the 24 recorded components of the eight `infinite` maps at `points`.
    Every export, passthrough included, must keep the covered source bit for bit."""
    size = source.shape[0]
    ys = np.array([y for _, y in points])
    xs = np.array([x for x, _ in points])
    rings: dict[Any, dict[int, Image]] = {}
    for recording in record["recordings"]:
        for output in recording["outputs"]:
            if output["kind"] != "exported_map":
                continue
            settings = output["export_settings"]
            mode, step = settings["paddingAlgorithm"], settings["step"]
            if output["texture_set"] != material or STEPS.get(step) != mode:
                raise ValueError("unexpected export")
            if load_oracle(store, output["blob"]) is None:
                raise ValueError("export blob unavailable")
            channel = int(output["map"][4:])
            values = image(store.blob_path(output["blob"]["sha256"]), size)
            own = source[..., 3 * channel : 3 * channel + 3]
            if np.any(values.view(np.uint32)[covered] != own.view(np.uint32)[covered]):
                raise ValueError("covered source differs")
            if mode == "infinite":
                rings.setdefault((recording["recording_id"], step), {})[channel] = values[ys, xs]
    if len(rings) != 4 or any(set(g) != set(range(8)) for g in rings.values()):
        raise ValueError("incomplete export groups")
    return {key: np.concatenate([g[i] for i in range(8)], axis=-1) for key, g in rings.items()}


def bins_of(t: list[Any], ref: Any) -> list[int]:
    """The quantised level `u` of each chain fraction (decision 268)."""
    out = []
    for level, value in enumerate(t):
        k, levels = ref.LEVELS[level]
        out.append(round((float(value) * k * levels - levels) / (k - 1)))
    return out


def fraction_of(level: int, u: int, ref: Any) -> np.float32:
    k, levels = ref.LEVELS[level]
    return np.float32((levels + (k - 1) * u) / (k * levels))


def inverse_bins(
    values: Image, recorded: Image, guess: list[int], ref: Any, radius: int = 6
) -> list[int] | None:
    """Quantised levels near `guess` whose chain over `values` (taps x components) reproduces
    `recorded` on every component bit for bit, nearest to `guess` first; None when none does."""
    n = values.shape[0]
    if n < 2:
        return None
    ranges = []
    for level in range(n - 1):
        levels = ref.LEVELS[level][1]
        reach = levels if n == 2 else radius
        lo, hi = max(0, guess[level] - reach), min(levels, guess[level] + reach)
        ranges.append(sorted(range(lo, hi + 1), key=lambda u: abs(u - guess[level])))
    best: tuple[int, list[int]] | None = None
    for combo in itertools.product(*ranges):
        cost = sum(abs(u - g) for u, g in zip(combo, guess, strict=True))
        if best is not None and cost >= best[0]:
            continue
        t = [fraction_of(level, u, ref) for level, u in enumerate(combo)]
        if all(
            ref.chain(values[:, c], t).view(np.uint32) == recorded[c].view(np.uint32)
            for c in range(values.shape[1])
        ):
            best = (cost, list(combo))
    return None if best is None else best[1]


class Probe:
    """A kernel probe: the reference, its ring under a policy, the source and the recorded ring."""

    def __init__(self, probe: str) -> None:
        store = locate()
        if store is None:
            raise ValueError("store unavailable")
        self.name = probe
        self.ref = load_module(REPO_ROOT / "tests/export/padding_reference.py", f"ref_{probe}")
        self.patched: dict[str, Any] = {}
        path = MANIFEST_ROOT / f"export-padding-{probe}.json"
        manifest = json.loads(path.read_text("utf-8"))
        refs = [r for r in manifest["private_records"] if r["record_id"] == "golden-record"]
        if len(refs) != 1 or (raw := load_oracle(store, refs[0])) is None:
            raise ValueError("private record unavailable")
        record = json.loads(raw)
        validate_record(record, manifest)
        inputs = {row["input_id"]: row for row in manifest["inputs"]}
        size = int(next(k for k in inputs if k.startswith("kernel-onehot-a-")).rsplit("-n", 1)[1])
        self.size = size
        self.source = np.concatenate(
            [image(REPO_ROOT / inputs[key]["path"], size) for key in kernel_bitmaps(size)], axis=-1
        )
        mesh = next(r["path"] for r in manifest["inputs"] if r["path"].endswith(".obj"))
        self.mesh = REPO_ROOT / mesh
        self.material = material_of(manifest)
        covered = self.ring("baseline").owner >= 0
        self.covered = covered
        self.points = ring_points(covered)
        self.index = {point: i for i, point in enumerate(self.points)}
        self.recorded = exports(record, self.material, self.source, covered, self.points, store)
        base = next(iter(self.recorded.values())).view(np.uint32)
        self.unstable = sum(
            int(np.count_nonzero(np.any(v.view(np.uint32) != base, axis=-1)))
            for v in self.recorded.values()
        )

    def ring(self, policy: str) -> Any:
        """The ring under `policy`: `baseline` (the current reference) or `git:<revision>` (the
        reference at that revision), then `+`-joined PATCHES."""
        base, *patches = policy.split("+")
        if base != "baseline" and not base.startswith("git:"):
            raise ValueError(f"unknown reference {base}")
        if policy == "baseline":
            ref = self.ref
        else:
            if policy not in self.patched:
                text = reference_text(None if base == "baseline" else base[4:])
                for name in patches:
                    for old, new in PATCHES[name]:
                        if text.count(old) != 1:
                            raise ValueError(f"patch {name} does not apply")
                        text = text.replace(old, new)
                module = types.ModuleType(f"ref_{self.name}_{len(self.patched)}")
                exec(compile(text, f"padding_reference@{policy}", "exec"), module.__dict__)
                self.patched[policy] = module
            ref = self.patched[policy]
        return ref.Ring(self.mesh, self.material, self.size, self.size)

    def taps(self, ring: Any) -> list[tuple[Point, list[Any], list[np.float32], Image]]:
        """Each ring texel's chain taps, fractions and tap values under the ring's frame."""
        out = []
        for x, y, candidates, count in ring.texels():
            taps = candidates[:count]
            weights = ring.chain_fractions(x, y, taps)
            values = np.asarray([self.source[ty, tx] for _, _, (tx, ty) in taps], np.float32)
            out.append(((x, y), taps, weights, values))
        return out

    def chain(self, values: Image, weights: list[np.float32]) -> Image:
        return np.array(
            [self.ref.chain(values[:, c], weights) for c in range(values.shape[1])], np.float32
        )

    def missed(self, point: Point, prediction: Image) -> bool:
        row = self.index[point]
        bits = prediction.view(np.uint32)
        return any(not np.array_equal(bits, r[row].view(np.uint32)) for r in self.recorded.values())


def explain(probe: str, policy: str, limit: int) -> dict[str, Any]:
    """Classify `policy`'s residual ring texels on `probe`: support or order (no levels near the
    predicted ones reproduce the recording) or weights (the levels off by how many bins)."""
    p = Probe(probe)
    recorded = next(iter(p.recorded.values()))
    classes: dict[str, int] = {}
    shifts: dict[str, int] = {}
    seen = 0
    for point, taps, weights, values in p.taps(p.ring(policy)):
        if not p.missed(point, p.chain(values, weights)):
            continue
        seen += 1
        if seen > limit:
            continue
        kind = "far" if any(c[1] for c in taps) else "own"
        guess = bins_of(weights, p.ref)
        found = inverse_bins(values, recorded[p.index[point]], guess, p.ref)
        if found is None:
            label = f"{kind}-{len(taps)}tap-support"
        else:
            label = f"{kind}-{len(taps)}tap-weights"
            delta = ",".join(f"{a - b:+d}" for a, b in zip(found, guess, strict=True))
            shifts[delta] = shifts.get(delta, 0) + 1
        classes[label] = classes.get(label, 0) + 1
    return {
        "probe": probe,
        "policy": policy,
        "residual": seen,
        "classes": classes,
        "shifts": shifts,
    }


def weights_of(values: Image, recorded: Image) -> npt.NDArray[np.float64]:
    """Affine weights (summing to 1) of candidate values (candidates x components) that best give
    `recorded`, by least squares."""
    base = values[0].astype(np.float64)
    a = (values[1:].astype(np.float64) - base).T
    b = recorded.astype(np.float64) - base
    rest = np.linalg.lstsq(a, b, rcond=None)[0] if len(values) > 1 else np.zeros(0)
    return np.concatenate([[1.0 - rest.sum()], rest])


def decode(
    p: Probe, point: Point, around: Sequence[Point] = (), radius: int = 6
) -> tuple[list[tuple[Point, float]], float]:
    """Painter's taps of ring texel `point`: nonnegative least squares over every covered texel
    within `radius` (x wrapped) of the ring texel, of each texel of `around`, and of the points
    the recorded UV-ramp centroid extrapolates to when far taps hold a quarter, half or three
    quarters of the weight, with the weights summing to 1. Returns (texel, weight) by weight and
    the fit's largest component error."""
    from scipy.optimize import nnls

    x, y = point
    target = next(iter(p.recorded.values()))[p.index[point]].astype(np.float64)
    cx, cy = target[9] * p.size - 0.5, target[10] * p.size - 0.5
    centres = [point, *around] + [
        (round(x + (cx - x) / share), round(y + (cy - y) / share)) for share in (0.25, 0.5, 0.75)
    ]
    seen: set[Point] = set()
    pool: list[Point] = []
    for ox, oy in centres:
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                t = ((ox + dx) % p.size, oy + dy)
                if 0 <= t[1] < p.size and p.covered[t[1], t[0]] and t not in seen:
                    seen.add(t)
                    pool.append(t)
    a = np.array([p.source[ty, tx] for tx, ty in pool], np.float64).T
    a = np.vstack([a * 64.0, np.full((1, len(pool)), 64.0)])
    w, _ = nnls(a, np.concatenate([target * 64.0, [64.0]]), maxiter=2000)
    fit = float(np.abs(a[:-1] @ w / 64.0 - target).max())
    order = np.argsort(-w)
    return [(pool[i], float(w[i])) for i in order if w[i] > 1e-5], fit


def decode_sparse(
    p: Probe, point: Point, around: Sequence[Point] = (), radius: int = 8
) -> list[tuple[Point, float]] | None:
    """Painter's taps of ring texel `point`, at most one per kernel class: the one-hot maps give
    each class's weight; one covered texel per weighted class, within `radius` of the ring texel,
    of a texel of `around` or of the UV-ramp centroid's extrapolations (as `decode`), must
    reproduce every recorded component. None when no such set does."""
    x, y = point
    target = next(iter(p.recorded.values()))[p.index[point]].astype(np.float64)
    weights = target[:9]
    classes = [c for c in range(9) if weights[c] > 1e-6]
    if abs(weights.sum() - 1.0) > 1e-4 or not classes:
        return None
    cx, cy = target[9] * p.size - 0.5, target[10] * p.size - 0.5
    centres = [point, *around] + [
        (round(x + (cx - x) / share), round(y + (cy - y) / share)) for share in (0.25, 0.5, 0.75)
    ]
    by_class: dict[int, list[Point]] = {c: [] for c in classes}
    seen: set[Point] = set()
    for ox, oy in centres:
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                t = ((ox + dx) % p.size, oy + dy)
                if not (0 <= t[1] < p.size and p.covered[t[1], t[0]]) or t in seen:
                    continue
                seen.add(t)
                k = t[0] % 3 + 3 * (t[1] % 3)
                if k in by_class:
                    by_class[k].append(t)
    if any(not by_class[c] for c in classes):
        return None

    def features(t: Point) -> npt.NDArray[np.float64]:
        return p.source[t[1], t[0], 9:].astype(np.float64)

    rest = target[9:]
    *head, last = classes
    lookup: dict[tuple[int, ...], Point] = {}
    for t in by_class[last]:
        lookup[tuple(np.round(features(t) * weights[last] * 2**14).astype(int))] = t
    for combo in itertools.product(*(by_class[c] for c in head)):
        partial = sum((weights[c] * features(t) for c, t in zip(head, combo, strict=True)), 0.0)
        key = tuple(np.round((rest - partial) * 2**14).astype(int))
        found = lookup.get(key)
        if found is not None:
            taps = [*zip(combo, (weights[c] for c in head), strict=True), (found, weights[last])]
            return sorted(((t, float(w)) for t, w in taps), key=lambda tw: -tw[1])
    return None


def infer(probe: str, policy: str, limit: int, dump: Path | None = None) -> dict[str, Any]:
    """For `policy`'s residual ring texels on `probe`, Painter's support among the candidates
    (least-squares weights over the first KEPT candidates): the same taps in the same order, the
    same taps reordered, other candidates, or none that fits (support outside the candidates)."""
    p = Probe(probe)
    recorded = next(iter(p.recorded.values()))
    classes: dict[str, int] = {}
    rows = []
    seen = 0
    ring = p.ring(policy)
    for x, y, candidates, count in ring.texels():
        taps = candidates[:count]
        weights = ring.chain_fractions(x, y, taps)
        tapped = np.asarray([p.source[ty, tx] for _, _, (tx, ty) in taps], np.float32)
        if not p.missed((x, y), p.chain(tapped, weights)):
            continue
        values = np.asarray([p.source[ty, tx] for _, _, (tx, ty) in candidates], np.float32)
        target = recorded[p.index[(x, y)]]
        w = weights_of(values, target)
        fit = float(np.abs(values.T.astype(np.float64) @ w - target).max())
        used = [int(i) for i in np.argsort(-w) if w[i] > 1e-4]
        predicted = list(range(count))
        seen += 1
        if seen > limit:
            continue
        if fit >= 1e-4:
            label = "outside-candidates"
        elif used == predicted:
            label = "same-taps"
        elif sorted(used) == predicted:
            label = "reordered"
        elif set(predicted) < set(used):
            label = f"more-taps-{len(used)}-for-{count}"
        elif set(used) < set(predicted):
            label = f"fewer-taps-{len(used)}-for-{count}"
        else:
            label = "other-candidates"
        kind = "far" if any(c[1] for c in taps) or any(candidates[i][1] for i in used) else "own"
        classes[f"{kind}:{label}"] = classes.get(f"{kind}:{label}", 0) + 1
        rows.append(
            {
                "texel": [x, y],
                "label": label,
                "candidates": [[c[0], c[1], list(c[2])] for c in candidates],
                "count": count,
                "weights": [float(v) for v in w],
                "fit": fit,
            }
        )
    if dump is not None:
        dump.write_text(json.dumps(rows), encoding="utf-8")
    return {"probe": probe, "policy": policy, "classes": classes}


def native(probe: str, exe: Path) -> dict[str, Any]:
    """UzPainter's ring (`uzp-export-tests ring`) on `probe`'s mesh with the 24 kernel components
    as values, against the reference's chains and against Painter's recording, bit for bit on every
    ring texel. The values and the native output are throwaway files in `tmp/scratch`."""
    p = Probe(probe)
    scratch = REPO_ROOT / "tmp" / "scratch"
    cases = scratch / f"native-{probe}-cases.json"
    groups = range(0, p.source.shape[-1], 4)  # the command pads at most four channels
    files = []
    entries: list[dict[str, Any]] = []
    for first in groups:
        values = scratch / f"native-{probe}-{first}-values.f32"
        result = scratch / f"native-{probe}-{first}-out.f32"
        values.write_bytes(np.ascontiguousarray(p.source[..., first : first + 4]).tobytes())
        files += [values, result]
        entries.append(
            {
                "mesh": str(p.mesh),
                "material": p.material,
                "width": p.size,
                "height": p.size,
                "channels": 4,
                "values": str(values),
                "out": str(result),
            }
        )
    cases.write_text(json.dumps(entries), encoding="utf-8")
    try:
        run = subprocess.run(
            [str(exe), "ring", str(cases)],
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
        if run.returncode != 0:
            raise ValueError(f"native ring failed: {run.stderr[-400:]}")
        lines = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
        rows = {(r["x"], r["y"]): r for r in lines[0]["ring"]}
        out = np.concatenate(
            [
                np.frombuffer(Path(e["out"]).read_bytes(), np.float32).reshape(p.size, p.size, 4)
                for e in entries
            ],
            axis=-1,
        )
    finally:
        for path in (*files, cases):
            path.unlink(missing_ok=True)
    taps_differ = values_differ = painter = 0
    for point, taps, weights, tapped in p.taps(p.ring("baseline")):
        x, y = point
        row = rows.get(point)
        if row is None or [tuple(c[:2]) for c in row["candidates"][: row["taps"]]] != [
            c[2] for c in taps
        ]:
            taps_differ += 1
        if not np.array_equal(out[y, x].view(np.uint32), p.chain(tapped, weights).view(np.uint32)):
            values_differ += 1
        if p.missed(point, out[y, x]):
            painter += 1
    return {
        "probe": probe,
        "ring": len(p.points),
        "native_rows": len(rows),
        "taps_differ": taps_differ,
        "values_differ": values_differ,
        "painter_misses": painter,
    }


def score(probe: str, policies: tuple[str, ...]) -> dict[str, Any]:
    p = Probe(probe)
    misses: dict[str, list[Point]] = {}
    for policy in policies:
        chains = p.taps(p.ring(policy))
        if {point for point, *_ in chains} != set(p.points):
            raise ValueError("ring population differs")
        misses[policy] = sorted(
            point for point, _, w, values in chains if p.missed(point, p.chain(values, w))
        )
    return {
        "probe": probe,
        "ring": len(p.points),
        "unstable_infinite": p.unstable,
        "misses": misses,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", action="append")
    parser.add_argument("--probe", action="append")
    parser.add_argument("--out", type=Path, help="private JSON file for residual coordinates")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument(
        "--explain", action="store_true", help="classify the first policy's residuals instead"
    )
    parser.add_argument("--limit", type=int, default=400)
    parser.add_argument("--infer", action="store_true", help="infer Painter's support instead")
    parser.add_argument("--native", type=Path, help="compare uzp-export-tests.exe's ring instead")
    args = parser.parse_args(argv)
    policies = tuple(args.policy or POLICIES)
    names = args.probe or probes()
    if args.native is not None:
        with ProcessPoolExecutor(args.jobs) as pool:
            for line in pool.map(native, names, [args.native] * len(names)):
                print(json.dumps(line, sort_keys=True), flush=True)
        return 0
    if args.infer:
        with ProcessPoolExecutor(args.jobs) as pool:
            dumps = [
                None if args.out is None else args.out.with_name(f"{args.out.stem}-{n}.json")
                for n in names
            ]
            for line in pool.map(
                infer, names, [policies[0]] * len(names), [args.limit] * len(names), dumps
            ):
                print(json.dumps(line, sort_keys=True), flush=True)
        return 0
    if args.explain:
        with ProcessPoolExecutor(args.jobs) as pool:
            for line in pool.map(
                explain, names, [policies[0]] * len(names), [args.limit] * len(names)
            ):
                print(json.dumps(line, sort_keys=True), flush=True)
        return 0
    with ProcessPoolExecutor(args.jobs) as pool:
        results = list(pool.map(score, names, [policies] * len(names)))
    totals = {policy: 0 for policy in policies}
    for result in results:
        counts = {policy: len(result["misses"][policy]) for policy in policies}
        row: dict[str, Any] = {"probe": result["probe"], "ring": result["ring"], **counts}
        base = set(map(tuple, result["misses"][policies[0]]))
        for policy in policies[1:]:
            other = set(map(tuple, result["misses"][policy]))
            row[f"{policy}_fixed"] = len(base - other)
            row[f"{policy}_new"] = len(other - base)
        if result["unstable_infinite"]:
            row["unstable_infinite"] = result["unstable_infinite"]
        for policy in policies:
            totals[policy] += counts[policy]
        print(json.dumps(row, sort_keys=True))
    print(json.dumps({"totals": totals}, sort_keys=True))
    if args.out is not None:
        args.out.write_text(json.dumps(results), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
