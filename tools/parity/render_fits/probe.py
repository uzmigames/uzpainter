"""Decision 052's capture request and decision 033's reproducibility probe (task
`phase0.9_render-reference-capture`, decision 062). Numbers and hashes only.

Inputs, on the owner's machine: the admitted references of `plane-mid-grey` and
`cube-saturated--ref-match-180` (private store) and the staged captures of the nine stability
goldens (`render_procedure.stability`). Every comparison is a run-to-run pair (a) of two S
renders of one scene, measured with the noise tools of decision 050:

- per region, `noise.region_statistics` on the 16-bit display codes;
- per pair, `stability.half_steps` over the interior and, on the flat-faced meshes, per facet
  (`stability.face_regions`, the facet seen at each pixel centre).

Each facet of a pair gets a class: `identical` (no sample differs), `rounding` (under 5% of its
pixels differ and at least 70% of the differing samples by one binary16 step; the 19 rounding
goldens of decision 052 span 0.1-4.1% and 0.73-1.00 per facet), `decorrelated` (over 50% of its
pixels differ; the face-confined class measured 86-96.5%), else `indeterminate`. A pair is
`decorrelated` when any facet is, `identical` or `rounding` when every facet is, else
`indeterminate`. Within a cluster of renders of one scene, renders joined by identical or
rounding pairs form one class (connected components); the cluster is consistent with a binary
choice when it shows at most two classes and every pair across two classes is decorrelated.

The reproducibility probe (decision 033) is the `plane-mid-grey` scene: its six S renders (two
admitted, two `--repeat`, two `--same-session`) and the admitted k*S render. It publishes byte and
decoded-pixel equality per pair, each render's provenance, the high-pass sigma of each render,
(a) per pair and (b) = each S render against the k*S render, and the per-setting observability of
the captures (`observability`).
"""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.recorder.iray import SAME_SESSION
from tools.parity.recorder.job import canonical_json
from tools.parity.render_fits import fixtures, stability
from tools.parity.render_fits.oracle import load
from tools.parity.render_fits.scene import Camera
from tools.parity.render_procedure import references as refs
from tools.parity.render_procedure import stability as captures
from tools.parity.render_procedure.answers import load_answers
from tools.parity.render_procedure.noise import (
    FULL_SCALE,
    private_record,
    region_masks,
    region_statistics,
    rgb,
)
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore

U16 = npt.NDArray[np.uint16]
F64 = npt.NDArray[np.float64]
Mask = npt.NDArray[np.bool_]
ROUNDING_DIFFERING, ROUNDING_ONE_STEP, DECORRELATED = 0.05, 0.70, 0.50
FLAT_MESHES = ("plane", "bevelled-cube")
PLANE, CUBE_180 = "plane-mid-grey", "cube-saturated--ref-match-180"
CLUSTERS = {
    PLANE: (PLANE, "plane-mid-grey--repeat", "plane-mid-grey--same-session"),
    CUBE_180: (CUBE_180, "cube-saturated--ref-match-180--repeat"),
}


@dataclass
class Render:
    golden: str
    recording_id: str
    condition: str
    session_id: str
    recorded_at: str
    sha256: str
    codes: U16
    key_sha256: str
    recording: dict[str, Any]

    @property
    def label(self) -> str:
        return f"{self.golden}/{self.recording_id}"


@dataclass
class Scene:
    """Renders of one golden with its regions and facet masks."""

    fixture: refs.Fixture
    renders: list[Render]
    regions: dict[str, Mask]
    faces: dict[str, Mask]
    k: Render | None = None


def as_codes(png: bytes) -> U16:
    result: U16 = np.round(rgb(png) * FULL_SCALE).astype(np.uint16)
    return result


def fixture_named(name: str) -> refs.Fixture:
    for fixture in (*refs.FIXTURES, *refs.STABILITY_FIXTURES):
        if fixture.name == name:
            return fixture
    raise KeyError(name)


def facets(fixture: refs.Fixture, interior: Mask) -> dict[str, Mask]:
    base = fixture.mesh.split("-yaw-")[0]
    if base not in FLAT_MESHES:
        return {}
    height, width = interior.shape
    camera = Camera((0.0, 0.0, refs.CAMERA_DISTANCE), refs.FIELD_OF_VIEW, width, height)
    return stability.face_regions(fixtures.mesh(fixture.mesh), camera, interior)


