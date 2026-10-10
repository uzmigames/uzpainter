"""Tier 0 polygon-triangulation comparison (phase1.4_mesh-importers, item 3.3;
`docs/architecture/12-mesh-import.md` §3: polygonal faces are triangulated by a documented rule,
"a Tier 0 item compared with Painter's result on the same quad mesh").

**Fixture** (`parity/fixtures/mesh-import/polygon-triangulation.obj`, UzmiGames-authored,
Apache-2.0): seven separate non-planar polygons, each with its own convex UV polygon in one cell
of a 3 x 3 layout. Every triangulation of a polygon gives a different 3D position inside it, so
the split Painter used is read from its Position bake.

| Polygon | Corners | Shape | Face starts at | Non-planar by |
|---|---|---|---|---|
| a | 4 | square | bottom-left | top-right corner displaced in x, y, z |
| b | 4 | square | bottom-right | top-right corner displaced |
| c | 4 | kite | bottom-left | top-left corner displaced |
| d | 4 | kite | bottom-right | bottom-left corner displaced |
| e | 5 | regular pentagon | corner 0 | distinct heights per corner |
| f | 6 | regular hexagon | corner 0 | distinct heights per corner |
| g | 6 | the hexagon of f | corner 2 | the same heights as f |

The quads separate "a fixed corner of the face", "the shortest 3D diagonal" and "a fixed diagonal
of the UV square"; the pentagon and hexagons separate every fan and, for the hexagons, the
triangulations that are not fans; g repeats f with the face starting two corners later.

**Golden** (`phase1/mesh-import/polygon-triangulation`): a Painter project created from the
fixture, its Position mesh map baked with the low mesh as its own high mesh (`LowAsHigh`) at
512 px and exported at 16 bits; recorded twice (same session; after save and reopen).

**Comparison**: texels whose centre lies `MARGIN` texels inside a polygon and off every chord
have an exact position for each triangulation (barycentric interpolation in UV). Painter's
normalisation of the Position map is affine per channel. Stage 1 fits it (code ~ a x + b y + c z
+ d per channel, least squares) over the quads for each of the 2^4 combinations of their splits
and keeps the best; stage 2 scores every triangulation of each polygon with those coefficients.
A polygon's triangulation is *identified* when its RMS residual is at most `IDENTIFICATION_RATIO`
times the next best. UzPainter's triangulation is read from `uzp-mesh-tests import` of the same
file (the production importer).
"""

from __future__ import annotations

import itertools
import json
import math
import subprocess
import tempfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.feasibility import png
from tools.parity.recorder.job import sha256_file
from tools.parity.schemas import REPO_ROOT, load_json
from tools.parity.store.store import OracleStore, load_oracle

FIXTURE_PATH = REPO_ROOT / "parity" / "fixtures" / "mesh-import" / "polygon-triangulation.obj"
MANIFEST_PATH = (
    REPO_ROOT / "parity" / "manifests" / "phase1" / "mesh-import" / "polygon-triangulation.json"
)
REPORT_PATH = REPO_ROOT / "parity" / "reports" / "phase1" / "polygon-triangulation.md"
SEMANTICS_PATH = REPO_ROOT / "parity" / "semantics" / "polygon-triangulation.json"
GOLDEN_ID = "phase1/mesh-import/polygon-triangulation"
PAINTER = {"product": "Adobe Substance 3D Painter", "version": "12.1.0"}
PAINTER_BUILD_ID = "12.1.0+js-api.1.1.20"
RESOLUTION = 512
OUTPUT_SIZE_LOG2 = 9
BAKED_MAP = "position"
MARGIN = 2.0  # texels
IDENTIFICATION_RATIO = 0.1
UNCONTROLLED = ["preferences.bake_backend"]
BAKING_SET = "substance_painter.baking.BakingParameters.set"

