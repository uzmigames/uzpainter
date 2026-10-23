"""Base-mesh controls use only the documented, undisplaced export and retain its outcome."""

from __future__ import annotations

import types
from collections.abc import Callable
from typing import Any

import pytest

from tools.parity.recorder.session import PainterCallError, PainterSession


@pytest.mark.parametrize("status", ["Success", "Warning", "Error", "Cancelled"])
def test_base_mesh_export_retains_outcome_and_never_selects_tessellation(
    fake: types.ModuleType,
    make_session: Callable[[Any], PainterSession],
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    world = fake.FakeWorld()
    project = world.modules["substance_painter.project"]
    export = world.modules["substance_painter.export"]
    base_mesh = object()
    calls = []

    def record(path: str, option: object) -> Any:
        calls.append((path, option))
        return types.SimpleNamespace(status=types.SimpleNamespace(name=status), message="detail")

    monkeypatch.setattr(project, "is_in_edition_state", lambda: True)
    monkeypatch.setattr(project, "is_busy", lambda: False)
    monkeypatch.setattr(export, "export_mesh", record, raising=False)
    monkeypatch.setattr(
        export, "MeshExportOption", types.SimpleNamespace(BaseMesh=base_mesh), raising=False
    )
    session = make_session(world)
    session.connect()
    result = session.call("export_base_mesh", path="private/control.obj")
    assert calls == [("private/control.obj", base_mesh)]
    assert result["status"] == status and result["message"] == "detail"
    assert result["called_at"] <= result["returned_at"]


@pytest.mark.parametrize("edition,busy", [(False, False), (True, True)])
def test_base_mesh_export_refuses_before_the_api_when_project_is_not_ready(
    fake: types.ModuleType,
    make_session: Callable[[Any], PainterSession],
    monkeypatch: pytest.MonkeyPatch,
    edition: bool,
    busy: bool,
) -> None:
    world = fake.FakeWorld()
    project = world.modules["substance_painter.project"]
    export = world.modules["substance_painter.export"]

    def forbidden(*args: Any) -> None:
        pytest.fail("mesh export was called before the project was ready")

    monkeypatch.setattr(project, "is_in_edition_state", lambda: edition)
    monkeypatch.setattr(project, "is_busy", lambda: busy)
    monkeypatch.setattr(export, "export_mesh", forbidden, raising=False)
    session = make_session(world)
    session.connect()
    with pytest.raises(PainterCallError, match="project not ready for mesh export"):
        session.call("export_base_mesh", path="private/control.obj")
