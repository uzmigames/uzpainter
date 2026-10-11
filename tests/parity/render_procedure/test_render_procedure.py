"""Iray procedure qualification without Painter (task `phase0.6_render-reference-procedure`):
committed fixtures, the camera projection behind silhouette verification, the probe's image
analyses, and the answers file (item 3.3: every row of 07 §2.1 answered with evidence)."""

from __future__ import annotations

import math
import random
import re
from pathlib import Path

import pytest

from tools.parity.recorder.capture import Image, measure_storage_format
from tools.parity.recorder.iray import settings_sheet
from tools.parity.recorder.job import load_job
from tools.parity.recorder.session import RecorderError
from tools.parity.render_procedure import fixtures
from tools.parity.render_procedure.analysis import (
    Diff,
    changed,
    difference,
    residual_correlation,
    rotation_order_scores,
)
from tools.parity.render_procedure.answers import (
    ROWS,
    STATUSES,
    load_answers,
    pending,
    problems,
    table,
    table_in_report,
)
from tools.parity.render_procedure.projection import (
    BACKGROUND,
    BAND,
    OBJECT,
    ROTATION_ORDERS,
    Camera,
    check_scene_bounds,
    coverage_rows,
    load_obj,
    orbit_position,
    project,
    silhouette_mask,
)
from tools.parity.schemas import REPO_ROOT

SPHERE = fixtures.FIXTURE_DIR / "sphere.obj"
ON_AXIS = Camera((0.0, 0.0, 60.0), (0.0, 0.0, 0.0), 40.0, "Perspective")


def test_committed_fixtures_match_their_generator() -> None:
    for name, data in fixtures.committed_fixtures().items():
        assert (fixtures.FIXTURE_DIR / name).read_bytes() == data, name
    environment = measure_storage_format(fixtures.FIXTURE_DIR / "sky-patch.exr")
    assert (environment.container, environment.sample_type, environment.channels) == (
        "exr",
        "half",
        3,
    )
    assert load_obj(SPHERE).bounds() == ((-10.0, -10.0, -10.0), (10.0, 10.0, 10.0))


def test_environment_background_is_constant_within_the_probe_view() -> None:
    pixels = fixtures.sky_patch_pixels()
    for y in range(fixtures.ENV_HEIGHT):
        elevation = 90.0 - 180.0 * (y + 0.5) / fixtures.ENV_HEIGHT
        row = pixels[y * fixtures.ENV_WIDTH : (y + 1) * fixtures.ENV_WIDTH]
        if abs(elevation) < 40.0:
            assert {p[0] for p in row} == {fixtures.BASE}


