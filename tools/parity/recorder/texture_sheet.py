"""The operator step of texture goldens: settings only Painter's UI can set (decision 029).

Task `phase0.7_tier0-semantics-ui-cases`. Some Tier 0 cases depend on values the documented API
can neither set nor read: the height-to-normal method of a texture set (Texture Set Settings) and
a group's `Passthrough` blending mode (Layers; the python-doc's `BlendingMode.PassThrough` does
not exist at runtime, so the recorder never sets it through the API). The settings sheet is the
manifest's `applied_settings` with `applied_by: operator_settings_sheet`, one entry per target:

| Sheet name | Target |
|---|---|
| `Texture Set Settings/Height to normal method (<texture set>)` | that texture set |
| `Layers/Blending mode (step <n>, <channel>)` | the node inserted by step n, one channel |

After the state steps are replayed and before recording `r1`, the recorder shows each target
through the documented API (`textureset.set_active_stack`) and asks the operator (a person at the
console or `painter_ui.UiOperator`) to apply the sheet value and enter what the widget then shows.
A layer value is also read back through the documented `Node.get_blending_mode`. Any value that
differs from the sheet refuses the golden before anything is written. The operator gives an image
of the panel for each target. After save and reopen (`r2`) the same values are read again, not
applied, and must still equal the sheet. Entries and images are private outputs of both
recordings (`operator_recorded_settings`, `settings_panel_evidence`).
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import Job, sha256_file
from tools.parity.recorder.output import slug
from tools.parity.recorder.session import PainterSession, RecorderError

OPERATOR = "operator_settings_sheet"
TEXTURE_SET_PANEL = "Texture Set Settings"
LAYERS_PANEL = "Layers"
HEIGHT_METHOD = "Height to normal method"
BLENDING_MODE = "Blending mode"
HEIGHT_METHODS = ("Sharp", "Smooth (Sobel)")
TEXTURE_SET_NAME = re.compile(
    rf"^{TEXTURE_SET_PANEL}/(?P<setting>{HEIGHT_METHOD}) \((?P<texture_set>[^()]+)\)$"
)
LAYER_NAME = re.compile(
    rf"^{LAYERS_PANEL}/(?P<setting>{BLENDING_MODE}) \(step (?P<step>\d+), (?P<channel>\w+)\)$"
)
PANEL_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


class Operator(Protocol):
    """The operator of the settings panels (`iray.Operator`: console or UI automation)."""

    def tell(self, message: str) -> None: ...

    def ask(self, question: str) -> str: ...


@dataclass(frozen=True)
class SheetEntry:
    """One UI-set value of the sheet and the target it applies to."""

    name: str
    panel: str
    setting: str
    value: str
    texture_set: str | None = None
    node_step: int | None = None
    channel: str | None = None


def texture_sheet(job: Job) -> tuple[SheetEntry, ...]:
    """The operator entries of a texture golden's sheet; refuses a name it cannot target."""
    entries: list[SheetEntry] = []
    inserted = {s.step for s in job.state_steps if s.call in (ps.INSERT_GROUP, ps.INSERT_FILL)}
    for setting in job.manifest["applied_settings"]:
        if setting["applied_by"] != OPERATOR:
            continue
        name, value = str(setting["name"]), setting["value"]
        if not isinstance(value, str):
            raise RecorderError(f"operator setting {name!r}: value {value!r} is not a label")
        if match := TEXTURE_SET_NAME.match(name):
            if value not in HEIGHT_METHODS:
                raise RecorderError(f"{name}: {value!r} is not one of {HEIGHT_METHODS}")
            entries.append(
                SheetEntry(
                    name,
                    TEXTURE_SET_PANEL,
                    match["setting"],
                    value,
                    texture_set=match["texture_set"],
                )
            )
        elif match := LAYER_NAME.match(name):
            step = int(match["step"])
            if step not in inserted:
                raise RecorderError(f"{name}: step {step} inserts no layer")
            entries.append(
                SheetEntry(
                    name,
                    LAYERS_PANEL,
                    match["setting"],
                    value,
                    node_step=step,
                    channel=match["channel"],
                )
            )
        else:
            raise RecorderError(
                f"operator setting {name!r} names no target the texture operator knows "
                f"('{TEXTURE_SET_PANEL}/{HEIGHT_METHOD} (<texture set>)' or "
                f"'{LAYERS_PANEL}/{BLENDING_MODE} (step <n>, <channel>)')"
            )
    names = [e.name for e in entries]
    if len(names) != len(set(names)):
        raise RecorderError("the settings sheet names a target twice")
    return tuple(entries)


