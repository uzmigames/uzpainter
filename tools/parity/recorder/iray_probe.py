"""Iray procedure probe: one operator-assisted Painter session that answers the "not confirmed"
rows of 07-preview-and-render-parity.md §2.1 (task `phase0.6_render-reference-procedure`).

The recorder applies everything the documented Python API can (project, camera, environment,
tone mapping, colour-profile LUT, a height fill); the operator does what only Painter's panels
can (Iray and viewer settings, Save Render) and types what the panels show. Every saved render
is checked like a reference capture: a fresh directory, a fence written before the operator is
asked to save, exactly one file written after it. Evidence stays in the private work directory
(`UZP_ORACLE_WORK/iray-probe/<run>/`); `probe.json` lists every file with its SHA-256 and the
answers of `tools.parity.render_procedure.analysis`.

Renders (Save Render, `renders/<name>/<name>.png`):

| Name | State |
|---|---|
| A | probe sheet, S = 64 samples, 256x256, Linear tone mapping (also `A_exr` when offered) |
| B | A again after a camera nudge and its undo (same-session repeat) |
| C | A with ACES tone mapping (also `C_exr`) |
| D | A with an all-magenta colour-profile LUT, Activate Color Profile on |
| E | A with the Vignette post effect at full strength |
| F, G | Environment Rotation 90: F saved at once while rendering, G once Done |
| H | camera rotated to `ROTATED_CAMERA` around the sphere |
| I | Min = Max Sample = 2 |
| J | A with a stripe height map in a fill layer (Height channel) |

Then the persistence form: the operator sets distinct values, the recorder saves, closes and
reopens the project, and the operator reads the panels again; then again on a new project.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.capture import (
    StaleCaptureError,
    measure_storage_format,
    verify_current_outputs,
    write_fence,
)
from tools.parity.recorder.iray import (
    IRAY_PANEL,
    PANEL_IMAGE_TYPES,
    Operator,
    PanelSetting,
    SettingsSheet,
    convergence,
    operator_form,
)
from tools.parity.recorder.job import canonical_json, sha256_bytes, sha256_file
from tools.parity.recorder.output import ensure_outside_repository, run_name, slug
from tools.parity.recorder.session import PainterSession, RecorderError
from tools.parity.recorder.texture import Now, close_quietly, utc_now
from tools.parity.render_procedure import fixtures
from tools.parity.render_procedure.analysis import PERSISTED_SETTINGS, analyse_probe
from tools.parity.render_procedure.projection import load_obj, orbit_position

PROBE_SCHEMA = "uzpainter/parity/iray-probe/1"
VIEWER_PANEL = "Viewer and MDL Settings"
DISPLAY_PANEL = "Display Settings"
SAMPLES = 64
SAVE_ATTEMPTS = 3
LOW_SAMPLES = 2
SIZE = 256
CAMERA_DISTANCE = 60.0
FIELD_OF_VIEW = 40.0
ROTATED_CAMERA = (-15.0, 25.0, 10.0)
CAMERA_HYPOTHESIS = "ZXY"
MDL_PARAMETERS = (
    "Emissive Intensity",
    "Refraction",
    "IOR",
    "Scattering",
    "Absorption",
    "Absorption Color",
)


def panel_setting(panel: str, setting: str, value: Any, unit: str | None = None) -> PanelSetting:
    return PanelSetting(panel, setting, value, unit)


PROBE_SHEET = (
    panel_setting(IRAY_PANEL, "Min Sample", SAMPLES),
    panel_setting(IRAY_PANEL, "Max Sample", SAMPLES),
    panel_setting(IRAY_PANEL, "Max Time", 10, "min"),
    panel_setting(IRAY_PANEL, "Caustic Sampler", False),
    panel_setting(IRAY_PANEL, "Firefly Filter", False),
    panel_setting(IRAY_PANEL, "Override viewport resolution", True),
    panel_setting(IRAY_PANEL, "Width", SIZE, "px"),
    panel_setting(IRAY_PANEL, "Height", SIZE, "px"),
    panel_setting(VIEWER_PANEL, "Environment Exposure", 0.0),
    panel_setting(VIEWER_PANEL, "Environment Rotation", 0.0),
    panel_setting(VIEWER_PANEL, "Dome", "Infinite Sphere"),
)

PERSISTENCE_SAMPLES = 37
PERSISTENCE_SHEET = (
    panel_setting(IRAY_PANEL, "Min Sample", PERSISTENCE_SAMPLES),
    panel_setting(IRAY_PANEL, "Max Sample", PERSISTENCE_SAMPLES),
    panel_setting(IRAY_PANEL, "Max Time", 17, "min"),
    panel_setting(IRAY_PANEL, "Caustic Sampler", True),
    panel_setting(IRAY_PANEL, "Firefly Filter", True),
    panel_setting(IRAY_PANEL, "Width", 320, "px"),
    panel_setting(IRAY_PANEL, "Height", 192, "px"),
    panel_setting(VIEWER_PANEL, "Environment Exposure", 0.5),
    panel_setting(VIEWER_PANEL, "Environment Rotation", 33.0),
    panel_setting(VIEWER_PANEL, "Emissive Intensity", 2.0),
    panel_setting(VIEWER_PANEL, "IOR", 1.33),
)


def sheet_of(settings: tuple[PanelSetting, ...], samples: int) -> SettingsSheet:
    by_name = {f"{s.panel}/{s.setting}": s for s in settings}
    width = by_name[f"{IRAY_PANEL}/Width"].value
    height = by_name[f"{IRAY_PANEL}/Height"].value
    max_time = by_name[f"{IRAY_PANEL}/Max Time"].value
    return SettingsSheet(
        samples=samples,
        max_time_s=float(max_time) * 60.0,
        width=int(width),
        height=int(height),
        panel_settings=settings,
        capture_encoding=None,
        sha256=sha256_bytes(
            canonical_json([[s.panel, s.setting, s.value, s.unit] for s in settings])
        ),
    )


def is_yes(text: str) -> bool:
    return text.strip().lower() in ("y", "yes", "true", "on")


class ProbeSession:
    """State of one probe run: Painter calls, operator prompts and the evidence written."""

    def __init__(self, session: PainterSession, operator: Operator, directory: Path) -> None:
        self.session = session
        self.operator = operator
        self.directory = directory
        self.step = 0
        self.files: dict[str, dict[str, Any]] = {}
        self.renders: dict[str, dict[str, Any]] = {}
        self.entries: dict[str, list[dict[str, Any]]] = {}
        self.panels: list[dict[str, Any]] = []
        self.record: dict[str, Any] = {}

    def keep(self, name: str, path: Path) -> dict[str, Any]:
        entry = {
            "file": path.relative_to(self.directory).as_posix(),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        self.files[name] = entry
        return entry

    def apply(self, call: str, args: dict[str, Any], resolved: dict[str, str] | None = None) -> Any:
        """One documented state change. Only project creation is asynchronous; the other calls
        return once applied (Iray mode need not count as an edition state to poll)."""
        self.step += 1
        result = self.session.call(
            "apply_step", step=self.step, call=call, args=args, resolved=resolved or {}
        )
        if call == ps.CREATE:
            self.session.wait_ready()
        return result

    def mode(self, mode: str) -> None:
        switched = self.session.call("switch_mode", mode=mode)
        if switched["mode"] != mode:
            raise RecorderError(f"Painter stayed in {switched['mode']} mode")

    def camera(self, name: str, value: Any) -> None:
        self.apply(ps.CAMERA + name, {"value": value})

    def panel_images(self, label: str, panels: tuple[str, ...]) -> None:
        for panel in panels:
            source = Path(
                self.operator.ask(f"Path of a screenshot of the '{panel}' panel ({label}):")
            )
            if not source.is_file() or source.suffix.lower() not in PANEL_IMAGE_TYPES:
                raise RecorderError(f"panel image {source} is not an existing PNG or JPEG file")
            target = self.directory / "panels" / f"{label}-{slug(panel)}{source.suffix.lower()}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            name = f"panel/{label}/{slug(panel)}"
            self.panels.append({"name": name, "panel": panel, "label": label})
            self.keep(name, target)

    def form(self, label: str, settings: tuple[PanelSetting, ...], samples: int) -> None:
        """The operator applies `settings`; entries must equal them (iray.operator_form)."""
        outputs, evidence, images = operator_form(
            self.operator, sheet_of(settings, samples), samples, self.directory / "forms" / label
        )
        self.entries[label] = outputs[0]["entries"]
        for item, image in zip(evidence, images, strict=True):
            self.keep(f"panel/{label}/{slug(item['panel'])}", image)

    def read_panels(self, label: str, settings: tuple[tuple[str, str], ...]) -> None:
        """The operator types what each panel shows now (no expected value)."""
        self.entries[label] = [
            {
                "panel": panel,
                "setting": setting,
                "value": self.operator.ask(f"[{panel}] {setting}: value shown now:"),
            }
            for panel, setting in settings
        ]

    def save_render(self, name: str, suffix: str = ".png", require_done: bool = True) -> None:
        """Save Render into a fresh directory after a fence; a refused file may be redone."""
        directory = self.directory / "renders" / name
        target = directory / f"{name}{suffix}"
        for attempt in range(1, SAVE_ATTEMPTS + 1):
            if directory.exists():
                shutil.rmtree(directory)  # the probe's own capture directory, refused content
            directory.mkdir(parents=True)
            fence_ns = write_fence(self.directory / "fences" / name)
            if require_done and not is_yes(
                self.operator.ask("Does Status in the Iray information section read Done? (yes/no)")
            ):
                raise RecorderError(f"render {name}: Iray has not finished; probe stopped")
            self.operator.tell(f"Use Save Render now and save the image as: {target}")
            self.operator.ask("Press Enter once the file is saved.")
            try:
                verify_current_outputs([target], directory, fence_ns)
                break
            except StaleCaptureError as error:
                if attempt == SAVE_ATTEMPTS:
                    raise
                self.operator.tell(f"That save was refused ({error}); save it again.")
        measured = measure_storage_format(target)
        self.renders[name] = {
            **self.keep(f"render/{name}", target),
            "container": measured.container,
            "sample_type": measured.sample_type,
            "bits_per_channel": measured.bits_per_channel,
            "channels": measured.channels,
            "colour_chunk": measured.encoding if measured.container == "png" else None,
        }

    def wait_done(self, what: str) -> None:
        self.operator.tell(f"{what} Wait until Status reads Done.")


def stage_probe_inputs(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True)
    staged = {
        "sphere": directory / "sphere.obj",
        "environment": directory / "sky-patch.exr",
        "lut": directory / "magenta-lut.exr",
        "height": directory / "stripes-height.png",
    }
    shutil.copyfile(fixtures.FIXTURE_DIR / "sphere.obj", staged["sphere"])
    shutil.copyfile(fixtures.FIXTURE_DIR / "sky-patch.exr", staged["environment"])
    staged["lut"].write_bytes(fixtures.magenta_lut())
    staged["height"].write_bytes(fixtures.stripe_height_png())
    return staged


def run_probe(session: PainterSession, operator: Operator, work: Path, now: Now = utc_now) -> Path:
    """Run the probe session; returns the evidence directory holding `probe.json`."""
    identity = session.connect()
    started = now()
    directory = (
        ensure_outside_repository(work) / "iray-probe" / run_name(identity.session_id, started)
    )
    staged = stage_probe_inputs(directory / "inputs")
    probe = ProbeSession(session, operator, directory)
    for name, path in staged.items():
        probe.keep(f"input/{name}", path)

    def write(**extra: Any) -> dict[str, Any]:
        data = {
            "schema": PROBE_SCHEMA,
            "painter_build": identity.painter_build(),
            "session_id": identity.session_id,
            "colour_management": identity.colour_management,
            "started_at": started.isoformat(),
            "finished_at": now().isoformat(),
            **probe.record,
            "sheet": {"samples": SAMPLES, "width": SIZE, "height": SIZE},
            "renders": probe.renders,
            "entries": probe.entries,
            "panels": probe.panels,
            "files": probe.files,
            **extra,
        }
        (directory / "probe.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data

    try:
        probe_steps(probe, staged)
    except Exception as error:
        write(failed=repr(error))  # keep the evidence gathered so far
        raise
    finally:
        close_quietly(session)
    data = write()
    try:
        answers = analyse_probe(data, directory, load_obj(staged["sphere"]))
    except Exception as error:  # evidence is kept; `iray-probe-analyse` re-runs the analysis
        write(analysis_error=repr(error))
    else:
        write(answers=answers)
    return directory


def probe_steps(probe: ProbeSession, staged: dict[str, Path]) -> None:
    """The probe protocol; facts go to `probe.record` as soon as they are known."""
    operator, session, record = probe.operator, probe.session, probe.record
    probe.apply(ps.CREATE, {"mesh": "sphere"}, {"mesh": staged["sphere"].as_posix()})
    probe.camera("projection_type", "Perspective")
    probe.camera("position", [0.0, 0.0, CAMERA_DISTANCE])
    probe.camera("rotation", [0.0, 0.0, 0.0])
    probe.camera("field_of_view", FIELD_OF_VIEW)
    probe.camera("aperture", 0.0)
    probe.apply(
        ps.SET_ENVIRONMENT,
        {"environment": "environment"},
        {"environment": staged["environment"].as_posix()},
    )
    probe.apply(ps.SET_TONE_MAPPING, {"function": "Linear"})
    render_state = session.call("render_state")
    render_state["scene_bounding_box"] = session.call("scene_bounding_box")
    record["render_state"] = render_state
    probe.mode("Visualisation")

    operator.tell(
        "Painter is in Iray mode with the probe sphere. Do not change anything yet: take a "
        "screenshot of each panel below as it is now (defaults)."
    )
    probe.panel_images("defaults", (IRAY_PANEL, VIEWER_PANEL, DISPLAY_PANEL))
    probe.read_panels("mdl_defaults", tuple((VIEWER_PANEL, p) for p in MDL_PARAMETERS))

    operator.tell("Now apply the probe settings below in the panels.")
    probe.form("probe_sheet", PROBE_SHEET, SAMPLES)
    record["convergence"] = convergence(operator, sheet_of(PROBE_SHEET, SAMPLES), SAMPLES)
    record["save_render_types"] = operator.ask(
        "Open Save Render: which file types does its dialog offer? (e.g. png, jpg, exr):"
    )
    record["save_render_options"] = operator.ask(
        "Any other option in that dialog (bit depth, alpha, ...)? (or none):"
    )
    operator.tell(
        "Cancel that dialog. From now on, each time the probe names a file, use Save Render "
        "and type that full path, extension included, as the file name."
    )
    exr = "exr" in record["save_render_types"].lower()
    probe.save_render("A")
    if exr:
        probe.save_render("A_exr", ".exr")

    probe.camera("field_of_view", FIELD_OF_VIEW + 1.0)
    probe.camera("field_of_view", FIELD_OF_VIEW)
    probe.wait_done("The recorder nudged the camera and put it back; Iray restarts.")
    probe.save_render("B")

    probe.apply(ps.SET_TONE_MAPPING, {"function": "ACES"})
    probe.wait_done("The recorder switched tone mapping to ACES.")
    probe.save_render("C")
    if exr:
        probe.save_render("C_exr", ".exr")
    probe.apply(ps.SET_TONE_MAPPING, {"function": "Linear"})

    lut = session.call("import_resource", path=staged["lut"].as_posix(), usage="COLOR_LUT")
    lut_set = session.call("set_color_lut", url=lut["url"])
    record["lut"] = {"url": lut["url"], "readback": lut_set["color_lut_url"]}
    record["lut"]["activate_already_ticked"] = is_yes(
        operator.ask(
            "In Display Settings, is 'Activate Color Profile' ticked? If not, tick it now. "
            "Was it already ticked? (yes/no)"
        )
    )
    record["lut"]["viewport_magenta"] = is_yes(
        operator.ask("Does the Iray view now look magenta? (yes/no)")
    )
    probe.wait_done("Colour profile LUT active.")
    probe.save_render("D")
    operator.ask("Untick 'Activate Color Profile' in Display Settings, then press Enter.")

    operator.tell(
        "In Display Settings, turn the Vignette post effect on (and post effects on if they "
        "have their own switch) with its strength at the maximum."
    )
    probe.wait_done("Vignette on.")
    probe.save_render("E")
    operator.ask("Turn Vignette (and any post-effect switch you turned on) off, then press Enter.")

    operator.tell(
        "Next: copy the file path printed below first. Then set "
        f"{VIEWER_PANEL} / Environment Rotation to 90 and IMMEDIATELY (while Status still "
        "reads Rendering, if you can) use Save Render with that path."
    )
    probe.save_render("F", require_done=False)
    record["stale"] = {
        "status_at_save": operator.ask(
            "What did Status read when you saved? (Rendering/Paused/Done)"
        )
    }
    probe.wait_done("Environment Rotation 90.")
    probe.save_render("G")
    operator.ask(f"Set {VIEWER_PANEL} / Environment Rotation back to 0, then press Enter.")

    position = list(orbit_position(ROTATED_CAMERA, CAMERA_DISTANCE, CAMERA_HYPOTHESIS))
    probe.camera("rotation", list(ROTATED_CAMERA))
    probe.camera("position", position)
    camera_state = session.call("render_state")
    record["camera_probe"] = {
        "rotation": list(ROTATED_CAMERA),
        "position": position,
        "field_of_view": FIELD_OF_VIEW,
        "hypothesis": CAMERA_HYPOTHESIS,
        "readback": {k: v for k, v in camera_state.items() if k.startswith("camera.")},
    }
    probe.wait_done("The recorder rotated the camera around the sphere.")
    probe.save_render("H")
    probe.camera("rotation", [0.0, 0.0, 0.0])
    probe.camera("position", [0.0, 0.0, CAMERA_DISTANCE])

    operator.ask(
        f"Set {IRAY_PANEL} / Min Sample and Max Sample to {LOW_SAMPLES}, then press Enter."
    )
    probe.wait_done(f"{LOW_SAMPLES} samples.")
    probe.save_render("I")
    operator.ask(
        f"Set {IRAY_PANEL} / Min Sample and Max Sample back to {SAMPLES}, then press Enter."
    )

    probe.mode("Edition")
    height = session.call("import_resource", path=staged["height"].as_posix(), usage="TEXTURE")
    record["height_url"] = height["url"]
    fill = probe.step + 1
    probe.apply(ps.INSERT_FILL, {"position": "top"})
    probe.apply(ps.SET_ACTIVE_CHANNELS, {"node_step": fill, "channels": ["Height"]})
    probe.apply(ps.SET_SOURCE, {"node_step": fill, "channel": "Height", "resource": height["url"]})
    probe.mode("Visualisation")
    probe.wait_done("The recorder added a stripe height map (fill layer, Height channel).")
    probe.save_render("J")

    operator.tell("Persistence: set these distinct values in the panels.")
    probe.form("persistence", PERSISTENCE_SHEET, PERSISTENCE_SAMPLES)
    project = probe.directory / "project" / "probe.spp"
    project.parent.mkdir(parents=True)
    probe.mode("Edition")
    session.wait_ready()
    session.call("save_as", path=project.as_posix())
    session.wait_ready()
    session.call("close_project")
    session.wait_closed()
    session.call("open_project", path=project.as_posix())
    session.wait_ready()
    probe.mode("Visualisation")
    operator.tell("The recorder saved, closed and reopened the project (Iray mode).")
    probe.read_panels("after_reopen", PERSISTED_SETTINGS)
    probe.panel_images("after-reopen", (IRAY_PANEL, VIEWER_PANEL))
    probe.mode("Edition")
    session.call("close_project")
    session.wait_closed()
    probe.apply(ps.CREATE, {"mesh": "sphere"}, {"mesh": staged["sphere"].as_posix()})
    probe.mode("Visualisation")
    operator.tell("The recorder created a new project from the same sphere (Iray mode).")
    probe.read_panels("new_project", PERSISTED_SETTINGS)
    probe.mode("Edition")


def reanalyse(directory: Path) -> dict[str, Any]:
    """Re-run the analysis of a finished probe (no Painter needed); rewrites `probe.json`."""
    path = directory / "probe.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["answers"] = analyse_probe(data, directory, load_obj(directory / "inputs" / "sphere.obj"))
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return dict(data["answers"])
