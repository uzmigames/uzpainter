"""Native trace/census and full F9 hashes against authored Python evidence only."""

from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from tests.parity.test_filter_context_run import mutate, recipe
from tests.parity.test_filter_context_settings_validation import authored as authored
from tests.parity.test_filter_context_settings_validation import png_bytes
from tools.parity.filter_context_contract import ContextRefused, typed
from tools.parity.filter_context_settings import SettingsRefused, split_settings_outputs
from tools.parity.recorder.filter_context_run import _f_evidence_from_record
from tools.parity.tier0_semantics.filter_context_settings_control import GOLDEN_ID


def digest(value: Any) -> str:
    return hashlib.sha256(typed(value)).hexdigest()


def expected(record: dict[str, Any]) -> list[dict[str, str]] | None:
    try:
        stripped, _ = split_settings_outputs(record)
        _f_evidence_from_record(stripped, recipe(), expected_golden_id=GOLDEN_ID)
    except (ContextRefused, SettingsRefused):
        return None
    rounds = []
    for recording in stripped["recordings"]:
        outputs = recording["outputs"]
        frames: list[dict[str, Any]] = []
        for output in outputs:
            if not output["output_id"].startswith("context/"):
                continue
            boundary = output["output_id"].split("/")[1]
            if not frames or frames[-1]["boundary"] != boundary:
                frames.append(
                    {
                        "schema": "uzpainter/parity/filter-context-readback/1",
                        "boundary": boundary,
                        "condition": recording["condition"],
                        "outputs": [],
                    }
                )
            frames[-1]["outputs"].append(output)
        pre16 = next(frame for frame in frames if frame["boundary"].startswith("pre16-"))
        probes = [
            output
            for output in outputs
            if output["output_id"].startswith("s")
            and 7 <= int(output["output_id"].split("/")[0][1:]) <= 24
        ]
        result = {
            "condition": recording["condition"],
            "probe_sequence_sha256": digest(probes),
            "context_readback_sha256": digest(frames),
        }
        for role in ("host", "filter"):
            result[f"{role}_readback_sha256"] = digest(
                [
                    output
                    for output in pre16["outputs"]
                    if output["args"]["selector"]
                    in ({"role": role}, {"role": role, "source": True})
                ]
            )
        rounds.append(result)
    return rounds


def rebind_panels(record: dict[str, Any]) -> None:
    """Keep authored UI bracketing valid when exercising deeper census refusals."""
    for recording in record["recordings"]:
        for panel in recording["outputs"]:
            if panel["kind"] != "settings_panel_readback":
                continue
            values = panel["values"]
            frame = [
                output
                for output in recording["outputs"]
                if output["output_id"].startswith(f"context/{values['boundary']}/")
            ]
            binding = values["binding"]
            binding["context_before_sha256"] = digest(frame)
            binding["context_after_sha256"] = digest(frame)
            binding["context_after_outputs"] = deepcopy(frame)


