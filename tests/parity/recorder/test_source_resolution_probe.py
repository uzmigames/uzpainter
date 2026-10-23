"""Authored value-type probe transport, independent of Painter behavior and asset catalogs."""

from __future__ import annotations

import enum
import importlib.util
import json
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.parity.recorder.probes import (
    ProbeSession,
    load_probe_job,
    manifest_symbol_problems,
    record_probe_golden,
)
from tools.parity.schemas import REPO_ROOT, record_problems

REQUEST = (
    REPO_ROOT
    / "parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7"
    / "requests/tier0/api-probes/source-resolution-values.json"
)


class FakeMode(enum.Enum):
    Auto = 10
    Asset = 11
    Custom = 12
    TextureSet = 13
    UVTile = 14
    Document = Asset
    Manual = Custom


@dataclass
class FakeOverride:
    mode: Any
    value: Any
    log2_offset: Any


def test_request_is_read_only_and_names_documented_calls() -> None:
    job = load_probe_job(REQUEST)
    assert manifest_symbol_problems(job.manifest) == []
    assert not job.state_steps and not job.exports
    assert len(job.probe_steps) == 46
    assert {step.call for step in job.probe_steps} == {
        "substance_painter.source.ResolutionMode",
        "substance_painter.source.ResolutionOverride",
    }


def test_value_probe_preserves_errors_raw_values_and_assignment_across_reopen(
    fake: types.ModuleType, tmp_path: Path
) -> None:
    name = "uzp_recorder_fake_probe_painter"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).with_name("fake_probe_painter.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    world = sys.modules[name].ProbeWorld()
    world.version, world.version_info = "12.2.0", (12, 2, 0)
    source = world.modules["substance_painter.source"]
    source.ResolutionMode, source.ResolutionOverride = FakeMode, FakeOverride
    session = ProbeSession(
        fake.LocalTransport(world),
        sleep=lambda _: None,
        allowed_builds=lambda: frozenset({"12.2.0+js-api.1.1.20"}),
    )
    job = load_probe_job(REQUEST)
    run = record_probe_golden(session, job, tmp_path / "work", tmp_path / "inbox")
    record = json.loads((run / "record.json").read_text())
    assert record_problems(record) == []
    outputs = []
    for recording in record["recordings"]:
        outputs.append(
            {
                entry["output_id"]: {"raised": entry["raised"]}
                if "raised" in entry
                else entry["value"]
                for entry in recording["outputs"]
                if entry["kind"] == "api_readback" and entry["output_id"].startswith("s")
            }
        )
    assert outputs[0] == outputs[1]
    values = outputs[0]
    assert values["s7/ResolutionMode"] == {"name": "Asset", "value": 11}
    assert values["s8/ResolutionMode"] == {"name": "Custom", "value": 12}
    assert values["s18/ResolutionOverride"]["raised"]["type"] == "TypeError"
    assert values["s47/ResolutionOverride"] == {
        "mode": "Auto",
        "value": [257, 0],
        "value_kind": "tuple",
        "log2_offset": -1,
    }
    assert world.roots == []
