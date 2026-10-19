"""Windows UI automation of Painter's settings panels: the operator of the Iray procedure
(decision 029; task `phase0.6_render-reference-procedure`).

Decision 029 lets an agent operate Painter's UI through Windows UI automation and screenshots
when the documented API cannot reach a setting. This module is that operator, out of process:
it reads Painter's panels through Microsoft UI Automation (the accessibility tree Qt publishes,
where each widget's automation id is its object-name path) and acts through real mouse clicks
and keystrokes on the visible widgets. Painter's process is never entered, no Painter code is
read or called, and UI Automation patterns that change a widget without Qt's user signals
(Toggle, SetValue on Qt widgets) are not used: in Painter 12.1.5 they change the widget
without applying the setting. Every value set is read back from the widget after it is
committed (Enter for fields, the widget's own state for buttons and combo boxes); Iray's
information section is read back the same way. Panel images are taken with `PrintWindow`
(no focus change).

The native Save Render file dialog is driven through UI Automation patterns only (file type,
file name, Save), which the Windows dialog applies directly.

`UiOperator` answers the recorder's operator prompts (`iray.py`, `iray_probe.py`, and the
texture-golden settings sheet of `texture_sheet.py`) with these actions, so the console operator
and the automated operator follow the same procedure text. A prompt it does not recognise stops
the run.

Texture goldens (task `phase0.7_tier0-semantics-ui-cases`) use docked panels that Painter
12.1.5 shows as tabs of the main window: Texture Set Settings (the height-to-normal method of
the texture set the recorder made active) and Layers (a layer's blending mode in the channel
chosen in the panel's channel selector, through the row's blending-mode menu). The Texture Set
List renames a texture set (a double click on its row's name, the name typed and committed with
Enter; decision 093), which the documented API cannot do. A hidden tab is
brought forward with UI Automation's tab selection, which only navigates and sets nothing.
Before every click on these panels the point is checked to belong to Painter's own window (or
to the menu it opened), so a click can never land on a window that covers Painter.

Dev-only dependencies (never shipped): `pywinauto` (with `comtypes`), `pywin32`, `Pillow`. They
are imported when a `PainterUi` is created, so the rest of the recorder and its tests do not
need them.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.parity.recorder.iray import same_value
from tools.parity.recorder.session import RecorderError

MAIN_WINDOW_CLASS = "Alg::S4MainWindow"
DIALOG_CLASS = "#32770"
COLOR_WIDGET_CLASS = "Alg::ColorWidget"

# Panel name in a settings sheet -> (dock toggle button text, dock automation id).
DOCKS = {
    "Renderer Settings": ("Renderer Settings", "QApplication.irayParametersView"),
    "Display Settings": ("Display Settings", "QApplication.displaySettings"),
    "Shader Settings": ("Shader settings", "QApplication.ShaderSettings"),
}
# Sheet panel names that are UzPainter's names for a Painter 12.1.5 dock.
PANEL_DOCKS = {
    "Iray Settings": "Renderer Settings",
    "Renderer Settings": "Renderer Settings",
    "Display Settings": "Display Settings",
    "Viewer and MDL Settings": "Display Settings",
    "Shader Settings": "Shader Settings",
}
SLIDER_VALUE = ".QWidget.Alg::SliderHeader.value"
# Main-window docks shown as tabs (texture goldens): sheet panel -> (tab title, automation id).
TAB_DOCKS = {
    "Texture Set Settings": (
        "Texture Set Settings",
        "QApplication.S4MainWindow.textureSetSettings",
    ),
    "Layers": ("Layers", "QApplication.S4MainWindow.LayersStackView"),
    "Texture Set List": ("Texture Set List", "QApplication.S4MainWindow.TextureSetsView"),
}
TEXTURE_SET_NAME = ".MaterialViewGeneralProperties.name.Alg::ElidedLabel.QLabel"
TEXTURE_SET_COMBOS = {"Height to normal method": ".height2NormalMethod"}
CHANNEL_SELECTOR = ".channelSelector"
LAYER_NAME = ".layerWidget.name.Alg::ElidedLabel.QLabel"
LAYER_BLENDING = ".layerWidget.blendingMode"
MENU_CLASS = "QMenu"
# What a layer row's blending-mode button shows for a menu label (Painter 12.1.5, observed).
BLENDING_SHOWN = {"Pthr": "Passthrough", "Norm": "Normal"}
TEXTURE_SET_TARGET = re.compile(r"^(?P<setting>.+) of texture set '(?P<texture_set>[^']+)'$")
LIST_TARGET = re.compile(r"^Name of texture set '(?P<texture_set>[^']+)'$")
# The Texture Set List's rows: a double click on a row's name (this far from the row's left
# edge, past the visibility icon) opens the name for editing (Painter 12.1.5, observed).
LIST_ROW_NAME_X = 40
LAYER_TARGET = re.compile(
    r"^Blending mode of layer '(?P<layer>[^']+)' in channel '(?P<channel>[^']+)'$"
)
# The Assets window (decision 300): the dock's title, the item types that can show a resource,
# and the label of the Export resource menu item (`&` mnemonics and a trailing ellipsis removed).
ASSETS_TITLE = "Assets"
ASSET_ITEM_TYPES = ("ListItem", "DataItem", "TreeItem")
EXPORT_RESOURCE_ITEM = re.compile(r"^export\b.*\bresources?$", re.IGNORECASE)
QT_FILE_DIALOG_CLASS = "QFileDialog"
TIME_UNITS = {"s": "Seconds", "min": "Minutes", "h": "Hours"}
VIEWPORT_TRANSFORM = "Viewport display transform"
TRANSFORM_OVERLAY = (320, 60)  # pixels at the viewport's top-right corner holding the selector


@dataclass(frozen=True)
class Control:
    """One settings widget: its dock, the end of its automation id and how it is operated."""

    dock: str
    path: str
    kind: str  # edit | spin | onoff | check | groupcheck | toggle_button | combo | colour
    unit_combo: str | None = None


def slider(dock: str, name: str) -> Control:
    return Control(dock, f".{name}{SLIDER_VALUE}", "edit")


R, D = "Renderer Settings", "Display Settings"
# Settings-sheet name -> widget (Painter 12.1.5 object names, read from the UI Automation tree).
CONTROLS: dict[str, Control] = {
    "Iray Settings/Min Sample": slider(R, "minSamples"),
    "Iray Settings/Max Sample": slider(R, "maxSamples"),
    "Iray Settings/Max Time": Control(R, f".maxTime{SLIDER_VALUE}", "edit", ".timeFormat"),
    "Iray Settings/Caustic Sampler": Control(R, ".causticSamplerEnabled.QToolButton", "onoff"),
    "Iray Settings/Firefly Filter": Control(R, ".fireflyFilterEnabled.QToolButton", "onoff"),
    "Iray Settings/Override viewport resolution": Control(
        R, ".overrideViewportRes", "toggle_button"
    ),
    "Iray Settings/Width": Control(R, ".resframe.width", "spin"),
    "Iray Settings/Height": Control(R, ".resframe.height", "spin"),
    "Display Settings/View mode": Control(D, ".viewmodebox", "combo"),
    "Display Settings/Override environment map color space": Control(
        D, ".override_envmap_colorspace", "groupcheck"
    ),
    "Display Settings/Environment map color space": Control(
        D, ".envmap_colorspace_combobox", "combo"
    ),
    "Display Settings/Environment Opacity": slider(D, "cubemapOpacity"),
    "Display Settings/Environment Exposure": slider(D, "pbrExposure"),
    "Display Settings/Environment Blur": slider(D, "envBlur"),
    "Display Settings/Environment Rotation": slider(D, "envRotation"),
    "Display Settings/Environment Alignment": Control(D, ".envSpace", "combo"),
    "Display Settings/Shadows": Control(D, ".parametersShadowBox.shadows", "check"),
    "Display Settings/Dome": Control(D, ".environment_mode", "combo"),
    "Display Settings/Clear color": Control(D, ".use_clear_color", "check"),
    "Display Settings/Clear color value": Control(D, ".clear_color.colorZone", "colour"),
    "Display Settings/Ground": Control(D, ".ground_group", "groupcheck"),
    "Display Settings/Activate Post Effects": Control(
        D, ".postFXParameters.QGroupBox", "groupcheck"
    ),
    "Display Settings/Activate Color Profile": Control(
        D, ".colorprofileparametersview.parameterBox", "groupcheck"
    ),
    "Display Settings/Activate Subsurface Scattering": Control(
        D, ".content.parametersBoxSSS", "groupcheck"
    ),
}
# The help page's panel name for the environment settings (07 §2.1) names the same widgets.
for _name in ("Environment Exposure", "Environment Rotation", "Dome"):
    CONTROLS[f"Viewer and MDL Settings/{_name}"] = CONTROLS[f"Display Settings/{_name}"]


def control_for(panel: str, setting: str) -> Control:
    name = f"{panel}/{setting}"
    if name not in CONTROLS:
        raise RecorderError(f"the UI operator has no widget for {name!r}")
    return CONTROLS[name]


@dataclass(frozen=True)
class IrayInfo:
    """Iray's information section as displayed (Renderer Settings > Iray Info)."""

    status: str
    iterations: int
    max_iterations: int
    seconds: int
    max_seconds: int
    resolution: str

    def as_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "iterations": self.iterations,
            "max_iterations": self.max_iterations,
            "rendering_time_s": self.seconds,
            "max_time_s": self.max_seconds,
            "resolution": self.resolution,
        }


