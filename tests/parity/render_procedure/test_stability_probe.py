"""Stability probe of decision 052's capture request and decision 033's reproducibility probe
(task `phase0.9_render-reference-capture`, decision 062): fixture rows, turned meshes, admission
of the staged captures and the pair classification."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tools.parity.recorder.iray import SAME_SESSION, SEPARATE_SESSION, stage
from tools.parity.recorder.job import sha256_file
from tools.parity.render_fits import display, probe
from tools.parity.render_procedure import references as refs
from tools.parity.render_procedure import stability
from tools.parity.schemas import Schema, validation_errors
from tools.parity.store.store import OracleStore


def test_stability_manifests_match_the_table() -> None:
    for fixture in refs.STABILITY_FIXTURES:
        path = refs.manifest_path(fixture)
        assert path.parent == refs.STABILITY_DIR
        committed = json.loads(path.read_text(encoding="utf-8"))
        generated = refs.manifest(fixture)
        generated["private_records"] = committed["private_records"]
        assert committed == generated, fixture.name
        assert validation_errors(committed, Schema.GOLDEN_PUBLIC) == []
        assert committed["golden_id"] == f"phase0/iray-stability/{fixture.name}"
        assert "not an admitted golden" in committed["description"]
    assert sorted(p.name for p in refs.STABILITY_DIR.glob("*.json")) == sorted(
        f"{f.name}.json" for f in refs.STABILITY_FIXTURES
    )
    assert len(refs.STABILITY_FIXTURES) * stability.RENDERS == 18  # decision 052 item 3


@pytest.mark.parametrize("name", sorted(refs.STABILITY_PARENTS))
def test_repeats_keep_their_parent_scene(name: str) -> None:
    repeat = json.loads(refs.manifest_path(probe.fixture_named(name)).read_text(encoding="utf-8"))
    parent_fixture = probe.fixture_named(refs.STABILITY_PARENTS[name])
    parent = json.loads(refs.manifest_path(parent_fixture).read_text(encoding="utf-8"))
    for field in ("inputs", "instruction_sequence", "applied_settings", "uncontrolled_settings"):
        assert repeat[field] == parent[field], field


def facet_normals(data: bytes) -> list[tuple[float, ...]]:
    lines = data.decode("utf-8").splitlines()
    return [tuple(float(v) for v in line.split()[1:]) for line in lines if line.startswith("vn ")]


@pytest.mark.parametrize("mesh", ["plane", "bevelled-cube"])
def test_turned_meshes_have_no_zero_x_normal(mesh: str) -> None:
    committed = refs.committed_fixtures()
    unturned = facet_normals(committed[f"{mesh}.obj"])
    assert any(n[0] == 0.0 for n in unturned)  # the face-confined facets of decision 052
    for yaw, label in refs.TURNS:
        turned = facet_normals(committed[f"{mesh}-yaw-{label}.obj"])
        assert len(turned) == len(unturned)
        assert all(abs(n[0]) >= 0.005 for n in turned), label
        for before, after in zip(unturned, turned, strict=True):
            expected = refs.rotate_y(before, yaw)  # type: ignore[arg-type]
            assert after == pytest.approx(expected, abs=2e-6)


def write_png(path: Path, value: int) -> Path:
    path.write_bytes(refs.png(2, 2, 16, 2, [value.to_bytes(2, "big") * 6] * 2))
    return path


def stage_capture(
    work: Path, fixture: refs.Fixture, recording_id: str, condition: str, session: str
) -> None:
    source = work.parent / "sources" / recording_id
    source.mkdir(parents=True)
    render = write_png(source / "reference.png", len(recording_id))
    panel = write_png(source / "panel.png", 7)
    recording: dict[str, Any] = {
        "recording_id": recording_id,
        "condition": condition,
        "session_id": session,
        "recorded_at": "2026-10-11T17:00:00+00:00",
        "outputs": [
            {
                "output_id": "render/reference",
                "kind": "iray_reference",
                "blob": {"sha256": sha256_file(render), "size_bytes": render.stat().st_size},
                "convergence": {"status": "Done", "iterations": 256, "rendering_time_s": 1.0},
            },
            {
                "output_id": "panel/iray-settings",
                "kind": "settings_panel_evidence",
                "blob": {"sha256": sha256_file(panel), "size_bytes": panel.stat().st_size},
            },
        ],
    }
    folder = stability.staging_folder(work, fixture) / recording_id
    stage(folder, {"inputs": [1]}, recording, [render, panel], {"painter_build": "x"})


def test_staged_captures_are_checked_and_admitted(tmp_path: Path) -> None:
    fixture = probe.fixture_named("plane-mid-grey--repeat")
    work = tmp_path / "work"
    stage_capture(work, fixture, "s-aaaaaaaaaaaa", SEPARATE_SESSION, "a")
    with pytest.raises(stability.StabilityError, match="1 staged renders"):
        stability.captures(work, fixture)
    stage_capture(work, fixture, "s-bbbbbbbbbbbb", SEPARATE_SESSION, "b")
    found = stability.captures(work, fixture)
    assert [c.recording_id for c in found] == ["s-aaaaaaaaaaaa", "s-bbbbbbbbbbbb"]
    manifest = tmp_path / "manifest.json"
    shutil.copyfile(refs.manifest_path(fixture), manifest)
    store = OracleStore.init(tmp_path / "store")
    written = stability.admit(store, work, fixture, manifest)
    assert written == [
        "s-aaaaaaaaaaaa-render-reference",
        "s-aaaaaaaaaaaa-panel-iray-settings",
        "s-aaaaaaaaaaaa-oracle-environment",
        "s-bbbbbbbbbbbb-render-reference",
        "s-bbbbbbbbbbbb-panel-iray-settings",
        "s-bbbbbbbbbbbb-oracle-environment",
    ]
    records = json.loads(manifest.read_text(encoding="utf-8"))["private_records"]
    kinds = {r["record_id"]: r["kind"] for r in records}
    assert kinds["s-aaaaaaaaaaaa-render-reference"] == "iray_reference"
    assert kinds["s-bbbbbbbbbbbb-oracle-environment"] == "oracle_environment_record"
    by_id = {r["record_id"]: r["sha256"] for r in records}
    assert by_id["s-aaaaaaaaaaaa-render-reference"] == found[0].render_sha256


def test_separate_session_captures_must_come_from_two_sessions(tmp_path: Path) -> None:
    fixture = probe.fixture_named("plane-mid-grey--repeat")
    work = tmp_path / "work"
    stage_capture(work, fixture, "s-aaaaaaaaaaaa", SEPARATE_SESSION, "a")
    stage_capture(work, fixture, "s-bbbbbbbbbbbb", SEPARATE_SESSION, "a")
    with pytest.raises(stability.StabilityError, match="share a session"):
        stability.captures(work, fixture)


def test_same_session_captures_must_share_their_session(tmp_path: Path) -> None:
    fixture = probe.fixture_named("plane-mid-grey--same-session")
    work = tmp_path / "work"
    stage_capture(work, fixture, "s-aaaaaaaaaaaa-1", SAME_SESSION, "a")
    stage_capture(work, fixture, "s-aaaaaaaaaaaa-2", SAME_SESSION, "b")
    with pytest.raises(stability.StabilityError, match="two sessions"):
        stability.captures(work, fixture)


@pytest.mark.parametrize(
    ("differing", "fraction", "one_step", "expected"),
    [
        (0, 0.0, 0.0, "identical"),
        (40, 0.01, 0.73, "rounding"),
        (40, 0.01, 0.60, "indeterminate"),
        (900, 0.20, 0.90, "indeterminate"),
        (90000, 0.96, 0.28, "decorrelated"),
    ],
)
def test_facet_classes(differing: int, fraction: float, one_step: float, expected: str) -> None:
    assert probe.classify(differing, fraction, one_step) == expected


def test_pair_class_takes_the_worst_facet() -> None:
    assert probe.pair_class(["identical", "identical"]) == "identical"
    assert probe.pair_class(["identical", "rounding"]) == "rounding"
    assert probe.pair_class(["rounding", "indeterminate"]) == "indeterminate"
    assert probe.pair_class(["rounding", "decorrelated"]) == "decorrelated"


def lattice_codes(halves: np.ndarray[Any, np.dtype[np.uint16]]) -> np.ndarray[Any, Any]:
    values = display.encode(halves.view(np.float16).astype(np.float64))
    return np.round(values * display.FULL_SCALE).astype(np.uint16)


def render(name: str, session: str, codes: np.ndarray[Any, Any]) -> probe.Render:
    return probe.Render("g", name, SEPARATE_SESSION, session, "", name, codes, "key", {})


def scene_of(size: int) -> probe.Scene:
    mask = np.zeros((size, size), dtype=bool)
    mask[2:-2, 2:-2] = True
    edge = np.zeros_like(mask)
    regions = {"interior": mask, "edge": edge, "background": ~mask}
    return probe.Scene(probe.fixture_named("plane-mid-grey"), [], regions, {"face": mask})


def test_clusters_find_two_mirrored_classes() -> None:
    """Renders A and B differ by single binary16 steps in a few samples (rounding); C and D
    likewise, and the two groups differ broadly: two classes, consistent with a binary choice."""
    size = 32
    rng = np.random.default_rng(3)
    base = rng.integers(0x3000, 0x3400, (size, size, 3)).astype(np.uint16)
    mirrored = rng.integers(0x3000, 0x3400, (size, size, 3)).astype(np.uint16)
    flip = np.zeros_like(base)
    flip[5, 5, 0] = 1
    codes = {
        "a": lattice_codes(base),
        "b": lattice_codes(base + flip),
        "c": lattice_codes(mirrored),
        "d": lattice_codes(mirrored + flip),
    }
    scene = scene_of(size)
    scene.renders = [render(n, n, c) for n, c in codes.items()]
    found = probe.cluster([scene])
    assert found["same_key"] is True
    assert found["classes"] == [["g/a", "g/b"], ["g/c", "g/d"]]
    assert found["binary_consistent"] is True
    classes = {(p["a"], p["b"]): p["class"] for p in found["pairs"]}
    assert classes[("g/a", "g/b")] == "rounding"
    assert classes[("g/a", "g/c")] == "decorrelated"
    scene.renders.append(render("e", "e", lattice_codes(base ^ np.uint16(0x0055))))
    assert probe.cluster([scene])["binary_consistent"] is False  # a third class
