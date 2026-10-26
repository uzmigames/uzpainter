"""The bound Project Configuration collector against an authored owned session (the real context
extension over the authored world) and an authored survey that drives the collector's sink as the
bound survey does; then one integrated chain: the real runner and collector, the real
configuration_survey over authored widgets, and the settings contract's split and derivation.
No UI automation, Painter or private data."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

from tests.parity.test_filter_context_run import Painter, load
from tests.parity.test_painter_filter_context import Session as ContextSession
from tests.parity.test_painter_filter_context import World
from tools.parity import filter_context_settings as settings
from tools.parity.filter_context_contract import BOUNDARIES, typed
from tools.parity.recorder import filter_context_run as run
from tools.parity.recorder import project_configuration_survey as survey
from tools.parity.recorder import settings_panel as panel
from tools.parity.recorder.filter_context import context_readback
from tools.parity.recorder.painter_ui import PainterUi
from tools.parity.recorder.probes import probe_job_from_manifest
from tools.parity.recorder.raw_capability_capture import RawSession
from tools.parity.recorder.session import PainterIdentity, PainterSession, RecorderError
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import filter_context_settings_control as settings_control

MESH = {
    "input_id": "plane",
    "resolved_path": "C:/private/run/inputs/plane.obj",
    "before": {"sha256": "1" * 64, "size_bytes": 371},
    "after": {"sha256": "1" * 64, "size_bytes": 371},
}
PID = 4242
MAIN = 9001
DIALOG = 7001
UUID = "authored-project"


class Picture:
    def save(self, stream: Any, format: str) -> None:
        assert format == "PNG"
        stream.write(b"authored png")


def owned() -> tuple[World, Any, Any]:
    """A session that claimed its own creation of the authored project, and its UI."""
    world = World()
    world.setup = True
    context = ContextSession(world)
    session = SimpleNamespace(
        identity=SimpleNamespace(session_id="authored-session"),
        owned=SimpleNamespace(
            launcher=SimpleNamespace(pid=PID),
            started="authored-start",
            project_uuid=UUID,
            verify=lambda: None,
        ),
        created=True,
        created_uuid=UUID,
        call=context.call,
    )
    ui = SimpleNamespace(
        window=SimpleNamespace(handle=MAIN, process_id=lambda: PID),
        print_window=Mock(return_value=(Picture(), (1, 1))),
    )
    return world, session, ui


def bound_survey(change: Any = None) -> Any:
    """Calls the sink as configuration_survey(physical_size=True, bind_identity=True) does."""

    def collect(
        ui: Any, owned: Any, sink: Any, *, physical_size: bool, bind_identity: bool
    ) -> None:
        assert physical_size and bind_identity
        dialog = {"hwnd": DIALOG, "pid": owned.launcher.pid}
        sink.log("navigation", phase="before_front")
        sink.json("menu", [{"authored": "Edit menu"}])
        sink.json(
            "configuration", {"tree": {"authored": 1}, "values": [{"v": 0}], "dialog": dialog}
        )
        sink.image("configuration_image", ui, DIALOG)
        if change is not None:
            change(ui, owned, sink)
        sink.json(
            "physical_size",
            {
                "expanded_by_click": True,
                "tree": {"authored": 2},
                "values": [{"v": 1}],
                "dialog": dialog,
            },
        )
        sink.image("physical_size_image", ui, DIALOG)

    return collect


def read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: Any = None,
    *,
    setup: Any = None,
    pid_of: Any = None,
    **kwargs: Any,
) -> tuple[Any, list[dict[str, Any]], list[Path], Any]:
    world, session, ui = owned()
    if setup is not None:
        setup(world, session, ui)
    collect = Mock(side_effect=bound_survey(change))
    monkeypatch.setattr(survey, "configuration_survey", collect)
    frame = context_readback(session, "after-setup6")
    outputs, files = panel.read_settings_panel(
        cast(RawSession, session),
        cast(PainterUi, ui),
        kwargs.get("boundary", "after-setup6"),
        frame,
        kwargs.get("run_dir", tmp_path),
        kwargs.get("mesh", MESH),
        pid_of=pid_of or (lambda handle: PID),
    )
    return frame, outputs, files, collect


def test_the_panel_binds_ui_observations_to_the_owned_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame, outputs, files, _ = read(tmp_path, monkeypatch)
    readback, configuration, physical = outputs
    assert set(readback) == {"output_id", "kind", "panel", "values"}
    assert readback["output_id"] == "settings/after-setup6/panel"
    assert readback["kind"] == "settings_panel_readback"
    values = readback["values"]
    assert set(values) == {
        "schema",
        "boundary",
        "condition",
        "binding",
        "mesh_import",
        "ui",
        "images",
    }
    assert (values["schema"], values["boundary"], values["condition"]) == (
        panel.SCHEMA,
        "after-setup6",
        "same_session",
    )
    binding = values["binding"]
    assert set(binding) == {
        "before",
        "after",
        "context_before_sha256",
        "context_after_sha256",
        "context_after_outputs",
    }
    assert (
        binding["before"]
        == binding["after"]
        == {
            "session_id": "authored-session",
            "pid": PID,
            "started": "authored-start",
            "project_uuid": UUID,
            "main_hwnd": MAIN,
        }
    )
    digest = hashlib.sha256(typed(frame["outputs"])).hexdigest()
    assert binding["context_before_sha256"] == binding["context_after_sha256"] == digest
    assert typed(binding["context_after_outputs"]) == typed(frame["outputs"])
    assert values["mesh_import"] == MESH
    assert set(values["ui"]) == {"configuration", "physical_size"}
    assert values["images"] == [
        {"output_id": "settings/after-setup6/configuration-image", "hwnd": DIALOG, "pid": PID},
        {"output_id": "settings/after-setup6/physical-size-image", "hwnd": DIALOG, "pid": PID},
    ]
    assert [o["output_id"] for o in (configuration, physical)] == [
        "settings/after-setup6/configuration-image",
        "settings/after-setup6/physical-size-image",
    ]
    for output, path in zip((configuration, physical), files, strict=True):
        assert output["kind"] == "settings_panel_evidence" and output["panel"] == panel.PANEL
        assert path.parent == tmp_path.resolve() and path.read_bytes() == b"authored png"
        assert output["blob"] == {
            "sha256": hashlib.sha256(b"authored png").hexdigest(),
            "size_bytes": len(b"authored png"),
            "media_type": "image/png",
        }


def _other_process(ui: Any, owned: Any, sink: Any) -> None:
    owned.launcher.pid = 4343


def _other_window(ui: Any, owned: Any, sink: Any) -> None:
    ui.window.handle = 9002


def _repeat(ui: Any, owned: Any, sink: Any) -> None:
    sink.json("configuration", {})


def _unexpected(ui: Any, owned: Any, sink: Any) -> None:
    sink.json("main", {})


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (_other_process, "owned identity changed"),
        (_other_window, "owned identity changed"),
        (_repeat, "repeated configuration snapshot"),
        (_unexpected, "unexpected main snapshot"),
    ],
)
def test_a_changed_identity_or_snapshot_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: Any, reason: str
) -> None:
    with pytest.raises(ValueError, match=reason):
        read(tmp_path, monkeypatch, change)


def test_a_context_changed_by_the_survey_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worlds: list[World] = []

    def change(ui: Any, owner: Any, sink: Any) -> None:
        worlds[0].setup = False

    with pytest.raises(ValueError, match="changed the context"):
        read(tmp_path, monkeypatch, change, setup=lambda world, *_: worlds.append(world))


def test_a_foreign_panel_window_refuses_before_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uis: list[Any] = []
    with pytest.raises(survey.OwnershipLost, match="foreign panel window"):
        read(tmp_path, monkeypatch, setup=lambda _w, _s, ui: uis.append(ui), pid_of=lambda h: 99)
    uis[0].print_window.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_a_window_changed_during_capture_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = iter([PID, 99])
    with pytest.raises(survey.OwnershipLost, match="changed during capture"):
        read(tmp_path, monkeypatch, pid_of=lambda handle: next(answers))
    assert list(tmp_path.iterdir()) == []


def test_ownership_lost_during_capture_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checks: list[int] = []

    def verify() -> None:
        checks.append(1)
        if len(checks) > 2:  # the collector's guard and the sink's guard before the capture
            raise survey.OwnershipLost("authored ownership loss")

    def setup(world: Any, session: Any, ui: Any) -> None:
        session.owned.verify = verify

    with pytest.raises(survey.OwnershipLost, match="authored ownership loss"):
        read(tmp_path, monkeypatch, setup=setup)
    assert len(checks) == 3
    assert list(tmp_path.iterdir()) == []


def _not_created(world: Any, session: Any, ui: Any) -> None:
    session.created = False


def _empty_uuid(world: Any, session: Any, ui: Any) -> None:
    session.created_uuid = session.owned.project_uuid = ""


def _other_uuid(world: Any, session: Any, ui: Any) -> None:
    session.created_uuid = session.owned.project_uuid = "another-project"


def _foreign_ui(world: Any, session: Any, ui: Any) -> None:
    ui.window.process_id = lambda: 99


@pytest.mark.parametrize(
    ("setup", "where", "reason"),
    [
        (None, "repository", "inside the repository"),
        (None, "missing", "private run directory must exist"),
        (_not_created, None, "has not claimed the owned project"),
        (_empty_uuid, None, "has not claimed the owned project"),
        (_other_uuid, None, "has not claimed the owned project"),
        (_foreign_ui, None, "UI window process changed"),
    ],
)
def test_unowned_preconditions_refuse_before_any_ui_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    setup: Any,
    where: str | None,
    reason: str,
) -> None:
    run_dir = {"repository": REPO_ROOT / "tmp" / "scratch", "missing": tmp_path / "absent"}
    kwargs = {"run_dir": run_dir[where]} if where else {}
    uis: list[Any] = []

    def observe(world: Any, session: Any, ui: Any) -> None:
        uis.append(ui)
        if setup is not None:
            setup(world, session, ui)

    with pytest.raises((ValueError, RecorderError), match=reason):
        read(tmp_path, monkeypatch, setup=observe, **kwargs)
    cast(Mock, survey.configuration_survey).assert_not_called()
    uis[0].print_window.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_inputs_outside_the_protocol_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="unknown boundary"):
        read(tmp_path, monkeypatch, boundary="pre16-r1")
    with pytest.raises(ValueError, match="mesh import packet incomplete"):
        read(tmp_path, monkeypatch, mesh={k: v for k, v in MESH.items() if k != "after"})


def test_images_are_written_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "settings-after-setup6-configuration-image.png").write_bytes(b"earlier")
    with pytest.raises(FileExistsError):
        read(tmp_path, monkeypatch)
    assert (tmp_path / "settings-after-setup6-configuration-image.png").read_bytes() == b"earlier"


# The integrated chain ---------------------------------------------------------------------------


class Control:
    """An authored UI Automation element exposing what configuration_survey and PainterUi.survey
    read; the toggle and selection patterns exist only where the authored widget has them."""

    def __init__(
        self,
        label: str,
        kind: str,
        automation_id: str = "",
        *,
        handle: int = 0,
        children: list[Control] | None = None,
        toggle: int | None = None,
        selected: int | None = None,
        visible: bool = True,
    ) -> None:
        self.label, self.handle, self.visible = label, handle, visible
        self.element_info = SimpleNamespace(
            control_type=kind, automation_id=automation_id, class_name="QWidget"
        )
        self.items = children or []
        if toggle is not None:
            self.iface_toggle = SimpleNamespace(CurrentToggleState=toggle)
        if selected is not None:
            self.iface_selection_item = SimpleNamespace(CurrentIsSelected=selected)

    def process_id(self) -> int:
        return PID

    def is_visible(self) -> bool:
        return self.visible

    def is_enabled(self) -> bool:
        return True

    def window_text(self) -> str:
        return self.label

    def children(self) -> list[Control]:
        return list(self.items)

    def iter_children(self) -> Any:
        return iter(self.items)

    def descendants(self) -> list[Control]:
        found: list[Control] = []
        for child in self.items:
            found += [child, *child.descendants()]
        return found

    def rectangle(self) -> Any:
        return SimpleNamespace(left=0, top=0, right=10, bottom=10)


def widget(name: str, **state: Any) -> Control:
    automation_id, kind, label = settings.SELECTORS[name]
    return Control(label, kind, automation_id, **state)


def configuration_ui(custom: int) -> Any:
    """The main window, and a Project Configuration dialog whose Physical size content stays
    hidden until its title is clicked; Cancel hides the dialog."""
    internal = widget("internal", selected=1, visible=False)
    other = widget("custom", selected=custom, visible=False)
    title = Control("Physical size", "Button", survey.PHYSICAL_SIZE_TITLE)
    section = Control("", "Group", survey.PHYSICAL_SIZE_SECTION, children=[title, internal, other])
    dialog = Control(
        "Project Configuration",
        "Window",
        handle=DIALOG,
        children=[
            widget("tangent", toggle=0),
            widget("workflow", toggle=0),
            section,
            Control("Cancel", "Button"),
        ],
    )
    main = Control("Painter", "Window", handle=MAIN)

    def click(element: Control, **_: Any) -> None:
        if element is title:
            internal.visible = other.visible = True
        if element.label == "Cancel":
            dialog.visible = False

    ui = Mock(window=main, settle_s=0)
    ui.menu_item.side_effect = lambda label: Control(label, "MenuItem")
    ui.menu_containers.return_value = [main]
    ui.desktop.windows.return_value = [dialog]
    ui.survey.side_effect = PainterUi.survey
    ui.print_window.return_value = (Picture(), (1, 1))
    ui.click.side_effect = click
    return ui


class OwnedPainter(Painter):
    """The authored Painter as an owned session that claims the project it creates; creation
    records the staged mesh as the last imported mesh."""

    def __init__(self) -> None:
        super().__init__({13: {"value": None}, 15: {"value": None}})
        self.created = False
        self.created_uuid: str | None = None
        self.owned = SimpleNamespace(
            launcher=SimpleNamespace(pid=PID),
            started="authored-start",
            project_uuid=None,
            verify=lambda: None,
        )

    def connect(self) -> PainterIdentity:
        self.identity = super().connect()
        return self.identity

    def call(self, operation: str, **args: Any) -> Any:
        if operation == "apply_step" and "mesh" in args.get("resolved", {}):
            mesh = args["resolved"]["mesh"]
            self.context.probes["substance_painter"].project.last_imported_mesh_path = lambda: mesh
            self.created, self.created_uuid, self.owned.project_uuid = True, UUID, UUID
        return super().call(operation, **args)


def record_settings_golden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, custom: int) -> Path:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(survey, "desktop_state", lambda: {"available": True, "reason": "ok"})
    monkeypatch.setattr(survey, "navigation_state", lambda ui, element: {})
    painter = OwnedPainter()

    def reader(
        boundary: str, frame: dict[str, Any], run_dir: Path, mesh_import: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[Path]]:
        return panel.read_settings_panel(
            cast(RawSession, painter),
            cast(PainterUi, configuration_ui(custom)),
            boundary,
            frame,
            run_dir,
            mesh_import,
            pid_of=lambda handle: PID,
        )

    return run.record_filter_context_golden(
        cast(PainterSession, painter),
        probe_job_from_manifest(settings_control.request()),
        tmp_path / "work",
        tmp_path / "inbox",
        settings_panel=reader,
    )


def test_the_integrated_chain_derives_the_target_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = record_settings_golden(tmp_path, monkeypatch, custom=0)
    assert run.check_capture(directory, settings_control)["golden_id"] == settings.GOLDEN_ID
    stripped, panels = settings.split_settings_outputs(load(directory))
    assert [p["boundary"] for p in panels] == list(BOUNDARIES)
    assert all(p["ui"]["physical_size"]["expanded_by_click"] is True for p in panels)
    evidence = run._f_evidence_from_record(
        stripped,
        settings_control.request()["instruction_sequence"],
        expected_golden_id=settings.GOLDEN_ID,
    )
    derived = settings.derive_effective_settings(evidence, panels, survey.PLANE.read_bytes())
    assert (
        derived.tangent_space,
        derived.workflow,
        derived.effective_cm_per_unit,
        derived.provenance_basis,
    ) == ("PerVertex", "Default", 1, settings.PROVENANCE_BASIS)
    # Each image was written once in the private run directory; the inbox keeps its blob.
    images = list((tmp_path / "work").rglob("settings-*.png"))
    assert len(images) == 2 * len(BOUNDARIES)
    digest = hashlib.sha256(b"authored png").hexdigest()
    assert (directory / "blobs" / digest).read_bytes() == b"authored png"


def test_the_integrated_chain_refuses_a_non_target_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = record_settings_golden(tmp_path, monkeypatch, custom=1)
    with pytest.raises(settings.SettingsRefused, match="NON_TARGET_STATE"):
        settings.split_settings_outputs(load(directory))