def parse_fraction(text: str) -> tuple[int, int]:
    """`808/1000` -> (808, 1000)."""
    match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", text)
    if match is None:
        raise RecorderError(f"Iray iterations label {text!r} is not <n>/<max>")
    return int(match.group(1)), int(match.group(2))


def hms_seconds(text: str) -> int:
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})", text.strip())
    if match is None:
        raise RecorderError(f"Iray time {text!r} is not hh:mm:ss")
    hours, minutes, seconds = (int(g) for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def parse_times(text: str) -> tuple[int, int]:
    """`00:00:10/01:00:00` -> (10, 3600)."""
    parts = text.split("/")
    if len(parts) != 2:
        raise RecorderError(f"Iray rendering-time label {text!r} is not <time>/<max>")
    return hms_seconds(parts[0]), hms_seconds(parts[1])


def iray_info_from_labels(labels: dict[str, str]) -> IrayInfo:
    iterations, max_iterations = parse_fraction(labels["iterationsLabel"])
    seconds, max_seconds = parse_times(labels["timeLabel"])
    return IrayInfo(
        labels["statusLabel"].strip(),
        iterations,
        max_iterations,
        seconds,
        max_seconds,
        labels["resolutionLabel"].strip(),
    )


def number_text(value: float | int | str | bool) -> str:
    """How a sheet value is typed into a field: integers without a decimal point."""
    if isinstance(value, bool):
        raise RecorderError("a boolean is not typed into a field")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def on_off(value: float | int | str | bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "on", "yes", "1"):
        return True
    if text in ("false", "off", "no", "0"):
        return False
    raise RecorderError(f"{value!r} is not on or off")


def hex_colour(value: float | int | str | bool) -> str:
    text = str(value).strip().lstrip("#").upper()
    if not re.fullmatch(r"[0-9A-F]{6}", text):
        raise RecorderError(f"clear colour {value!r} is not RRGGBB")
    return text


class PainterUi:
    """Painter's main window and settings docks, through UI Automation (pywinauto)."""

    def __init__(
        self, settle_s: float = 0.4, timeout_s: float = 30.0, pid: int | None = None
    ) -> None:
        """`pid`: the process whose main window is operated (the Painter a recorder started);
        any other process's window, also one that already existed, is never bound."""
        from pywinauto import Desktop, mouse  # dev-only dependency (decision 029)
        from pywinauto.findwindows import ElementAmbiguousError, ElementNotFoundError

        self.desktop = Desktop(backend="uia")
        self.mouse = mouse
        self.settle_s = settle_s
        self.timeout_s = timeout_s
        criteria: dict[str, Any] = {"class_name": MAIN_WINDOW_CLASS}
        if pid is not None:
            criteria["process"] = pid
        spec = self.desktop.window(**criteria)
        self.button_spec = spec
        try:
            self.window = spec.wrapper_object()
        except (ElementNotFoundError, ElementAmbiguousError) as error:
            owner = f" of process {pid}" if pid is not None else ""
            raise RecorderError(f"no single main window of Painter{owner}: {error}") from error
        if pid is not None and self.window.process_id() != pid:
            raise RecorderError(
                f"the bound main window belongs to process {self.window.process_id()}, not {pid}"
            )
        self.window_surveyed = False

    def front(self) -> None:
        """Bring Painter to the foreground before a mouse or keyboard action, so the action
        lands on Painter and never on a window that covers it."""
        self.window.set_focus()
        time.sleep(0.2)

    # -- tree helpers -------------------------------------------------------------------------

    def children_windows(self) -> dict[str, Any]:
        return {
            c.element_info.automation_id: c
            for c in self.window.children()
            if c.element_info.control_type == "Window"
        }

    def dock(self, panel: str) -> Any:
        """The dock of a sheet panel, opened through its button in the Docks toolbar."""
        button_text, automation_id = DOCKS[PANEL_DOCKS.get(panel, panel)]
        for _ in range(4):
            docks = self.children_windows()
            if automation_id in docks:
                return docks[automation_id]
            button = self.button_spec.child_window(title=button_text, control_type="CheckBox")
            self.front()
            button.wrapper_object().click_input()
            time.sleep(1.0)
        raise RecorderError(f"Painter's {panel!r} panel did not open")

    @staticmethod
    def find(root: Any, suffix: str, control_type: str | None = None) -> Any:
        found = [
            e
            for e in root.descendants()
            if e.element_info.automation_id.endswith(suffix)
            and (control_type is None or e.element_info.control_type == control_type)
        ]
        if len(found) != 1:
            raise RecorderError(f"widget *{suffix}: expected one, found {len(found)}")
        return found[0]

    def visible(self, dock: Any, suffix: str, control_type: str | None = None) -> Any:
        """The widget, scrolled into the visible part of its dock with the mouse wheel."""
        for _ in range(80):
            element = self.find(dock, suffix, control_type)
            box = element.rectangle()
            area = dock.rectangle()
            if ".scrollArea." in element.element_info.automation_id:
                viewports = [
                    e
                    for e in dock.descendants()
                    if e.element_info.automation_id.endswith("scrollArea.qt_scrollarea_viewport")
                ]
                if viewports:
                    area = viewports[0].rectangle()
            if box.top >= area.top and box.bottom <= area.bottom:
                return element
            centre = ((area.left + area.right) // 2, (area.top + area.bottom) // 2)
            self.mouse.scroll(coords=centre, wheel_dist=-2 if box.bottom > area.bottom else 2)
            time.sleep(0.15)
        raise RecorderError(f"widget *{suffix} cannot be scrolled into view")

    # -- tabbed docks of texture goldens -------------------------------------------------------

    def on_screen(self, element: Any) -> bool:
        box, frame = element.rectangle(), self.window.rectangle()
        return bool(
            frame.left <= box.left < box.right <= frame.right
            and frame.top <= box.top < box.bottom <= frame.bottom
        )

    def tab_dock(self, panel: str) -> Any:
        """A main-window dock, its tab brought forward when another tab hides it (UI Automation
        tab selection: navigation only, it changes no setting)."""
        title, automation_id = TAB_DOCKS[panel]
        for _ in range(3):
            docks = [
                c for c in self.window.children() if c.element_info.automation_id == automation_id
            ]
            if len(docks) != 1:
                raise RecorderError(f"Painter's {panel!r} dock was not found")
            if self.on_screen(docks[0]):
                return docks[0]
            tabs = [
                tab
                for bar in self.window.children()
                if bar.element_info.class_name == "QMainWindowTabBar"
                for tab in bar.children()
                if str(tab.window_text()).strip() == title
            ]
            if len(tabs) != 1:
                raise RecorderError(f"Painter's {panel!r} dock is hidden and has no single tab")
            tabs[0].iface_selection_item.Select()
            time.sleep(1.0)
        raise RecorderError(f"Painter's {panel!r} dock could not be shown")

    def click(self, element: Any, owner: int | None = None) -> None:
        """A real click at the element's centre, after checking that the point belongs to
        Painter's window (or to `owner`, a menu Painter opened)."""
        import win32gui

        box = element.rectangle()
        point = ((box.left + box.right) // 2, (box.top + box.bottom) // 2)
        root = win32gui.GetAncestor(win32gui.WindowFromPoint(point), 2)  # GA_ROOT
        if root != (owner or self.window.handle):
            raise RecorderError(
                f"the point {point} of a Painter widget is covered by another window; "
                "nothing was clicked"
            )
        element.click_input()

    def choose(self, combo: Any, text: str) -> None:
        """Pick a combo box item by its text with real clicks."""
        if str(combo.iface_value.CurrentValue) == text:
            return
        self.front()
        self.click(combo)
        time.sleep(0.5)
        items = [
            i
            for i in combo.descendants()
            if i.element_info.control_type == "ListItem" and i.window_text() == text
        ]
        if len(items) != 1:
            combo.collapse()
            raise RecorderError(f"combo box offers no single item {text!r}")
        items[0].click_input()
        time.sleep(self.settle_s)

    def texture_set_dock(self, texture_set: str) -> Any:
        """Texture Set Settings, checked to show `texture_set` (the recorder made it active)."""
        dock = self.tab_dock("Texture Set Settings")
        shown = str(self.find(dock, TEXTURE_SET_NAME).window_text())
        if shown != texture_set:
            raise RecorderError(f"Texture Set Settings shows {shown!r}, not {texture_set!r}")
        return dock

    def texture_set_value(self, setting: str, texture_set: str, value: str | None) -> str:
        if setting not in TEXTURE_SET_COMBOS:
            raise RecorderError(f"the UI operator has no Texture Set Settings widget {setting!r}")
        combo = TEXTURE_SET_COMBOS[setting]
        dock = self.texture_set_dock(texture_set)
        if value is not None:
            self.choose(self.visible(dock, combo, "ComboBox"), value)
            dock = self.texture_set_dock(texture_set)
        return str(self.find(dock, combo, "ComboBox").iface_value.CurrentValue)

    def layer_blending(self, layer: str, channel: str, value: str | None) -> str:
        """A layer row's blending mode in one channel (the panel's channel selector), set through
        the row's menu when `value` is given; returns the menu label the row shows."""
        dock = self.tab_dock("Layers")
        self.choose(self.find(dock, CHANNEL_SELECTOR, "ComboBox"), channel)
        shown_channel = str(self.find(dock, CHANNEL_SELECTOR, "ComboBox").iface_value.CurrentValue)
        if shown_channel != channel:
            raise RecorderError(f"the Layers channel selector shows {shown_channel!r}")
        button = self.layer_button(dock, layer)
        if value is not None and BLENDING_SHOWN.get(str(button.window_text())) != value:
            self.front()
            self.click(button)
            menu = self.menu()
            items = [
                i for i in menu.descendants(control_type="MenuItem") if i.window_text() == value
            ]
            if len(items) != 1:
                menu.type_keys("{ESC}")
                raise RecorderError(f"the blending-mode menu offers no single item {value!r}")
            self.click(items[0], owner=menu.handle)
            time.sleep(self.settle_s)
            button = self.layer_button(self.tab_dock("Layers"), layer)
        shown = str(button.window_text())
        return BLENDING_SHOWN.get(shown, shown)

    def layer_button(self, dock: Any, layer: str) -> Any:
        """The blending-mode button of the one row of the Layers panel named `layer`."""
        labels = [
            e
            for e in dock.descendants()
            if e.element_info.automation_id.endswith(LAYER_NAME) and e.window_text() == layer
        ]
        if len(labels) != 1:
            raise RecorderError(f"the Layers panel lists {len(labels)} layers named {layer!r}")
        if not self.on_screen(labels[0]):
            raise RecorderError(f"layer {layer!r} is not in the visible part of the Layers panel")
        row = labels[0].parent().parent().parent()
        buttons = [
            c for c in row.children() if c.element_info.automation_id.endswith(LAYER_BLENDING)
        ]
        if len(buttons) != 1:
            raise RecorderError(f"layer {layer!r}: no single blending-mode button")
        return buttons[0]

    def menu(self) -> Any:
        deadline = time.monotonic() + self.timeout_s
        while True:
            menus = [
                w
                for w in self.desktop.windows(process=self.window.process_id())
                if w.element_info.class_name == MENU_CLASS
            ]
            if len(menus) == 1:
                return menus[0]
            if time.monotonic() > deadline:
                raise RecorderError("the blending-mode menu did not open")
            time.sleep(0.2)

    def list_rows(self) -> list[Any]:
        """The Texture Set List's rows (one per texture set, in the list's order)."""
        dock = self.tab_dock("Texture Set List")
        return [e for e in dock.descendants() if e.element_info.control_type == "TreeItem"]

    def texture_set_name(self, listed: str, value: str | None) -> str:
        """The name of the Texture Set List row showing `listed`, renamed to `value` when given
        (a guarded double click on the row's name, the new name typed and committed with
        Enter); returns the name the row then shows."""
        rows = self.list_rows()
        names = [str(r.window_text()) for r in rows]
        if names.count(listed) != 1:
            raise RecorderError(f"the Texture Set List shows {names.count(listed)} rows {listed!r}")
        index = names.index(listed)
        if value is None or value == listed:
            return listed
        import win32gui
        from pywinauto.keyboard import send_keys

        box = rows[index].rectangle()
        point = (box.left + LIST_ROW_NAME_X, (box.top + box.bottom) // 2)
        self.front()
        if win32gui.GetAncestor(win32gui.WindowFromPoint(point), 2) != self.window.handle:
            raise RecorderError(
                f"the point {point} of the Texture Set List is covered by another window; "
                "nothing was clicked"
            )
        self.mouse.double_click(coords=point)
        time.sleep(self.settle_s)
        send_keys("^a" + value + "{ENTER}")
        time.sleep(self.settle_s)
        return str(self.list_rows()[index].window_text())

    def target_value(self, panel: str, setting: str, value: str | None) -> str | None:
        """Read (`value` None) or set a targeted texture-golden setting; None when `setting`
        names no target."""
        if panel == "Texture Set List" and (match := LIST_TARGET.match(setting)):
            return self.texture_set_name(match["texture_set"], value)
        if panel == "Texture Set Settings" and (match := TEXTURE_SET_TARGET.match(setting)):
            return self.texture_set_value(match["setting"], match["texture_set"], value)
        if panel == "Layers" and (match := LAYER_TARGET.match(setting)):
            return self.layer_blending(match["layer"], match["channel"], value)
        return None

    # -- values -------------------------------------------------------------------------------

    def read(self, panel: str, setting: str) -> str:
        """What the widget shows now, as text."""
        targeted = self.target_value(panel, setting, None)
        if targeted is not None:
            return targeted
        control = control_for(panel, setting)
        dock = self.dock(panel)
        if control.kind == "colour":
            return self.read_colour(dock, control)
        element = self.find(dock, control.path)
        shown = self.shown(element, control)
        if control.unit_combo is not None:
            unit = self.find(dock, control.unit_combo, "ComboBox").iface_value.CurrentValue
            shown = f"{shown} {unit}"
        return shown

    @staticmethod
    def shown(element: Any, control: Control) -> str:
        if control.kind in ("edit", "spin", "combo"):
            return str(element.iface_value.CurrentValue)
        if control.kind == "onoff":
            return str(element.window_text())
        return "on" if element.iface_toggle.CurrentToggleState == 1 else "off"

    def apply(
        self, panel: str, setting: str, value: float | int | str | bool, unit: str | None
    ) -> str:
        """Set one widget to `value`, commit it, and return what the widget shows afterwards."""
        targeted = self.target_value(panel, setting, str(value))
        if targeted is not None:
            return targeted
        control = control_for(panel, setting)
        dock = self.dock(panel)
        self.front()
        if control.unit_combo is not None:
            if unit not in TIME_UNITS:
                raise RecorderError(f"{panel}/{setting}: unit {unit!r} not in {sorted(TIME_UNITS)}")
            self.select(dock, control.unit_combo, TIME_UNITS[unit])
            shown_unit = self.find(dock, control.unit_combo, "ComboBox").iface_value.CurrentValue
            if shown_unit != TIME_UNITS[unit]:
                raise RecorderError(f"{panel}/{setting}: unit shows {shown_unit!r}")
        if control.kind == "colour":
            return self.apply_colour(dock, control, hex_colour(value))
        element = self.visible(dock, control.path)
        if not element.is_enabled():
            shown = self.shown(element, control)
            if same_value(shown, value):
                return shown  # Painter disables it in this mode and it already shows the value
            raise RecorderError(
                f"{panel}/{setting} is disabled in Painter's current mode (shows {shown!r})"
            )
        if control.kind in ("edit", "spin"):
            type_into(element, number_text(value))
        elif control.kind == "combo":
            self.select(dock, control.path, str(value))
        elif control.kind == "onoff":
            if (element.window_text().strip().lower() == "on") != on_off(value):
                element.click_input()
        elif control.kind in ("check", "toggle_button"):
            if (element.iface_toggle.CurrentToggleState == 1) != on_off(value):
                element.click_input()
        elif control.kind == "groupcheck":
            if (element.iface_toggle.CurrentToggleState == 1) != on_off(value):
                box = element.rectangle()
                self.mouse.click(coords=(box.left + 8, box.top + 9))
        else:
            raise RecorderError(f"unknown control kind {control.kind!r}")
        time.sleep(self.settle_s)
        return self.shown(self.find(self.dock(panel), control.path), control)

    def select(self, dock: Any, suffix: str, text: str) -> None:
        combo = self.visible(dock, suffix, "ComboBox")
        if str(combo.iface_value.CurrentValue).casefold() == text.casefold():
            return
        combo.click_input()
        time.sleep(0.5)
        items = [
            i
            for i in combo.descendants()
            if i.element_info.control_type == "ListItem"
            and i.window_text().casefold() == text.casefold()
        ]
        if len(items) != 1:
            combo.collapse()
            raise RecorderError(f"combo box *{suffix} offers no single item {text!r}")
        items[0].click_input()
        time.sleep(0.5)

    def colour_widget(self) -> Any:
        widgets = [
            w
            for w in self.desktop.windows(process=self.window.process_id())
            if w.element_info.class_name == COLOR_WIDGET_CLASS
        ]
        return widgets[0] if widgets else None

    def open_colour(self, dock: Any, control: Control) -> Any:
        self.front()
        self.visible(dock, control.path).click_input()
        deadline = time.monotonic() + self.timeout_s
        while (widget := self.colour_widget()) is None:
            if time.monotonic() > deadline:
                raise RecorderError("the colour picker did not open")
            time.sleep(0.2)
        return widget

    def read_colour(self, dock: Any, control: Control) -> str:
        widget = self.open_colour(dock, control)
        try:
            return str(self.find(widget, ".colorHexa", "Edit").iface_value.CurrentValue).upper()
        finally:
            widget.type_keys("{ESC}")
            time.sleep(self.settle_s)

    def apply_colour(self, dock: Any, control: Control, value: str) -> str:
        widget = self.open_colour(dock, control)
        try:
            type_into(self.find(widget, ".colorHexa", "Edit"), value)
            time.sleep(self.settle_s)
            return str(self.find(widget, ".colorHexa", "Edit").iface_value.CurrentValue).upper()
        finally:
            widget.type_keys("{ESC}")
            time.sleep(self.settle_s)

    # -- Iray ---------------------------------------------------------------------------------

    def iray_info(self) -> IrayInfo:
        dock = self.dock("Renderer Settings")
        labels = {
            name: str(self.find(dock, f".{name}").window_text())
            for name in ("statusLabel", "iterationsLabel", "timeLabel", "resolutionLabel")
        }
        return iray_info_from_labels(labels)

    def wait_done(self, timeout_s: float, quiet_s: float = 3.0, poll_s: float = 0.5) -> IrayInfo:
        """Wait until Iray reads Done with every iteration run, on two reads `quiet_s` apart
        (a settings change restarts Iray a moment after it is made)."""
        time.sleep(quiet_s)
        deadline = time.monotonic() + timeout_s
        while True:
            first = self.iray_info()
            if first.status == "Done" and first.iterations == first.max_iterations:
                time.sleep(quiet_s)
                second = self.iray_info()
                if second == first:
                    return second
            if time.monotonic() > deadline:
                raise RecorderError(f"Iray did not finish within {timeout_s:.0f} s: {first}")
            time.sleep(poll_s)

    # -- images -------------------------------------------------------------------------------

    @staticmethod
    def print_window(handle: int) -> tuple[Any, tuple[int, int]]:
        """The window's pixels through `PrintWindow(PW_RENDERFULLCONTENT)` (no focus change)."""
        import ctypes

        import win32gui
        import win32ui
        from PIL import Image

        left, top, right, bottom = win32gui.GetWindowRect(handle)
        width, height = right - left, bottom - top
        window_dc = win32gui.GetWindowDC(handle)
        source = win32ui.CreateDCFromHandle(window_dc)
        memory = source.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(source, width, height)
        memory.SelectObject(bitmap)
        try:
            if not ctypes.windll.user32.PrintWindow(handle, memory.GetSafeHdc(), 2):
                raise RecorderError("PrintWindow failed")
            info = bitmap.GetInfo()
            image = Image.frombuffer(
                "RGB",
                (info["bmWidth"], info["bmHeight"]),
                bitmap.GetBitmapBits(True),
                "raw",
                "BGRX",
                0,
                1,
            )
        finally:
            win32gui.DeleteObject(bitmap.GetHandle())
            memory.DeleteDC()
            source.DeleteDC()
            win32gui.ReleaseDC(handle, window_dc)
        return image.copy(), (left, top)

    def panel_image(self, panel: str, path: Path) -> Path:
        if panel == VIEWPORT_TRANSFORM:
            return self.display_transform_image(path)
        if panel in TAB_DOCKS or panel == ASSETS_TITLE:
            image, (left, top) = self.print_window(self.window.handle)
            dock = self.assets_dock() if panel == ASSETS_TITLE else self.tab_dock(panel)
            box = dock.rectangle()
            crop = image.crop((box.left - left, box.top - top, box.right - left, box.bottom - top))
            path.parent.mkdir(parents=True, exist_ok=True)
            crop.save(path)
            return path
        dock = self.dock(panel)
        image, _ = self.print_window(dock.handle)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        return path

    def viewer_rectangle(self) -> Any:
        def walk(element: Any) -> Any:
            for child in element.children():
                if child.element_info.automation_id.endswith(".Viewer3D"):
                    return child
                found = walk(child)
                if found is not None:
                    return found
            return None

        viewer = walk(self.window)
        if viewer is None:
            raise RecorderError("Painter's 3D viewport was not found")
        return viewer.rectangle()

    def display_transform_image(self, path: Path) -> Path:
        """The viewport's display-transform selector (top right of the 3D viewport). It is drawn
        over the viewport and is not in the UI Automation tree, so its image is the evidence."""
        image, (left, top) = self.print_window(self.window.handle)
        box = self.viewer_rectangle()
        width, height = TRANSFORM_OVERLAY
        crop = image.crop(
            (box.right - left - width, box.top - top, box.right - left, box.top - top + height)
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        crop.save(path)
        return path

    def viewport_image(self, path: Path) -> tuple[int, int]:
        """The displayed 3D viewport (live view), cropped from the main window's pixels."""
        image, (left, top) = self.print_window(self.window.handle)
        box = self.viewer_rectangle()
        crop = image.crop((box.left - left, box.top - top, box.right - left, box.bottom - top))
        path.parent.mkdir(parents=True, exist_ok=True)
        crop.save(path)
        return crop.width, crop.height

    # -- Save Render --------------------------------------------------------------------------

    def save_dialog(self) -> Any:
        deadline = time.monotonic() + self.timeout_s
        while True:
            dialogs = [
                c for c in self.window.children() if c.element_info.class_name == DIALOG_CLASS
            ]
            if dialogs:
                return dialogs[0]
            if time.monotonic() > deadline:
                raise RecorderError("the Save Render dialog did not open")
            time.sleep(0.25)

    def open_save_dialog(self) -> Any:
        dock = self.dock("Renderer Settings")
        self.find(dock, ".saveRender", "Button").invoke()
        return self.save_dialog()

    @staticmethod
    def dialog_elements(dialog: Any) -> list[Any]:
        found: list[Any] = []

        def walk(element: Any) -> None:
            for child in element.children():
                found.append(child)
                walk(child)

        walk(dialog)
        return found

    def file_types(self, dialog: Any) -> list[str]:
        combo = next(
            e
            for e in self.dialog_elements(dialog)
            if e.element_info.automation_id == "FileTypeControlHost"
        )
        combo.expand()
        time.sleep(0.3)
        items = [
            str(i.window_text())
            for i in self.dialog_elements(combo)
            if i.element_info.control_type == "ListItem"
        ]
        combo.collapse()
        return items

    def extra_options(self, dialog: Any) -> list[str]:
        """Dialog controls beyond the standard file name and type (e.g. bit depth)."""
        standard = {"FileNameControlHost", "FileTypeControlHost"}
        return sorted(
            f"{e.element_info.control_type}:{e.window_text()}"
            for e in self.dialog_elements(dialog)
            if (
                e.element_info.control_type == "ComboBox"
                and e.element_info.automation_id not in standard
            )
            or e.element_info.control_type == "CheckBox"
        )

    def cancel(self, dialog: Any) -> None:
        self.dialog_button(dialog, "2").invoke()
        self.wait_dialog_closed()

    def dialog_button(self, dialog: Any, automation_id: str) -> Any:
        return next(
            e
            for e in self.dialog_elements(dialog)
            if e.element_info.control_type == "Button"
            and e.element_info.automation_id == automation_id
        )

    def wait_dialog_closed(self) -> None:
        deadline = time.monotonic() + self.timeout_s
        while any(c.element_info.class_name == DIALOG_CLASS for c in self.window.children()):
            if time.monotonic() > deadline:
                raise RecorderError("the Save Render dialog did not close")
            time.sleep(0.25)

    def save_render(self, target: Path) -> IrayInfo:
        """Save Render to `target` (type chosen by its extension); returns the Iray state read
        right before the button was pressed."""
        before = self.iray_info()
        dialog = self.open_save_dialog()
        prefix = {".png": "PNG", ".exr": "EXR"}.get(target.suffix.lower())
        if prefix is None:
            self.cancel(dialog)
            raise RecorderError(f"Save Render target {target} is neither .png nor .exr")
        elements = self.dialog_elements(dialog)
        combo = next(e for e in elements if e.element_info.automation_id == "FileTypeControlHost")
        combo.expand()
        time.sleep(0.3)
        items = [
            i
            for i in self.dialog_elements(combo)
            if i.element_info.control_type == "ListItem"
            and str(i.window_text()).startswith(prefix + " ")
        ]
        if len(items) != 1:
            combo.collapse()
            self.cancel(dialog)
            raise RecorderError(f"Save Render offers no single {prefix} file type")
        items[0].select()
        time.sleep(0.3)
        name = next(
            e
            for e in elements
            if e.element_info.control_type == "Edit" and e.element_info.automation_id == "1001"
        )
        name.iface_value.SetValue(str(target))
        self.dialog_button(dialog, "1").invoke()
        self.wait_dialog_closed()
        wait_file(target, self.timeout_s)
        return before

    # -- Assets window: Export resource (decision 300) ------------------------------------------

    @staticmethod
    def survey(root: Any) -> list[dict[str, Any]]:
        """Every element under `root` as UI Automation shows it (private evidence, read only):
        the record a re-run's locators are fixed from when a step cannot be completed."""
        rows = []
        for element in [root, *root.descendants()]:
            info = element.element_info
            box = element.rectangle()
            rows.append(
                {
                    "control_type": info.control_type,
                    "automation_id": info.automation_id,
                    "class_name": info.class_name,
                    "text": str(element.window_text())[:120],
                    "enabled": bool(element.is_enabled()),
                    "box": [box.left, box.top, box.right, box.bottom],
                }
            )
        return rows

    def assets_dock(self) -> Any:
        """The Assets window docked in the main window, its tab brought forward when another tab
        hides it (UI Automation tab selection: navigation only)."""
        for _ in range(3):
            docks = [
                c for c in self.window.children() if str(c.window_text()).strip() == ASSETS_TITLE
            ]
            if len(docks) == 1 and self.on_screen(docks[0]):
                return docks[0]
            tabs = [
                tab
                for bar in self.window.children()
                if bar.element_info.class_name == "QMainWindowTabBar"
                for tab in bar.children()
                if str(tab.window_text()).strip() == ASSETS_TITLE
            ]
            if len(tabs) != 1:
                raise RecorderError(
                    f"Painter's Assets window: {len(docks)} docks and {len(tabs)} tabs found"
                )
            tabs[0].iface_selection_item.Select()
            time.sleep(1.0)
        raise RecorderError("Painter's Assets window could not be shown")

    def asset_items(self, dock: Any, gui_name: str) -> list[Any]:
        return [
            e
            for e in dock.descendants()
            if e.element_info.control_type in ASSET_ITEM_TYPES
            and str(e.window_text()).strip() == gui_name
            and self.on_screen(e)
        ]

    def asset_item(self, gui_name: str, evidence: dict[str, Any]) -> Any:
        """The one visible item showing `gui_name` (the recorder highlighted it through the
        documented `Resource.show_in_ui`); when none is visible, the name is typed into the
        window's one search field (a filter of the view, no setting) and the items read again."""
        dock = self.assets_dock()
        items = self.asset_items(dock, gui_name)
        if not items:
            fields = [
                e
                for e in dock.descendants()
                if e.element_info.control_type == "Edit" and self.on_screen(e)
            ]
            evidence["search_fields"] = len(fields)
            if len(fields) == 1:
                self.front()
                type_into(fields[0], gui_name)
                time.sleep(1.0)
                evidence["searched"] = gui_name
                items = self.asset_items(self.assets_dock(), gui_name)
        if len(items) != 1:
            evidence["assets_survey"] = self.survey(self.assets_dock())
            raise RecorderError(
                f"the Assets window shows {len(items)} visible items named {gui_name!r}"
            )
        return items[0]

    def context_menu(self, element: Any) -> Any:
        """A real right click at the element's centre (the point checked to belong to Painter's
        window, as for every click), and the menu it opened."""
        import win32gui

        box = element.rectangle()
        point = ((box.left + box.right) // 2, (box.top + box.bottom) // 2)
        self.front()
        if win32gui.GetAncestor(win32gui.WindowFromPoint(point), 2) != self.window.handle:
            raise RecorderError(
                f"the point {point} of the Assets window is covered by another window; "
                "nothing was clicked"
            )
        element.click_input(button="right")
        return self.menu()

    def file_dialog(self) -> Any | None:
        """The dialog the menu item opened, or None when none opened within the timeout."""
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            dialogs = [
                c
                for c in self.window.children()
                if c.element_info.class_name in (DIALOG_CLASS, QT_FILE_DIALOG_CLASS)
            ]
            if dialogs:
                return dialogs[0]
            time.sleep(0.25)
        return None

    def export_resource(self, gui_name: str, target: Path, evidence: dict[str, Any]) -> str:
        """Export resource on the highlighted project resource into the folder `target`; returns
        the label of the menu item used, or `absent` or `disabled` when no enabled Export
        resource item is offered (an observation: nothing else is clicked).

        `evidence` receives what happened, also when the step is refused: the menu's items, the
        dialog's kind and title and survey, the file name it proposed and its file types, and
        the text of any message box after it. A native folder picker is given `target`; a
        native save dialog is given `target` joined with the name it proposed, only when that
        name is a simple file name that stays inside `target` (`contained_file`; any other
        proposal cancels the dialog and refuses the step). A Qt
        (non-native) dialog is cancelled and the step refused, with the dialog's survey kept."""
        evidence.update(resource=gui_name, target=str(target))
        try:
            item = self.asset_item(gui_name, evidence)
        except RecorderError:
            if "assets_survey" not in evidence and not self.window_surveyed:
                self.window_surveyed = True  # once per process: the whole window is large
                evidence["window_survey"] = self.survey(self.window)
            raise
        menu = self.context_menu(item)
        entries = menu.descendants(control_type="MenuItem")
        evidence["menu"] = [
            {"text": str(e.window_text()), "enabled": bool(e.is_enabled())} for e in entries
        ]
        matches = [e for e in entries if EXPORT_RESOURCE_ITEM.match(menu_label(e.window_text()))]
        if len(matches) > 1:
            menu.type_keys("{ESC}")
            raise RecorderError(f"the menu offers {len(matches)} Export resource items")
        if not matches or not matches[0].is_enabled():
            menu.type_keys("{ESC}")
            evidence["label"] = "absent" if not matches else "disabled"
            return str(evidence["label"])
        evidence["label"] = str(matches[0].window_text())
        self.click(matches[0], owner=menu.handle)
        dialog = self.file_dialog()
        if dialog is None:
            evidence["dialog"] = None
            return str(evidence["label"])
        evidence["dialog"] = {
            "class": dialog.element_info.class_name,
            "title": str(dialog.window_text()),
            "survey": self.survey(dialog),
        }
        if dialog.element_info.class_name != DIALOG_CLASS:
            dialog.type_keys("{ESC}")
            raise RecorderError("Export resource opened a non-native dialog; it was cancelled")
        elements = self.dialog_elements(dialog)
        saving = any(e.element_info.automation_id == "FileTypeControlHost" for e in elements)
        evidence["dialog"]["kind"] = "save" if saving else "folder"
        edits = [e for e in elements if e.element_info.control_type == "Edit"]
        named = [e for e in edits if e.element_info.automation_id in ("1001", "1152")]
        field = named[0] if named else edits[0] if len(edits) == 1 else None
        if field is None:
            self.cancel(dialog)
            raise RecorderError(f"the {evidence['dialog']['kind']} dialog has no single name field")
        if saving:
            evidence["dialog"]["file_types"] = self.file_types(dialog)
            proposed = str(field.iface_value.CurrentValue)
            evidence["dialog"]["proposed"] = proposed
            try:
                destination = contained_file(target, proposed)
            except RecorderError:
                self.cancel(dialog)
                raise
            field.iface_value.SetValue(str(destination))
        else:
            field.iface_value.SetValue(str(target))
        self.dialog_button(dialog, "1").invoke()
        time.sleep(1.0)
        messages = [c for c in self.window.children() if c.element_info.class_name == DIALOG_CLASS]
        if messages:
            evidence["message"] = [
                str(e.window_text())
                for e in self.dialog_elements(messages[0])
                if e.element_info.control_type == "Text"
            ]
            messages[0].type_keys("{ESC}")
        self.wait_dialog_closed()
        return str(evidence["label"])


WINDOWS_DEVICE = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE)
UNSAFE_NAME = re.compile(r'[\x00-\x1f<>:"/\\|?*]')


def contained_file(target: Path, proposed: str) -> Path:
    """`target / proposed`, when `proposed` is a simple file name and the destination resolves
    to a new file directly inside `target`; anything else (empty, `.` or `..`, absolute, rooted,
    drive-relative, a separator, a wildcard or stream colon, a device name, a trailing dot or
    space) is refused, so a dialog's suggestion can never write outside the private folder."""
    from pathlib import PurePosixPath, PureWindowsPath

    windows = PureWindowsPath(proposed)
    if (
        not proposed
        or proposed in (".", "..")
        or UNSAFE_NAME.search(proposed)
        or windows.drive
        or windows.root
        or windows.name != proposed
        or PurePosixPath(proposed).name != proposed
        or proposed[-1] in ". "
        or WINDOWS_DEVICE.match(proposed.split(".", 1)[0].rstrip(" "))
    ):
        raise RecorderError(f"the dialog proposed {proposed!r}, not a simple file name")
    folder = target.resolve(strict=True)
    destination = (folder / proposed).resolve()
    if destination.parent != folder or destination.name != proposed or destination.exists():
        raise RecorderError(
            f"the dialog's name {proposed!r} does not give a new file inside {target}"
        )
    return folder / proposed


def menu_label(text: str) -> str:
    """A menu item's label without its `&` mnemonics and trailing ellipsis."""
    return str(text).replace("&", "").rstrip(".… ").strip()


def type_into(element: Any, text: str) -> None:
    """Replace a field's text and commit it with Enter. A double click gives the field the
    keyboard focus (UI Automation's SetFocus does not reliably reach Painter's fields)."""
    element.click_input(double=True)
    time.sleep(0.2)
    element.type_keys("^a" + text + "{ENTER}", set_foreground=False)


def wait_file(path: Path, timeout_s: float, stable_s: float = 0.5) -> None:
    """Wait until `path` exists and its size has stopped changing."""
    deadline = time.monotonic() + timeout_s
    size = -1
    while True:
        if path.is_file():
            current = path.stat().st_size
            if current == size and current > 0:
                return
            size = current
        if time.monotonic() > deadline:
            raise RecorderError(f"Save Render wrote no complete file at {path}")
        time.sleep(stable_s)


# Prompts of iray.py and iray_probe.py the automated operator answers.
SET_PROMPT = re.compile(r"^\[(?P<panel>[^\]]+)\] (?P<setting>.+) \(sheet: (?P<value>.*)\):$")
READ_PROMPT = re.compile(r"^\[(?P<panel>[^\]]+)\] (?P<setting>.+): value shown now:$")
IMAGE_PROMPT = re.compile(r"^Path of an image of the '(?P<panel>[^']+)' panel")
VIEWPORT_PROMPT = re.compile(r"^Path of an image of the 3D viewport")
SAVE_TELL = re.compile(r"Use Save Render now and save the image as: (?P<path>.+)$")
CHANGE_PROMPT = re.compile(
    r"^Set (?P<panel>[^/]+) / (?P<setting>.+?) to (?P<value>.+?)"
    r"(?: (?P<unit>s|min|h|px))?, then press Enter\.$"
)
WAIT_TELL = re.compile(r"(Wait until Status reads Done\.|^Let Iray converge)")
# The Export resource prompt of `resource_qualification.py` (decision 300).
RESOURCE_EXPORT_PROMPT = re.compile(
    r"^Export resource: in the Assets window, export the highlighted project resource "
    r"'(?P<gui_name>[^']+)' with its Export resource menu item into the folder (?P<target>.+)\. "
    r"Enter the menu item's label as shown, or 'absent' or 'disabled':$"
)


@dataclass
class UiOperator:
    """The Operator of `iray.py` (tell/ask) answered by UI automation of Painter's panels."""

    ui: PainterUi
    images: Path
    render_timeout_s: float = 3600.0
    log: list[dict[str, Any]] = field(default_factory=list)
    target: Path | None = None
    last_save: IrayInfo | None = None
    converged: IrayInfo | None = None
    extras: list[str] = field(default_factory=list)
    clock: Callable[[], float] = time.time

    def note(self, action: str, **details: Any) -> None:
        self.log.append({"at": self.clock(), "action": action, **details})

    def tell(self, message: str) -> None:
        saved = SAVE_TELL.search(message)
        if saved:
            self.target = Path(saved.group("path").strip())
            return
        if WAIT_TELL.search(message):
            self.converged = self.ui.wait_done(self.render_timeout_s)
            self.note("wait_done", iray=self.converged.as_json())
            return
        self.note("tell", message=message)

    def ask(self, question: str) -> str:
        match = SET_PROMPT.match(question)
        if match:
            return self.set_from_sheet(match.group("panel"), match.group("setting"), match["value"])
        match = CHANGE_PROMPT.match(question)
        if match:
            shown = self.ui.apply(
                match["panel"], match["setting"], parse_value(match["value"]), match["unit"]
            )
            self.note("set", panel=match["panel"], setting=match["setting"], shown=shown)
            return ""
        match = READ_PROMPT.match(question)
        if match:
            shown = self.ui.read(match["panel"], match["setting"])
            self.note("read", panel=match["panel"], setting=match["setting"], shown=shown)
            return shown
        match = IMAGE_PROMPT.match(question)
        if match:
            return str(self.panel_image(match["panel"]))
        match = RESOURCE_EXPORT_PROMPT.match(question)
        if match:
            return self.export_resource(match["gui_name"], Path(match["target"]))
        if VIEWPORT_PROMPT.match(question):
            path = self.images / f"viewport-{len(self.log):03d}.png"
            size = self.ui.viewport_image(path)
            self.note("viewport_image", file=path.name, size=list(size))
            return str(path)
        return self.answer(question)

    def set_from_sheet(self, panel: str, setting: str, sheet: str) -> str:
        value, _, unit = sheet.rpartition(" ")
        if unit not in (*TIME_UNITS, "px"):
            value, unit = sheet, ""
        shown = self.ui.apply(panel, setting, parse_value(value), unit or None)
        self.note("set", panel=panel, setting=setting, sheet=sheet, shown=shown)
        if unit and shown.endswith(" " + TIME_UNITS.get(unit, unit)):
            shown = shown.rsplit(" ", 1)[0]
        return shown

    def export_resource(self, gui_name: str, target: Path) -> str:
        """Export resource through the Assets window; the step's evidence (menu, dialog and
        surveys) is written next to the panel images, also when the step is refused."""
        evidence: dict[str, Any] = {}
        path = self.images / f"export-{len(self.log):03d}.json"
        try:
            label = self.ui.export_resource(gui_name, target, evidence)
        except RecorderError as error:
            evidence["refused"] = str(error)
            raise
        finally:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(evidence, indent=1), encoding="utf-8")
            self.note("export_resource", resource=gui_name, file=path.name)
        return label

    def panel_image(self, panel: str) -> Path:
        name = re.sub(r"[^a-z0-9]+", "-", panel.lower())
        path = self.images / f"panel-{len(self.log):03d}-{name}.png"
        self.ui.panel_image(panel, path)
        self.note("panel_image", panel=panel, file=path.name)
        return path

    def answer(self, question: str) -> str:
        if question.startswith("Status shown"):
            info = self.converged or self.ui.iray_info()
            return info.status
        if question.startswith("Iterations shown"):
            info = self.converged or self.ui.iray_info()
            return str(info.iterations)
        if question.startswith("Rendering time shown"):
            info = self.converged or self.ui.iray_info()
            return str(info.seconds)
        if question.startswith("Does Status in the Iray information section read Done"):
            info = self.ui.iray_info()
            self.note("status", iray=info.as_json())
            done = info.status == "Done" and info.iterations == info.max_iterations
            return "yes" if done else "no"
        if question.startswith("Press Enter once the file is saved"):
            if self.target is None:
                raise RecorderError("no Save Render target was named")
            self.last_save = self.ui.save_render(self.target)
            self.note("save_render", file=str(self.target), iray=self.last_save.as_json())
            self.target = None
            return ""
        if question.startswith("What did Status read when you saved"):
            if self.last_save is None:
                raise RecorderError("no Save Render was made")
            return self.last_save.status
        if question.startswith("Open Save Render: which file types"):
            dialog = self.ui.open_save_dialog()
            try:
                types = self.ui.file_types(dialog)
                self.extras = self.ui.extra_options(dialog)
            finally:
                self.ui.cancel(dialog)
            self.note("save_render_types", types=types, extra_options=self.extras)
            return ", ".join(types)
        if question.startswith("Any other option in that dialog"):
            return ", ".join(self.extras) or "none"
        raise RecorderError(f"the UI operator does not handle the prompt {question!r}")


def parse_value(text: str) -> float | int | str | bool:
    text = text.strip()
    if text in ("True", "False"):
        return text == "True"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text