Vec3 = tuple[float, float, float]
Vec2 = tuple[float, float]
Diagonal = tuple[int, int]
Triangulation = tuple[tuple[int, int, int], ...]
Codes = npt.NDArray[np.int64]
Floats = npt.NDArray[np.float64]

CELL = 1.0 / 3.0
# Quads: square-corner keys counter-clockwise seen from +y (u right, v up; -z is "up").
SQUARE = {
    "bl": (0.0, 0.0, 0.0),
    "br": (1.0, 0.0, 0.0),
    "tr": (1.0, 0.0, -1.0),
    "tl": (0.0, 0.0, -1.0),
}
KITE = {
    "bl": (0.0, 0.0, 0.0),
    "br": (1.0, 0.0, 0.0),
    "tr": (1.8, 0.0, -1.8),
    "tl": (0.0, 0.0, -1.0),
}
UV_CORNER = {"bl": (0.0, 0.0), "br": (1.0, 0.0), "tr": (1.0, 1.0), "tl": (0.0, 1.0)}
ORDER_FROM = {"bl": ("bl", "br", "tr", "tl"), "br": ("br", "tr", "tl", "bl")}
DISPLACEMENT = (0.25, 0.6, 0.15)
QUAD_INSET = 0.03
QUAD_SIZE = CELL - 2 * QUAD_INSET
# Regular polygons: circumradius in UV, 3D scale, corner heights by geometric corner.
RADIUS = 0.14
SCALE = 4.0
HEIGHTS = {5: (0.0, 0.45, 0.1, 0.7, 0.25), 6: (0.0, 0.5, 0.2, 0.75, 0.05, 0.4)}


@dataclass(frozen=True)
class Polygon:
    name: str
    shape: str
    start: str
    positions: tuple[Vec3, ...]
    uvs: tuple[Vec2, ...]

    @property
    def size(self) -> int:
        return len(self.positions)


def _quad(
    name: str, shape: str, start: str, raised: str, cell: tuple[int, int], x0: float
) -> Polygon:
    base = SQUARE if shape == "square" else KITE
    positions: list[Vec3] = []
    uvs: list[Vec2] = []
    for key in ORDER_FROM[start]:
        x, y, z = base[key]
        if key == raised:
            x, y, z = x + DISPLACEMENT[0], y + DISPLACEMENT[1], z + DISPLACEMENT[2]
        positions.append((x + x0, y, z))
        u, v = UV_CORNER[key]
        uvs.append(
            (
                cell[0] * CELL + QUAD_INSET + u * QUAD_SIZE,
                cell[1] * CELL + QUAD_INSET + v * QUAD_SIZE,
            )
        )
    return Polygon(
        name,
        shape,
        {"bl": "bottom-left", "br": "bottom-right"}[start],
        tuple(positions),
        tuple(uvs),
    )


def _regular(name: str, n: int, start: int, cell: tuple[int, int], x0: float) -> Polygon:
    cu, cv = (cell[0] + 0.5) * CELL, (cell[1] + 0.5) * CELL
    corners = []
    for k in range(n):
        angle = 2.0 * math.pi * k / n - math.pi / 2.0
        du, dv = RADIUS * math.cos(angle), RADIUS * math.sin(angle)
        corners.append(((x0 + SCALE * du, HEIGHTS[n][k], -SCALE * dv), (cu + du, cv + dv)))
    order = [corners[(start + k) % n] for k in range(n)]
    shape = {5: "regular pentagon", 6: "regular hexagon"}[n]
    return Polygon(
        name, shape, f"corner {start}", tuple(p for p, _ in order), tuple(uv for _, uv in order)
    )


POLYGONS = (
    _quad("a", "square", "bl", "tr", (0, 2), 0.0),
    _quad("b", "square", "br", "tr", (1, 2), 3.0),
    _quad("c", "kite", "bl", "tl", (2, 2), 6.0),
    _quad("d", "kite", "br", "bl", (0, 1), 9.0),
    _regular("e", 5, 0, (1, 1), 12.0),
    _regular("f", 6, 0, (2, 1), 15.0),
    _regular("g", 6, 2, (0, 0), 18.0),
)
QUADS = tuple(p for p in POLYGONS if p.size == 4)


