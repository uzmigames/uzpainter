"""Read-only Project Configuration observations bound to an owned F context boundary.

At a boundary whose context frame was just read, the owned Painter's Project Configuration panel
is surveyed with `project_configuration_survey.configuration_survey(physical_size=True,
bind_identity=True)` (Edit > Project Configuration > expand Physical size > Cancel; no Apply, OK,
checkbox, radio or reimport), then the frame is read again. The panel output binds the raw UI
observations to the owned identity (recording session, process, start, project, main window)
before and after, to the frame's typed hash before and the re-read frame after (which must be
typed-equal), and to the run's mesh import packet. Screenshots are written once, privately,
directly inside the run directory. Nothing here is an API readback, an operator-entered setting or
a derived setting: deriving effective settings is the settings contract's.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from tools.parity.filter_context_contract import BOUNDARIES, CONDITIONS, typed
from tools.parity.recorder import project_configuration_survey as survey
from tools.parity.recorder.filter_context import context_readback
from tools.parity.recorder.output import ensure_outside_repository
from tools.parity.recorder.painter_ui import PainterUi
from tools.parity.recorder.raw_capability_capture import RawSession

SCHEMA = "uzpainter/parity/settings-panel-readback/1"
PANEL = "Project Configuration"
UUID_CALL = "substance_painter.project.get_uuid"
IMAGES = {
    "configuration_image": "configuration-image",
    "physical_size_image": "physical-size-image",
}
Output = dict[str, Any]


def window_pid(handle: int) -> int:
    """The process owning the window `handle`, as Windows reports it."""
    import ctypes
    from ctypes import wintypes

    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(wintypes.HWND(handle), ctypes.byref(pid))
    return int(pid.value)


class PanelSink:
    """The survey's evidence sink for one boundary: the JSON snapshots kept in memory, each image
    written once as a PNG directly inside the private run directory, with the window it was taken
    from. Before and after each capture the owned identity is guarded and the window must belong
    to the owned process; a change refuses before anything is written."""

    def __init__(
        self,
        run_dir: Path,
        boundary: str,
        *,
        expected_pid: int,
        guard: Callable[[], None],
        pid_of: Callable[[int], int] = window_pid,
    ):
        self.run_dir, self.boundary, self.pid_of = run_dir, boundary, pid_of
        self.expected_pid, self.guard = expected_pid, guard
        self.values: dict[str, Any] = {}
        self.images: list[dict[str, Any]] = []
        self.files: list[Path] = []

    def log(self, event: str, **fields: Any) -> None:
        """Navigation events stay out of the record (the survey's own log is not evidence here)."""

    def json(self, name: str, value: Any) -> None:
        if name == "menu":
            # The opened Edit menu is navigation evidence, like the log: not a panel observation.
            return
        survey.require(name in ("configuration", "physical_size"), f"unexpected {name} snapshot")
        survey.require(name not in self.values, f"repeated {name} snapshot")
        self.values[name] = deepcopy(value)

    def image(self, name: str, ui: PainterUi, handle: int) -> None:
        survey.require(name in IMAGES, "unexpected panel image")
        output_id = f"settings/{self.boundary}/{IMAGES[name]}"
        survey.require(
            all(image["output_id"] != output_id for image in self.images), "repeated panel image"
        )
        self.guard()
        survey.require_owned(self.pid_of(handle) == self.expected_pid, "foreign panel window")
        frame, _ = ui.print_window(handle)
        self.guard()
        survey.require_owned(
            self.pid_of(handle) == self.expected_pid, "the panel window changed during capture"
        )
        path = self.run_dir / f"settings-{self.boundary}-{IMAGES[name]}.png"
        survey.require(path.resolve().parent == self.run_dir, "image outside the run directory")
        with path.open("xb") as stream:
            frame.save(stream, format="PNG")
        self.images.append({"output_id": output_id, "hwnd": handle, "pid": self.expected_pid})
        self.files.append(path)


def _uuid(frame: dict[str, Any]) -> Any:
    leaves = [
        o["value"]
        for o in frame["outputs"]
        if o["call"] == UUID_CALL and typed(o["args"]) == typed({"selector": {}, "parameters": {}})
    ]
    survey.require(len(leaves) == 1, "one project UUID leaf required")
    return leaves[0]


def _identity(session: RawSession, ui: PainterUi, frame: dict[str, Any]) -> dict[str, Any]:
    identity = session.identity
    survey.require(identity is not None, "the owned session is not connected")
    assert identity is not None
    return {
        "session_id": identity.session_id,
        "pid": session.owned.launcher.pid,
        "started": session.owned.started,
        "project_uuid": _uuid(frame),
        "main_hwnd": ui.window.handle,
    }


def _hash(frame: dict[str, Any]) -> str:
    return hashlib.sha256(typed(frame["outputs"])).hexdigest()


def _file(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "media_type": "image/png",
    }


def read_settings_panel(
    session: RawSession,
    ui: PainterUi,
    boundary: str,
    frame: dict[str, Any],
    run_dir: Path,
    mesh_import: dict[str, Any],
    *,
    pid_of: Callable[[int], int] = window_pid,
) -> tuple[list[Output], list[Path]]:
    """The bound panel output and its two image outputs for `boundary`, and the image files.
    Only a session that claimed its own creation is admitted: its created UUID must be the owned
    transport's and the frame's; the owned identity and UI window are guarded before the survey,
    after it and after the context re-read."""
    survey.require(boundary in BOUNDARIES and frame["boundary"] == boundary, "unknown boundary")
    survey.require(
        set(mesh_import) == {"input_id", "resolved_path", "before", "after"},
        "mesh import packet incomplete",
    )
    private = ensure_outside_repository(run_dir)
    survey.require(private.is_dir(), "the private run directory must exist")
    pid = session.owned.launcher.pid

    def guard() -> None:
        session.owned.verify()
        survey.require_owned(ui.window.process_id() == pid, "UI window process changed")

    def claimed(observed: dict[str, Any]) -> None:
        uuid = session.created_uuid
        survey.require(
            session.created is True
            and type(uuid) is str
            and bool(uuid)
            and uuid == session.owned.project_uuid == _uuid(observed),
            "the session has not claimed the owned project",
        )

    claimed(frame)
    guard()
    before = _identity(session, ui, frame)
    sink = PanelSink(private, boundary, expected_pid=pid, guard=guard, pid_of=pid_of)
    survey.configuration_survey(ui, session.owned, sink, physical_size=True, bind_identity=True)
    guard()
    again = context_readback(session, boundary)
    guard()
    claimed(again)
    after = _identity(session, ui, again)
    survey.require(after == before, "owned identity changed across the panel survey")
    survey.require(
        typed(again["outputs"]) == typed(frame["outputs"]), "the panel survey changed the context"
    )
    survey.require(
        set(sink.values) == {"configuration", "physical_size"}
        and [image["output_id"] for image in sink.images]
        == [f"settings/{boundary}/{IMAGES[name]}" for name in IMAGES],
        "panel survey incomplete",
    )
    values = {
        "schema": SCHEMA,
        "boundary": boundary,
        "condition": CONDITIONS[boundary],
        "binding": {
            "before": before,
            "after": after,
            "context_before_sha256": _hash(frame),
            "context_after_sha256": _hash(again),
            "context_after_outputs": deepcopy(again["outputs"]),
        },
        "mesh_import": deepcopy(mesh_import),
        "ui": {
            "configuration": sink.values["configuration"],
            "physical_size": sink.values["physical_size"],
        },
        "images": deepcopy(sink.images),
    }
    outputs: list[Output] = [
        {
            "output_id": f"settings/{boundary}/panel",
            "kind": "settings_panel_readback",
            "panel": PANEL,
            "values": values,
        }
    ]
    for image, path in zip(sink.images, sink.files, strict=True):
        outputs.append(
            {
                "output_id": image["output_id"],
                "kind": "settings_panel_evidence",
                "panel": PANEL,
                "blob": _file(path),
            }
        )
    return outputs, sink.files
