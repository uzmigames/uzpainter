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