def _number(value: float) -> str:
    return f"{value:.6f}"


def fixture_text() -> str:
    lines = [
        "# UzPainter polygon-triangulation fixture (tools/parity/polygon_triangulation/core.py).",
        "# Authored by UzmiGames (Apache-2.0) from closed-form geometry.",
        "o uzp_polygons",
    ]
    for polygon in POLYGONS:
        lines += [f"v {' '.join(_number(c) for c in p)}" for p in polygon.positions]
    for polygon in POLYGONS:
        lines += [f"vt {' '.join(_number(c) for c in uv)}" for uv in polygon.uvs]
    lines.append("usemtl uzp_polygons")
    first = 1
    for polygon in POLYGONS:
        lines.append("f " + " ".join(f"{first + k}/{first + k}" for k in range(polygon.size)))
        first += polygon.size
    return "\n".join(lines) + "\n"


def write_fixture() -> Path:
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(fixture_text(), encoding="utf-8", newline="\n")
    return FIXTURE_PATH


# ---------------------------------------------------------------------------------------------
# Triangulations of a convex polygon


@cache
def triangulations(n: int) -> tuple[Triangulation, ...]:
    """Every triangulation of the convex polygon 0 .. n-1 (Catalan(n-2) of them), each as
    triangles with counter-clockwise corner order kept."""

    def chain(vertices: tuple[int, ...]) -> list[list[tuple[int, int, int]]]:
        if len(vertices) < 3:
            return [[]]
        first, last = vertices[0], vertices[-1]
        found = []
        for m in range(1, len(vertices) - 1):
            for left in chain(vertices[: m + 1]):
                for right in chain(vertices[m:]):
                    found.append([*left, (first, vertices[m], last), *right])
        return found

    return tuple(tuple(sorted(t)) for t in chain(tuple(range(n))))


def diagonals_of(triangles: Triangulation | list[tuple[int, ...]], n: int) -> frozenset[Diagonal]:
    """The chords of a triangulation: triangle edges that are not polygon edges."""
    edges: set[Diagonal] = set()
    for tri in triangles:
        for i in range(3):
            a, b = sorted((tri[i], tri[(i + 1) % 3]))
            if (b - a) % n not in (1, n - 1):
                edges.add((a, b))
    return frozenset(edges)


def label(diagonals: frozenset[Diagonal]) -> str:
    return "+".join(f"c{a}-c{b}" for a, b in sorted(diagonals)) or "none"


def fan_corner(diagonals: frozenset[Diagonal], n: int) -> int | None:
    """The corner every chord starts from when the triangulation is a fan (the lowest such
    corner for a quad, whose single chord has two ends)."""
    for k in range(n):
        if len(diagonals) == n - 3 and all(k in d for d in diagonals):
            return k
    return None


def shortest_quad_diagonal(polygon: Polygon) -> str:
    p = np.asarray(polygon.positions)
    return "c0-c2" if np.linalg.norm(p[2] - p[0]) < np.linalg.norm(p[3] - p[1]) else "c1-c3"


# ---------------------------------------------------------------------------------------------
# Manifest


def instruction_steps() -> list[dict[str, Any]]:
    calls: list[tuple[str, dict[str, Any]]] = [
        (
            "substance_painter.project.create",
            {"mesh": "polygons", "default_texture_resolution": RESOLUTION},
        ),
        (BAKING_SET, {"parameter": "OutputSize", "value": [OUTPUT_SIZE_LOG2, OUTPUT_SIZE_LOG2]}),
        (BAKING_SET, {"parameter": "LowAsHigh", "value": True}),
        ("substance_painter.baking.BakingParameters.set_enabled_bakers", {"usages": ["Position"]}),
        ("substance_painter.baking.bake_async", {}),
        (
            "substance_painter.export.export_project_textures",
            {
                "maps": [f"meshMap/{BAKED_MAP}:RGB"],
                "file_format": "png",
                "bit_depth": 16,
                "padding": "passthrough",
                "dithering": False,
            },
        ),
    ]
    return [{"step": i, "call": call, "args": args} for i, (call, args) in enumerate(calls, 1)]