def admitted_scene(store: OracleStore | None, name: str) -> Scene:
    """The admitted golden: its two S renders and its k*S render, from the private store."""
    fixture = fixture_named(name)
    ref = load(store, name)
    record = private_record(store, ref.manifest)
    by_id = {r["recording_id"]: r for r in record["recordings"]}
    key = hashlib.sha256(canonical_json(record["key"])).hexdigest()

    def render(recording_id: str, codes: U16) -> Render:
        recording = by_id[recording_id]
        (output,) = [o for o in recording["outputs"] if o["kind"] == "iray_reference"]
        return Render(
            name,
            recording_id,
            recording["condition"],
            recording["session_id"],
            recording["recorded_at"],
            output["blob"]["sha256"],
            codes,
            key,
            recording,
        )

    s1, s2, k_id = ref.recordings
    renders = [render(s1, ref.s[0]), render(s2, ref.s[1])]
    return Scene(
        fixture,
        renders,
        ref.regions,
        facets(fixture, ref.regions["interior"]),
        render(k_id, ref.k),
    )


def stability_scene(work: Path, fixture: refs.Fixture) -> Scene:
    """A stability golden's two staged S renders."""
    found = captures.captures(work, fixture)
    renders = [
        Render(
            fixture.name,
            c.recording_id,
            c.condition,
            c.session_id,
            c.recorded_at,
            c.render_sha256,
            as_codes(c.render_path.read_bytes()),
            c.key_sha256,
            c.staged.recording,
        )
        for c in found
    ]
    manifest = refs.manifest(fixture)
    height, width, _ = renders[0].codes.shape
    regions = region_masks(manifest, found[0].staged.key, (width, height))
    return Scene(fixture, renders, regions, facets(fixture, regions["interior"]))


def classify(differing_samples: int, differing_fraction: float, one_step: float) -> str:
    if differing_samples == 0:
        return "identical"
    if differing_fraction < ROUNDING_DIFFERING and one_step >= ROUNDING_ONE_STEP:
        return "rounding"
    if differing_fraction > DECORRELATED:
        return "decorrelated"
    return "indeterminate"


def pair_class(classes: list[str]) -> str:
    if "decorrelated" in classes:
        return "decorrelated"
    if all(c == "identical" for c in classes):
        return "identical"
    if all(c in ("identical", "rounding") for c in classes):
        return "rounding"
    return "indeterminate"


def region_entry(a: F64, b: F64, mask: Mask) -> dict[str, Any]:
    stats = region_statistics((a - b) / FULL_SCALE, mask)
    steps = stability.half_steps(a, b, mask)
    pixels = int(mask.sum())
    fraction = stats["differing_pixels"] / pixels if pixels else 0.0
    return {
        "pixels": pixels,
        "differing_pixels": stats["differing_pixels"],
        "differing_fraction": fraction,
        "rms_codes": stats["rms"] * FULL_SCALE,
        "max_abs_codes": stats["max_abs"] * FULL_SCALE,
        "mean_signed_codes": stats["mean_signed"] * FULL_SCALE,
        "half_steps": steps,
        "class": classify(steps["differing_samples"], fraction, steps["one_step_fraction"]),
    }


def pair(a: Render, b: Render, scene: Scene) -> dict[str, Any]:
    x, y = a.codes.astype(np.float64), b.codes.astype(np.float64)
    regions = {
        r: region_entry(x, y, scene.regions[r])
        for r in ("interior", "edge")
        if scene.regions[r].any()
    }
    faces = {label: region_entry(x, y, mask) for label, mask in scene.faces.items()}
    classes = [f["class"] for f in faces.values()] or [regions["interior"]["class"]]
    return {
        "a": a.label,
        "b": b.label,
        "same_session": a.session_id == b.session_id,
        "byte_identical": a.sha256 == b.sha256,
        "pixel_identical": bool(np.array_equal(a.codes, b.codes)),
        "regions": regions,
        "faces": faces,
        "class": pair_class(classes),
    }


