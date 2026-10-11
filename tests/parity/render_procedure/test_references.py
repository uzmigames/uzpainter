"""Iray reference fixtures, manifests and noise terms (task `phase0.7_render-reference-captures`
items 2.1-2.3, 2.5, 2.6 and 3.1; decisions 038, 039 and 043)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tools.parity.recorder.capture import decode_png
from tools.parity.recorder.iray import K_TIMES_SAMPLES, SEPARATE_SESSION, settings_sheet
from tools.parity.recorder.iray_probe import REF_MATCH_HDRI_SHA256, STUDIO_WHITE_SOFT
from tools.parity.recorder.job import load_job
from tools.parity.render_procedure import references as refs
from tools.parity.render_procedure.noise import (
    admission_problems,
    noise_terms,
    region_masks,
    summary_rows,
)
from tools.parity.render_procedure.projection import (
    BACKGROUND,
    OBJECT,
    Camera,
    load_obj,
    silhouette_mask,
)
from tools.parity.render_procedure.report import replace_block
from tools.parity.schemas import Schema, validation_errors

SIZE = 96


def test_committed_fixtures_match_their_generator() -> None:
    for name, data in refs.committed_fixtures().items():
        assert (refs.FIXTURE_DIR / name).read_bytes() == data, name


def test_committed_manifests_match_the_fixture_table() -> None:
    for fixture in refs.FIXTURES:
        path = refs.manifest_path(fixture)
        committed = json.loads(path.read_text(encoding="utf-8"))
        generated = refs.manifest(fixture)
        generated["private_records"] = committed["private_records"]
        assert committed == generated, fixture.name
        assert validation_errors(committed, Schema.GOLDEN_PUBLIC) == []
    assert sorted(p.name for p in refs.MANIFEST_DIR.glob("*.json")) == sorted(
        f"{f.name}.json" for f in refs.FIXTURES
    )


@pytest.mark.parametrize("path", refs.reference_manifests(), ids=lambda p: p.stem)
def test_every_reference_is_a_fixed_pipeline_sheet(path: Path) -> None:
    sheet = settings_sheet(load_job(path))
    assert (sheet.samples, sheet.max_time_s, sheet.width, sheet.height) == (256, 3600, 1200, 1200)
    assert (sheet.bits_per_channel, sheet.display_transform) == (16, "Default - sRGB")
    panel = {f"{p.panel}/{p.setting}": p.value for p in sheet.panel_settings}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    steps = manifest["instruction_sequence"]["steps"]
    (environment,) = [s for s in steps if s["call"].endswith("set_environment_resource")]
    if sheet.background_srgb8 == (141, 142, 148):
        assert panel["Display Settings/Clear color value"] == "8D8E94"
        assert panel["Display Settings/Environment Rotation"] in (0.0, 180.0)
        assert environment["args"]["session_environment"] == REF_MATCH_HDRI_SHA256
    else:
        assert sheet.background_srgb8 == (89, 89, 89)
        assert panel["Display Settings/Clear color value"] == "595959"
        assert panel["Display Settings/Environment Rotation"] == 0.0
        assert environment["args"]["resource_url"] == STUDIO_WHITE_SOFT
    assert manifest["uncontrolled_settings"] == ["random_seed"]


def test_ref_match_covers_both_views_and_an_asymmetric_fixture() -> None:
    ref_match = [f for f in refs.FIXTURES if f.preset == "ref_match"]
    assert {(f.mesh, f.rotation) for f in ref_match} >= {
        ("sphere", 0.0),
        ("sphere", 180.0),
        ("bevelled-cube", 0.0),
        ("bevelled-cube", 180.0),
    }


def camera() -> Camera:
    return Camera(
        (0.0, 0.0, refs.CAMERA_DISTANCE), (0.0, 0.0, 0.0), refs.FIELD_OF_VIEW, "Perspective"
    )


@pytest.mark.parametrize("name", ["plane.obj", "bevelled-cube.obj"])
def test_meshes_lie_inside_the_frame(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(refs.committed_fixtures()[name])
    rows = silhouette_mask(load_obj(path), camera(), SIZE, SIZE)
    assert OBJECT in rows[SIZE // 2]
    border = rows[0] + rows[-1] + bytes(r[0] for r in rows) + bytes(r[-1] for r in rows)
    assert set(border) == {BACKGROUND}


def test_bevelled_cube_is_closed_with_outward_faces(tmp_path: Path) -> None:
    polygons = refs.chamfered_cube_polygons()
    assert sorted(len(p) for p in polygons) == [3] * 8 + [4] * 18
    for polygon in polygons:
        normal = refs.cross(refs.sub(polygon[1], polygon[0]), refs.sub(polygon[2], polygon[0]))
        centre = tuple(sum(p[k] for p in polygon) / len(polygon) for k in range(3))
        assert refs.dot(normal, centre) > 0  # type: ignore[arg-type]
    edges: dict[tuple[Any, Any], int] = {}
    for polygon in polygons:
        for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True):
            edges[(a, b)] = edges.get((a, b), 0) + 1
    assert all((b, a) in edges for a, b in edges)  # every edge is shared, opposite directions


def test_normal_map_tilts_only_along_u(tmp_path: Path) -> None:
    path = tmp_path / "n.png"
    path.write_bytes(refs.ridges_normal_png())
    image = decode_png(path)
    assert {p[1] for p in image.pixels} == {128}  # same in the OpenGL and DirectX conventions
    tilts = []
    for r, g, b in image.pixels[: image.width]:
        n = [(c / 255) * 2 - 1 for c in (r, g, b)]
        assert abs(math.sqrt(sum(c * c for c in n)) - 1) < 0.02
        tilts.append(math.degrees(math.atan2(abs(n[0]), n[2])))
    assert max(tilts) == pytest.approx(refs.RIDGE_TILT, abs=0.5)


def test_regions_follow_the_recorded_camera() -> None:
    manifest = json.loads(refs.manifest_path(refs.FIXTURES[0]).read_text(encoding="utf-8"))
    key = {
        "render_state": {
            "camera.position": [0.0, 0.0, 60.0],
            "camera.rotation": [0.0, 0.0, 0.0],
            "camera.field_of_view": 40.0,
            "camera.projection_type": "Perspective",
        }
    }
    masks = region_masks(manifest, key, (SIZE, SIZE))
    total = sum(int(m.sum()) for m in masks.values())
    assert total == SIZE * SIZE
    assert masks["interior"][SIZE // 2, SIZE // 2] and masks["background"][0, 0]
    assert masks["edge"].any()


def recording(rid: str, condition: str, session: str, samples: int, **render: Any) -> Any:
    return {
        "recording_id": rid,
        "condition": condition,
        "session_id": session,
        "outputs": [
            {
                "kind": "iray_reference",
                "samples": samples,
                "current_frame_verified": True,
                "convergence": {"status": "Done", "iterations": samples},
                **render,
            }
        ],
    }


def test_admission_needs_two_sessions_and_one_k_reference() -> None:
    good = {
        "recordings": [
            recording("s-a", SEPARATE_SESSION, "a", 256),
            recording("s-b", SEPARATE_SESSION, "b", 256),
            recording("k-c", K_TIMES_SAMPLES, "c", 1024),
        ]
    }
    assert admission_problems(good, 256, 4) == []
    same_session = {
        "recordings": [
            *good["recordings"][:1],
            recording("s-b", SEPARATE_SESSION, "a", 256),
            good["recordings"][2],
        ]
    }
    assert any("different sessions" in p for p in admission_problems(same_session, 256, 4))
    unverified = {
        "recordings": [
            *good["recordings"][:2],
            recording("k-c", K_TIMES_SAMPLES, "c", 1024, current_frame_verified=False),
        ]
    }
    assert any("current-frame" in p for p in admission_problems(unverified, 256, 4))
    short = {"recordings": [*good["recordings"][:2], recording("k-c", K_TIMES_SAMPLES, "c", 512)]}
    assert any("512 samples" in p for p in admission_problems(short, 256, 4))


def masks_of(size: int) -> dict[str, Any]:
    yy, xx = np.mgrid[0:size, 0:size]
    radius = np.hypot(yy - size / 2, xx - size / 2)
    interior = radius < size / 4
    edge = (radius >= size / 4) & (radius < size / 4 + 2)
    return {"interior": interior, "edge": edge, "background": ~(interior | edge)}


def test_identical_references_report_zero_run_to_run_difference() -> None:
    rng = np.random.default_rng(1)
    image = rng.random((32, 32, 3))
    images = {"s-a": image, "s-b": image.copy(), "k-c": image + 0.001}
    conditions = {"s-a": SEPARATE_SESSION, "s-b": SEPARATE_SESSION, "k-c": K_TIMES_SAMPLES}
    terms = noise_terms(images, conditions, masks_of(32), 4)
    assert terms["bit_identical_run_to_run"] is True
    assert terms["run_to_run"]["interior"]["max_abs"] == 0.0
    mc = terms["mc_error_at_s"]["s-a"]["interior"]
    assert mc["mean_signed"] == pytest.approx(-0.001)
    assert mc["downsampled"]["2"]["mean_abs"] == pytest.approx(0.001)
    rows = summary_rows([{"golden_id": "phase0/iray-references/x", **terms}])
    assert rows[2].startswith("| `x` | interior |")


def test_noise_sigma_estimates_agree_on_white_noise() -> None:
    rng = np.random.default_rng(7)
    truth = np.full((256, 256, 3), 0.5)
    sigma, k = 0.01, 4
    images = {
        "s-a": truth + rng.normal(0, sigma, truth.shape),
        "s-b": truth + rng.normal(0, sigma, truth.shape),
        "k-c": truth + rng.normal(0, sigma / math.sqrt(k), truth.shape),
    }
    conditions = {"s-a": SEPARATE_SESSION, "s-b": SEPARATE_SESSION, "k-c": K_TIMES_SAMPLES}
    estimate = noise_terms(images, conditions, masks_of(256), k)["s_render_sigma"]["background"]
    assert estimate["from_run_to_run"] == pytest.approx(sigma, rel=0.02)
    assert estimate["from_mc_error"] == pytest.approx(sigma, rel=0.02)


def test_report_blocks_are_replaced_in_place() -> None:
    text = "a\n<!-- x:begin -->\nold\n<!-- x:end -->\nb\n"
    assert replace_block(text, "x", "new\n") == "a\n<!-- x:begin -->\nnew\n<!-- x:end -->\nb\n"
    with pytest.raises(ValueError, match="no y block"):
        replace_block(text, "y", "")