def blending_readback(entry: SheetEntry) -> dict[str, Any]:
    return {
        "call": ps.GET_BLENDING_MODE,
        "args": {"node_step": entry.node_step, "channel": entry.channel},
    }


def readback_specs(entries: tuple[SheetEntry, ...]) -> list[dict[str, Any]]:
    """Documented readbacks of the UI-set values (every layer entry)."""
    return [blending_readback(e) for e in entries if e.node_step is not None]


def show_target(session: PainterSession, entry: SheetEntry) -> str:
    """Make the entry's target the one Painter's panels show; returns how a prompt names it."""
    if entry.texture_set is not None:
        shown = session.call("show_texture_set", texture_set=entry.texture_set)
        if shown != entry.texture_set:
            raise RecorderError(f"{entry.name}: Painter shows texture set {shown!r}")
        return f"{entry.setting} of texture set '{entry.texture_set}'"
    node = session.call("show_node", node_step=entry.node_step)
    return f"{entry.setting} of layer '{node['name']}' in channel '{entry.channel}'"


def check_api_value(session: PainterSession, entry: SheetEntry) -> None:
    """A layer's blending mode as the documented getter reports it must be the sheet's."""
    if entry.node_step is None:
        return
    spec = blending_readback(entry)
    read = session.call("readback", call=spec["call"], args=spec["args"])
    if read != entry.value:
        raise RecorderError(
            f"{entry.name}: Node.get_blending_mode reads {read!r}, sheet says {entry.value!r}; "
            "golden refused"
        )


def operate(
    session: PainterSession,
    operator: Operator,
    entries: tuple[SheetEntry, ...],
    directory: Path,
    *,
    apply: bool,
) -> tuple[list[dict[str, Any]], list[Path]]:
    """Apply (r1) or re-read (r2) every entry; returns the private outputs and the images."""
    from tools.parity.recorder.iray import same_value  # iray imports texture, which imports this

    if apply:
        operator.tell("Apply these settings in Painter's panels; enter the value each one shows.")
    else:
        operator.tell("Read these settings in Painter's panels after the reopen; change nothing.")
    recorded: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    images: list[Path] = []
    evidence_dir = directory / "panels"
    evidence_dir.mkdir(parents=True)
    for index, entry in enumerate(entries):
        target = show_target(session, entry)
        if apply:
            shown = operator.ask(f"[{entry.panel}] {target} (sheet: {entry.value}):")
        else:
            shown = operator.ask(f"[{entry.panel}] {target}: value shown now:")
        if not same_value(shown, entry.value):
            raise RecorderError(
                f"{entry.name}: panel shows {shown!r}, sheet says {entry.value!r}; golden refused"
            )
        check_api_value(session, entry)
        recorded.append(
            {"panel": entry.panel, "setting": sheet_setting(entry), "value": entry.value}
        )
        source = Path(
            operator.ask(f"Path of an image of the '{entry.panel}' panel as set ({target}):")
        )
        if not source.is_file() or source.suffix.lower() not in PANEL_IMAGE_TYPES:
            raise RecorderError(f"panel image {source} is not an existing PNG or JPEG file")
        image = evidence_dir / f"{index:02d}-{slug(entry.name)}{source.suffix.lower()}"
        shutil.copyfile(source, image)
        evidence.append(
            {
                "output_id": f"panel/{index:02d}-{slug(entry.name)}",
                "kind": "settings_panel_evidence",
                "panel": entry.panel,
                "blob": {
                    "sha256": sha256_file(image),
                    "size_bytes": image.stat().st_size,
                    "media_type": PANEL_IMAGE_TYPES[image.suffix],
                },
            }
        )
        images.append(image)
    outputs = [
        {
            "output_id": "operator/settings",
            "kind": "operator_recorded_settings",
            "entries": recorded,
        },
        *evidence,
    ]
    return outputs, images


def sheet_setting(entry: SheetEntry) -> str:
    """The sheet name without its panel: the setting and its target."""
    return entry.name.split("/", 1)[1]