def components(labels: list[str], joined: list[tuple[str, str]]) -> list[list[str]]:
    parent = {label: label for label in labels}

    def root(label: str) -> str:
        while parent[label] != label:
            label = parent[label]
        return label

    for a, b in joined:
        parent[root(a)] = root(b)
    groups: dict[str, list[str]] = {}
    for label in labels:
        groups.setdefault(root(label), []).append(label)
    return sorted(groups.values())


def cluster(scenes: list[Scene]) -> dict[str, Any]:
    """Every pair among the S renders of one scene (same golden key) and their classes."""
    base = scenes[0]
    renders = [r for s in scenes for r in s.renders]
    keys = sorted({r.key_sha256 for r in renders})
    pairs = [pair(a, b, base) for a, b in itertools.combinations(renders, 2)]
    joined = [(p["a"], p["b"]) for p in pairs if p["class"] in ("identical", "rounding")]
    classes = components([r.label for r in renders], joined)
    member = {label: i for i, group in enumerate(classes) for label in group}
    across = [p for p in pairs if member[p["a"]] != member[p["b"]]]
    return {
        "renders": [r.label for r in renders],
        "same_key": len(keys) == 1,
        "pairs": pairs,
        "classes": classes,
        "binary_consistent": len(classes) <= 2
        and all(p["class"] == "decorrelated" for p in across),
    }


def highpass_codes(render: Render, mask: Mask) -> float:
    return stability.highpass_sigma(render.codes.astype(np.float64), mask)


def reproducibility(scenes: list[Scene], plane_cluster: dict[str, Any]) -> dict[str, Any]:
    """Decision 033's probe on the plane scene: provenance, equality, variance."""
    admitted = scenes[0]
    assert admitted.k is not None
    k = admitted.k.codes.astype(np.float64)
    interior = admitted.regions["interior"]
    rows = []
    for scene in scenes:
        for render in scene.renders:
            b = region_statistics((render.codes.astype(np.float64) - k) / FULL_SCALE, interior)
            convergence = next(
                o["convergence"]
                for o in render.recording["outputs"]
                if o["kind"] == "iray_reference"
            )
            rows.append(
                {
                    "render": render.label,
                    "condition": render.condition,
                    "session": render.session_id[:12],
                    "recorded_at": render.recorded_at,
                    "render_sha256": render.sha256,
                    "rendering_time_s": convergence["rendering_time_s"],
                    "highpass_sigma_codes": highpass_codes(render, interior),
                    "b_rms_codes": b["rms"] * FULL_SCALE,
                    "b_mean_signed_codes": b["mean_signed"] * FULL_SCALE,
                }
            )
    pairs = plane_cluster["pairs"]
    return {
        "scene": refs.manifest_path(admitted.fixture).relative_to(REPO_ROOT).as_posix(),
        "k_render": admitted.k.label,
        "k_render_sha256": admitted.k.sha256,
        "k_highpass_sigma_codes": highpass_codes(admitted.k, interior),
        "renders": rows,
        "pairs": len(pairs),
        "byte_identical_pairs": sum(p["byte_identical"] for p in pairs),
        "pixel_identical_pairs": sum(p["pixel_identical"] for p in pairs),
    }


SHEET_ROWS = {
    "Iray Settings": "iray_settings",
    "Display Settings/View mode": "display_settings",
    "Display Settings/Activate Post Effects": "display_settings",
    "Display Settings/Activate Color Profile": "display_settings",
    "Display Settings/Activate Subsurface Scattering": "display_settings",
    "Display Settings": "viewer_mdl_settings",
}


def sheet_row(name: str) -> str:
    return SHEET_ROWS.get(name) or SHEET_ROWS[name.split("/", 1)[0]]


