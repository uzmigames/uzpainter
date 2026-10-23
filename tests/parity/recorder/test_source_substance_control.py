"""Authored transport tests; fake values do not assert Painter asset behavior."""

from __future__ import annotations

import enum
import hashlib
import importlib.util
import json
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder.probes import (
    ProbeSession,
    manifest_symbol_problems,
    probe_job_from_manifest,
    record_probe_golden,
)
from tools.parity.schemas import REPO_ROOT, Schema, record_problems, validation_errors
from tools.parity.tier0_semantics.source_substance_control import (
    GETTERS,
    NAME,
    PREFIX,
    RESOURCE_URL,
    request,
)


class Mode(enum.Enum):
    Auto = 0
    Custom = 1


@dataclass
class Override:
    mode: Any
    value: Any = (128, 128)
    log2_offset: Any = 0


def test_request_has_documented_calls_and_no_authored_parameter_defaults() -> None:
    manifest = request()
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest_symbol_problems(manifest) == []
    job = probe_job_from_manifest(manifest)
    assert len(job.state_steps) == 4
    assert len(job.probe_steps) == len(GETTERS) * 6 + 5
    assert job.state_steps[-1].args["resource_url"] == RESOURCE_URL
    edits = [step for step in job.probe_steps if step.args.get("roundtrip")]
    assert [step.call for step in edits] == [
        PREFIX + name for name in ("set_parameters", "active_output", "resolution")
    ]
    assert all(set(step.args) == {"node_step", "channel", "roundtrip"} for step in edits)


def test_committed_request_pins_authored_inputs_and_current_envelope() -> None:
    manifest = request()
    entry = current_envelope()
    path = manifest_root(entry).parent / "requests/tier0/api-probes" / f"{NAME}.json"
    assert json.loads(path.read_text(encoding="utf-8")) == manifest
    assert manifest["private_records"] == []
    assert manifest["software"]["painter"]["build_id"] == entry["painter_build"]
    for source in manifest["inputs"]:
        assert (
            hashlib.sha256((REPO_ROOT / source["path"]).read_bytes()).hexdigest()
            == source["sha256"]
        )


@pytest.mark.parametrize("refuse_parameters", [False, True])
def test_source_roundtrips_replay_after_reopen(
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    refuse_parameters: bool,
) -> None:
    # This transport fake has only User8..31; alias one scalar slot for this control.
    monkeypatch.setattr(fake.ChannelType, "User0", fake.ChannelType.User8, raising=False)
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
    calls: list[dict[str, Any]] = []

    class Substance:
        def __init__(self, rid: Any) -> None:
            self.rid = self.resource_id = rid
            self.active_output = "authored_scalar"
            self.resolution = Override(Mode.Auto, (128, 128), 0)
            self.image_inputs: list[str] = []
            self.image_outputs = ["authored_scalar"]

        def get_parameters(self) -> dict[str, Any]:
            if refuse_parameters:
                return {"authored_boolean": True}
            return {"authored_integer": 7, "authored_vector": [0.25, 0.75]}

        def set_parameters(self, values: dict[str, Any]) -> None:
            assert values == self.get_parameters()
            if refuse_parameters:
                assert values["authored_boolean"] is True
                raise TypeError("authored boolean refusal")
            calls.append(values)

        def get_properties(self) -> dict[str, Any]:
            return {}

        def get_preset_list(self) -> list[str]:
            return []

    source.SourceSubstance = Substance
    source.ResolutionOverride = Override
    source.ResolutionMode = Mode
    node_class = world.modules["substance_painter.layerstack"].FillLayerNode
    original_get = node_class.get_source
    original_set = node_class.set_source

    def get_source(node: Any, channel: Any = None) -> Any:
        value = original_get(node, channel)
        if isinstance(value, source.SourceBitmap) and value.rid.url() == RESOURCE_URL:
            value = Substance(value.rid)
            node.data.sources[node.source_key(channel)] = value
        return value

    def set_source(node: Any, channel: Any, value: Any) -> Any:
        original_set(node, channel, value)
        return get_source(node, channel)

    node_class.get_source = get_source
    node_class.set_source = set_source
    session = ProbeSession(
        fake.LocalTransport(world),
        sleep=lambda _: world.modules["substance_painter.project"].is_busy(),
        allowed_builds=lambda: frozenset({"12.2.0+js-api.1.1.20"}),
    )
    job = probe_job_from_manifest(request())
    run = record_probe_golden(session, job, tmp_path / "work", tmp_path / "inbox")
    record = json.loads((run / "record.json").read_text())
    assert record_problems(record) == []
    values = []
    for recording in record["recordings"]:
        outputs = [o for o in recording["outputs"] if o["kind"] == "api_readback"]
        errors = [output for output in outputs if "raised" in output]
        if refuse_parameters:
            assert len(errors) == 1
            assert errors[0]["call"] == PREFIX + "set_parameters"
            assert errors[0]["raised"] == {
                "type": "TypeError",
                "message": "authored boolean refusal",
            }
        else:
            assert not errors
        values.append(
            {o["output_id"]: o["value"] for o in outputs if o.get("call", "").startswith(PREFIX)}
        )
    assert values[0] == values[1]
    assert len(calls) == (0 if refuse_parameters else 2)
    assert len(values[0]) == len(job.probe_steps)
    assert values[0]["s11/resource_id"]["url"] == RESOURCE_URL
    resolutions = [
        value for key, value in values[0].items() if key.endswith("/resolution") and value
    ]
    assert any(value["mode"] == "Custom" for value in resolutions)
    assert resolutions[-1]["mode"] == "Auto"
    assert values[0]["s13/resolution"] == {
        "mode": "Auto",
        "value": [128, 128],
        "value_kind": "tuple",
        "log2_offset": 0,
    }
