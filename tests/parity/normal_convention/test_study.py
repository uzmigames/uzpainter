"""Comparison, verdicts and publication of the normal-convention fixture (tasks 2.5, 2.7, 3.2).

The verdict logic and the published documents are checked on synthetic numbers everywhere; the
comparison against Painter's recorded bakes runs on the owner's machine only, where the private
store holds the oracles, and skips elsewhere with the reason.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from tools.parity.feasibility.compare import Difference
from tools.parity.normal_convention.cases import CASES
from tools.parity.normal_convention.prototype import MODES, TRANSFORMS, PrototypeBake
from tools.parity.normal_convention.report import (
    REPORT_PATH,
    SEMANTICS_PATH,
    green_sign,
    report_markdown,
    semantics_document,
)
from tools.parity.normal_convention.study import (
    OracleUnavailable,
    Residual,
    frame_verdict,
    run_study,
)
from tools.parity.schemas import Schema, load_json, validation_errors
from tools.parity.store.store import locate

PREFIX = "phase0/normal-convention/"


def diff(maximum: int, mean: float) -> Difference:
    return Difference(maximum, mean, maximum, 10 if maximum else 0, 300, 5 if maximum else 0, 100)


def hemisphere_residuals(golden: str, means: dict[str, float]) -> list[Residual]:
    return [
        Residual(golden, rec, name, "hit", diff(0 if mean == 0 else int(mean) + 3, mean))
        for rec in ("r1", "r2")
        for name, mean in means.items()
    ]


def test_frame_verdict_identifies_equal_and_close_modes() -> None:
    golden = PREFIX + "hemisphere/per-fragment"
    means = {f"{m}-{t}-opengl": 50.0 for m in MODES for t in TRANSFORMS}
    means["PerFragment-inverse-opengl"] = 0.0
    verdict = frame_verdict(hemisphere_residuals(golden, means))
    assert verdict["best_mode"] == "PerFragment" and verdict["equal"] and verdict["identified"]
    means["PerFragment-inverse-opengl"] = 2.0
    verdict = frame_verdict(hemisphere_residuals(golden, means))
    assert verdict["best_mode"] == "PerFragment" and not verdict["equal"]
    means["PerFragment-inverse-opengl"] = 40.0  # not a tenth of the other mode's 50
    verdict = frame_verdict(hemisphere_residuals(golden, means))
    assert verdict["best_mode"] is None and verdict["closest_mode"] == "PerFragment"
    assert not verdict["identified"]


def test_green_sign() -> None:
    base = {"red_plus_u": 5000.0, "red_minus_u": -5000.0}
    assert green_sign({**base, "green_plus_v": 4000.0, "green_minus_v": -4000.0}) == 1
    assert green_sign({**base, "green_plus_v": -4000.0, "green_minus_v": 4000.0}) == -1
    assert green_sign({**base, "green_plus_v": 4000.0, "green_minus_v": 4000.0}) == 0


def synthetic_study() -> dict[str, Any]:
    residuals: list[Residual] = []
    frames: dict[str, Any] = {}
    for case in CASES:
        if case.pair == "plane-dome":
            name = f"PerFragment-inverse-{case.normal_map_format.lower()}"
            for rec in ("r1", "r2"):
                residuals.append(Residual(case.golden_id, rec, name, "hit", diff(1, 0.1)))
                if case.normal_map_format == "OpenGL":
                    residuals.append(Residual(case.golden_id, rec, name, "miss", diff(0, 0.0)))
        else:
            means = {f"{m}-{t}-opengl": 60.0 for m in MODES for t in TRANSFORMS}
            means["PerFragment-inverse-opengl"] = 1.0
            mine = hemisphere_residuals(case.golden_id, means)
            residuals += mine
            frames[case.golden_id] = frame_verdict(mine)
    flat = {"red_plus_u": 9000.0, "red_minus_u": -9000.0}
    return {
        "stability": [
            {"golden_id": c.golden_id, "domain": "hit", "difference": diff(0, 0.0).as_dict()}
            for c in CASES
        ],
        "residuals": [r.as_dict() for r in residuals],
        "frames": frames,
        "project_default_vs": {
            "per-fragment": diff(0, 0.0).as_dict(),
            "per-vertex": diff(900, 70.0).as_dict(),
        },
        "directions": {
            PREFIX + "plane-dome/opengl": {
                "normal_map_format": "OpenGL",
                "oracle_r1": {**flat, "green_plus_v": 9000.0, "green_minus_v": -9000.0},
                "oracle_r2": {**flat, "green_plus_v": 9000.0, "green_minus_v": -9000.0},
                "prototype": {**flat, "green_plus_v": 9000.0, "green_minus_v": -9000.0},
            },
            PREFIX + "plane-dome/directx": {
                "normal_map_format": "DirectX",
                "oracle_r1": {**flat, "green_plus_v": -9000.0, "green_minus_v": 9000.0},
                "oracle_r2": {**flat, "green_plus_v": -9000.0, "green_minus_v": 9000.0},
                "prototype": {**flat, "green_plus_v": -9000.0, "green_minus_v": 9000.0},
            },
        },
        "prototype_summaries": {
            "hemisphere": {"round_trip_degrees": {"PerVertex-inverse": {"exact": 0, "coded": 0}}}
        },
        "domain_texels": {"plane-dome": {"hit": 10, "miss": 5}, "hemisphere": {"hit": 20}},
    }


def test_semantics_document_validates_and_states_verdicts() -> None:
    document = semantics_document(synthetic_study())
    assert validation_errors(document, Schema.SEMANTICS) == []
    entries = {e["entry_id"]: e for e in document["entries"]}
    assert entries["green-channel-opengl"]["status"] == "calibrated"
    assert entries["no-hit-texels"]["status"] == "exact"
    assert entries["tangent-frame-per-fragment"]["status"] == "calibrated"
    params = {p["name"]: p["value"] for p in entries["tangent-frame-per-fragment"]["parameters"]}
    assert params["identified_mode"] == "PerFragment"
    report = report_markdown(synthetic_study(), {"machine": "test"})
    assert "tangent-frame-per-vertex" in report and "## 8. External consumer" in report


def test_published_documents_hold_numbers_only() -> None:
    """The committed semantics validate and the report quotes no recorded value: no file paths
    of the store, no blob hashes beyond the manifests' (none at all here)."""
    if not SEMANTICS_PATH.exists():
        pytest.skip("parity/semantics/tangent-frame.json is written by the owner-machine run")
    document = load_json(SEMANTICS_PATH)
    assert validation_errors(document, Schema.SEMANTICS) == []
    assert set(document["corpus"]) == {c.golden_id for c in CASES}
    report = REPORT_PATH.read_text(encoding="utf-8")
    assert not re.search(r"\b[0-9a-f]{64}\b", report)
    assert "parity-store" not in report and "oracle-inbox" not in report


