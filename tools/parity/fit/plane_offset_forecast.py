"""One authored plane-offset pair; no oracle, capture, fitting or parameter search.

Only the two uncovered source-seam triangles change their cyclic corner order.
Any changed prerequisite or zero final prediction differences ends the forecast
as inconclusive. The pair is never adjusted from its observed forecast.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from tools.parity.fit.plane_transform_diagnostic import (
    check_deadline,
    install_frame,
    neighbours,
    reference,
    source_plane,
)
from tools.parity.fit.plane_transforms import Vector, _normal
from tools.parity.tier0_semantics import request_fixtures as rf

MATERIAL = "uzp_plane_offset_forecast"
SOURCE_TRIANGLES = (4, 5)


@dataclass(frozen=True)
class MemoryMesh:
    """Read-only text source accepted by the reference OBJ reader."""

    text: str

    def read_text(self, *, encoding: str) -> str:
        if encoding != "utf-8":
            raise ValueError("expected UTF-8")
        return self.text


def triangles(cyclic: bool) -> list[rf.Tri]:
    copy = rf.HingeCopy(
        "one-offset-pair",
        [(0.125, 0.0, 0.0, 1.0), (3.875, 0.0, 0.0, 1.0)],
        a=[(0.25, 0.0, 0.0, 1.0), (3.75, 12.0, 0.0, 1.0)],
        fold=0.0,
    )
    result = []
    along, depth, lift = (1, 2, 3), (260, 513, 775), (176, 80, -112)
    for index, (positions, uv) in enumerate(copy.tris):
        moved = [
            rf._vec3([x * depth[i] + y * lift[i] + z * along[i] for i in range(3)])
            for x, y, z in positions
        ]
        if cyclic and index in SOURCE_TRIANGLES:
            moved, uv = moved[1:] + moved[:1], uv[1:] + uv[:1]
        result.append((moved, uv))
    return result


def mesh(cyclic: bool) -> MemoryMesh:
    lines = [f"usemtl {MATERIAL}"]
    for index, (positions, uv) in enumerate(triangles(cyclic)):
        lines += [
            "v " + " ".join(format(float(np.float32(v)), ".17g") for v in p) for p in positions
        ]
        lines += [f"vt {(x + 8) / 512:.17g} {1 - (y + 8) / 512:.17g}" for x, y in uv]
        ids = [3 * index + c + 1 for c in range(3)]
        lines.append("f " + " ".join(f"{i}/{i}" for i in ids))
    return MemoryMesh("\n".join(lines) + "\n")


def authored_values(x: int, y: int) -> list[np.float32]:
    """Dyadic authored signals expose chain differences without external inputs."""
    return [np.float32(((c + 1) * x + (2 * c + 1) * y) % 17 / 16) for c in range(24)]


def plane_offset(normal: Vector, point: Vector) -> float:
    """Use the transform's exact float64 normalization before its plane dot."""
    return float(np.dot(_normal(normal), np.asarray(point, dtype=np.float64)))


def forecast() -> dict[str, Any]:
    deadline = time.monotonic() + 900
    ref = reference()
    meshes = [mesh(False), mesh(True)]
    report: dict[str, Any] = {
        "pair_sha256": [hashlib.sha256(m.text.encode()).hexdigest() for m in meshes],
        "status": "inconclusive",
    }
    rings = [ref.Ring(m, MATERIAL, 512, 512) for m in meshes]
    a, b = rings
    normals = all(
        np.array_equal(np.asarray(x.normal).view(np.uint32), np.asarray(y.normal).view(np.uint32))
        for x, y in zip(a.tris, b.tris, strict=True)
    )
    gates = all(
        a.folded(i, j) == b.folded(i, j) for i in range(len(a.tris)) for j in range(len(a.tris))
    )
    coverage = np.array_equal(a.owner, b.owner)
    uncovered_j = all(not np.isin(r.owner, SOURCE_TRIANGLES).any() for r in rings)
    report["prerequisites"] = {
        "normal_bits_equal": normals,
        "gates_equal": gates,
        "coverage_equal": coverage,
        "source_J_uncovered": uncovered_j,
    }
    if not all(report["prerequisites"].values()):
        report["reason"] = "confounded_geometry"
        return report
    changed_offsets = sum(
        plane_offset(a.tris[i].normal, a.tris[i].p[0])
        != plane_offset(b.tris[i].normal, b.tris[i].p[0])
        for i in SOURCE_TRIANGLES
    )
    points = {(x, y) for x, y, _, _ in a.texels()}
    if points != {(x, y) for x, y, _, _ in b.texels()}:
        report["reason"] = "ring_population_changed"
        return report
    for ring in rings:
        install_frame(ring, ref, "intersection")
    changed, used_j = 0, set()
    for x, y in sorted(points):
        check_deadline(deadline)
        predictions, orders, taus, selections = [], [], [], []
        for ring in rings:
            own = neighbours(ring, ref, x, y)
            tau = ring.tau(x, y, own)
            taus.append(tau)
            candidates, _ = ring.candidates(x, y, own, tau)
            taps = candidates[: ref.tap_count(candidates)]
            orders.append([(far, xy) for _, far, xy in taps])
            selected_sources = []
            for _, far, (tx, ty) in taps:
                if far:
                    selected = source_plane(ring, int(ring.owner[ty, tx]), tau)
                    selected_sources.append(selected)
                    if selected in SOURCE_TRIANGLES:
                        used_j.add(selected)
            selections.append(selected_sources)
            weights = ring.chain_fractions(x, y, taps)
            signals = [authored_values(tx, ty) for _, _, (tx, ty) in taps]
            predictions.append(
                np.asarray(
                    [ref.chain([signal[c] for signal in signals], weights) for c in range(24)],
                    np.float32,
                )
            )
        if taus[0] != taus[1] or orders[0] != orders[1]:
            report["reason"] = "query_or_tap_order_changed"
            return report
        if selections[0] != selections[1]:
            report["reason"] = "source_plane_selection_changed"
            return report
        changed += not np.array_equal(
            predictions[0].view(np.uint32), predictions[1].view(np.uint32)
        )
    report.update(
        tested=len(points),
        changed_source_offsets=int(changed_offsets),
        exercised_source_triangles=len(used_j),
        differing_quantized_predictions=int(changed),
        query_and_tap_order_equal=True,
        source_plane_selection_equal=True,
    )
    if changed and changed_offsets and used_j:
        report["status"] = "discriminating_authored_pair"
    else:
        report["reason"] = "no_isolated_final_discriminator"
    return report


if __name__ == "__main__":
    print(json.dumps(forecast(), sort_keys=True))