def manifest() -> dict[str, Any]:
    applied = [
        {
            "name": "texture_set.resolution",
            "value": RESOLUTION,
            "unit": "px",
            "applied_by": "recorder_api",
        },
        {
            "name": "baking.common.OutputSize",
            "value": OUTPUT_SIZE_LOG2,
            "unit": "log2 px",
            "applied_by": "recorder_api",
        },
        {"name": "baking.common.LowAsHigh", "value": True, "applied_by": "recorder_api"},
        {"name": "baking.enabled_bakers", "value": "Position", "applied_by": "recorder_api"},
        {"name": "export.file_format", "value": "png", "applied_by": "recorder_api"},
        {"name": "export.bit_depth", "value": 16, "applied_by": "recorder_api"},
        {"name": "export.padding", "value": "passthrough", "applied_by": "recorder_api"},
        {"name": "export.dithering", "value": False, "applied_by": "recorder_api"},
    ]
    return {
        "schema": "uzpainter/parity/golden-public/1",
        "record_class": "public_manifest",
        "golden_id": GOLDEN_ID,
        "tier": "0",
        "domain": "bake_map/position",
        "description": (
            "Polygon triangulation at mesh import (12-mesh-import.md section 3, Tier 0): four "
            "non-planar quads, a pentagon and two hexagons of an OBJ; the Position mesh map baked "
            f"by Painter at {RESOLUTION} px with the low mesh as its own high mesh (LowAsHigh), "
            "other baking parameters at their defaults, exported at 16 bits; the triangulation "
            "of each polygon is read from the baked positions. Recorded twice (same session; "
            "after save and reopen)."
        ),
        "inputs": [
            {
                "input_id": "polygons",
                "kind": "mesh",
                "path": FIXTURE_PATH.relative_to(REPO_ROOT).as_posix(),
                "sha256": sha256_file(FIXTURE_PATH),
                "provenance": {"origin": "uzmigames_authored", "licence": "Apache-2.0"},
            }
        ],
        "instruction_sequence": {
            "author": "UzmiGames",
            "interface": "substance_painter_documented_python_api",
            "steps": instruction_steps(),
        },
        "applied_settings": applied,
        "uncontrolled_settings": list(UNCONTROLLED),
        "expectations": [],
        "software": {
            "painter": {**PAINTER, "build_id": PAINTER_BUILD_ID},
            "uzpainter_build_hash": None,
        },
        "private_records": [],
    }


def write_manifest() -> Path:
    """Writes the manifest; an existing one keeps its admitted private records."""
    document = manifest()
    if MANIFEST_PATH.exists():
        previous = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        changed = (
            previous["instruction_sequence"] != document["instruction_sequence"]
            or previous["inputs"] != document["inputs"]
        )
        if changed and previous["private_records"]:
            raise ValueError(f"{MANIFEST_PATH}: inputs or instructions changed after recording")
        document["private_records"] = previous["private_records"]
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    return MANIFEST_PATH


# ---------------------------------------------------------------------------------------------
# UzPainter's triangulation (the production importer)