def test_comparison_against_painter_recordings(
    prototype_bakes: dict[str, PrototypeBake],
) -> None:
    """Task 3.2 (owner's machine): both frame modes against both recordings of every golden;
    the published residuals are reproduced exactly; oracle recordings are stable; the OpenGL
    golden's green rises towards +v and the DirectX golden's towards -v."""
    unrecorded = [
        c.golden_id
        for c in CASES
        if not json.loads(c.manifest_path.read_text(encoding="utf-8"))["private_records"]
    ]
    if unrecorded:
        pytest.skip(f"not recorded yet: {unrecorded}")
    store = locate()
    if store is None:
        pytest.skip("no private oracle store on this machine (oracle_unavailable)")
    try:
        study = run_study(store, prototype_bakes)
    except OracleUnavailable as error:
        pytest.skip(f"oracle_unavailable: {error}")
    for item in study["stability"]:
        assert item["difference"]["max"] == 0, item["golden_id"]
    published = load_json(SEMANTICS_PATH)
    assert semantics_document(study)["entries"] == published["entries"]
    directions = study["directions"]
    for key, value in directions[PREFIX + "plane-dome/opengl"].items():
        if key.startswith("oracle_"):
            assert green_sign(value) == 1, key
    for key, value in directions[PREFIX + "plane-dome/directx"].items():
        if key.startswith("oracle_"):
            assert green_sign(value) == -1, key
