"""R-322 TGA8 diagnostics from authored inputs; no production export or preset acceptance.

Oracle TGA bytes are comparison targets only. The native candidate receives an authored
project spec and one inline PNG8 map, then encodes its own samples as TGA. Even an exact
diagnostic comparison leaves the complete preset blocked by its unresolved own defaults.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import struct
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from python.uzpainter_facade.bitmap_defaults import (
    DefaultContext,
    describe_png,
    lookup,
    native_tag,
)
from tests.evaluator.masks_fits import spec_from_steps
from tests.export.conftest import REPO_ROOT
from tests.export.encoders_tier0 import OCIO_CONFIG_SHA256
from tests.export.tier0 import export_spec
from tools.parity import tga
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder.output import slug
from tools.parity.recorder.texture import output_safe
from tools.parity.store.store import OracleStore, Status, locate, resolve_oracle

MODEL = "native-png8-processing-candidate"
CONFIG_ID = "probe-presets-unreal-packed-bevelled-cube-unreal-tga8"
TEXTURE_SET = "uzp_bevelled_cube"
MAPS = ("basecolor", "emissive", "normal", "occlusionroughnessmetallic")
SESSIONS = ("legacy", "ocio")
STEPS = {"legacy": (54, 55), "ocio": (56, 57)}
PRESET_URL = "resource://starter_assets/Unreal Engine (Packed)?version=8339356058946582545.spexp"
PARAMETERS = {
    "fileFormat": "tga",
    "bitDepth": "8",
    "dithering": False,
    "paddingAlgorithm": "infinite",
}


class SetupFailure(RuntimeError):
    """A malformed experiment, protocol or input; never a measured difference or refusal."""


def valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= set("0123456789abcdef")


@dataclass(frozen=True)
class Target:
    session: str
    recording: str
    step: int
    map_name: str
    reference: dict[str, Any]

    @property
    def filename(self) -> str:
        return str(self.reference["record_id"]).removeprefix(
            f"{self.recording}-probe-s{self.step}-"
        )

    @property
    def label(self) -> str:
        return f"{self.session}/{self.recording}/s{self.step}/{self.map_name}"


def public_manifest(session: str) -> dict[str, Any]:
    if session not in SESSIONS:
        raise SetupFailure("unknown colour session")
    path = (
        manifest_root(current_envelope())
        / "tier0/semantics"
        / f"export-presets-unreal-packed-{session}.json"
    )
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return result


def targets(manifest: dict[str, Any], session: str) -> list[Target]:
    if (
        session not in SESSIONS
        or manifest.get("golden_id") != f"tier0/semantics/export-presets-unreal-packed-{session}"
    ):
        raise SetupFailure("manifest identity mismatch")
    selected = [
        step["step"]
        for step in manifest["instruction_sequence"]["steps"]
        if step["call"] == "substance_painter.export.list_project_textures"
        and step["args"].get("config") == CONFIG_ID
    ]
    if tuple(selected) != STEPS[session]:
        raise SetupFailure("TGA probe selection changed")
    references = manifest["private_records"]
    by_id = {reference["record_id"]: reference for reference in references}
    if len(by_id) != len(references):
        raise SetupFailure("duplicate oracle reference")
    result = []
    for recording in ("r1", "r2"):
        for step in selected:
            for map_name in MAPS:
                prefix = f"{recording}-probe-s{step}-bevelled-cube_{TEXTURE_SET}_{map_name}"
                matches = [
                    ref
                    for key, ref in by_id.items()
                    if key == prefix + ".tga"
                    or (key.startswith(prefix + "_") and key.endswith(".tga"))
                ]
                reference = matches[0] if len(matches) == 1 else None
                if not isinstance(reference, dict) or reference.get("kind") != "exported_map":
                    raise SetupFailure("missing TGA oracle reference")
                if (
                    not valid_sha256(reference.get("sha256"))
                    or type(reference.get("size_bytes")) is not int
                    or reference["size_bytes"] <= 0
                ):
                    raise SetupFailure("invalid TGA oracle identity")
                result.append(Target(session, recording, step, map_name, reference))
    if {key for key in by_id if key.endswith(".tga")} != {t.reference["record_id"] for t in result}:
        raise SetupFailure("unexpected TGA oracle reference")
    return result


def authored_inputs(manifest: dict[str, Any]) -> dict[str, Path]:
    result = {}
    for entry in manifest["inputs"]:
        path = (REPO_ROOT / entry["path"]).resolve()
        if not path.is_relative_to(REPO_ROOT.resolve()) or not path.is_file():
            raise SetupFailure("authored input path is invalid")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise SetupFailure("authored input hash mismatch")
        if entry["input_id"] in result:
            raise SetupFailure("duplicate authored input")
        result[entry["input_id"]] = path
    return result


def candidate_config(recipe: dict[str, Any], map_name: str, directory: Path) -> dict[str, Any]:
    if (
        recipe.get("defaultExportPreset") != PRESET_URL
        or recipe.get("exportShaderParams") is not False
        or recipe.get("exportList") != [{"rootPath": TEXTURE_SET}]
        or recipe.get("exportParameters") != [{"parameters": PARAMETERS}]
        or map_name not in MAPS
    ):
        raise SetupFailure("explicit TGA recipe preconditions changed")
    # This shipped, hand-authored layout remains a hypothesis. Its provenance is not changed.
    layout = json.loads((REPO_ROOT / "assets/export-presets/unreal-engine-packed.json").read_text())
    maps = [m for m in layout["maps"] if m["fileName"].rsplit("_", 1)[-1].lower() == map_name]
    if len(maps) != 1:
        raise SetupFailure("candidate layout does not name exactly one map")
    mapping = deepcopy(maps[0])
    mapping["fileName"] = "candidate"
    mapping["parameters"] = {**PARAMETERS, "fileFormat": "png"}
    return {
        "exportShaderParams": False,
        "exportPath": directory.as_posix(),
        "defaultExportPreset": "tga-processing-candidate",
        "exportPresets": [{"name": "tga-processing-candidate", "maps": [mapping]}],
        "exportList": [{"rootPath": TEXTURE_SET}],
        "exportParameters": [{"parameters": {**PARAMETERS, "fileFormat": "png"}}],
    }


def channel_aliases() -> dict[str, str]:
    path = REPO_ROOT / "python/uzpainter_facade/textureset.py"
    assignments = [
        node
        for node in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_CHANNEL_ALIASES"
            for target in node.targets
        )
    ]
    if len(assignments) != 1:
        raise SetupFailure("channel alias declaration is ambiguous")
    aliases = ast.literal_eval(assignments[0].value)
    if not isinstance(aliases, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in aliases.items()
    ):
        raise SetupFailure("channel alias declaration is invalid")
    return aliases


def r322_spec(manifest: dict[str, Any], work: Path) -> dict[str, Any]:
    inputs = authored_inputs(manifest)
    canonical_manifest = deepcopy(manifest)
    steps = canonical_manifest["instruction_sequence"]["steps"]
    creates = [s["args"] for s in steps if s["call"] == "substance_painter.project.create"]
    if len(creates) != 1:
        raise SetupFailure("project creation is ambiguous")
    create = creates[0]
    if (
        create.get("default_texture_resolution") != 256
        or create.get("normal_map_format") != "OpenGL"
    ):
        raise SetupFailure("R-322 geometry settings changed")
    templates = [
        json.loads(path.read_text()) for path in (REPO_ROOT / "assets/templates").glob("*.json")
    ]
    selected = [
        t
        for t in templates
        if t.get("kind") == "project" and t.get("painter_template") == create.get("template")
    ]
    if len(selected) != 1:
        raise SetupFailure("project template is ambiguous")
    template = selected[0]
    aliases = channel_aliases()
    for step in steps:
        args = step["args"]
        if "channel" in args:
            args["channel"] = aliases.get(args["channel"], args["channel"])
        if "channels" in args:
            args["channels"] = [aliases.get(channel, channel) for channel in args["channels"]]
    explicit_modes: set[tuple[int, str | None]] = set()
    for step in steps:
        args = step["args"]
        channel = args.get("channel")
        key = (args.get("node_step", -1), aliases.get(channel, channel))
        if step["call"].endswith(".set_blending_mode"):
            explicit_modes.add(key)
        elif step["call"].endswith(".set_opacity") and key not in explicit_modes:
            raise SetupFailure("opacity-only edits need explicit replay modelling")
    channels: dict[str, str] = {}
    declarations = [{"channel": c["type"], "format": c["format"]} for c in template["channels"]]
    declarations += [s["args"] for s in steps if s["call"].endswith("Stack.add_channel")]
    for declaration in declarations:
        name = aliases.get(declaration["channel"], declaration["channel"])
        if name in channels:
            raise SetupFailure("duplicate canonical channel declaration")
        channels[name] = declaration["format"]
    settings = {s["name"]: s["value"] for s in canonical_manifest["applied_settings"]}
    if (
        settings.get("texture_set.resolution") != 256
        or settings.get("project.normal_map_format") != "OpenGL"
    ):
        raise SetupFailure("applied project settings disagree")
    if "OCIO" in settings:
        if settings["OCIO"] != "resources/ocio/substance/config.ocio":
            raise SetupFailure("unrecognised authored colour profile")
        profile, config_hash = "ocio", OCIO_CONFIG_SHA256
    else:
        profile, config_hash = "legacy", None

    def resolve_default(channel: str | None, png: bytes) -> str:
        if channel is None or channel not in channels:
            raise SetupFailure("default resolver received an undeclared channel")
        context = DefaultContext(
            profile=profile,
            config_sha256=config_hash,
            template_id=template["id"],
            channel=channel,
            channel_format=channels[channel],
        )
        identity = lookup(context, describe_png(png))
        if identity is None:
            raise SetupFailure("R-322 bitmap default is outside the recorded policy domain")
        return native_tag(identity, profile)

    spec = export_spec(
        canonical_manifest, TEXTURE_SET, work, bitmap_default_resolver=resolve_default
    )
    spec.update(
        template=template["id"],
        channels=[{"type": k, "format": v} for k, v in channels.items()],
        mesh=str(inputs[create["mesh"]]),
        normal_map_format=create["normal_map_format"],
        color_management=profile,
    )
    if config_hash is not None:
        spec["config_hash"] = config_hash
    for layer in spec["layers"]:
        if layer["kind"] != "fill" or layer.get("effects") or layer.get("mask"):
            raise SetupFailure("R-322 layer reconstruction is outside the authored domain")
        for field in ("sources", "blending"):
            original = layer.get(field, {})
            canonical = {aliases.get(k, k): v for k, v in original.items()}
            if len(canonical) != len(original) or not canonical.keys() <= channels.keys():
                raise SetupFailure("layer channel references are invalid")
            layer[field] = canonical
        if "active_channels" in layer:
            active = [aliases.get(k, k) for k in layer["active_channels"]]
            if len(set(active)) != len(active) or not set(active) <= channels.keys():
                raise SetupFailure("active channel references are invalid")
            layer["active_channels"] = active
    resources = {r["sha256"] for r in spec["resources"]}
    if not set(spec["mesh_maps"].values()) <= resources:
        raise SetupFailure("mesh map references are invalid")
    return spec


def oracle_bytes(store: OracleStore | None, reference: dict[str, Any]) -> bytes | None:
    resolved = resolve_oracle(store, reference)
    if resolved.status != Status.AVAILABLE or resolved.path is None:
        return None
    data = resolved.path.read_bytes()
    if (
        len(data) != reference["size_bytes"]
        or hashlib.sha256(data).hexdigest() != reference["sha256"]
    ):
        raise SetupFailure("oracle changed after verification")
    return data


def verify_record(manifest: dict[str, Any], selected: list[Target], data: bytes) -> None:
    record = json.loads(data)
    recordings = {r["recording_id"]: r for r in record["recordings"]}
    if set(recordings) != {"r1", "r2"} or len(record["recordings"]) != 2:
        raise SetupFailure("oracle recording identities changed")
    for target in selected:
        recording = recordings[target.recording]
        condition = "same_session" if target.recording == "r1" else "after_save_reopen"
        if recording.get("condition") != condition:
            raise SetupFailure("oracle recording condition changed")
        outputs = {o["output_id"]: o for o in recording["outputs"]}
        if len(outputs) != len(recording["outputs"]):
            raise SetupFailure("duplicate oracle output")
        matches = [
            output
            for output_id, output in outputs.items()
            if f"{slug(recording['recording_id'])}-{slug(output_id)}"
            == target.reference["record_id"]
        ]
        if len(matches) != 1:
            raise SetupFailure("oracle reference does not identify exactly one output")
        output = matches[0]
        if (
            not isinstance(output, dict)
            or output.get("kind") != "exported_map"
            or not isinstance(output.get("map"), str)
            or output["output_id"] != f"probe/s{target.step}/{output_safe(output['map'])}"
            or output.get("export_settings", {}).get("step") != target.step
            or any(
                output.get("blob", {}).get(key) != target.reference[key]
                for key in ("sha256", "size_bytes")
            )
        ):
            raise SetupFailure("oracle map reference does not match its probe")


def run_candidate(
    exe: Path, spec: Path, config: Path, output: Path, diagnostics: list[Any]
) -> dict[str, Any]:
    problem = ""
    report: Any = None
    try:
        process = subprocess.run(
            [
                str(exe),
                "tga-processing-candidate",
                str(REPO_ROOT / "assets/templates"),
                str(spec),
                str(config),
                str(output),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        diagnostics.append(
            {"stdout": process.stdout, "stderr": process.stderr, "returncode": process.returncode}
        )
        if process.returncode != 0:
            problem = "native candidate exited unsuccessfully"
        else:
            report = json.loads(process.stdout)
            if not isinstance(report, dict):
                problem = "native candidate returned invalid JSON shape"
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        diagnostics.append({"error_type": type(error).__name__, "error": str(error)})
        problem = "native candidate transport failed"
    if problem:
        raise SetupFailure(problem)
    result: dict[str, Any] = report
    return result


def new_replay_report() -> dict[str, Any]:
    """Progress survives failure; returned candidates and classified targets are not successes."""
    return {
        "model": MODEL,
        "global_status": "blocked",
        "preset_status": "blocked",
        "reason": "unresolved-own-defaults",
        "execution_status": "running",
        "complete": False,
        "stage": "setup",
        "attempted_candidates": 0,
        "candidate_runs": 0,
        "classified_targets": 0,
        "maps": [],
    }


def replay_targets(
    exe: Path,
    work: Path,
    store: OracleStore | None,
    diagnostics: list[Any],
    *,
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = {} if report is None else report
    report.update(new_replay_report())
    rows: list[dict[str, Any]] = []
    report["maps"] = rows
    for session in SESSIONS:
        report.update(stage="load_public_manifest", session=session, map=None, target=None)
        manifest = public_manifest(session)
        selected = targets(manifest, session)
        report["stage"] = "authored_inputs"
        inputs = authored_inputs(manifest)
        recipe = json.loads(inputs[CONFIG_ID].read_text())
        record_ref = next(
            r for r in manifest["private_records"] if r["record_id"] == "golden-record"
        )
        report["stage"] = "oracle_record"
        record = oracle_bytes(store, record_ref)
        if record is None:
            rows.extend(
                {
                    "id": t.label,
                    "status": "blocked",
                    "reason": "oracle-unavailable",
                    "diagnostic_pixels": "blocked",
                }
                for t in selected
            )
            report["classified_targets"] = len(rows)
            continue
        report["stage"] = "verify_record"
        verify_record(manifest, selected, record)
        report["stage"] = "reconstruct_spec"
        spec = r322_spec(manifest, work)
        spec_path = work / f"tga-{session}-spec.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        # One native evaluation per authored session/map; compare all four independent targets.
        for map_name in MAPS:
            report.update(stage="prepare_candidate", map=map_name, target=None)
            report.pop("native_stage", None)
            config_path = work / f"tga-{session}-{map_name}-candidate.json"
            config_path.write_text(
                json.dumps(candidate_config(recipe, map_name, work)), encoding="utf-8"
            )
            output_path = work / f"tga-{session}-{map_name}.tga"
            report["stage"] = "run_candidate"
            report["attempted_candidates"] += 1
            native = run_candidate(exe, spec_path, config_path, output_path, diagnostics)
            report["candidate_runs"] += 1
            native_stage = native.get("stage")
            if isinstance(native_stage, str) and native_stage in {
                "parse_spec",
                "compile_plan",
                "encode_export",
                "decode_png",
                "encode_tga",
                "write_tga",
            }:
                report["native_stage"] = native_stage
            report["stage"] = "read_candidate"
            data = output_path.read_bytes() if output_path.is_file() else None
            for target in (t for t in selected if t.map_name == map_name):
                report.update(stage="read_oracle_target", target=target.label)
                recorded = oracle_bytes(store, target.reference)
                report["stage"] = "classify_candidate"
                comparison = classify(native, data, recorded)
                rows.append(
                    {"id": target.label, "oracle_sha256": target.reference["sha256"], **comparison}
                )
                report["classified_targets"] = len(rows)
    report["stage"] = "coverage"
    if len(rows) != 32 or len({row["id"] for row in rows}) != 32:
        raise SetupFailure("incomplete TGA comparison coverage")
    report.update(stage="complete", execution_status="completed", complete=True)
    return report


def test_r322_tga_capture_diagnostic(export_tests: Path, tmp_path: Path) -> None:
    diagnostics: list[Any] = []
    report = new_replay_report()
    problem = ""
    try:
        replay_targets(export_tests, tmp_path, locate(), diagnostics, report=report)
    except Exception as error:
        diagnostics.append({"error_type": type(error).__name__, "error": str(error)})
        report.update(
            execution_status="failed", complete=False, failure_code="tga_diagnostic_failed"
        )
        problem = "TGA diagnostic setup or execution failed"
    saved = False
    try:
        path = Path(os.environ["LOCALAPPDATA"]) / "UzPainter/tga-capture-replay-private.json"
        path.write_text(
            json.dumps({"report": report, "diagnostics": diagnostics}, indent=1), encoding="utf-8"
        )
        saved = True
    except (OSError, KeyError, TypeError, ValueError):
        pass
    if problem or not saved:
        pytest.fail(problem or "TGA diagnostic private report could not be saved", pytrace=False)
    counts = {
        status: sum(row["status"] == status for row in report["maps"])
        for status in ("exact", "different", "blocked")
    }
    print("TGA diagnostic:", json.dumps(counts, sort_keys=True), "global=blocked preset=blocked")


def compare_tga(recorded: bytes, candidate: bytes) -> dict[str, Any]:
    expected, actual = tga.decode(recorded), tga.decode(candidate)
    result: dict[str, Any] = {
        "file_equal": recorded == candidate,
        "shape_equal": expected.shape == actual.shape,
        "expected_shape": list(expected.shape),
        "candidate_shape": list(actual.shape),
    }
    if expected.shape != actual.shape:
        return {**result, "diagnostic_pixels": "different", "reason": "shape-or-alpha"}
    delta = np.abs(expected.astype(np.int64) - actual.astype(np.int64))
    different = delta != 0
    return {
        **result,
        "diagnostic_pixels": "different" if np.any(different) else "exact",
        "differing_samples": int(np.count_nonzero(different)),
        "differing_texels": int(np.count_nonzero(np.any(different, axis=2))),
        "max_abs": int(delta.max()),
        "mean_abs": float(delta.mean()),
        "p99_abs": float(np.percentile(delta, 99)),
    }


def classify(
    report: dict[str, Any], candidate: bytes | None, recorded: bytes | None
) -> dict[str, Any]:
    if report.get("model") != MODEL or report.get("non_conformant") is not True:
        raise SetupFailure("candidate model identity mismatch")
    if report.get("blocked") is True:
        if (
            report.get("error") != "NotYetSupported"
            or report.get("reason_code") != "compile_plan_not_yet_supported"
            or report.get("stage") != "compile_plan"
            or not isinstance(report.get("message"), str)
            or candidate is not None
        ):
            raise SetupFailure("native candidate setup failed")
        return {
            "status": "blocked",
            "reason": report["reason_code"],
            "stage": report["stage"],
            "diagnostic_pixels": "blocked",
        }
    if set(report) & {
        "error",
        "message",
        "stage",
        "reason_code",
        "code",
        "eval_kind",
        "eval_class",
    }:
        raise SetupFailure("native candidate reported failure with success metadata")
    metadata = report.get("tga")
    if (
        not isinstance(metadata, dict)
        or candidate is None
        or not isinstance(report.get("bypassed"), list)
        or any(not isinstance(reason, str) for reason in report["bypassed"])
        or type(report.get("undecided")) is not int
        or report["undecided"] < 0
        or not valid_sha256(report.get("png8_sha256"))
        or any(
            type(metadata.get(key)) is not int or metadata[key] <= 0
            for key in ("size", "height", "width", "channels")
        )
    ):
        raise SetupFailure("malformed native candidate result")
    if metadata.get("sha256") != hashlib.sha256(candidate).hexdigest() or metadata.get(
        "size"
    ) != len(candidate):
        raise SetupFailure("native candidate file identity mismatch")
    decoded = tga.decode(candidate)
    if tuple(metadata.get(key) for key in ("height", "width", "channels")) != decoded.shape:
        raise SetupFailure("native candidate shape mismatch")
    if recorded is None:
        return {"status": "blocked", "reason": "oracle-unavailable", "diagnostic_pixels": "blocked"}
    comparison = compare_tga(recorded, candidate)
    blocked = bool(report["bypassed"] or report["undecided"])
    return {
        **comparison,
        "status": "blocked" if blocked else comparison["diagnostic_pixels"],
        "reason": "diagnostic-bypass" if blocked else "compared",
        "bypassed": report["bypassed"],
        "undecided": report["undecided"],
    }


def _authored_tga(channels: int = 3, top: bool = True, changed: bool = False) -> bytes:
    rows = bytes(range(1, 1 + 4 * channels))
    if changed:
        rows = bytes([rows[0] + 1]) + rows[1:]
    if not top:
        rows = rows[2 * channels :] + rows[: 2 * channels]
    # Authored BGR values; both sides use the same source ordering.
    descriptor = (32 if top else 0) | (8 if channels == 4 else 0)
    return (
        struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, 2, 2, channels * 8, descriptor) + rows
    )


def _authored_report(data: bytes, **changes: Any) -> dict[str, Any]:
    shape = tga.decode(data).shape
    return {
        "model": MODEL,
        "non_conformant": True,
        "png8_sha256": "0" * 64,
        "tga": {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "height": shape[0],
            "width": shape[1],
            "channels": shape[2],
        },
        "bypassed": [],
        "undecided": 0,
        **changes,
    }


def test_public_selection_has_32_tga_targets() -> None:
    selected = [
        target for session in SESSIONS for target in targets(public_manifest(session), session)
    ]
    assert len(selected) == len({t.label for t in selected}) == 32
    assert {t.map_name for t in selected} == set(MAPS)


def _authored_record() -> tuple[Target, dict[str, Any]]:
    map_name = "Authored_BaseColor.TGA"
    output_id = f"probe/s54/{output_safe(map_name)}"
    reference = {"record_id": f"r1-{slug(output_id)}", "sha256": "a" * 64, "size_bytes": 42}
    output = {
        "output_id": output_id,
        "kind": "exported_map",
        "map": map_name,
        "export_settings": {"step": 54},
        "blob": {"sha256": reference["sha256"], "size_bytes": reference["size_bytes"]},
    }
    return Target("legacy", "r1", 54, "basecolor", reference), {
        "recordings": [
            {"recording_id": "r1", "condition": "same_session", "outputs": [output]},
            {"recording_id": "r2", "condition": "after_save_reopen", "outputs": []},
        ]
    }


def test_verify_record_matches_forward_slug_without_recovering_casing() -> None:
    target, record = _authored_record()
    assert target.filename != record["recordings"][0]["outputs"][0]["map"]
    verify_record({}, [target], json.dumps(record).encode())


@pytest.mark.parametrize(
    "change", ["collision", "sha256", "size_bytes", "step", "map", "kind", "condition", "missing"]
)
def test_verify_record_rejects_ambiguous_or_inconsistent_output(change: str) -> None:
    target, record = _authored_record()
    recording = record["recordings"][0]
    output = recording["outputs"][0]
    if change == "collision":
        duplicate = deepcopy(output)
        duplicate["output_id"] = output["output_id"].lower()
        assert duplicate["output_id"] != output["output_id"]
        assert slug(duplicate["output_id"]) == slug(output["output_id"])
        recording["outputs"].append(duplicate)
    elif change in {"sha256", "size_bytes"}:
        output["blob"][change] = "b" * 64 if change == "sha256" else 43
    elif change == "step":
        output["export_settings"]["step"] = 55
    elif change == "map":
        output["map"] = output["map"].lower()
    elif change == "kind":
        output["kind"] = "api_readback"
    elif change == "condition":
        recording["condition"] = "after_save_reopen"
    else:
        recording["outputs"].clear()
    with pytest.raises(SetupFailure):
        verify_record({}, [target], json.dumps(record).encode())


@pytest.mark.parametrize("session", SESSIONS)
def test_r322_authoring_reconstructs_template_channels_and_aliases(
    session: str, tmp_path: Path
) -> None:
    spec = r322_spec(public_manifest(session), tmp_path)
    assert spec["template"] == (
        "default" if session == "ocio" else "pbr-metallic-roughness-alpha-blend"
    )
    channels = {c["type"] for c in spec["channels"]}
    assert len(channels) == 9
    assert {
        "BaseColor",
        "SpecularRoughness",
        "BaseMetalness",
        "Normal",
        "Height",
        "Opacity",
        "EmissionColor",
        "AO",
        "SpecularWeight",
    } == channels
    assert spec["normal_map_format"] == "OpenGL" and spec["resolution"] == [256, 256]
    assert spec["color_management"] == session
    assert all(set(channel) == {"type", "format"} for channel in spec["channels"])
    assert all(
        layer["blending"]["Height"] == {"mode": "Normal", "opacity": 1.0}
        for layer in spec["layers"]
    )
    assert all(
        layer["blending"]["Normal"] == {"mode": "Normal", "opacity": 1.0}
        for layer in spec["layers"]
    )
    assert all(set(layer["sources"]) <= channels for layer in spec["layers"])
    assert all(
        "Roughness" not in layer["sources"] and "Metallic" not in layer["sources"]
        for layer in spec["layers"]
    )


@pytest.mark.parametrize("change", ["step", "missing", "duplicate"])
def test_bad_public_selection_refuses(change: str) -> None:
    manifest = public_manifest("legacy")
    if change == "step":
        for step in manifest["instruction_sequence"]["steps"]:
            if step["args"].get("config") == CONFIG_ID:
                step["step"] += 100
    elif change == "missing":
        manifest["private_records"] = [
            r for r in manifest["private_records"] if not r["record_id"].endswith("basecolor.tga")
        ]
    else:
        manifest["private_records"].append(deepcopy(manifest["private_records"][0]))
    with pytest.raises(SetupFailure):
        targets(manifest, "legacy")


def test_candidate_uses_only_authored_map_and_explicit_processing(tmp_path: Path) -> None:
    inputs = authored_inputs(public_manifest("legacy"))
    recipe = json.loads(inputs[CONFIG_ID].read_text())
    candidate = candidate_config(recipe, "occlusionroughnessmetallic", tmp_path)
    mapping = candidate["exportPresets"][0]["maps"][0]
    assert mapping["channels"][0]["srcMapName"] == "AO_Mixed"
    assert mapping["parameters"] == {**PARAMETERS, "fileFormat": "png"}
    assert candidate["defaultExportPreset"] != PRESET_URL
    recipe["exportParameters"][0]["parameters"]["dithering"] = True
    with pytest.raises(SetupFailure):
        candidate_config(recipe, "basecolor", tmp_path)


def test_orientation_is_decoded_but_alpha_is_never_filled() -> None:
    comparison = compare_tga(_authored_tga(), _authored_tga(top=False))
    assert comparison["diagnostic_pixels"] == "exact" and not comparison["file_equal"]
    assert compare_tga(_authored_tga(), _authored_tga(4))["diagnostic_pixels"] == "different"


def test_residual_and_blocking_are_separate() -> None:
    expected, actual = _authored_tga(), _authored_tga(changed=True)
    assert classify(_authored_report(expected), expected, expected)["status"] == "exact"
    different = classify(_authored_report(actual), actual, expected)
    assert different["status"] == "different" and different["differing_samples"] == 1
    blocked = classify(
        _authored_report(actual, bypassed=["authored padding refusal"]), actual, expected
    )
    assert blocked["status"] == "blocked" and blocked["diagnostic_pixels"] == "different"
    assert classify(_authored_report(actual, undecided=1), actual, expected)["status"] == "blocked"
    assert classify(_authored_report(actual), actual, None)["status"] == "blocked"


def test_native_refusal_is_blocked_but_setup_error_fails() -> None:
    report = {
        "model": MODEL,
        "non_conformant": True,
        "blocked": True,
        "error": "NotYetSupported",
        "message": "authored refusal",
        "reason_code": "compile_plan_not_yet_supported",
        "stage": "compile_plan",
    }
    assert classify(report, None, None)["status"] == "blocked"
    with pytest.raises(SetupFailure):
        classify({**report, "error": "ValueError"}, None, None)


@pytest.mark.parametrize("field,value", [("sha256", "wrong"), ("size", 1), ("channels", 4)])
def test_native_file_identity_mismatch_fails(field: str, value: Any) -> None:
    data = _authored_tga()
    report = _authored_report(data)
    report["tga"][field] = value
    with pytest.raises(SetupFailure):
        classify(report, data, data)


@pytest.mark.parametrize("error", ["Failure", "ValueError", "InternalError"])
@pytest.mark.parametrize("bypassed", [False, True])
def test_failure_fields_never_become_a_comparison(error: str, bypassed: bool) -> None:
    data = _authored_tga()
    report = _authored_report(data, error=error, bypassed=["authored refusal"] if bypassed else [])
    with pytest.raises(SetupFailure):
        classify(report, data, data)
    with pytest.raises(SetupFailure):
        classify(report, data, None)


@pytest.mark.parametrize("change", ["duplicate", "opacity"])
def test_r322_unmodelled_channel_or_opacity_setup_refuses(change: str, tmp_path: Path) -> None:
    manifest = public_manifest("legacy")
    steps = manifest["instruction_sequence"]["steps"]
    if change == "duplicate":
        steps.append(
            {
                "step": 999,
                "call": "substance_painter.textureset.Stack.add_channel",
                "args": {"channel": "Roughness", "format": "L16"},
            }
        )
    else:
        steps.append(
            {
                "step": 999,
                "call": "substance_painter.layerstack.LayerNode.set_opacity",
                "args": {"node_step": 1, "opacity": 0.5},
            }
        )
    with pytest.raises(SetupFailure):
        r322_spec(manifest, tmp_path)


@pytest.mark.parametrize("adapter", ["export", "masks"])
@pytest.mark.parametrize("mode", ["default", "resolver", "explicit", "refusal"])
def test_bitmap_default_resolver_adapter_contract(adapter: str, mode: str, tmp_path: Path) -> None:
    source = next(i for i in public_manifest("legacy")["inputs"] if i["input_id"] == "field-a")
    data: dict[str, Any] = {
        "inputs": [source],
        "instruction_sequence": {
            "steps": [
                {"step": 1, "call": "substance_painter.project.create", "args": {}},
                {
                    "step": 2,
                    "call": "substance_painter.resource.import_project_resource",
                    "args": {"input": "field-a"},
                },
                {"step": 3, "call": "substance_painter.layerstack.insert_fill", "args": {}},
                {
                    "step": 4,
                    "call": "substance_painter.layerstack.FillLayerNode.set_source",
                    "args": {"node_step": 3, "channel": "BaseColor", "resource_step": 2},
                },
            ]
        },
    }
    if mode == "explicit":
        data["instruction_sequence"]["steps"][-1]["args"]["color_space"] = "authored-explicit"
    before = deepcopy(data)
    calls: list[tuple[str | None, bytes]] = []

    def resolve(channel: str | None, png: bytes) -> str:
        calls.append((channel, png))
        if mode == "refusal":
            raise SetupFailure("authored resolver refusal")
        return "authored-synthetic-default"

    def convert() -> dict[str, Any]:
        resolver = None if mode == "default" else resolve
        if adapter == "export":
            return export_spec(data, "authored", tmp_path, bitmap_default_resolver=resolver)
        return spec_from_steps(data, "authored", tmp_path, [], bitmap_default_resolver=resolver)

    if mode == "refusal":
        with pytest.raises(SetupFailure, match="authored resolver refusal"):
            convert()
    else:
        result = convert()
        expected = {
            "default": "sRGB",
            "resolver": "authored-synthetic-default",
            "explicit": "authored-explicit",
        }[mode]
        assert result["layers"][0]["sources"]["BaseColor"]["color_space"] == expected
    assert data == before
    assert calls == (
        [("BaseColor", (REPO_ROOT / source["path"]).read_bytes())]
        if mode in {"resolver", "refusal"}
        else []
    )


@pytest.mark.parametrize("failure", ["setup", "encode_export", "timeout", "none"])
def test_tga_progress_survives_failure_without_public_details(
    failure: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Synthetic oracle transport and native subprocess; no private store or binary is read."""
    marker = "AUTHORED_PRIVATE_ERROR_MARKER"
    candidate = _authored_tga()
    records: dict[str, bytes] = {}
    for session in SESSIONS:
        manifest = public_manifest(session)
        selected = targets(manifest, session)
        recordings = []
        for recording in ("r1", "r2"):
            outputs = [
                {
                    "output_id": f"probe/s{target.step}/{target.filename}",
                    "kind": "exported_map",
                    "map": target.filename,
                    "export_settings": {"step": target.step},
                    "blob": {key: target.reference[key] for key in ("sha256", "size_bytes")},
                }
                for target in selected
                if target.recording == recording
            ]
            recordings.append(
                {
                    "recording_id": recording,
                    "condition": "same_session" if recording == "r1" else "after_save_reopen",
                    "outputs": outputs,
                }
            )
        reference = next(
            r for r in manifest["private_records"] if r["record_id"] == "golden-record"
        )
        records[reference["sha256"]] = json.dumps({"recordings": recordings}).encode()

    def fake_oracle(store: OracleStore | None, reference: dict[str, Any]) -> bytes:
        return (
            records[reference["sha256"]] if reference["record_id"] == "golden-record" else candidate
        )

    def fake_locate() -> None:
        if failure == "setup":
            raise SetupFailure(marker)

    calls = 0

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 2 and failure == "timeout":
            raise subprocess.TimeoutExpired(command, 600, output=marker)
        if calls == 2 and failure == "encode_export":
            native: dict[str, Any] = {
                "model": MODEL,
                "non_conformant": True,
                "error": "Failure",
                "stage": "encode_export",
                "message": marker,
            }
        else:
            Path(command[-1]).write_bytes(candidate)
            native = _authored_report(candidate)
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(native), stderr="")

    monkeypatch.setitem(globals(), "locate", fake_locate)
    monkeypatch.setitem(globals(), "oracle_bytes", fake_oracle)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    (tmp_path / "UzPainter").mkdir()
    if failure == "none":
        test_r322_tga_capture_diagnostic(Path("authored-fake-native"), tmp_path)
    else:
        with pytest.raises(pytest.fail.Exception) as raised:
            test_r322_tga_capture_diagnostic(Path("authored-fake-native"), tmp_path)
        assert str(raised.value) == "TGA diagnostic setup or execution failed"
        assert raised.value.__context__ is None
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err
    saved = json.loads((tmp_path / "UzPainter/tga-capture-replay-private.json").read_text())
    report = saved["report"]
    assert marker not in json.dumps(report)
    expected = {
        "setup": (0, 0, 0, "setup"),
        "encode_export": (2, 2, 4, "classify_candidate"),
        "timeout": (2, 1, 4, "run_candidate"),
        "none": (8, 8, 32, "complete"),
    }[failure]
    assert (
        report["attempted_candidates"],
        report["candidate_runs"],
        report["classified_targets"],
        report["stage"],
    ) == expected
    assert calls == report["attempted_candidates"]
    assert len(report["maps"]) == report["classified_targets"]
    assert all(row["status"] == "exact" for row in report["maps"])
    assert report["global_status"] == report["preset_status"] == "blocked"
    assert report["complete"] is (failure == "none")
    assert report["execution_status"] == ("completed" if failure == "none" else "failed")
    if failure != "none":
        assert report["failure_code"] == "tga_diagnostic_failed"
    if failure == "encode_export":
        assert report["native_stage"] == "encode_export"
        assert marker in json.dumps(saved["diagnostics"])
    if failure == "timeout":
        assert any(item.get("error_type") == "TimeoutExpired" for item in saved["diagnostics"])