def test_native_filter_trace(
    export_tests: Path,
    tmp_path: Path,
    authored: tuple[dict[str, Any], dict[str, Any]],  # noqa: F811
) -> None:
    _, record = authored
    scenarios: list[dict[str, Any]] = [{"name": "baseline", "record": record}]
    changes = [
        "missing-boundary",
        "late-boundary",
        "split-boundary",
        "repeated-step",
        "unknown-output",
        "closed-still-open",
        "opened-elsewhere",
        "missing-create",
        "setup-failed",
        "rebind-failed",
        "other-key",
        "other-golden",
        "rounds-swapped",
        "identity-other-call",
        "identity-not-kept",
        "identity-missing",
        "identity-extra-step",
        "identity-after-probe",
        "template-not-first",
        "rebind-other-args",
        "rebind-found-by-uid",
        "lifecycle-other-args",
        "lifecycle-other-kind",
        "lifecycle-order",
        "lifecycle-split",
    ]
    for change in changes:
        changed = deepcopy(record)
        mutate(changed, change)
        scenarios.append({"name": change, "record": changed})
    for name, probe_value in (("integer-zero", 0), ("float-zero", 0.0), ("negative-zero", -0.0)):
        changed = deepcopy(record)
        probe = next(
            output
            for output in changed["recordings"][0]["outputs"]
            if output["output_id"].startswith("s7/")
        )
        probe.pop("raised", None)
        probe["value"] = probe_value
        scenarios.append({"name": name, "record": changed})
    for name, suffix, value in (
        ("source-boolean", "SourceSubstance.get_parameters", {"x": True}),
        ("source-vector", "SourceSubstance.get_parameters", {"x": [1, 2]}),
        ("unknown-format", "Channel.format", "Unknown"),
        ("uid-zero", "Node.uid", 0),
        ("uid-boolean", "Node.uid", True),
        ("uid-float", "Node.uid", 1.0),
        ("uuid-drift", "project.get_uuid", "other-project"),
        ("visible-false", "Node.is_visible", False),
        ("mask-true", "Node.is_in_mask_stack", True),
        ("source-identity", "SourceSubstance.resource_id", {"url": "missing-wrapper"}),
        ("filter-channels", "FilterEffectNode.active_channels", ["Unknown"]),
    ):
        changed = deepcopy(record)
        leaf = next(
            output
            for output in changed["recordings"][0]["outputs"]
            if output["output_id"].startswith("context/pre16-r1/")
            and output["call"].endswith(suffix)
        )
        leaf["value"] = value
        rebind_panels(changed)
        scenarios.append({"name": name, "record": changed})
    census_names = {scenario["name"] for scenario in scenarios[29:]}
    census_names.remove("uuid-drift")
    for name, suffix, role, error in (
        ("symmetry-value-error", "FillLayerNode.is_symmetry_enabled", None, "ValueError"),
        ("symmetry-type-error", "FillLayerNode.is_symmetry_enabled", None, "TypeError"),
        ("filter-output-error", "SourceSubstance.active_output", "filter", "RuntimeError"),
        ("filter-resolution-error", "SourceSubstance.resolution", "filter", "RuntimeError"),
        ("host-output-error", "SourceSubstance.active_output", "host", "RuntimeError"),
    ):
        changed = deepcopy(record)
        leaf = next(
            output
            for output in changed["recordings"][0]["outputs"]
            if output["output_id"].startswith("context/pre16-r1/")
            and output["call"].endswith(suffix)
            and (role is None or output["args"]["selector"].get("role") == role)
        )
        leaf["value"] = None
        leaf["raised"] = {"type": error, "message": "authored exception preserved"}
        rebind_panels(changed)
        scenarios.append({"name": name, "record": changed})
    for name, value in (("uv-integer", 0), ("uv-negative-zero", -0.0), ("uv-boolean", False)):
        changed = deepcopy(record)
        leaf = next(
            output
            for output in changed["recordings"][0]["outputs"]
            if output["output_id"].startswith("context/pre16-r1/")
            and output["call"].endswith("FillLayerNode.get_projection_parameters")
        )
        leaf["value"]["uv_transformation"]["rotation"] = value
        rebind_panels(changed)
        scenarios.append({"name": name, "record": changed})
    for name in ("duplicate-leaf", "unused-leaf"):
        changed = deepcopy(record)
        outputs = changed["recordings"][0]["outputs"]
        frame = [o for o in outputs if o["output_id"].startswith("context/pre16-r1/")]
        leaf = deepcopy(next(o for o in frame if o["call"].endswith("TextureSet.name")))
        leaf["output_id"] = f"context/pre16-r1/{len(frame):04d}-name"
        if name == "unused-leaf":
            leaf["args"]["selector"]["set"] = 1
        outputs.insert(outputs.index(frame[-1]) + 1, leaf)
        rebind_panels(changed)
        scenarios.append({"name": name, "record": changed})
    census_names.update({"symmetry-type-error", "host-output-error", "uv-boolean", "unused-leaf"})
    wanted = {scenario["name"]: expected(scenario["record"]) for scenario in scenarios}
    assert wanted["baseline"] is not None
    assert all(wanted[name] is None for name in changes)
    assert (
        len({digest(wanted[name]) for name in ("integer-zero", "float-zero", "negative-zero")}) == 3
    )
    (tmp_path / "trace-records.json").write_text(json.dumps(scenarios), encoding="utf-8")
    (tmp_path / "trace-panel.png").write_bytes(png_bytes())
    proc = subprocess.run(
        [str(export_tests), "filter-gate-trace", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.startswith("FILTER_GATE_TRACE: ")]
    assert len(lines) == 1, proc.stdout
    result = json.loads(lines[0].split(": ", 1)[1])
    assert result["checks"] == len(scenarios) + 1
    assert len(result["results"]) == len(scenarios)
    for row in result["results"]:
        oracle = wanted[row["name"]]
        assert row["accepted"] == (oracle is not None), row
        if row["name"] in census_names:
            assert oracle is None and row["stage"] == "trace", row
        if row["name"] == "uuid-drift":
            assert oracle is None and row["stage"] == "panels", row
        if oracle is not None:
            assert row["rounds"] == oracle, row["name"]
