"""The UI operator of the Iray procedure (decision 029, task `phase0.6_render-reference-procedure`)
without Painter: label parsing, value formatting, and how `UiOperator` answers the recorder's
prompts through a stand-in for Painter's panels."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder.iray import (
    PanelSetting,
    SettingsSheet,
    convergence,
    operator_form,
)
from tools.parity.recorder.painter_ui import (
    CONTROLS,
    IrayInfo,
    UiOperator,
    control_for,
    hex_colour,
    iray_info_from_labels,
    number_text,
    on_off,
    parse_fraction,
    parse_times,
    parse_value,
)
from tools.parity.recorder.session import RecorderError

DONE = IrayInfo("Done", 256, 256, 2, 3600, "1200x1200")


def test_iray_information_labels_are_parsed() -> None:
    info = iray_info_from_labels(
        {
            "statusLabel": "Done",
            "iterationsLabel": "256/256",
            "timeLabel": "00:00:02/01:00:00",
            "resolutionLabel": "1200x1200",
        }
    )
    assert info == DONE
    assert parse_fraction("808/1000") == (808, 1000)
    assert parse_times("01:02:03/02:00:00") == (3723, 7200)
    with pytest.raises(RecorderError):
        parse_fraction("808 of 1000")
    with pytest.raises(RecorderError):
        parse_times("00:00:10")


def test_values_are_typed_and_read_as_painter_shows_them() -> None:
    assert number_text(256) == "256" and number_text(0.0) == "0" and number_text(1.5) == "1.5"
    with pytest.raises(RecorderError):
        number_text(True)
    assert on_off(False) is False and on_off("On") is True
    with pytest.raises(RecorderError):
        on_off("maybe")
    assert hex_colour("#8d8e94") == "8D8E94"
    with pytest.raises(RecorderError):
        hex_colour("8D8E9")
    assert parse_value("256") == 256 and parse_value("0.0") == 0.0
    assert parse_value("False") is False and parse_value("Infinite sphere") == "Infinite sphere"


def test_every_sheet_setting_of_the_procedure_has_a_widget() -> None:
    from tools.parity.recorder.iray_probe import V2_SHEET, VIEWPORT_SHEET

    for setting in (*V2_SHEET, *VIEWPORT_SHEET):
        control_for(setting.panel, setting.setting)
    assert CONTROLS["Viewer and MDL Settings/Dome"] == CONTROLS["Display Settings/Dome"]
    with pytest.raises(RecorderError, match="no widget"):
        control_for("Iray Settings", "Denoiser")


@dataclass
class FakeUi:
    """Painter's panels as the operator sees them: a value per setting and Iray's state."""

    values: dict[str, str] = field(default_factory=dict)
    saved: list[Path] = field(default_factory=list)
    images: list[str] = field(default_factory=list)

    def apply(self, panel: str, setting: str, value: Any, unit: str | None) -> str:
        shown = ("on" if value else "off") if isinstance(value, bool) else str(value)
        self.values[f"{panel}/{setting}"] = shown
        return shown

    def read(self, panel: str, setting: str) -> str:
        return self.values[f"{panel}/{setting}"]

    def wait_done(self, timeout_s: float) -> IrayInfo:
        return DONE

    def iray_info(self) -> IrayInfo:
        return DONE

    def panel_image(self, panel: str, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.images.append(panel)
        return path

    def viewport_image(self, path: Path) -> tuple[int, int]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return (1523, 1174)

    def save_render(self, target: Path) -> IrayInfo:
        target.write_bytes(b"render")
        self.saved.append(target)
        return DONE


def operator(tmp_path: Path) -> tuple[UiOperator, FakeUi]:
    ui = FakeUi()
    return UiOperator(ui, tmp_path / "images", clock=lambda: 0.0), ui  # type: ignore[arg-type]


def test_the_operator_form_is_applied_and_read_back(tmp_path: Path) -> None:
    robot, ui = operator(tmp_path)
    settings = (
        PanelSetting("Iray Settings", "Max Time", 3600, "s"),
        PanelSetting("Iray Settings", "Firefly Filter", False, None),
        PanelSetting("Display Settings", "Dome", "Infinite sphere", None),
        PanelSetting("Iray Settings", "Width", 1200, "px"),
    )
    sheet = SettingsSheet(256, 3600.0, 1200, 1200, settings, None, "0" * 64)
    outputs, evidence, _ = operator_form(robot, sheet, 256, tmp_path / "form")
    assert [e["value"] for e in outputs[0]["entries"]] == [3600, False, "Infinite sphere", 1200]
    assert ui.values["Display Settings/Dome"] == "Infinite sphere"
    assert sorted(item["panel"] for item in evidence) == ["Display Settings", "Iray Settings"]
    robot.tell("Let Iray converge: Min Sample = Max Sample = 256, Max Time 3600 s.")
    assert convergence(robot, sheet, 256)["iterations"] == 256
    assert [entry["action"] for entry in robot.log].count("set") == 4


def test_save_render_and_changes_follow_the_prompts(tmp_path: Path) -> None:
    robot, ui = operator(tmp_path)
    target = tmp_path / "render" / "reference.png"
    target.parent.mkdir()
    robot.tell(f"Use Save Render now and save the image as: {target}")
    assert robot.ask("Press Enter once the file is saved.") == ""
    assert ui.saved == [target]
    assert robot.ask("What did Status read when you saved? (Rendering/Paused/Done)") == "Done"
    robot.ask("Set Display Settings / Clear color value to 8D8E94, then press Enter.")
    robot.ask("Set Iray Settings / Max Time to 60 s, then press Enter.")
    assert ui.values["Display Settings/Clear color value"] == "8D8E94"
    assert robot.ask("[Display Settings] Clear color value: value shown now:") == "8D8E94"
    assert Path(robot.ask("Path of an image of the 3D viewport (live view, V):")).is_file()
    assert robot.ask("Does Status in the Iray information section read Done? (yes/no)") == "yes"


def test_an_unknown_prompt_stops_the_run(tmp_path: Path) -> None:
    robot, _ = operator(tmp_path)
    with pytest.raises(RecorderError, match="does not handle"):
        robot.ask("Paint a stroke on the sphere:")
    with pytest.raises(RecorderError, match="no Save Render target"):
        robot.ask("Press Enter once the file is saved.")


def test_a_texture_set_list_prompt_reaches_the_rename(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision 093: the sheet's `Texture Set List/Name (<set>)` prompt names the row by the
    name the set has now; reading it changes nothing, setting it renames that row."""
    from tools.parity.recorder.painter_ui import PainterUi

    calls: list[tuple[str, str | None]] = []

    def rename(listed: str, value: str | None) -> str:
        calls.append((listed, value))
        return "renamed0"

    ui = PainterUi.__new__(PainterUi)
    monkeypatch.setattr(ui, "texture_set_name", rename)
    assert ui.target_value("Texture Set List", "Name of texture set 's0'", "renamed0") == "renamed0"
    assert ui.target_value("Texture Set List", "Name of texture set 'renamed0'", None) == "renamed0"
    assert ui.target_value("Texture Set List", "Visibility of texture set 's0'", None) is None
    assert calls == [("s0", "renamed0"), ("renamed0", None)]


