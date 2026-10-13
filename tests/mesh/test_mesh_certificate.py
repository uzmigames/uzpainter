"""Tangent frames and the mesh certificate (phase1.5_mesh-tangents-certificate;
`docs/architecture/12-mesh-import.md` §3 Tangents, §4).

The native cases (`uzp-mesh-tests.exe run`, listed in `test_mesh_import.NATIVE_CASES`) cover the
mirrored-UV, hard-edge, coincident-opposite-faces, defect and two-island fixtures. These tests add
the certificate of every format's import report and the normal-convention fixture re-run with the
production tangent frames: `uzp-normal-bake.exe` (`tests/mesh/normal_bake.cpp`) bakes the P0-NORMAL
pairs through `src/mesh/` and must equal the Phase 0 prototype's bakes byte for byte (CPU
lane) and reproduce `parity/semantics/tangent-frame.json` against the private Painter recordings
(owner's machine, decision 028).
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.mesh.mesh_fixtures import (
    FbxGeometry,
    FbxModel,
    GltfNode,
    Primitive,
    fbx_ascii,
    gltf_document,
    write_gltf,
)
from tools.parity.normal_convention.__main__ import residual_numbers
from tools.parity.normal_convention.cases import FIXTURE_DIR
from tools.parity.normal_convention.fixtures import pairs
from tools.parity.normal_convention.prototype import PrototypeBake, run_prototype
from tools.parity.normal_convention.report import SEMANTICS_PATH, semantics_document
from tools.parity.normal_convention.study import OracleUnavailable, run_study
from tools.parity.schemas import load_json
from tools.parity.store.store import locate

REPO_ROOT = Path(__file__).resolve().parents[2]

# The triangle of every format: (0,0,0), (1,0,0), (0,1,0) facing +Z, UVs (0.1, 0.1), (0.9, 0.1),
# (0.1, 0.9) with v up: tangent +X, bitangent +Y, sign +1.
TRIANGLE = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
UVS_V_UP = [(0.1, 0.1), (0.9, 0.1), (0.1, 0.9)]


@pytest.fixture(scope="session")
def bake_prefix(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`zig build mesh-tests normal-prototype` into one prefix (same optimize mode for both)."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-mesh-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("uzp-mesh-bake")
    build = subprocess.run(
        [zig, "build", "mesh-tests", "normal-prototype", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin"


def _bakes(exe: Path, out: Path) -> dict[str, PrototypeBake]:
    return {pair: run_prototype(exe, pair, FIXTURE_DIR, out) for pair in pairs()}


@pytest.fixture(scope="session")
def production_bakes(
    bake_prefix: Path, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, PrototypeBake]:
    return _bakes(bake_prefix / "uzp-normal-bake.exe", tmp_path_factory.mktemp("production"))


def _certificate(exe: Path, path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [str(exe), "import", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report: dict[str, Any] = json.loads(proc.stdout)["report"]
    assert report["certificate"]["hashes"] == report["hashes"]
    certificate: dict[str, Any] = report["certificate"]
    return certificate


def _expected_density(cm_per_unit: float) -> float:
    uv_px = 0.5 * 0.8 * 0.8 * 1024 * 1024
    surface_cm2 = 0.5 * cm_per_unit**2
    return math.sqrt(uv_px / surface_cm2)


@pytest.mark.parametrize("fmt", ["obj", "gltf", "fbx"])
def test_certificate_of_every_format(bake_prefix: Path, tmp_path: Path, fmt: str) -> None:
    """The same sound triangle passes from OBJ, glTF (v flipped at import) and FBX: no mirrored
    frame, one island, and a density in the file's units (cm for OBJ and FBX, m for glTF)."""
    if fmt == "obj":
        lines = [f"v {x} {y} {z}" for x, y, z in TRIANGLE] + [f"vt {u} {v}" for u, v in UVS_V_UP]
        path = tmp_path / "t.obj"
        path.write_text(
            "\n".join([*lines, "vn 0 0 1", "f 1/1/1 2/2/1 3/3/1", ""]), encoding="utf-8"
        )
        cm_per_unit = 1.0
    elif fmt == "gltf":
        primitive = Primitive(
            positions=TRIANGLE,
            indices=[0, 1, 2],
            normals=[(0.0, 0.0, 1.0)] * 3,
            uvs=[(u, 1.0 - v) for u, v in UVS_V_UP],  # glTF: v grows downwards
            material=0,
        )
        document, blob = gltf_document([[primitive]], [GltfNode("T", mesh=0)], ["M"], [0])
        path = write_gltf(tmp_path / "t.gltf", document, blob)
        cm_per_unit = 100.0
    else:
        geometry = FbxGeometry(
            100,
            "T",
            TRIANGLE,
            [[0, 1, 2]],
            normals=[(0.0, 0.0, 1.0)] * 3,
            uvs=UVS_V_UP,
            polygon_materials=[0],
        )
        path = tmp_path / "t.fbx"
        model = FbxModel(200, "T", 100, materials=[300])
        path.write_text(fbx_ascii([geometry], [model], {300: "M"}), encoding="utf-8")
        cm_per_unit = 1.0
    cert = _certificate(bake_prefix / "uzp-mesh-tests.exe", path)
    assert cert["status"] == "pass"
    assert set(cert["corners"].values()) == {0}
    assert set(cert["faces"].values()) == {0}
    assert cert["uv"]["outside_0_1"] == 0
    (metrics,) = cert["uv"]["per_set"].values()
    assert metrics["islands"] == 1 and metrics["overlap_px"] == 0 and metrics["gap_px"] is None
    density = _expected_density(cm_per_unit)
    assert metrics["density_px_per_cm"] == pytest.approx(
        {"min": density, "p50": density, "max": density}, rel=1e-6
    )
    assert metrics["border_px"] == pytest.approx(0.1 * 1024, rel=1e-6)
    assert cert["mesh"]["triangles"] == 1 and cert["mesh"]["objects"] == 1