def test_on_axis_sphere_projects_to_its_analytic_disc() -> None:
    size = 200
    rows = coverage_rows(load_obj(SPHERE), ON_AXIS, size, size)
    covered = sum(bin(row).count("1") for row in rows)
    angular = math.tan(math.asin(10.0 / 60.0)) / math.tan(math.radians(20.0))
    expected = math.pi * (angular * size / 2.0) ** 2
    assert abs(covered - expected) / expected < 0.02  # 64-segment sphere vs a true disc
    centre = rows[size // 2]
    assert centre >> (size // 2) & 1


def test_mask_codes_and_band() -> None:
    mask = silhouette_mask(load_obj(SPHERE), ON_AXIS, 40, 40, band=2)
    codes = {code for row in mask for code in row}
    assert codes == {BACKGROUND, BAND, OBJECT}
    assert mask[20][20] == OBJECT and mask[0][0] == BACKGROUND


def test_orbit_camera_sees_the_origin_at_the_image_centre() -> None:
    for order in ROTATION_ORDERS:
        rotation = (-15.0, 25.0, 10.0)
        camera = Camera(orbit_position(rotation, 60.0, order), rotation, 40.0, "Perspective")
        ((u, v),) = project(((0.0, 0.0, 0.0),), camera, 64, 64, order)
        assert abs(u - 32.0) < 1e-9 and abs(v - 32.0) < 1e-9


@pytest.mark.parametrize(
    ("camera", "size", "message"),
    [
        (ON_AXIS, (64, 32), "square render"),
        (Camera((0.0, 0.0, 60.0), (0.0, 0.0, 0.0), 40.0, "Orthographic"), (8, 8), "Perspective"),
        (Camera((0.0, 0.0, 5.0), (0.0, 0.0, 0.0), 40.0, "Perspective"), (8, 8), "in front"),
    ],
)
def test_unqualified_projections_are_refused(
    camera: Camera, size: tuple[int, int], message: str
) -> None:
    with pytest.raises(RecorderError, match=message):
        coverage_rows(load_obj(SPHERE), camera, *size)


def test_scene_bounds_must_be_the_mesh_files() -> None:
    mesh = load_obj(SPHERE)
    check_scene_bounds(mesh, {"center": [0.0, 0.0, 0.0], "dimensions": [20.0, 20.0, 20.0]})
    with pytest.raises(RecorderError, match="moved or rescaled"):
        check_scene_bounds(mesh, {"center": [0.0, 0.0, 0.0], "dimensions": [0.2, 0.2, 0.2]})


def test_euler_order_is_identified_from_a_rotated_render() -> None:
    rotation = (-15.0, 25.0, 10.0)
    position = orbit_position(rotation, 60.0, "YXZ")
    camera = Camera(position, rotation, 40.0, "Perspective")
    size = 64
    rows = coverage_rows(load_obj(SPHERE), camera, size, size, "YXZ")
    pixels: list[tuple[int, ...]] = [
        (200, 100, 50) if rows[y] >> x & 1 else (0, 0, 0) for y in range(size) for x in range(size)
    ]
    scores = rotation_order_scores(
        Image(size, size, 3, pixels), load_obj(SPHERE), position, rotation, 40.0
    )
    assert [order for order, score in scores.items() if score == 0] == ["YXZ"]


def test_denoiser_statistic_separates_white_and_smoothed_noise() -> None:
    width = 48
    noise = random.Random(3)
    reference = [(0.5, 0.5, 0.5)] * (width * width)
    white = [(0.5 + noise.uniform(-0.1, 0.1),) * 3 for _ in range(width * width)]
    smooth = [
        (0.5 + 0.1 * math.sin(i % width / 4.0) * math.cos(i // width / 4.0),) * 3
        for i in range(width * width)
    ]
    region = [True] * (width * width)
    rho_white, sd_white = residual_correlation(white, reference, region, width)
    rho_smooth, _ = residual_correlation(smooth, reference, region, width)
    assert abs(rho_white) < 0.1 and sd_white > 0.03
    assert rho_smooth > 0.9


def test_difference_is_judged_against_the_repeat_noise() -> None:
    a = [(0.5, 0.5, 0.5)] * 4
    b = [(0.5, 0.5, 0.5)] * 3 + [(0.6, 0.5, 0.5)]
    diff = difference(a, b)
    assert diff.differing == 1 and abs(diff.max_abs - 0.1) < 1e-12
    assert changed(diff, Diff(0.0, 0.0, 0, 4))
    assert not changed(diff, Diff(0.06, 0.01, 4, 4))


def test_answers_cover_every_unconfirmed_row_of_07() -> None:
    """Item 3.3: one answer per "not confirmed" row (plus §3.3 height), each with evidence."""
    data = load_answers()
    assert problems(data) == []
    assert set(data["rows"]) == set(ROWS)
    text = (REPO_ROOT / "docs" / "architecture" / "07-preview-and-render-parity.md").read_text(
        encoding="utf-8"
    )
    table = text.split("### 2.1", 1)[1].split("### 2.2", 1)[0]
    unconfirmed = [
        line for line in table.splitlines() if line.startswith("|") and "not confirmed" in line
    ]
    answered_by = {
        "| Colour LUT": "colour_lut",
        "| Colour-management mode": "display_view_transform",
        "| Min Sample, Max Sample": "iray_settings",
        "| Convergence state": "readiness",
        "| Environment Exposure": "viewer_mdl_settings",
        "| Post effects": "display_settings",
        "| Material parameters": "default_mdl_parameters",
        "| Denoiser": "denoiser",
        "| Random seed": "random_seed",
        "| Save Render": "save_render",
    }
    for line in unconfirmed:
        (row,) = [row for start, row in answered_by.items() if line.startswith(start)]
        assert row in data["rows"]
    assert len(unconfirmed) == len(answered_by)
    assert re.search(r"bump or as displacement", text) and "height" in data["rows"]
    assert pending(data) == []
    for row, entry in data["rows"].items():
        assert entry["status"] in STATUSES and entry["status"] != "pending_probe", row
    for row in data["uncontrolled"]:
        assert data["rows"][row]["status"] == "uncontrolled"
    assert data["presets"]["ref_match"]["applied_and_verified"] is True
    assert data["presets"]["base_color"]["applied_and_verified"] is True


def test_problems_catch_unsettled_rows_without_evidence() -> None:
    data = load_answers()
    broken = {**data, "rows": {**data["rows"]}}
    broken["rows"]["denoiser"] = {"status": "uncontrolled", "answer": "x", "evidence": []}
    del broken["rows"]["height"]
    pinned = {**broken["rows"]["colour_lut"], "details": {}}
    broken["rows"]["colour_lut"] = pinned
    found = problems(broken)
    assert "denoiser: settled without evidence" in found
    assert "height: no answer" in found
    assert "colour_lut: not_required without its pinned value" in found


def test_probe_fixture_outputs_are_deterministic(tmp_path: Path) -> None:
    environment = tmp_path / "sky.exr"
    environment.write_bytes(fixtures.committed_fixtures()["sky-patch.exr"])
    assert measure_storage_format(environment).sample_type == "half"
    height = tmp_path / "height.png"
    height.write_bytes(fixtures.stripe_height_png())
    assert measure_storage_format(height).bits_per_channel == 16


def test_report_table_is_rendered_from_the_answers_block() -> None:
    assert table_in_report() == table(load_answers())


def test_qualification_job_is_a_qualified_procedure_sheet() -> None:
    job = load_job(
        REPO_ROOT
        / "parity"
        / "envelopes"
        / "painter-12.1.5_js-api.1.1.20"
        / "manifests"
        / "tier3"
        / "render-procedure"
        / "qualification-sphere.json"
    )
    sheet = settings_sheet(job)
    assert (sheet.samples, sheet.width, sheet.height, sheet.max_time_s) == (256, 1200, 1200, 3600.0)
    assert (sheet.background_srgb8, sheet.bits_per_channel) == ((89, 89, 89), 16)
    assert (sheet.display_transform, sheet.rotation_order) == ("Default - sRGB", "ZYX")
    from tools.parity.recorder.iray_probe import V2_SHEET

    named = {f"{s.panel}/{s.setting}": s.value for s in sheet.panel_settings}
    assert named == {f"{s.panel}/{s.setting}": s.value for s in V2_SHEET}
    camera = Camera((0.0, 0.0, 60.0), (0.0, 0.0, 0.0), 40.0, "Perspective")
    mask = silhouette_mask(load_obj(SPHERE), camera, sheet.width, sheet.height)
    assert mask[0].count(BACKGROUND) == sheet.width and mask[600][600] == OBJECT