# --- SUP-018: the window of the started process, and a contained Export resource name -------


class FakeElementNotFound(Exception):
    pass


class FakeElementAmbiguous(Exception):
    pass


@dataclass
class FakeWindow:
    pid: int

    def process_id(self) -> int:
        return self.pid


def fake_pywinauto(
    monkeypatch: pytest.MonkeyPatch, pids: list[int], report: int | None = None
) -> list[dict[str, Any]]:
    """A pywinauto stand-in whose desktop holds one main window per process id; `report`
    makes the bound window claim another process."""
    import sys
    import types

    criteria_seen: list[dict[str, Any]] = []

    class Spec:
        def __init__(self, criteria: dict[str, Any]) -> None:
            self.criteria = criteria

        def wrapper_object(self) -> FakeWindow:
            wanted = self.criteria.get("process")
            found = [p for p in pids if wanted is None or p == wanted]
            if not found:
                raise FakeElementNotFound(self.criteria)
            if len(found) > 1:
                raise FakeElementAmbiguous(self.criteria)
            return FakeWindow(report if report is not None else found[0])

    class Desktop:
        def __init__(self, backend: str) -> None:
            assert backend == "uia"

        def window(self, **criteria: Any) -> Spec:
            criteria_seen.append(criteria)
            return Spec(criteria)

    package = types.ModuleType("pywinauto")
    package.Desktop = Desktop  # type: ignore[attr-defined]
    package.mouse = object()  # type: ignore[attr-defined]
    findwindows = types.ModuleType("pywinauto.findwindows")
    findwindows.ElementNotFoundError = FakeElementNotFound  # type: ignore[attr-defined]
    findwindows.ElementAmbiguousError = FakeElementAmbiguous  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pywinauto", package)
    monkeypatch.setitem(sys.modules, "pywinauto.findwindows", findwindows)
    return criteria_seen


def test_the_ui_binds_only_the_main_window_of_the_given_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.parity.recorder.painter_ui import MAIN_WINDOW_CLASS, PainterUi

    seen = fake_pywinauto(monkeypatch, [7, 9])  # 7: a Painter this run did not start
    assert PainterUi(pid=9).window.process_id() == 9
    assert seen[-1] == {"class_name": MAIN_WINDOW_CLASS, "process": 9}
    with pytest.raises(RecorderError, match="process 11"):
        PainterUi(pid=11)
    fake_pywinauto(monkeypatch, [9], report=7)
    with pytest.raises(RecorderError, match="belongs to process 7, not 9"):
        PainterUi(pid=9)


