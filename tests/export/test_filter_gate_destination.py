"""Native destination mapping from authored F evidence; no Painter or private reads."""

from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tests.parity.test_filter_context_run import Painter, load, recipe, record_with
from tests.parity.test_filter_context_settings import IMPORT_PATH
from tests.parity.test_filter_context_settings_validation import authored as authored
from tests.parity.test_filter_context_settings_validation import png_bytes
from tests.parity.test_painter_filter_context import ChannelType, Mode, Node, NodeType
from tools.parity.filter_context_contract import typed
from tools.parity.filter_context_settings import split_settings_outputs
from tools.parity.recorder.filter_context_run import _f_evidence_from_record


def inactive_record(baseline: dict[str, Any], work: Path, variant: str) -> dict[str, Any]:
    painter = Painter()
    painter.world.stack.all_channels = lambda: {
        ChannelType.User0: painter.world.channel,
        ChannelType.User1: painter.world.channel,
    }
    original_mode, original_opacity = Node.get_blending_mode, Node.get_opacity

    def mode(node: Node, channel: ChannelType) -> Mode:
        if (
            variant == "inactive-raised"
            and node.kind == NodeType.FilterEffect
            and channel == ChannelType.User1
        ):
            raise ValueError("authored inactive channel")
        return original_mode(node, channel)

    def opacity(node: Node, channel: ChannelType) -> float:
        filter_error = (
            variant in ("inactive-raised", "inactive-mixed") and node.kind == NodeType.FilterEffect
        )
        host_error = variant == "host-inactive-raised" and node.kind == NodeType.FillLayer
        if channel == ChannelType.User1 and (filter_error or host_error):
            raise ValueError("authored inactive channel")
        return original_opacity(node, channel)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Node, "get_blending_mode", mode)
        patch.setattr(Node, "get_opacity", opacity)
        generated = load(record_with(painter, work))

    result = deepcopy(baseline)
    result["recordings"] = generated["recordings"]
    originals = {
        output["output_id"]: output
        for recording in baseline["recordings"]
        for output in recording["outputs"]
    }
    panels = {
        output["values"]["boundary"]: output
        for output in originals.values()
        if output["kind"] == "settings_panel_readback"
    }
    # Reuse only authored UI evidence; each bracket binds the newly recorded getter frame.
    for recording in result["recordings"]:
        outputs = recording["outputs"]
        amended: list[dict[str, Any]] = []
        index = 0
        while index < len(outputs):
            output = outputs[index]
            if not output["output_id"].startswith("context/"):
                amended.append(output)
                index += 1
                continue
            boundary = output["output_id"].split("/")[1]
            frame = []
            while index < len(outputs) and outputs[index]["output_id"].startswith(
                f"context/{boundary}/"
            ):
                row = outputs[index]
                if row["call"].endswith("project.last_imported_mesh_path"):
                    row["value"] = IMPORT_PATH
                frame.append(row)
                amended.append(row)
                index += 1
            panel = deepcopy(panels[boundary])
            binding = panel["values"]["binding"]
            for side in ("before", "after"):
                binding[side]["session_id"] = recording["session_id"]
            digest = hashlib.sha256(typed(frame)).hexdigest()
            binding["context_before_sha256"] = digest
            binding["context_after_sha256"] = digest
            binding["context_after_outputs"] = deepcopy(frame)
            amended.append(panel)
            amended.extend(
                deepcopy(originals[image["output_id"]]) for image in panel["values"]["images"]
            )
        recording["outputs"] = amended
    stripped, _ = split_settings_outputs(result)
    _f_evidence_from_record(stripped, recipe(), expected_golden_id=result["golden_id"])
    return result


def test_filter_gate_destination_on_authored_evidence(
    export_tests: Path,
    tmp_path: Path,
    authored: tuple[dict[str, Any], dict[str, Any]],  # noqa: F811
) -> None:
    _, record = authored
    (tmp_path / "destination-record.json").write_text(json.dumps(record), encoding="utf-8")
    (tmp_path / "destination-panel.png").write_bytes(png_bytes())
    for variant in (
        "inactive-observed",
        "inactive-raised",
        "inactive-mixed",
        "host-inactive-raised",
    ):
        generated = inactive_record(record, tmp_path / variant, variant)
        (tmp_path / f"destination-record-{variant}.json").write_text(
            json.dumps(generated), encoding="utf-8"
        )
    result = subprocess.run(
        [str(export_tests), "filter-gate-destination", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    prefix = "FILTER_GATE_DESTINATION: "
    summaries = [
        line[len(prefix) :] for line in result.stdout.splitlines() if line.startswith(prefix)
    ]
    assert len(summaries) == 1, result.stdout
    assert json.loads(summaries[0]) == {"checks": 66}
