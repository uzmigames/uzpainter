"""Comparison of the prototype bakes with Painter's recorded bakes (P0-NORMAL, task items 2.5, 3.2,
3.3).

Values are compared as stored 16-bit codes (`parity/CONTRACT.md` §3.1, §8.1), in tangent space,
over the fixture's comparison domain (`fixtures.analytic_field`): texels whose 5 x 5
neighbourhood lies in one low triangle and one high triangle, so that neither the ray hit nor the
frame interpolation can change across a triangle edge. `hit` texels have a high-poly hit; `miss`
texels (outside the dome's footprint on the plane) have none; Painter leaves them empty (code 0)
and its bake dilation fills those near a hit, so only `miss` texels more than `DILATION_MARGIN`
texels from every hit texel are compared.

- Oracle stability: recording `r1` (same session) against `r2` (after save and reopen).
- Residuals: each recording against each prototype map. The plane's frame is constant, so the
  plane-dome goldens are compared with one map (`PerFragment-inverse`, equal to every other frame
  variant there) in the golden's normal-map format; the hemisphere goldens with all four
  `<mode>-<transform>` maps in OpenGL.
- Frame mode: per hemisphere golden, the prototype mode whose best transform has the smallest mean
  |Δ|. It is *identified* when that mean is at most a tenth of the other mode's best mean, and
  *equal* when its max |Δ| is 0 in both recordings.
- Project default: the `project-default` recording against the `per-fragment` and `per-vertex`
  recordings.
- Direction (3.3): on the plane-dome maps, the mean green code minus 32768 over texels whose
  analytic tangent-space normal leans towards +v (y > 0.1) and towards -v (y < -0.1), and the
  same for red over +u / -u as a control.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.feasibility import png
from tools.parity.feasibility.compare import Difference, difference
from tools.parity.normal_convention.cases import BAKED_MAP, CASES, FIXTURE_DIR, Case
from tools.parity.normal_convention.fixtures import (
    Field,
    analytic_field,
    fixture_files,
    plane_tangent_normal,
    read_corners,
)
from tools.parity.normal_convention.prototype import (
    MODES,
    TRANSFORMS,
    PrototypeBake,
)
from tools.parity.schemas import load_json
from tools.parity.store.store import OracleStore, load_oracle

Codes = npt.NDArray[np.int64]
Mask = npt.NDArray[np.bool_]

IDENTIFICATION_RATIO = 0.1
# Texels without a hit are filled by the bake's dilation (`DilationWidth`, default 32 px) from
# their hit neighbours; only those farther than this from every hit texel are compared.
DILATION_MARGIN = 40
DIRECTION_THRESHOLD = 0.1


class OracleUnavailable(RuntimeError):
    """A golden's record or blob is missing from the store (`oracle_unavailable`)."""


def oracle_recordings(store: OracleStore | None, case: Case) -> dict[str, Codes]:
    """The exported baked map of every recording of `case`, by recording id."""
    manifest = load_json(case.manifest_path)
    refs = {ref["record_id"]: ref for ref in manifest["private_records"]}
    if "golden-record" not in refs:
        raise OracleUnavailable(f"{case.golden_id}: no recorded golden in the manifest")
    data = load_oracle(store, refs["golden-record"])
    if data is None:
        raise OracleUnavailable(f"{case.golden_id}: golden record unavailable")
    record = json.loads(data.decode("utf-8"))
    maps: dict[str, Codes] = {}
    for recording in record["recordings"]:
        for output in recording["outputs"]:
            if output["kind"] != "exported_map" or output["map"] != BAKED_MAP:
                continue
            blob = load_oracle(
                store,
                {"sha256": output["blob"]["sha256"], "size_bytes": output["blob"]["size_bytes"]},
            )
            if blob is None:
                raise OracleUnavailable(f"{case.golden_id}: exported map unavailable")
            maps[str(recording["recording_id"])] = png.decode(blob).astype(np.int64)
    if len(maps) < 2:
        raise OracleUnavailable(f"{case.golden_id}: fewer than two recordings of {BAKED_MAP}")
    return maps


def pair_fields() -> dict[str, Field]:
    files = fixture_files(FIXTURE_DIR)
    return {
        pair: analytic_field(
            pair, read_corners(files[f"{pair}/low"]), read_corners(files[f"{pair}/high"])
        )
        for pair in ("plane-dome", "hemisphere")
    }


def near(mask: Mask, radius: int) -> Mask:
    """Texels within `radius` texels (Chebyshev distance) of a texel of `mask`."""
    grown = mask.copy()
    for axis in (0, 1):
        source, grown = grown, grown.copy()
        padded = np.pad(source, [(radius, radius) if a == axis else (0, 0) for a in (0, 1)])
        for shift in range(2 * radius + 1):
            grown |= np.take(padded, range(shift, shift + source.shape[axis]), axis=axis)
    return grown


def domains(field: Field) -> dict[str, Mask]:
    """`hit` texels, and `miss` texels beyond the reach of Painter's bake dilation."""
    hit = field.domain & (field.high_face >= 0)
    miss = field.domain & (field.high_face < 0) & (field.low_face >= 0)
    miss &= ~near(field.high_face >= 0, DILATION_MARGIN)
    return {"hit": hit, "miss": miss} if miss.any() else {"hit": hit}


def check_prototype_faces(pair: str, bake: PrototypeBake, field: Field) -> None:
    """The prototype's rasterisation and ray hits equal the analytic field on the domain."""
    domain = field.domain
    if not np.array_equal(bake.low_face[domain], field.low_face[domain]) or not np.array_equal(
        bake.high_face[domain], field.high_face[domain]
    ):
        raise ValueError(f"{pair}: the prototype's triangles differ from the analytic field")