def observability(renders: list[Render], sheet: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per setting: how the captures set it, how each capture read it back, how many of the
    plane-scene captures confirm the sheet's value, and the procedure row (phase0.6) status."""
    rows_status = {name: row["status"] for name, row in load_answers()["rows"].items()}
    total = len(renders)
    out: list[dict[str, Any]] = []
    for item in sheet:
        name, value = item["name"], item["value"]
        if item["applied_by"] != "operator_settings_sheet":
            continue
        panel, setting = name.split("/", 1)
        count = 0
        for render in renders:
            entries = next(
                o["entries"]
                for o in render.recording["outputs"]
                if o["kind"] == "operator_recorded_settings"
            )
            shown = {(e["panel"], e["setting"]): e["value"] for e in entries}
            count += shown.get((panel, setting)) == value
        row = sheet_row(name)
        out.append(
            {
                "setting": name,
                "value": value,
                "set_by": "UI automation (decision 029)",
                "read_back": "widget value after commit",
                "confirmed": f"{count}/{total}",
                "row": row,
                "status": rows_status[row],
            }
        )
    fixed = [
        (
            "camera, environment resource (render_state)",
            "documented Python API",
            "documented API read-back in the golden key",
            "camera_projection",
        ),
        (
            "display transform Default - sRGB",
            "Painter's fresh-session default",
            "selector image and background canary",
            "display_view_transform",
        ),
        (
            "convergence (Status, Iterations, Rendering time)",
            "Min = Max Sample",
            "Renderer Settings labels",
            "readiness",
        ),
        ("Save Render 16-bit PNG at 1200 x 1200", "Save Render", "decoded file", "save_render"),
        ("denoiser", "no control", "not observable (no denoiser acts)", "denoiser"),
        ("random seed", "not settable", "not observable", "random_seed"),
    ]
    keys = {r.key_sha256 for r in renders}
    for name, set_by, read_back, row in fixed:
        if row == "camera_projection":
            confirmed = f"{total}/{total}" if len(keys) == 1 else f"{len(keys)} keys"
        elif row in ("denoiser", "random_seed"):
            confirmed = "-"
        else:
            confirmed = f"{total}/{total}"
        out.append(
            {
                "setting": name,
                "value": "",
                "set_by": set_by,
                "read_back": read_back,
                "confirmed": confirmed,
                "row": row,
                "status": rows_status[row],
            }
        )
    return out


def run(store: OracleStore | None, work: Path) -> dict[str, Any]:
    staged = {f.name: stability_scene(work, f) for f in refs.STABILITY_FIXTURES}
    admitted = {name: admitted_scene(store, name) for name in CLUSTERS}
    goldens: dict[str, dict[str, Any]] = {
        name: {
            "condition": scene.renders[0].condition,
            "captures": [
                {
                    "recording_id": r.recording_id,
                    "condition": r.condition,
                    "session": r.session_id[:12],
                    "recorded_at": r.recorded_at,
                    "render_sha256": r.sha256,
                    "staged_sha256": c.staged_sha256,
                    "key_sha256": r.key_sha256,
                }
                for r, c in zip(scene.renders, captures.captures(work, scene.fixture), strict=True)
            ],
            "pair": pair(scene.renders[0], scene.renders[1], scene),
        }
        for name, scene in staged.items()
    }
    clusters = {
        name: cluster([admitted[name], *(staged[m] for m in members[1:])])
        for name, members in CLUSTERS.items()
    }
    for name, members in CLUSTERS.items():
        parent_key = admitted[name].renders[0].key_sha256
        for member in members[1:]:
            goldens[member]["key_equals_parent"] = all(
                r.key_sha256 == parent_key for r in staged[member].renders
            )
    plane_scenes = [admitted[PLANE], *(staged[m] for m in CLUSTERS[PLANE][1:])]
    plane_renders = [r for s in plane_scenes for r in s.renders]
    sheet = refs.manifest(fixture_named(PLANE))["applied_settings"]
    same_session = staged["plane-mid-grey--same-session"].renders
    return {
        "thresholds": {
            "rounding_differing_fraction": ROUNDING_DIFFERING,
            "rounding_one_step_fraction": ROUNDING_ONE_STEP,
            "decorrelated_differing_fraction": DECORRELATED,
        },
        "goldens": goldens,
        "clusters": clusters,
        "same_session_condition": all(r.condition == SAME_SESSION for r in same_session),
        "reproducibility": reproducibility(plane_scenes, clusters[PLANE]),
        "observability": observability(plane_renders, sheet),
    }
