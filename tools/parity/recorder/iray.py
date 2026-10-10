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
   the fixture's authored silhouette mask (input `silhouette`).
5. The recording is staged in the private work directory. When two `separate_session`
   references (different Painter processes) and one `k_times_samples` reference with identical
   keys are staged, the private record and the public manifest are written to the inbox.

The procedure is qualified by `phase0.9_render-reference-capture` before any render golden is
admitted (14-parity-testing.md §2); until then the recorder only produces candidates.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

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

IRAY_PANEL = "Iray Settings"
MIN_SAMPLE = f"{IRAY_PANEL}/Min Sample"
MAX_SAMPLE = f"{IRAY_PANEL}/Max Sample"
MAX_TIME = f"{IRAY_PANEL}/Max Time"
WIDTH = f"{IRAY_PANEL}/Width"
HEIGHT = f"{IRAY_PANEL}/Height"
CAPTURE_ENCODING = "capture.encoding"
SILHOUETTE_INPUT = "silhouette"
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


def settings_sheet(job: Job) -> SettingsSheet:
    manifest = job.manifest
    panel: list[PanelSetting] = []
    capture_encoding: str | None = None
    for setting in manifest["applied_settings"]:
        if setting["name"] == CAPTURE_ENCODING:
            capture_encoding = str(setting["value"])
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
        capture_encoding=capture_encoding,
        sha256=sha256_bytes(canonical_json(sheet)),
    )


def same_value(entered: str, expected: float | int | str | bool) -> bool:
    if isinstance(expected, bool):
        return entered.lower() in (("true", "on", "yes") if expected else ("false", "off", "no"))
    if isinstance(expected, int | float):
        try:
            return float(entered) == float(expected)
        except ValueError:
            return False
    return entered == expected


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
    if SILHOUETTE_INPUT not in job.inputs:
        raise RecorderError(f"current-frame verification needs a {SILHOUETTE_INPUT!r} mask input")
    sheet = settings_sheet(job)
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
        switched = session.call("switch_mode", mode="Visualisation")
        if switched["mode"] != "Visualisation":
            raise RecorderError(f"Painter stayed in {switched['mode']} mode")
        operator_outputs, evidence, images = operator_form(operator, sheet, samples, directory)
        converged = convergence(operator, sheet, samples)
        reference, render_file = capture_render(
            operator, sheet, directory, staged_inputs[SILHOUETTE_INPUT]
        )
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
            if input_id != SILHOUETTE_INPUT
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
