"""Iray references (Tier 3): the capture procedure of 07-preview-and-render-parity.md §2.2.

Items 2.4 (capture path) and 2.5 (operator form). One invocation records one reference in one
Painter session:

1. Replay the job's state steps (project, fills, camera, environment, tone mapping), read back
   every documented render setting (§2.1) and switch to Iray mode (`ui.UIMode.Visualisation`).
2. Operator form: the operator applies each panel setting of the settings sheet (the manifest's
   `applied_settings` with `applied_by: operator_settings_sheet`, named `<panel>/<setting>`),
   enters the value the panel shows and an image of each panel; values must equal the sheet.
3. Convergence: Min Sample = Max Sample = S (k*S for the `k_times_samples` reference) and Max
   Time from the sheet; the operator reports Status, Iterations and Rendering time; accepted
   only for Status Done, Iterations = samples and Rendering time below Max Time.
4. The recorder writes the fence, then the operator saves the render (Save Render) to the path
   the recorder names. Current-frame verification: the file is the only file of a fresh
   directory, written after the fence, at the overridden resolution, and its silhouette matches
   the fixture mesh projected from the camera the recorder read back (`render_procedure/
   projection.py`), after checking that Painter's scene bounding box is the mesh file's.
5. The recording is staged in the private work directory. When two `separate_session`
   references (different Painter processes) and one `k_times_samples` reference with identical
   keys are staged, the private record and the public manifest are written to the inbox.

The `same_session` condition (stability probe of decision 052's capture request, decision 062)
records two S renders of one project in one Painter session: after the first Save Render the
recorder nudges the camera's field of view and puts it back through the documented API, which
restarts Iray (the procedure probe's same-session repeat), requires the read-back render state
to equal the first, and repeats steps 3 and 4. Such a golden never completes: it is stability
evidence, not an admitted reference.

The sheet names the procedure version (`capture.procedure`, `PROCEDURE_VERSION`) and the pixel
route (`capture.route`); the qualified procedure and its answers are
`parity/reports/phase0/iray-capture-procedure.md` (task `phase0.6_render-reference-procedure`).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.capture import (
    MEDIA_TYPES,
    check_silhouette,
    decode_png,
    measure_storage_format,
    verify_current_outputs,
    write_fence,
)
from tools.parity.recorder.environment import DIFFERS, UNKNOWN, envelope_match
from tools.parity.recorder.job import Job, canonical_json, sha256_bytes, sha256_file
from tools.parity.recorder.output import ensure_outside_repository, run_name, slug, write_run
from tools.parity.recorder.session import PainterSession, RecorderError
from tools.parity.recorder.texture import (
    Now,
    close_quietly,
    replay,
    stage_inputs,
    stage_session_files,
    utc_now,
)
from tools.parity.render_procedure.projection import (
    DEFAULT_ORDER,
    ROTATION_ORDERS,
    Camera,
    check_scene_bounds,
    load_obj,
    silhouette_mask,
    write_grey_png,
)

IRAY_PANEL = "Iray Settings"
MIN_SAMPLE = f"{IRAY_PANEL}/Min Sample"
MAX_SAMPLE = f"{IRAY_PANEL}/Max Sample"
MAX_TIME = f"{IRAY_PANEL}/Max Time"
WIDTH = f"{IRAY_PANEL}/Width"
HEIGHT = f"{IRAY_PANEL}/Height"
CAPTURE_ENCODING = "capture.encoding"
CAPTURE_PROCEDURE = "capture.procedure"
CAPTURE_ROUTE = "capture.route"
ROTATION_ORDER = "capture.camera_rotation_order"
CAPTURE_BACKGROUND = "capture.background_srgb8"
CAPTURE_BITS = "capture.bits_per_channel"
CAPTURE_TRANSFORM = "capture.display_transform"
DISPLAY_TRANSFORM_PANEL = "Viewport display transform"
PROCEDURE_VERSION = "iray-capture/1"
SAVE_RENDER = "save_render"
TIME_UNITS = {"s": 1.0, "min": 60.0, "h": 3600.0}
PANEL_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
SEPARATE_SESSION = "separate_session"
K_TIMES_SAMPLES = "k_times_samples"
SAME_SESSION = "same_session"
SAME_SESSION_RENDERS = 2
NUDGE_DEGREES = 1.0  # field-of-view nudge that restarts Iray (procedure probe step B)


class Operator(Protocol):
    """The person at the Painter window (settings panels, convergence, Save Render)."""

    def tell(self, message: str) -> None: ...

    def ask(self, question: str) -> str: ...


class ConsoleOperator:
    def tell(self, message: str) -> None:
        print(message)

    def ask(self, question: str) -> str:
        return input(f"{question} ").strip()


@dataclass(frozen=True)
class PanelSetting:
    panel: str
    setting: str
    value: float | int | str | bool
    unit: str | None


@dataclass(frozen=True)
class SettingsSheet:
    samples: int
    max_time_s: float
    width: int
    height: int
    panel_settings: tuple[PanelSetting, ...]
    capture_encoding: str | None
    sha256: str
    rotation_order: str | None = None
    background_srgb8: tuple[int, ...] | None = None
    bits_per_channel: int | None = None
    display_transform: str | None = None


def settings_sheet(job: Job) -> SettingsSheet:
    manifest = job.manifest
    panel: list[PanelSetting] = []
    capture: dict[str, str] = {}
    for setting in manifest["applied_settings"]:
        if setting["name"].startswith("capture."):
            capture[setting["name"]] = str(setting["value"])
        elif setting["applied_by"] == "operator_settings_sheet":
            name, _, label = setting["name"].partition("/")
            if not label:
                raise RecorderError(
                    f"operator setting {setting['name']!r} is not <panel>/<setting>"
                )
            panel.append(PanelSetting(name, label, setting["value"], setting.get("unit")))
    by_name = {f"{p.panel}/{p.setting}": p for p in panel}
    for required in (MIN_SAMPLE, MAX_SAMPLE, MAX_TIME, WIDTH, HEIGHT):
        if required not in by_name:
            raise RecorderError(f"settings sheet lacks {required!r}")
    if by_name[MIN_SAMPLE].value != by_name[MAX_SAMPLE].value:
        raise RecorderError("Min Sample must equal Max Sample (the sample count ends the render)")
    time_setting = by_name[MAX_TIME]
    if time_setting.unit not in TIME_UNITS:
        raise RecorderError(f"Max Time unit must be one of {sorted(TIME_UNITS)}")
    if capture.get(CAPTURE_PROCEDURE) != PROCEDURE_VERSION:
        raise RecorderError(
            f"the sheet must name the capture procedure: {CAPTURE_PROCEDURE} = "
            f"{PROCEDURE_VERSION!r} (found {capture.get(CAPTURE_PROCEDURE)!r})"
        )
    if capture.get(CAPTURE_ROUTE) != SAVE_RENDER:
        raise RecorderError(
            f"{CAPTURE_ROUTE} must be {SAVE_RENDER!r}: the recorder implements only the Save "
            "Render route of the qualified procedure"
        )
    order = capture.get(ROTATION_ORDER)
    if order is not None and order not in ROTATION_ORDERS:
        raise RecorderError(f"{ROTATION_ORDER} must be one of {ROTATION_ORDERS}")
    background = None
    if CAPTURE_BACKGROUND in capture:
        background = tuple(int(v) for v in capture[CAPTURE_BACKGROUND].split(","))
        if len(background) != 3 or not all(0 <= v <= 255 for v in background):
            raise RecorderError(f"{CAPTURE_BACKGROUND} must be three 8-bit codes R,G,B")
    bits = int(capture[CAPTURE_BITS]) if CAPTURE_BITS in capture else None
    sheet = {
        "golden_id": manifest["golden_id"],
        "instruction_sequence": manifest["instruction_sequence"],
        "applied_settings": manifest["applied_settings"],
        "uncontrolled_settings": manifest.get("uncontrolled_settings", []),
    }
    return SettingsSheet(
        samples=int(by_name[MIN_SAMPLE].value),
        max_time_s=float(time_setting.value) * TIME_UNITS[time_setting.unit],
        width=int(by_name[WIDTH].value),
        height=int(by_name[HEIGHT].value),
        panel_settings=tuple(panel),
        capture_encoding=capture.get(CAPTURE_ENCODING),
        sha256=sha256_bytes(canonical_json(sheet)),
        rotation_order=order,
        background_srgb8=background,
        bits_per_channel=bits,
        display_transform=capture.get(CAPTURE_TRANSFORM),
    )


def same_value(entered: str, expected: float | int | str | bool) -> bool:
    if isinstance(expected, bool):
        return entered.lower() in (("true", "on", "yes") if expected else ("false", "off", "no"))
    if isinstance(expected, int | float):
        try:
            return float(entered) == float(expected)
        except ValueError:
            return False
    return entered.strip().casefold() == str(expected).strip().casefold()


def expected_value(setting: PanelSetting, samples: int) -> float | int | str | bool:
    if f"{setting.panel}/{setting.setting}" in (MIN_SAMPLE, MAX_SAMPLE):
        return samples
    return setting.value


def operator_form(
    operator: Operator, sheet: SettingsSheet, samples: int, directory: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[Path]]:
    """Entries the operator confirms in each panel, and one panel image each (private)."""
    operator.tell("Apply these settings in Painter's panels; enter the value each panel shows.")
    entries: list[dict[str, Any]] = []
    for setting in sheet.panel_settings:
        expected = expected_value(setting, samples)
        unit = f" {setting.unit}" if setting.unit else ""
        entered = operator.ask(f"[{setting.panel}] {setting.setting} (sheet: {expected}{unit}):")
        if not same_value(entered, expected):
            raise RecorderError(
                f"{setting.panel}/{setting.setting}: panel shows {entered!r}, sheet says "
                f"{expected!r}; reference refused"
            )
        entry: dict[str, Any] = {
            "panel": setting.panel,
            "setting": setting.setting,
            "value": expected,
        }
        if setting.unit:
            entry["unit"] = setting.unit
        entries.append(entry)
    evidence: list[dict[str, Any]] = []
    images: list[Path] = []
    evidence_dir = directory / "panels"
    evidence_dir.mkdir(parents=True)
    panels = sorted({s.panel for s in sheet.panel_settings})
    if sheet.display_transform is not None:
        operator.tell(
            f"The viewport display transform must read {sheet.display_transform!r} "
            "(Painter's fresh-session default; no interface sets it)."
        )
        panels.append(DISPLAY_TRANSFORM_PANEL)
    for panel in panels:
        source = Path(operator.ask(f"Path of an image of the '{panel}' panel as set:"))
        if not source.is_file() or source.suffix.lower() not in PANEL_IMAGE_TYPES:
            raise RecorderError(f"panel image {source} is not an existing PNG or JPEG file")
        image = evidence_dir / f"{slug(panel)}{source.suffix.lower()}"
        shutil.copyfile(source, image)
        evidence.append(
            {
                "output_id": f"panel/{slug(panel)}",
                "kind": "settings_panel_evidence",
                "panel": panel,
                "blob": {
                    "sha256": sha256_file(image),
                    "size_bytes": image.stat().st_size,
                    "media_type": PANEL_IMAGE_TYPES[image.suffix],
                },
            }
        )
        images.append(image)
    operator_output = {
        "output_id": "operator/settings",
        "kind": "operator_recorded_settings",
        "entries": entries,
    }
    return [operator_output], evidence, images


def convergence(operator: Operator, sheet: SettingsSheet, samples: int) -> dict[str, Any]:
    operator.tell(
        f"Let Iray converge: Min Sample = Max Sample = {samples}, Max Time {sheet.max_time_s:g} s."
    )
    status = operator.ask("Status shown in the Iray information section:")
    iterations = int(operator.ask("Iterations shown:"))
    rendering_time = float(operator.ask("Rendering time shown, in seconds:"))
    if status != "Done" or iterations != samples or not rendering_time < sheet.max_time_s:
        raise RecorderError(
            f"not converged on the sample count: Status {status!r}, Iterations {iterations} "
            f"(need {samples}), Rendering time {rendering_time} s (Max Time {sheet.max_time_s} s)"
        )
    return {
        "status": "Done",
        "iterations": iterations,
        "rendering_time_s": rendering_time,
        "max_time_s": sheet.max_time_s,
    }


def mesh_input(job: Job) -> str:
    for step in job.state_steps:
        if step.call == ps.CREATE:
            return str(step.args["mesh"])
    raise RecorderError("the instruction sequence has no project.create step")


def expected_silhouette(
    mesh_file: Path, render_state: dict[str, Any], sheet: SettingsSheet, directory: Path
) -> Path:
    """The fixture projected from the recorded camera, written as a mask (private evidence)."""
    mesh = load_obj(mesh_file)
    check_scene_bounds(mesh, render_state["scene_bounding_box"])
    camera = Camera.from_render_state(render_state)
    order = sheet.rotation_order
    if order is None:
        if any(angle != 0.0 for angle in camera.rotation):
            raise RecorderError(
                f"camera rotation {list(camera.rotation)} needs {ROTATION_ORDER} in the sheet "
                "(the Euler order the probe confirmed)"
            )
        order = DEFAULT_ORDER  # irrelevant for a zero rotation
    mask = directory / "expected-silhouette.png"
    directory.mkdir(parents=True, exist_ok=True)
    write_grey_png(mask, silhouette_mask(mesh, camera, sheet.width, sheet.height, order))
    return mask


def capture_render(
    operator: Operator, sheet: SettingsSheet, directory: Path, silhouette: Path
) -> tuple[dict[str, Any], Path]:
    render_dir = directory / "render"
    render_dir.mkdir(parents=True)
    fence_ns = write_fence(directory / "fence-render")
    target = render_dir / "reference.png"
    operator.tell(f"Use Save Render now and save the image as: {target}")
    operator.ask("Press Enter once the file is saved.")
    verify_current_outputs([target], render_dir, fence_ns)
    measured = measure_storage_format(target)
    image = decode_png(target)
    if (image.width, image.height) != (sheet.width, sheet.height):
        raise RecorderError(
            f"render is {image.width}x{image.height}, "
            f"the sheet overrides {sheet.width}x{sheet.height}"
        )
    if sheet.bits_per_channel is not None and measured.bits_per_channel != sheet.bits_per_channel:
        raise RecorderError(
            f"render is {measured.bits_per_channel}-bit, the sheet requires "
            f"{sheet.bits_per_channel}-bit"
        )
    result = check_silhouette(target, silhouette)
    if sheet.background_srgb8 is not None:
        top = (1 << measured.bits_per_channel) - 1
        shown = tuple(round(v * 255 / top) for v in result.background_value[:3])
        if shown != sheet.background_srgb8:
            raise RecorderError(
                f"render background reads {list(shown)} in 8-bit codes, the sheet expects "
                f"{list(sheet.background_srgb8)} (clear colour through the display transform): "
                "wrong display transform, clear colour or frame"
            )
    if measured.encoding is not None:
        encoding = measured.encoding
    elif sheet.capture_encoding is not None:
        encoding = sheet.capture_encoding
    else:
        raise RecorderError(
            f"the saved render states no encoding and the sheet has no {CAPTURE_ENCODING!r}"
        )
    return {
        "blob": {
            "sha256": sha256_file(target),
            "size_bytes": target.stat().st_size,
            "media_type": MEDIA_TYPES[measured.container],
        },
        "storage_format": measured.as_schema(encoding),
        "resolution": {"width": image.width, "height": image.height},
    }, target


@dataclass(frozen=True)
class StagedRecording:
    key: dict[str, Any]
    recording: dict[str, Any]
    blobs: list[Path]
    environment: dict[str, Any] | None = None


def stage(
    directory: Path,
    key: dict[str, Any],
    recording: dict[str, Any],
    blobs: list[Path],
    environment: dict[str, Any] | None = None,
) -> None:
    blob_dir = directory / "blobs"
    blob_dir.mkdir(parents=True)
    for blob in blobs:
        shutil.copyfile(blob, blob_dir / sha256_file(blob))
    (directory / "staged.json").write_text(
        json.dumps({"key": key, "recording": recording, "environment": environment}, indent=2),
        encoding="utf-8",
    )


def load_staged(golden_dir: Path) -> list[StagedRecording]:
    staged: list[StagedRecording] = []
    for item in sorted(golden_dir.glob("*/staged.json")):
        data = json.loads(item.read_text(encoding="utf-8"))
        staged.append(
            StagedRecording(
                data["key"],
                data["recording"],
                sorted((item.parent / "blobs").iterdir()),
                data.get("environment"),
            )
        )
    return staged


def complete(staged: list[StagedRecording]) -> bool:
    sessions = {
        s.recording["session_id"] for s in staged if s.recording["condition"] == SEPARATE_SESSION
    }
    has_k = any(s.recording["condition"] == K_TIMES_SAMPLES for s in staged)
    return len(sessions) >= 2 and has_k


def staging_dir(work: Path, job: Job) -> Path:
    return ensure_outside_repository(work) / "iray-staging" / job.golden_id.replace("/", "__")


def reference_needed(job: Job, condition: str, work: Path) -> bool:
    """Whether a series run still has to record `condition` for this golden: not once the
    golden is admitted (its manifest names private records), nor once its staging holds two
    separate sessions (`separate_session`) or a k*S reference (`k_times_samples`)."""
    if job.manifest.get("private_records"):
        return False
    staged = load_staged(staging_dir(work, job))
    if condition == SEPARATE_SESSION:
        sessions = {
            s.recording["session_id"]
            for s in staged
            if s.recording["condition"] == SEPARATE_SESSION
        }
        return len(sessions) < 2
    return not any(s.recording["condition"] == condition for s in staged)


def restart_render(session: PainterSession, render_state: dict[str, Any]) -> None:
    """Nudge the field of view and put it back (documented camera API); Iray restarts. The
    render state read back afterwards must equal the first (read before the switch to
    Visualisation, so the mode is compared separately), or the second render is refused."""
    field_of_view = render_state["camera.field_of_view"]
    for value in (field_of_view + NUDGE_DEGREES, field_of_view):
        session.call("apply_step", step=0, call=ps.CAMERA + "field_of_view", args={"value": value})
    restored = session.call("render_state")
    restored["scene_bounding_box"] = session.call("scene_bounding_box")
    mode = restored.pop("ui_mode", None)
    first = {name: value for name, value in render_state.items() if name != "ui_mode"}
    if restored != first or mode != "Visualisation":
        raise RecorderError(
            "the render state after the same-session restart differs from the first render's: "
            "second render refused"
        )


def record_iray_reference(
    session: PainterSession,
    job: Job,
    condition: str,
    operator: Operator,
    work: Path,
    inbox: Path,
    k: int | None = None,
    now: Now = utc_now,
    *,
    operator_id: str = UNKNOWN,
    session_files: Sequence[Path] = (),
) -> Path | None:
    """Record one Iray reference; returns the inbox run once the golden is complete, else None.

    Every reference stages its session's environment record with `operator_id`; the references
    of one golden must share one envelope (decision 034 (a)), else assembly is refused.
    `session_files` are the files that session-environment steps name by SHA-256 (the
    `ref_match` HDRI, which stays outside the repository).

    A sheet that names a display transform belongs to the fixed pipeline, which is OCIO colour
    managed (decision 038): a Painter started without `OCIO` would render a Legacy project whose
    background reads the same 89,89,89, so the mode is checked before anything is recorded."""
    if job.tier != "3":
        raise RecorderError("Iray references are Tier 3 goldens")
    if job.exports or job.export_probes or job.api_captures:
        raise RecorderError("a Tier 3 job captures with Save Render, not texture exports")
    sheet = settings_sheet(job)
    mesh_id = mesh_input(job)
    if condition in (SEPARATE_SESSION, SAME_SESSION):
        samples = sheet.samples
    elif condition == K_TIMES_SAMPLES:
        if k is None or k <= 1:
            raise RecorderError("the k_times_samples reference needs an integer k > 1")
        samples = k * sheet.samples
    else:
        raise RecorderError(
            f"condition must be {SEPARATE_SESSION}, {K_TIMES_SAMPLES} or {SAME_SESSION}"
        )
    identity = session.connect()
    if sheet.display_transform is not None and identity.colour_management.get("mode") != "ocio":
        close_quietly(session)
        raise RecorderError(
            f"the sheet names the display transform {sheet.display_transform!r} of the fixed "
            "pipeline, which is OCIO colour managed: start Painter with OCIO naming its "
            f"resources/ocio/substance/config.ocio (found {identity.colour_management!r})"
        )
    golden_dir = staging_dir(work, job)
    for prior in load_staged(golden_dir):
        if prior.recording["session_id"] == identity.session_id:
            raise RecorderError(
                "this Painter session already recorded a reference of this golden: restart "
                "Painter (references are recorded in separate sessions)"
            )
        if condition == SAME_SESSION and prior.recording["condition"] == SAME_SESSION:
            raise RecorderError("this golden already holds its same-session renders")
    directory = ensure_outside_repository(work) / "iray" / job.golden_id.replace("/", "__")
    directory = directory / run_name(identity.session_id, now())
    staged_inputs = stage_inputs(job, directory / "inputs")
    staged_inputs |= stage_session_files(job, list(session_files), directory / "session-files")
    try:
        defaults = replay(session, job, staged_inputs)
        render_state = session.call("render_state")
        render_state["scene_bounding_box"] = session.call("scene_bounding_box")
        silhouette = expected_silhouette(
            staged_inputs[mesh_id], render_state, sheet, directory / "verification"
        )
        switched = session.call("switch_mode", mode="Visualisation")
        if switched["mode"] != "Visualisation":
            raise RecorderError(f"Painter stayed in {switched['mode']} mode")
        operator_outputs, evidence, images = operator_form(operator, sheet, samples, directory)
        renders = [convergence(operator, sheet, samples)]
        captures = [capture_render(operator, sheet, directory, silhouette)]
        if condition == SAME_SESSION:
            for index in range(2, SAME_SESSION_RENDERS + 1):
                restart_render(session, render_state)
                renders.append(convergence(operator, sheet, samples))
                repeat = directory / f"render-{index}"
                captures.append(capture_render(operator, sheet, repeat, silhouette))
    finally:
        close_quietly(session)
    key = {
        "inputs": job.input_hashes(),
        "instruction_sequence_sha256": job.instruction_sequence_sha256,
        "effective_defaults": defaults,
        "painter_build": identity.painter_build(),
        "project_settings": {
            "create": job.project_settings(),
            "colour_management": defaults["colour_management"],
        },
        "resource_hashes": [
            {"resource": input_id, "sha256": sha256_file(path)}
            for input_id, path in sorted(staged_inputs.items())
        ],
        "bake_backend": None,
        "render_state": render_state,
    }
    prefix = "k" if condition == K_TIMES_SAMPLES else "s"
    environment = (
        None
        if identity.environment is None
        else {**identity.environment, "operator_id": operator_id}
    )
    for index, (converged, (reference, render_file)) in enumerate(
        zip(renders, captures, strict=True), start=1
    ):
        recording_id = f"{prefix}-{slug(identity.session_id)[:12]}"
        if condition == SAME_SESSION:
            recording_id += f"-{index}"
        recording = {
            "recording_id": recording_id,
            "condition": condition,
            "session_id": identity.session_id,
            "recorded_at": now().isoformat(),
            "outputs": [
                {
                    "output_id": "render/reference",
                    "kind": "iray_reference",
                    **reference,
                    "samples": samples,
                    "convergence": converged,
                    "capture_route": "save_render",
                    "settings_sheet_sha256": sheet.sha256,
                    "operator_settings_output_id": "operator/settings",
                    "current_frame_verified": True,
                    "uncontrolled_settings": list(job.manifest.get("uncontrolled_settings", [])),
                },
                *operator_outputs,
                *evidence,
            ],
        }
        stage(golden_dir / recording_id, key, recording, [render_file, *images], environment)
    staged = load_staged(golden_dir)
    if not complete(staged):
        return None
    keys = {sha256_bytes(canonical_json(s.key)) for s in staged}
    if len(keys) != 1:
        raise RecorderError(
            "staged references disagree on the golden key (inputs, defaults, build or render "
            "state differ between sessions): oracle instability, not assembled"
        )
    record = {
        "schema": "uzpainter/parity/golden-private/1",
        "record_class": "private_oracle_record",
        "golden_id": job.golden_id,
        "tier": "3",
        "key": staged[0].key,
        "recordings": [s.recording for s in staged],
    }
    environments = [s.environment for s in staged]
    if any(envelope_match(environments[0], other) == DIFFERS for other in environments[1:]):
        raise RecorderError(
            "staged references were recorded under different envelopes (build, GPU, driver, OS "
            "or colour configuration differ): not assembled"
        )
    run = write_run(
        inbox,
        record,
        [b for s in staged for b in s.blobs],
        job.manifest,
        identity.session_id,
        environment=environments[0],
    )
    shutil.rmtree(golden_dir)
    return run
