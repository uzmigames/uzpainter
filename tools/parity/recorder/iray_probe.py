"""Iray procedure probe of the fixed render pipeline (decision 038): one Painter session that
answers the rows of 07-preview-and-render-parity.md §2.1 the fixed pipeline needs (task
`phase0.6_render-reference-procedure`).

The fixed pipeline is the Assets3D render comparison standard (`Render-Comparison-Standard.json`
v2 top-level block, the `ref_match` v3 preset and the `base_color` diagnostic). The recorder
applies what the documented Python API can (project, camera, environment, a height fill); the
operator, a person or `painter_ui.UiOperator` (decision 029), applies and reads back the panel
settings, reads Iray's information section and uses Save Render. Every saved render is checked
like a reference capture: a fresh directory, a fence written before the operator is asked to
save, exactly one file written after it. Evidence stays in the private work directory
(`UZP_ORACLE_WORK/iray-probe/<run>/`); `probe.json` lists every file with its SHA-256 and the
answers of `tools.parity.render_procedure.analysis`.

Renders (Save Render, `renders/<name>/<name>.<ext>`), all under the v2 sheet unless named:

| Name | State |
|---|---|
| A | v2 sheet, camera at +Z looking at the sphere (also `A_exr`, and the live view `V`) |
| B | A again after a camera nudge and its undo (same-session repeat) |
| F, G | field of view 41: F saved at once, G once Done (stale-frame behaviour) |
| H | camera rotated to `ROTATED_CAMERA` around the sphere (Euler order) |
| I | Min = Max Sample = 2 (denoiser) |
| J | a stripe height map in a fill layer, Height channel, shader at Painter's defaults |
| R | the `ref_match` preset: session-resource HDRI, clear colour 141,142,148, rotation 180 |

Then the `base_color` diagnostic: Edition mode, view mode Base color, environment opacity and
blur 0, one live-view image `BC`.
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
from tools.parity.render_procedure.analysis import analyse_probe
from tools.parity.render_procedure.projection import load_obj, orbit_position

PROBE_SCHEMA = "uzpainter/parity/iray-probe/2"
DISPLAY_PANEL = "Display Settings"
SHADER_PANEL = "Shader Settings"
SAMPLES = 256
SAVE_ATTEMPTS = 3
LOW_SAMPLES = 2
SIZE = 1200
MAX_TIME_S = 3600
CAMERA_DISTANCE = 60.0
FIELD_OF_VIEW = 40.0
NUDGED_FIELD_OF_VIEW = 41.0
ROTATED_CAMERA = (-15.0, 25.0, 10.0)
CAMERA_HYPOTHESIS = "ZXY"
# The v2 environment: a Painter starter asset named by its URL (decision 038; Assets3D
# Render-Comparison-Standard.json painter.lighting.environment_url).
STUDIO_WHITE_SOFT = (
    "resource://starter_assets/Studio White Soft?version=022c26ec30cd5575037b74f697993c1d73f52865"
    ".image"
)
# The ref_match v3 environment (Assets3D Pipeline/render/HDRI/TOS-RefMatch-Skeletal-Mage.exr,
# UzmiGames-authored, `presets.ref_match.blender.environment.sha256` of the standard).
REF_MATCH_HDRI_SHA256 = "77eeed8de580113581d50258e0ab3dd055aa29fa7d5ab614f2599ce036e0841d"
V2_CLEAR_COLOUR = "595959"  # the standard's expected background, sRGB8 89,89,89
REF_MATCH_CLEAR_COLOUR = "8D8E94"  # sRGB8 141,142,148
REF_MATCH_ROTATION = 180.0  # the back view of the per-view rotation rule


def panel_setting(panel: str, setting: str, value: Any, unit: str | None = None) -> PanelSetting:
    return PanelSetting(panel, setting, value, unit)


# The v2 values Painter applies in Iray mode (Assets3D standard, top-level block).
def v2_sheet(size: int = SIZE) -> tuple[PanelSetting, ...]:
    return (
        panel_setting(IRAY_PANEL, "Min Sample", SAMPLES),
        panel_setting(IRAY_PANEL, "Max Sample", SAMPLES),
        panel_setting(IRAY_PANEL, "Max Time", MAX_TIME_S, "s"),
        panel_setting(IRAY_PANEL, "Caustic Sampler", False),
        panel_setting(IRAY_PANEL, "Firefly Filter", False),
        panel_setting(IRAY_PANEL, "Override viewport resolution", True),
        panel_setting(IRAY_PANEL, "Width", size, "px"),
        panel_setting(IRAY_PANEL, "Height", size, "px"),
        panel_setting(DISPLAY_PANEL, "View mode", "Material"),
        panel_setting(DISPLAY_PANEL, "Override environment map color space", True),
        panel_setting(DISPLAY_PANEL, "Environment map color space", "Linear"),
        panel_setting(DISPLAY_PANEL, "Environment Exposure", 0.0),
        panel_setting(DISPLAY_PANEL, "Environment Rotation", 0.0),
        panel_setting(DISPLAY_PANEL, "Environment Alignment", "World"),
        panel_setting(DISPLAY_PANEL, "Dome", "Infinite sphere"),
        panel_setting(DISPLAY_PANEL, "Clear color", True),
        panel_setting(DISPLAY_PANEL, "Clear color value", V2_CLEAR_COLOUR),
        panel_setting(DISPLAY_PANEL, "Ground", False),
        panel_setting(DISPLAY_PANEL, "Activate Post Effects", False),
        panel_setting(DISPLAY_PANEL, "Activate Color Profile", False),
        panel_setting(DISPLAY_PANEL, "Activate Subsurface Scattering", False),
    )


V2_SHEET = v2_sheet()
# The v2 values that act only on the realtime viewport: Painter disables them in Iray mode.
# The view mode comes last: the Base color view disables the lighting controls.
VIEWPORT_SHEET = (
    panel_setting(DISPLAY_PANEL, "Environment Opacity", 0.0),
    panel_setting(DISPLAY_PANEL, "Environment Blur", 0.0),
    panel_setting(DISPLAY_PANEL, "Shadows", False),
    panel_setting(DISPLAY_PANEL, "View mode", "Base color"),
)


def sheet_of(settings: tuple[PanelSetting, ...], samples: int, size: int = SIZE) -> SettingsSheet:
    return SettingsSheet(
        samples=samples,
        max_time_s=float(MAX_TIME_S),
        width=size,
        height=size,
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

    def __init__(
        self, session: PainterSession, operator: Operator, directory: Path, size: int = SIZE
    ) -> None:
        self.size = size
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
        return once applied."""
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

    def copy_image(self, name: str, source: Path, target: Path) -> None:
        if not source.is_file() or source.suffix.lower() not in PANEL_IMAGE_TYPES:
            raise RecorderError(f"image {source} is not an existing PNG or JPEG file")
        target = target.with_suffix(source.suffix.lower())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        self.keep(name, target)

    def panel_images(self, label: str, panels: tuple[str, ...]) -> None:
        for panel in panels:
            source = Path(self.operator.ask(f"Path of an image of the '{panel}' panel ({label}):"))
            name = f"panel/{label}/{slug(panel)}"
            self.copy_image(name, source, self.directory / "panels" / f"{label}-{slug(panel)}")
            self.panels.append({"name": name, "panel": panel, "label": label})

    def live_view(self, name: str) -> None:
        question = f"Path of an image of the 3D viewport (live view, {name}):"
        source = Path(self.operator.ask(question))
        self.copy_image(f"view/{name}", source, self.directory / "views" / name)

    def form(self, label: str, settings: tuple[PanelSetting, ...], samples: int) -> None:
        """The operator applies `settings`; entries must equal them (iray.operator_form)."""
        outputs, evidence, images = operator_form(
            self.operator,
            sheet_of(settings, samples, self.size),
            samples,
            self.directory / "forms" / label,
        )
        self.entries[label] = outputs[0]["entries"]
        for item, image in zip(evidence, images, strict=True):
            self.keep(f"panel/{label}/{slug(item['panel'])}", image)

    def change(self, panel: str, setting: str, value: Any, unit: str | None = None) -> None:
        suffix = f" {unit}" if unit else ""
        self.operator.ask(f"Set {panel} / {setting} to {value}{suffix}, then press Enter.")

    def read(self, label: str, settings: tuple[tuple[str, str], ...]) -> None:
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