@dataclass(frozen=True)
class Residual:
    golden_id: str
    recording: str
    candidate: str
    domain: str
    difference: Difference

    def as_dict(self) -> dict[str, Any]:
        return {
            "golden_id": self.golden_id,
            "recording": self.recording,
            "candidate": self.candidate,
            "domain": self.domain,
            "difference": self.difference.as_dict(),
        }


def candidates(case: Case) -> list[str]:
    if case.pair == "plane-dome":
        return [f"PerFragment-inverse-{case.normal_map_format.lower()}"]
    return [f"{m}-{t}-opengl" for m in MODES for t in TRANSFORMS]


def frame_verdict(residuals: list[Residual]) -> dict[str, Any]:
    """Mode identified from one hemisphere golden's residuals on the hit domain."""
    by_mode: dict[str, tuple[float, str]] = {}
    for mode in MODES:
        means = [
            (
                float(np.mean([r.difference.mean for r in residuals if r.candidate == name])),
                name,
            )
            for name in (f"{mode}-{t}-opengl" for t in TRANSFORMS)
        ]
        by_mode[mode] = min(means)
    best_mode = min(by_mode, key=lambda m: by_mode[m][0])
    other = next(m for m in MODES if m != best_mode)
    best_mean, best_candidate = by_mode[best_mode]
    identified = best_mean <= IDENTIFICATION_RATIO * by_mode[other][0]
    equal = all(r.difference.max == 0 for r in residuals if r.candidate == best_candidate)
    return {
        "best_mode": best_mode if identified else None,
        "closest_mode": best_mode,
        "best_candidate": best_candidate,
        "best_mean": best_mean,
        "other_mode_best_mean": by_mode[other][0],
        "identified": identified,
        "equal": equal,
    }


def direction(codes: Codes, tangent: npt.NDArray[np.float64], hit: Mask) -> dict[str, float]:
    """Mean code minus 32768 of green over +v / -v texels and of red over +u / -u texels."""
    regions = {
        "green_plus_v": (1, hit & (tangent[..., 1] > DIRECTION_THRESHOLD)),
        "green_minus_v": (1, hit & (tangent[..., 1] < -DIRECTION_THRESHOLD)),
        "red_plus_u": (0, hit & (tangent[..., 0] > DIRECTION_THRESHOLD)),
        "red_minus_u": (0, hit & (tangent[..., 0] < -DIRECTION_THRESHOLD)),
    }
    return {
        name: float(codes[..., channel][mask].mean() - 32768)
        for name, (channel, mask) in regions.items()
    }


def run_study(store: OracleStore | None, bakes: dict[str, PrototypeBake]) -> dict[str, Any]:
    """Every comparison of the study as a JSON-ready document (no recorded value in it)."""
    fields = pair_fields()
    for pair, bake in bakes.items():
        check_prototype_faces(pair, bake, fields[pair])
    oracles = {case.golden_id: oracle_recordings(store, case) for case in CASES}
    stability: list[dict[str, Any]] = []
    residuals: list[Residual] = []
    for case in CASES:
        field = fields[case.pair]
        recordings = oracles[case.golden_id]
        for name, mask in domains(field).items():
            stability.append(
                {
                    "golden_id": case.golden_id,
                    "domain": name,
                    "difference": difference(recordings["r1"], recordings["r2"], mask).as_dict(),
                }
            )
            for recording_id in sorted(recordings):
                for candidate in candidates(case):
                    residuals.append(
                        Residual(
                            case.golden_id,
                            recording_id,
                            candidate,
                            name,
                            difference(
                                recordings[recording_id], bakes[case.pair].maps[candidate], mask
                            ),
                        )
                    )
    hemisphere_hit = domains(fields["hemisphere"])["hit"]
    frames = {
        case.golden_id: frame_verdict(
            [r for r in residuals if r.golden_id == case.golden_id and r.domain == "hit"]
        )
        for case in CASES
        if case.pair == "hemisphere"
    }
    default_id = "phase0/normal-convention/hemisphere/project-default"
    default_vs = {
        other: difference(
            oracles[default_id]["r1"],
            oracles[f"phase0/normal-convention/hemisphere/{other}"]["r1"],
            hemisphere_hit,
        ).as_dict()
        for other in ("per-fragment", "per-vertex")
    }
    plane = fields["plane-dome"]
    plane_hit = domains(plane)["hit"]
    tangent = plane_tangent_normal(plane.world_normal)
    directions: dict[str, Any] = {}
    for case in CASES:
        if case.pair != "plane-dome":
            continue
        fmt = case.normal_map_format.lower()
        directions[case.golden_id] = {
            "normal_map_format": case.normal_map_format,
            **{
                f"oracle_{rid}": direction(codes, tangent, plane_hit)
                for rid, codes in sorted(oracles[case.golden_id].items())
            },
            "prototype": direction(
                bakes["plane-dome"].maps[f"PerFragment-inverse-{fmt}"], tangent, plane_hit
            ),
        }
    return {
        "stability": stability,
        "residuals": [r.as_dict() for r in residuals],
        "frames": frames,
        "project_default_vs": default_vs,
        "directions": directions,
        "prototype_summaries": {pair: bake.summary for pair, bake in bakes.items()},
        "domain_texels": {
            pair: {name: int(mask.sum()) for name, mask in domains(field).items()}
            for pair, field in fields.items()
        },
    }