REJECTED_NAMES = [
    "",
    ".",
    "..",
    r"C:\Users\x\a.png",  # absolute
    "/tmp/a.png",  # rooted
    r"\a.png",  # rooted on the current drive
    "C:a.png",  # drive-relative
    r"\\server\share\a.png",  # UNC
    r"sub\a.png",  # separator
    "sub/a.png",
    r"..\a.png",  # parent
    "../a.png",
    "a.png:stream",  # alternate data stream
    "*.png",  # a dialog filter, not a name
    "a?.png",
    "NUL",  # device names
    "com1.png",
    "a.png.",  # Windows drops trailing dots and spaces
    "a.png ",
    "a\x00.png",
]


@pytest.mark.parametrize("name", REJECTED_NAMES)
def test_a_proposed_name_that_is_not_simple_is_refused(tmp_path: Path, name: str) -> None:
    from tools.parity.recorder.painter_ui import contained_file

    with pytest.raises(RecorderError):
        contained_file(tmp_path, name)


def test_a_simple_name_stays_inside_the_private_folder(tmp_path: Path) -> None:
    from tools.parity.recorder.painter_ui import contained_file

    assert contained_file(tmp_path, "uzp_rq_x_abcdef.png") == tmp_path.resolve() / (
        "uzp_rq_x_abcdef.png"
    )
    (tmp_path / "taken.png").write_bytes(b"")
    with pytest.raises(RecorderError, match="new file inside"):
        contained_file(tmp_path, "taken.png")


@dataclass
class Info:
    automation_id: str = ""
    control_type: str = ""
    class_name: str = ""


@dataclass
class Element:
    info: Info
    text: str = ""
    value: str = ""
    set_to: list[str] = field(default_factory=list)
    invoked: int = 0

    @property
    def element_info(self) -> Info:
        return self.info

    @property
    def iface_value(self) -> Element:
        return self

    @property
    def CurrentValue(self) -> str:
        return self.value

    def SetValue(self, text: str) -> None:
        self.set_to.append(text)

    def window_text(self) -> str:
        return self.text

    def is_enabled(self) -> bool:
        return True

    def invoke(self) -> None:
        self.invoked += 1

    def type_keys(self, keys: str) -> None:
        return None

    def descendants(self, control_type: str | None = None) -> list[Element]:
        return [Element(Info(control_type="MenuItem"), text="Export resource...")]

    def children(self) -> list[Element]:
        return []

    handle = 1


def save_dialog_ui(
    monkeypatch: pytest.MonkeyPatch, proposed: str
) -> tuple[Any, Element, Element, list[Any]]:
    """A PainterUi whose Export resource opens a native save dialog proposing `proposed`."""
    from tools.parity.recorder import painter_ui

    ui = painter_ui.PainterUi.__new__(painter_ui.PainterUi)
    ui.window_surveyed = False
    ui.window = Element(Info())
    name = Element(Info(automation_id="1001", control_type="Edit"), value=proposed)
    save = Element(Info(automation_id="1", control_type="Button"))
    dialog = Element(Info(class_name=painter_ui.DIALOG_CLASS), text="Save As")
    cancelled: list[Any] = []
    monkeypatch.setattr(ui, "asset_item", lambda gui_name, evidence: Element(Info()))
    monkeypatch.setattr(ui, "context_menu", lambda item: Element(Info()))
    monkeypatch.setattr(ui, "click", lambda element, owner=None: None)
    monkeypatch.setattr(ui, "file_dialog", lambda: dialog)
    monkeypatch.setattr(ui, "survey", lambda root: [])
    elements = [Element(Info(automation_id="FileTypeControlHost")), name]
    monkeypatch.setattr(ui, "dialog_elements", lambda d: elements)
    monkeypatch.setattr(ui, "file_types", lambda d: ["PNG (*.png)"])
    monkeypatch.setattr(ui, "cancel", cancelled.append)
    monkeypatch.setattr(ui, "dialog_button", lambda d, automation_id: save)
    monkeypatch.setattr(ui, "wait_dialog_closed", lambda: None)
    monkeypatch.setattr("tools.parity.recorder.painter_ui.time.sleep", lambda s: None)
    return ui, name, save, cancelled


def test_an_escaping_dialog_name_is_cancelled_before_saving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ui, name, save, cancelled = save_dialog_ui(monkeypatch, r"..\..\escape.png")
    evidence: dict[str, Any] = {}
    with pytest.raises(RecorderError, match="not a simple file name"):
        ui.export_resource("uzp_rq_x", tmp_path, evidence)
    assert name.set_to == [] and save.invoked == 0 and len(cancelled) == 1
    assert evidence["dialog"]["proposed"] == r"..\..\escape.png"


def test_a_simple_dialog_name_is_saved_inside_the_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ui, name, save, cancelled = save_dialog_ui(monkeypatch, "uzp_rq_x.png")
    assert ui.export_resource("uzp_rq_x", tmp_path, {}) == "Export resource..."
    assert name.set_to == [str(tmp_path.resolve() / "uzp_rq_x.png")]
    assert save.invoked == 1 and cancelled == []