def test_production_frames_bake_as_the_prototype(
    bake_prefix: Path, production_bakes: dict[str, PrototypeBake], tmp_path: Path
) -> None:
    """Every map of both P0-NORMAL pairs baked over the production importer and tangent frames
    equals the Phase 0 prototype's, code for code (CPU lane)."""
    prototype = _bakes(bake_prefix / "uzp-normal-prototype.exe", tmp_path)
    for pair, bake in production_bakes.items():
        assert bake.maps.keys() == prototype[pair].maps.keys()
        for name, codes in bake.maps.items():
            assert np.array_equal(codes, prototype[pair].maps[name]), (pair, name)
        assert np.array_equal(bake.low_face, prototype[pair].low_face), pair
        assert np.array_equal(bake.high_face, prototype[pair].high_face), pair
        assert bake.summary == prototype[pair].summary, pair


def test_normal_convention_rerun_reproduces_the_verdict(
    production_bakes: dict[str, PrototypeBake],
) -> None:
    """The production frames reproduce the P0-NORMAL verdicts and every published residual
    against Painter's recordings (private store; owner's machine, decision 028)."""
    try:
        study = run_study(locate(), production_bakes)
    except OracleUnavailable as error:
        pytest.skip(f"oracle_unavailable (no store, decision 028): {error}")
    semantics = semantics_document(study)
    published = load_json(SEMANTICS_PATH)
    assert residual_numbers(semantics) == residual_numbers(published)
    verdicts = {e["entry_id"]: e["status"] for e in semantics["entries"]}
    assert verdicts == {e["entry_id"]: e["status"] for e in published["entries"]}
    modes = {g: v["best_mode"] for g, v in study["frames"].items()}
    assert modes == {
        "phase0/normal-convention/hemisphere/per-fragment": "PerFragment",
        "phase0/normal-convention/hemisphere/per-vertex": "PerVertex",
        "phase0/normal-convention/hemisphere/project-default": "PerVertex",
    }