def stage_probe_inputs(directory: Path, ref_match_hdri: Path) -> dict[str, Path]:
    if sha256_file(ref_match_hdri) != REF_MATCH_HDRI_SHA256:
        raise RecorderError(
            f"{ref_match_hdri} is not the ref_match HDRI of the standard (SHA-256 differs)"
        )
    directory.mkdir(parents=True)
    staged = {
        "sphere": directory / "sphere.obj",
        "height": directory / "stripes-height.png",
        "ref_match_hdri": directory / ref_match_hdri.name,
    }
    shutil.copyfile(fixtures.FIXTURE_DIR / "sphere.obj", staged["sphere"])
    staged["height"].write_bytes(fixtures.stripe_height_png())
    shutil.copyfile(ref_match_hdri, staged["ref_match_hdri"])
    return staged


def run_probe(
    session: PainterSession,
    operator: Operator,
    work: Path,
    ref_match_hdri: Path,
    now: Now = utc_now,
    size: int = SIZE,
) -> Path:
    """Run the probe session; returns the evidence directory holding `probe.json`. `size` is
    the override resolution (the standard's 1200; tests use a small one)."""
    identity = session.connect()
    started = now()
    directory = (
        ensure_outside_repository(work) / "iray-probe" / run_name(identity.session_id, started)
    )
    staged = stage_probe_inputs(directory / "inputs", ref_match_hdri)
    probe = ProbeSession(session, operator, directory, size)
    for name, path in staged.items():
        probe.keep(f"input/{name}", path)

    def write(**extra: Any) -> dict[str, Any]:
        operator_log = getattr(operator, "log", None)
        data = {
            "schema": PROBE_SCHEMA,
            "painter_build": identity.painter_build(),
            "session_id": identity.session_id,
            "colour_management": identity.colour_management,
            "started_at": started.isoformat(),
            "finished_at": now().isoformat(),
            **probe.record,
            "sheet": {"samples": SAMPLES, "width": size, "height": size},
            "renders": probe.renders,
            "entries": probe.entries,
            "panels": probe.panels,
            "files": probe.files,
            "operator_log": operator_log if isinstance(operator_log, list) else None,
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
    probe.apply(ps.SET_ENVIRONMENT, {"resource_url": STUDIO_WHITE_SOFT})
    render_state = session.call("render_state")
    render_state["scene_bounding_box"] = session.call("scene_bounding_box")
    record["render_state"] = render_state
    if render_state["colour_management"]["mode"] != "ocio":
        raise RecorderError(
            "the fixed pipeline is colour managed: start Painter with OCIO naming Painter's "
            "resources/ocio/substance/config.ocio (decision 038)"
        )
    probe.mode("Visualisation")

    operator.tell("Painter is in Iray mode with the probe sphere; images of the defaults first.")
    probe.panel_images("defaults", (IRAY_PANEL, DISPLAY_PANEL, SHADER_PANEL))
    operator.tell("Apply the v2 sheet of the fixed pipeline.")
    sheet = v2_sheet(probe.size)
    probe.form("v2", sheet, SAMPLES)
    record["convergence"] = convergence(operator, sheet_of(sheet, SAMPLES, probe.size), SAMPLES)
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
    probe.save_render("A")
    probe.save_render("A_exr", ".exr")
    probe.live_view("V")
    probe.panel_images("v2", ("Viewport display transform",))

    probe.camera("field_of_view", NUDGED_FIELD_OF_VIEW)
    probe.camera("field_of_view", FIELD_OF_VIEW)
    probe.wait_done("The recorder nudged the camera and put it back; Iray restarts.")
    probe.save_render("B")

    probe.camera("field_of_view", NUDGED_FIELD_OF_VIEW)
    probe.save_render("F", require_done=False)
    record["stale"] = {
        "status_at_save": operator.ask(
            "What did Status read when you saved? (Rendering/Paused/Done)"
        ),
        "field_of_view": NUDGED_FIELD_OF_VIEW,
    }
    probe.wait_done("Field of view 41.")
    probe.save_render("G")
    probe.camera("field_of_view", FIELD_OF_VIEW)

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

    probe.change(IRAY_PANEL, "Min Sample", LOW_SAMPLES)
    probe.change(IRAY_PANEL, "Max Sample", LOW_SAMPLES)
    probe.wait_done(f"{LOW_SAMPLES} samples.")
    probe.save_render("I")
    probe.change(IRAY_PANEL, "Max Sample", SAMPLES)
    probe.change(IRAY_PANEL, "Min Sample", SAMPLES)

    probe.mode("Edition")
    session.wait_ready()
    height = session.call("import_resource", path=staged["height"].as_posix(), usage="TEXTURE")
    record["height_url"] = height["url"]
    fill = probe.step + 1
    probe.apply(ps.INSERT_FILL, {"position": "top"})
    probe.apply(ps.SET_ACTIVE_CHANNELS, {"node_step": fill, "channels": ["Height"]})
    probe.apply(ps.SET_SOURCE, {"node_step": fill, "channel": "Height", "resource": height["url"]})
    session.wait_ready()
    probe.mode("Visualisation")
    probe.panel_images("height", (SHADER_PANEL,))
    probe.wait_done("The recorder added a stripe height map (fill layer, Height channel).")
    probe.save_render("J")

    environment = session.call("set_session_environment", path=staged["ref_match_hdri"].as_posix())
    probe.change(DISPLAY_PANEL, "Clear color value", REF_MATCH_CLEAR_COLOUR)
    probe.change(DISPLAY_PANEL, "Environment Rotation", REF_MATCH_ROTATION)
    probe.read(
        "ref_match",
        (
            (DISPLAY_PANEL, "Clear color value"),
            (DISPLAY_PANEL, "Environment Rotation"),
            (DISPLAY_PANEL, "Environment map color space"),
            (DISPLAY_PANEL, "Dome"),
        ),
    )
    record["ref_match"] = {
        "environment_url": environment["environment_url"],
        "clear_colour": REF_MATCH_CLEAR_COLOUR,
        "rotation": REF_MATCH_ROTATION,
    }
    probe.wait_done("The ref_match preset is applied.")
    probe.save_render("R")
    probe.panel_images("ref_match", (DISPLAY_PANEL,))

    probe.mode("Edition")
    session.wait_ready()
    operator.tell("The base_color diagnostic: realtime viewport, Base color view mode.")
    probe.form("base_color", VIEWPORT_SHEET, SAMPLES)
    probe.live_view("BC")
    probe.change(DISPLAY_PANEL, "View mode", "Material")


def reanalyse(directory: Path) -> dict[str, Any]:
    """Re-run the analysis of a finished probe (no Painter needed); rewrites `probe.json`."""
    path = directory / "probe.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["answers"] = analyse_probe(data, directory, load_obj(directory / "inputs" / "sphere.obj"))
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return dict(data["answers"])
