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

The sheet names the procedure version (`capture.procedure`, `PROCEDURE_VERSION`) and the pixel
route (`capture.route`); the qualified procedure and its answers are
`parity/reports/phase0/iray-capture-procedure.md` (task `phase0.6_render-reference-procedure`).
"""

from __future__ import annotations

import json
import shutil
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
from tools.parity.recorder.job import Job, canonical_json, sha256_bytes, sha256_file
from tools.parity.recorder.output import ensure_outside_repository, run_name, slug, write_run
from tools.parity.recorder.session import PainterSession, RecorderError
from tools.parity.recorder.texture import Now, close_quietly, replay, stage_inputs, utc_now
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
PROCEDURE_VERSION = "iray-capture/1"
SAVE_RENDER = "save_render"
TIME_UNITS = {"s": 1.0, "min": 60.0, "h": 3600.0}
PANEL_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
SEPARATE_SESSION = "separate_session"
K_TIMES_SAMPLES = "k_times_samples"


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
    for panel in sorted({s.panel for s in sheet.panel_settings}):
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
    check_silhouette(target, silhouette)
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


def stage(
    directory: Path, key: dict[str, Any], recording: dict[str, Any], blobs: list[Path]
) -> None:
    blob_dir = directory / "blobs"
    blob_dir.mkdir(parents=True)
    for blob in blobs:
        shutil.copyfile(blob, blob_dir / sha256_file(blob))
    (directory / "staged.json").write_text(
        json.dumps({"key": key, "recording": recording}, indent=2), encoding="utf-8"
    )


def load_staged(golden_dir: Path) -> list[StagedRecording]:
    staged: list[StagedRecording] = []
    for item in sorted(golden_dir.glob("*/staged.json")):
        data = json.loads(item.read_text(encoding="utf-8"))
        staged.append(
            StagedRecording(
                data["key"], data["recording"], sorted((item.parent / "blobs").iterdir())
            )
        )
    return staged


def complete(staged: list[StagedRecording]) -> bool:
    sessions = {
        s.recording["session_id"] for s in staged if s.recording["condition"] == SEPARATE_SESSION
    }
    has_k = any(s.recording["condition"] == K_TIMES_SAMPLES for s in staged)
    return len(sessions) >= 2 and has_k


def record_iray_reference(
    session: PainterSession,
    job: Job,
    condition: str,
    operator: Operator,
    work: Path,
    inbox: Path,
    k: int | None = None,
    now: Now = utc_now,
) -> Path | None:
    """Record one Iray reference; returns the inbox run once the golden is complete, else None."""
    if job.tier != "3":
        raise RecorderError("Iray references are Tier 3 goldens")
    if job.exports:
        raise RecorderError("a Tier 3 job captures with Save Render, not texture exports")
    sheet = settings_sheet(job)
    mesh_id = mesh_input(job)
    if condition == SEPARATE_SESSION:
        samples = sheet.samples
    elif condition == K_TIMES_SAMPLES:
        if k is None or k <= 1:
            raise RecorderError("the k_times_samples reference needs an integer k > 1")
        samples = k * sheet.samples
    else:
        raise RecorderError(f"condition must be {SEPARATE_SESSION} or {K_TIMES_SAMPLES}")
    identity = session.connect()
    golden_dir = ensure_outside_repository(work) / "iray-staging" / job.golden_id.replace("/", "__")
    for prior in load_staged(golden_dir):
        if prior.recording["session_id"] == identity.session_id:
            raise RecorderError(
                "this Painter session already recorded a reference of this golden: restart "
                "Painter (references are recorded in separate sessions)"
            )
    directory = ensure_outside_repository(work) / "iray" / job.golden_id.replace("/", "__")
    directory = directory / run_name(identity.session_id, now())
    staged_inputs = stage_inputs(job, directory / "inputs")
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
        converged = convergence(operator, sheet, samples)
        reference, render_file = capture_render(operator, sheet, directory, silhouette)
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
            for input_id, path in sorted(job.inputs.items())
        ],
        "bake_backend": None,
        "render_state": render_state,
    }
    prefix = "k" if condition == K_TIMES_SAMPLES else "s"
    recording_id = f"{prefix}-{slug(identity.session_id)[:12]}"
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
    stage(golden_dir / recording_id, key, recording, [render_file, *images])
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
    run = write_run(
        inbox,
        record,
        [b for s in staged for b in s.blobs],
        job.manifest,
        identity.session_id,
    )
    shutil.rmtree(golden_dir)
    return run
