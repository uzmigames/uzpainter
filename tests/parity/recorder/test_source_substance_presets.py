"""Authored transport tests of the decision-412 probes; fake values assert no Painter behaviour."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
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
from tools.parity.tier0_semantics.source_substance_presets import (
    AFTER,
    ANCHOR_NAME,
    GETTERS,
    MISSING_PRESET,
    NAME,
    PREFIX,
    anchor_request,
    edits,
    request,
)

AUTHORED_URL = "resource://starter_assets/authored/authored?version=0123abcd.sbsar"


def test_requests_have_documented_calls_and_author_no_asset_names() -> None:
    for manifest in (request(AUTHORED_URL), anchor_request(AUTHORED_URL)):
        assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
        assert manifest_symbol_problems(manifest) == []
        text = json.dumps(manifest)
        # Only indices choose the preset, input and outputs; the one authored name is missing.
        assert "preset_name" not in text or MISSING_PRESET in text
    job = probe_job_from_manifest(request(AUTHORED_URL))
    assert [step.call.rsplit(".", 1)[-1] for step in job.state_steps] == [
        "insert_fill",
        "set_material_source",
        "import_project_resource",
        "insert_fill",
        "active_channels",
        "set_source",
    ]
    assert len(job.probe_steps) == 2 * len(GETTERS) + 1 + len(edits()) * (len(AFTER) + 2)
    with pytest.raises(ValueError):
        request("resource://starter_assets/unversioned/unversioned")


def test_committed_requests_match_their_generators() -> None:
    entry = current_envelope()
    root = manifest_root(entry).parent / "requests/tier0/api-probes"
    for name, build in ((NAME, request), (ANCHOR_NAME, anchor_request)):
        committed = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
        assert committed == build()
        assert committed["software"]["painter"]["build_id"] == entry["painter_build"]
        for source in committed["inputs"]:
            assert (REPO_ROOT / source["path"]).is_file()


def fake_world(fake: types.ModuleType) -> Any:
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
    return world


def test_multiple_output_edits_go_through_the_recorder(
    fake: types.ModuleType, tmp_path: Path
) -> None:
    """An authored material fake: every new edit and readback is recorded in both recordings."""
    world = fake_world(fake)
    source = world.modules["substance_painter.source"]
    layerstack = world.modules["substance_painter.layerstack"]

    class Mapping(dict[Any, Any]):
        pass

    class Substance:
        def __init__(self, rid: Any) -> None:
            self.rid = self.resource_id = rid
            self.values: dict[str, Any] = {"authored_amount": 0.5}
            self.inputs: dict[str, Any] = {}
            self.image_inputs = ["authored_input"]
            self.image_outputs = ["authored_a", "authored_b"]
            self.output_mapping = Mapping({fake.ChannelType.BaseColor: "authored_a"})
            self.output_mapping[fake.ChannelType.Height] = "authored_b"
            self.mask_output = "authored_b"
            self.resolution = None

        @property
        def active_output(self) -> str:
            raise RuntimeError("authored single output refusal")

        def get_parameters(self) -> dict[str, Any]:
            return dict(self.values)

        def get_properties(self) -> dict[str, Any]:
            return {}

        def get_preset_list(self) -> list[str]:
            return ["authored_preset"]

        def apply_preset(self, preset: str) -> None:
            if preset == "authored_preset":
                self.values["authored_amount"] = 1.0

        def get_source(self, name: str) -> Any:
            return self.inputs.get(name)

        def set_source(self, name: str, value: Any) -> Any:
            made = (
                source.SourceBitmap(value)
                if isinstance(value, world.modules["substance_painter.resource"].ResourceID)
                else source.SourceUniformColor(value)
            )
            self.inputs[name] = made
            return made

        def reset_source(self, name: str) -> None:
            self.inputs.pop(name, None)

        def remove_source(self, name: str) -> None:
            self.inputs.pop(name, None)

    class Reference:
        pass

    source.SourceSubstance = Substance
    source.SourceReference = Reference
    materials: dict[str, Substance] = {}
    node_class = layerstack.FillLayerNode
    original_get, original_set = node_class.get_source, node_class.set_source

    def set_material_source(node: Any, rid: Any) -> Any:
        # One material fill per probe: the fake's save keeps only JSON, so it lives here.
        materials["fill"] = Substance(rid)
        return materials["fill"]

    def get_material_source(node: Any) -> Any:
        return materials["fill"]

    def get_source(node: Any, channel: Any = None) -> Any:
        value = original_get(node, channel)
        if isinstance(value, source.SourceBitmap) and value.rid.url() == AUTHORED_URL:
            value = Substance(value.rid)
            node.data.sources[node.source_key(channel)] = value
        return value

    def set_source(node: Any, channel: Any, value: Any) -> Any:
        original_set(node, channel, value)
        return get_source(node, channel)

    node_class.set_material_source = set_material_source
    node_class.get_material_source = get_material_source
    node_class.get_source, node_class.set_source = get_source, set_source
    session = ProbeSession(
        fake.LocalTransport(world),
        sleep=lambda _: world.modules["substance_painter.project"].is_busy(),
        allowed_builds=lambda: frozenset({"12.2.0+js-api.1.1.20"}),
    )
    job = probe_job_from_manifest(request(AUTHORED_URL))
    run = record_probe_golden(session, job, tmp_path / "work", tmp_path / "inbox")
    record = json.loads((run / "record.json").read_text())
    assert record_problems(record) == []
    for recording in record["recordings"]:
        outputs = {
            o["output_id"]: o
            for o in recording["outputs"]
            if o["kind"] == "api_readback" and o.get("call", "").startswith(PREFIX)
        }
        assert len(outputs) == len(job.probe_steps)
        raised = {key for key, output in outputs.items() if "raised" in output}
        # The authored refusals only: active_output on both sources, and the fake's split
        # source has no multiple output members.
        assert {outputs[key]["call"].rsplit(".", 1)[-1] for key in raised} <= {
            "active_output",
            "output_mapping",
            "mask_output",
            "resolution",
        }
        mappings = [o["value"] for o in outputs.values() if o["call"].endswith("output_mapping")]
        assert {"value": "authored_a", "class": "str"} in [
            value.get("BaseColor") for value in mappings if isinstance(value, dict)
        ]
        inputs = [o["value"] for o in outputs.values() if o["call"].endswith("get_source")]
        assert {"class": None, "value": None} in inputs
        assert any(value and value["class"] == "SourceBitmap" for value in inputs)