def build_mesh_tests(prefix: Path) -> Path:
    subprocess.run(
        ["zig", "build", "mesh-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return prefix / "bin" / "uzp-mesh-tests.exe"


def uzpainter_triangulations(executable: Path | None = None) -> dict[str, str]:
    """The chords of each polygon in `uzp-mesh-tests import` of the fixture."""
    with tempfile.TemporaryDirectory(prefix="uzp-polygons-") as temp:
        exe = executable if executable is not None else build_mesh_tests(Path(temp))
        proc = subprocess.run(
            [str(exe), "import", str(FIXTURE_PATH)], capture_output=True, text=True, check=True
        )
    return triangulations_of_import(json.loads(proc.stdout))


def triangulations_of_import(result: dict[str, Any]) -> dict[str, str]:
    mesh = result["mesh"]
    corners = mesh["corners"]
    starts = list(itertools.accumulate((p.size for p in POLYGONS), initial=0))
    owner = {pos: i for i in range(len(POLYGONS)) for pos in range(starts[i], starts[i + 1])}
    triangles: dict[int, list[tuple[int, ...]]] = {}
    for obj in mesh["objects"]:
        for tri in obj["triangles"]:
            positions = [corners[c]["position"] for c in tri]
            index = owner[positions[0]]
            if any(owner[p] != index for p in positions):
                raise ValueError(f"a triangle spans polygons: {tri}")
            triangles.setdefault(index, []).append(tuple(p - starts[index] for p in positions))
    return {
        polygon.name: label(diagonals_of(triangles[i], polygon.size))
        for i, polygon in enumerate(POLYGONS)
    }


# ---------------------------------------------------------------------------------------------
# Expected positions


@dataclass(frozen=True)
class Domain:
    rows: npt.NDArray[np.int64]
    cols: npt.NDArray[np.int64]
    positions: dict[str, Floats]  # triangulation label -> (n, 3)


def _barycentric(p: Floats, a: Floats, b: Floats, c: Floats) -> Floats:
    v0, v1, v2 = b - a, c - a, p - a
    det = v0[0] * v1[1] - v1[0] * v0[1]
    w1 = (v2[:, 0] * v1[1] - v1[0] * v2[:, 1]) / det
    w2 = (v0[0] * v2[:, 1] - v2[:, 0] * v0[1]) / det
    return np.stack([1.0 - w1 - w2, w1, w2], axis=1)


def polygon_domain(polygon: Polygon, resolution: int = RESOLUTION) -> Domain:
    """Texels (row 0 at v = 1, centres at ((col + 1/2)/W, 1 - (row + 1/2)/H)) whose centre lies
    `MARGIN` texels inside the polygon's UV and off every chord, with their exact 3D position under
    each triangulation."""
    rows, cols = np.mgrid[0:resolution, 0:resolution]
    u = (cols + 0.5) / resolution
    v = 1.0 - (rows + 0.5) / resolution
    uv = np.asarray(polygon.uvs)
    xyz = np.asarray(polygon.positions)
    m = MARGIN / resolution
    n = polygon.size
    keep = np.ones_like(u, dtype=bool)
    for i in range(n):
        a, b = uv[i], uv[(i + 1) % n]
        d = b - a
        signed = ((u - a[0]) * d[1] - (v - a[1]) * d[0]) / math.hypot(d[0], d[1])
        keep &= signed <= -m  # inside a counter-clockwise polygon, at least `m` from the edge
    for i, j in itertools.combinations(range(n), 2):
        if (j - i) % n in (1, n - 1):
            continue
        d = uv[j] - uv[i]
        keep &= np.abs((u - uv[i][0]) * d[1] - (v - uv[i][1]) * d[0]) / math.hypot(d[0], d[1]) >= m
    r, c = np.nonzero(keep)
    p = np.stack([u[r, c], v[r, c]], axis=1)
    positions: dict[str, Floats] = {}
    for tris in triangulations(n):
        out = np.full((len(r), 3), np.nan)
        for tri in tris:
            w = _barycentric(p, uv[tri[0]], uv[tri[1]], uv[tri[2]])
            hit = np.all(w >= -1e-12, axis=1)
            out[hit] = w[hit] @ xyz[list(tri)]
        if np.isnan(out).any():
            raise ValueError(f"polygon {polygon.name}: a domain texel lies in no triangle")
        positions[label(diagonals_of(tris, n))] = out
    return Domain(r.astype(np.int64), c.astype(np.int64), positions)


# ---------------------------------------------------------------------------------------------
# Identification


@dataclass(frozen=True)
class Score:
    triangulation: str
    rms: float  # in 16-bit codes, over the polygon's domain texels and the three channels
    max_abs: float


@dataclass
class PolygonResult:
    best: Score
    runner_up: Score
    identified: bool


@dataclass
class RecordingResult:
    recording_id: str
    polygons: dict[str, PolygonResult]
    joint_rms: float
    joint_max_abs: float
    joint_mean_abs: float


def _design(xyz: Floats) -> Floats:
    return np.column_stack([xyz, np.ones(len(xyz))])


def identify(recording_id: str, codes: Codes, domains: dict[str, Domain]) -> RecordingResult:
    observed = {
        p.name: codes[domains[p.name].rows, domains[p.name].cols, :3].astype(np.float64)
        for p in POLYGONS
    }
    quad_labels = ("c0-c2", "c1-c3")
    best_coefficients: Floats | None = None
    best_rms = math.inf
    for combo in itertools.product(quad_labels, repeat=len(QUADS)):
        xyz = np.concatenate(
            [domains[q.name].positions[s] for q, s in zip(QUADS, combo, strict=True)]
        )
        obs = np.concatenate([observed[q.name] for q in QUADS])
        coefficients, *_ = np.linalg.lstsq(_design(xyz), obs, rcond=None)
        rms = float(np.sqrt(np.mean((obs - _design(xyz) @ coefficients) ** 2)))
        if rms < best_rms:
            best_rms, best_coefficients = rms, coefficients
    assert best_coefficients is not None
    polygons: dict[str, PolygonResult] = {}
    for polygon in POLYGONS:
        scores = []
        for name, xyz in domains[polygon.name].positions.items():
            residual = observed[polygon.name] - _design(xyz) @ best_coefficients
            scores.append(
                Score(name, float(np.sqrt(np.mean(residual**2))), float(np.abs(residual).max()))
            )
        scores.sort(key=lambda s: s.rms)
        polygons[polygon.name] = PolygonResult(
            scores[0], scores[1], scores[0].rms <= IDENTIFICATION_RATIO * scores[1].rms
        )
    xyz = np.concatenate(
        [domains[p.name].positions[polygons[p.name].best.triangulation] for p in POLYGONS]
    )
    obs = np.concatenate([observed[p.name] for p in POLYGONS])
    coefficients, *_ = np.linalg.lstsq(_design(xyz), obs, rcond=None)
    residual = obs - _design(xyz) @ coefficients
    return RecordingResult(
        recording_id,
        polygons,
        float(np.sqrt(np.mean(residual**2))),
        float(np.abs(residual).max()),
        float(np.abs(residual).mean()),
    )


class OracleUnavailable(RuntimeError):
    """The golden's record or an exported map is missing from the store (`oracle_unavailable`)."""


def oracle_recordings(store: OracleStore | None) -> dict[str, Codes]:
    manifest_doc = load_json(MANIFEST_PATH)
    refs = {ref["record_id"]: ref for ref in manifest_doc["private_records"]}
    if "golden-record" not in refs:
        raise OracleUnavailable(f"{GOLDEN_ID}: no recorded golden in the manifest")
    data = load_oracle(store, refs["golden-record"])
    if data is None:
        raise OracleUnavailable(f"{GOLDEN_ID}: golden record unavailable")
    record = json.loads(data.decode("utf-8"))
    maps: dict[str, Codes] = {}
    for recording in record["recordings"]:
        for output in recording["outputs"]:
            if output["kind"] != "exported_map" or output["map"] != BAKED_MAP:
                continue
            ref = {"sha256": output["blob"]["sha256"], "size_bytes": output["blob"]["size_bytes"]}
            blob = load_oracle(store, ref)
            if blob is None:
                raise OracleUnavailable(f"{GOLDEN_ID}: exported map unavailable")
            maps[str(recording["recording_id"])] = png.decode(blob).astype(np.int64)
    if len(maps) < 2:
        raise OracleUnavailable(f"{GOLDEN_ID}: fewer than two recordings of {BAKED_MAP}")
    return maps


@dataclass
class Study:
    uzpainter: dict[str, str]
    recordings: list[RecordingResult]
    stable: bool  # every recording equals the first code for code
    texels: dict[str, int]


def run_study(maps: dict[str, Codes], uzpainter: dict[str, str]) -> Study:
    domains = {p.name: polygon_domain(p) for p in POLYGONS}
    results = [identify(rid, codes, domains) for rid, codes in sorted(maps.items())]
    ordered = [maps[k] for k in sorted(maps)]
    stable = all(np.array_equal(ordered[0], other) for other in ordered[1:])
    return Study(uzpainter, results, stable, {p.name: len(domains[p.name].rows) for p in POLYGONS})


# ---------------------------------------------------------------------------------------------
# Publication


def mismatches(study: Study, result: RecordingResult) -> list[str]:
    return [
        p.name
        for p in POLYGONS
        if result.polygons[p.name].best.triangulation != study.uzpainter[p.name]
    ]


def status(study: Study) -> str:
    for result in study.recordings:
        if mismatches(study, result) or not all(r.identified for r in result.polygons.values()):
            return "gap"
    return "exact"


RULE = (
    "A face c0 .. c(n-1) with n > 3 becomes the fan from its last corner: the triangles "
    "(c[i], c[i+1], c(n-1)) for i = 0 .. n-3, following the face's corner order whatever the "
    "polygon's shape, planarity or shortest diagonal; a quad is split along c1-c3."
)


def semantics_document(study: Study) -> dict[str, Any]:
    total = sum(study.texels.values())
    residuals = []
    for result in study.recordings:
        wrong = mismatches(study, result)
        residuals.append(
            {
                "golden_id": GOLDEN_ID,
                "map": f"{BAKED_MAP}/triangulation-per-polygon",
                "compared_against": result.recording_id,
                "unit": "polygons triangulated otherwise",
                "difference": {
                    "max": 1 if wrong else 0,
                    "mean": len(wrong) / len(POLYGONS),
                    "p99": 1 if wrong else 0,
                    "differing": len(wrong),
                    "total": len(POLYGONS),
                    "affected_texels": sum(study.texels[name] for name in wrong),
                    "texels": total,
                },
            }
        )
    first = study.recordings[0]
    parameters: list[dict[str, Any]] = [
        {"name": "rule", "value": "fan_from_last_corner", "origin": "fitted"}
    ]
    for polygon in POLYGONS:
        parameters.append(
            {
                "name": f"uzpainter_polygon_{polygon.name}",
                "value": study.uzpainter[polygon.name],
                "origin": "authored",
            }
        )
        parameters.append(
            {
                "name": f"painter_polygon_{polygon.name}",
                "value": first.polygons[polygon.name].best.triangulation,
                "origin": "fitted",
            }
        )
    return {
        "schema": "uzpainter/parity/semantics/1",
        "record_class": "public_semantics",
        "semantics_id": "polygon-triangulation",
        "description": (
            "Triangulation of polygonal faces at mesh import (12-mesh-import.md section 3): the "
            "triangles Painter splits each polygon of an OBJ into, identified from its Position "
            "bake of non-planar quads, a pentagon and hexagons, against the rule of UzPainter's "
            "production importer (src/mesh/mesh_builder.cpp)."
        ),
        "painter_build_id": PAINTER_BUILD_ID,
        "corpus": [GOLDEN_ID],
        "entries": [
            {
                "entry_id": "polygon-split",
                "subject": "Triangles a face c0 .. c(n-1) of an imported OBJ is split into",
                "status": status(study),
                "formula": RULE,
                "public_sources": [
                    {
                        "source_id": "A-PYDOC",
                        "locator": (
                            "substance_painter.baking.BakingParameters; "
                            "textureset.MeshMapUsage.Position"
                        ),
                    }
                ],
                "parameters": parameters,
                "residuals": residuals,
            }
        ],
    }


def _describe(name: str, n: int) -> str:
    if name == "none":
        return name
    diagonals = frozenset(tuple(int(c[1:]) for c in chord.split("-")) for chord in name.split("+"))
    corner = fan_corner(diagonals, n)  # type: ignore[arg-type]
    return f"{name} (fan from c{corner})" if corner is not None and n > 4 else name


def report_markdown(study: Study, environment: dict[str, str]) -> str:
    lines = [
        "# Polygon triangulation — Tier 0 report (phase1.4_mesh-importers, item 3.3)",
        "",
        "Generated by `python -m tools.parity.polygon_triangulation run`; do not edit by hand. The "
        "oracle is a private Painter recording in the owner's store; this report and "
        "`parity/semantics/polygon-triangulation.json` hold numbers only. Method: "
        "`tools/parity/polygon_triangulation/core.py`.",
        "",
        f"## 1. Verdict: `{status(study)}`",
        "",
        f"Rule: {RULE}",
        "",
        "| Polygon | Corners | Shape | Face starts at | UzPainter | "
        + " | ".join(f"Painter {r.recording_id}" for r in study.recordings)
        + " | Shortest 3D diagonal |",
        "|---|---|---|---|---|" + "---|" * len(study.recordings) + "---|",
    ]
    for p in POLYGONS:
        cells = [
            _describe(r.polygons[p.name].best.triangulation, p.size)
            + ("" if r.polygons[p.name].identified else " (not identified)")
            for r in study.recordings
        ]
        shortest = shortest_quad_diagonal(p) if p.size == 4 else "—"
        lines.append(
            f"| {p.name} | {p.size} | {p.shape} | {p.start} | "
            f"{_describe(study.uzpainter[p.name], p.size)} | "
            + " | ".join(cells)
            + f" | {shortest} |"
        )
    lines += [
        "",
        "## 2. Residuals",
        "",
        f"Domain texels per polygon ({MARGIN:g} texels inside the polygon and off every chord): "
        + ", ".join(f"{k} {v}" for k, v in study.texels.items())
        + f". Oracle stability (every recording against r1, code for code): "
        f"{'identical' if study.stable else 'different'}.",
        "",
        "| Recording | Polygon | Best | RMS (codes) | max \\|Δ\\| | Next best | RMS (codes) "
        "| Ratio |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in study.recordings:
        for p in POLYGONS:
            res = r.polygons[p.name]
            lines.append(
                f"| {r.recording_id} | {p.name} | {res.best.triangulation} | {res.best.rms:.2f} | "
                f"{res.best.max_abs:.2f} | {res.runner_up.triangulation} | "
                f"{res.runner_up.rms:.2f} | "
                f"{res.best.rms / res.runner_up.rms:.4f} |"
            )
    lines += [
        "",
        "Joint affine fit with every polygon's best triangulation: "
        + "; ".join(
            f"{r.recording_id} RMS {r.joint_rms:.2f}, max |Δ| {r.joint_max_abs:.2f}, mean |Δ| "
            f"{r.joint_mean_abs:.3f} codes"
            for r in study.recordings
        )
        + f". Identification ratio: {IDENTIFICATION_RATIO}.",
        "",
        "## 3. Environment",
        "",
    ]
    lines += [f"- {k}: {v}" for k, v in environment.items()]
    return "\n".join(lines) + "\n"
