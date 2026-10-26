"""Execute the actual guarded cleanup body against public API-shaped fakes."""

from __future__ import annotations

import ast
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tools.parity.recorder.probes import probe_constants, probe_job_from_manifest
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control


def function(path: str, name: str, namespace: dict[str, Any]) -> Any:
    tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    module = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            node,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), path, "exec"), namespace)
    return namespace[name]


def setup() -> tuple[Any, dict[str, Any], Any, list[Any], Mock]:
    marker: dict[str, Any] = {"uuid": "public-project", "pending": True}
    node = SimpleNamespace(uid=lambda: 17, get_type=lambda: SimpleNamespace(name="PaintLayer"))
    roots = [node]
    delete = Mock(side_effect=lambda node: roots.clear())
    project = SimpleNamespace(is_open=lambda: True, get_uuid=lambda: "public-project")
    api = SimpleNamespace(
        project=project,
        textureset=SimpleNamespace(get_active_stack=lambda: "public-stack"),
        layerstack=SimpleNamespace(
            get_root_layer_nodes=lambda stack: list(roots),
            get_node_by_uid=lambda uid: node,
            delete_node=delete,
        ),
    )
    run = function(
        "tools/parity/recorder/painter_probes.py",
        "remove_initial_paint",
        {"OWN_PROJECT_CREATION": marker, "substance_painter": api},
    )
    return run, marker, api, roots, delete


def test_cleanup_uses_owned_uuid_and_revalidated_root_once() -> None:
    run, marker, _, roots, delete = setup()
    result = run(2, {"initial_root": True, "expected_type": "PaintLayer"})
    assert result == {
        "created_project_uuid": "public-project",
        "current_project_uuid": "public-project",
        "before": {"uid": 17, "node_type": "PaintLayer"},
        "after_root_count": 0,
    }
    assert not roots and "pending" not in marker
    delete.assert_called_once()
    with pytest.raises(ValueError):
        run(2, {"initial_root": True, "expected_type": "PaintLayer"})
    delete.assert_called_once()


@pytest.mark.parametrize(
    "case",
    [
        "unowned",
        "closed",
        "foreign",
        "two",
        "empty",
        "type",
        "uid",
        "step",
        "caller_uid",
        "boolean",
    ],
)
def test_cleanup_refuses_before_deletion(case: str) -> None:
    run, marker, api, roots, delete = setup()
    args: dict[str, Any] = {"initial_root": True, "expected_type": "PaintLayer"}
    step = 2
    if case == "unowned":
        marker.clear()
    elif case == "closed":
        api.project.is_open = lambda: False
    elif case == "foreign":
        api.project.get_uuid = lambda: "other-project"
    elif case == "two":
        roots.append(roots[0])
    elif case == "empty":
        roots.clear()
    elif case == "type":
        roots[0].get_type = lambda: SimpleNamespace(name="FillLayer")
    elif case == "uid":
        api.layerstack.get_node_by_uid = lambda uid: SimpleNamespace(
            uid=lambda: 18, get_type=lambda: SimpleNamespace(name="PaintLayer")
        )
    elif case == "step":
        step = 3
    elif case == "caller_uid":
        args["uid"] = 17
    else:
        args["initial_root"] = 1
    with pytest.raises(ValueError):
        run(step, args)
    delete.assert_not_called()


def test_creation_marker_cannot_claim_an_already_open_project() -> None:
    marker: dict[str, Any] = {"uuid": "stale", "pending": True}
    project = SimpleNamespace(is_open=lambda: True)
    run = function(
        "tools/parity/recorder/painter_side.py",
        "create_project",
        {"OWN_PROJECT_CREATION": marker, "substance_painter": SimpleNamespace(project=project)},
    )
    with pytest.raises(RuntimeError):
        run({}, {"mesh": "public.obj"})
    assert marker == {}


def test_ordinary_delete_keeps_its_target_and_invalidates_cleanup() -> None:
    marker = {"uuid": "public-project", "pending": True}
    delete = Mock(return_value="ordinary result")
    run = function(
        "tools/parity/recorder/painter_probes.py",
        "edit",
        {
            **probe_constants(),
            "OWN_PROJECT_CREATION": marker,
            "delete_node": delete,
            "P22B_CALLS": (),
            "substance_painter": SimpleNamespace(layerstack=SimpleNamespace()),
        },
    )
    assert (
        run(5, "substance_painter.layerstack.delete_node", {"node_step": 3}, {})
        == "ordinary result"
    )
    delete.assert_called_once_with(3)
    assert "pending" not in marker


@pytest.mark.parametrize("uuid_available", [True, False])
def test_only_successful_owned_creation_can_arm_cleanup(uuid_available: bool) -> None:
    marker: dict[str, Any] = {}
    project = SimpleNamespace(
        is_open=lambda: False,
        Settings=lambda **kwargs: kwargs,
        create=Mock(),
        get_uuid=Mock(
            return_value="public-created",
            side_effect=None if uuid_available else RuntimeError("unavailable"),
        ),
    )
    run = function(
        "tools/parity/recorder/painter_side.py",
        "create_project",
        {
            "OWN_PROJECT_CREATION": marker,
            "substance_painter": SimpleNamespace(project=project),
            "SETTINGS_FOLDERS": (),
            "colour_management": lambda: {"mode": "ocio"},
        },
    )
    assert run({}, {"mesh": "public.obj"}) == {"colour_management": {"mode": "ocio"}}
    project.create.assert_called_once()
    assert marker == ({"uuid": "public-created", "pending": True} if uuid_available else {})


@pytest.mark.parametrize("mutation", ["probe", "position", "type", "extra", "boolean", "call"])
def test_manifest_selector_is_closed_and_never_repeated(mutation: str) -> None:
    manifest = control.request("calibration-float")
    steps = manifest["instruction_sequence"]["steps"]
    cleanup = steps[1]
    if mutation == "probe":
        cleanup["args"]["probe"] = True
    elif mutation == "position":
        steps[1], steps[2] = steps[2], steps[1]
        for i, step in enumerate(steps, 1):
            step["step"] = i
    elif mutation == "type":
        cleanup["args"]["expected_type"] = "FillLayer"
    elif mutation == "extra":
        cleanup["args"]["node_step"] = 1
    elif mutation == "boolean":
        cleanup["args"]["initial_root"] = 1
    else:
        cleanup["call"] = "substance_painter.layerstack.Node.set_visible"
    with pytest.raises(RecorderError):
        probe_job_from_manifest(manifest)
