"""R-322 request contracts, independent of Painter and private recorded files."""

import json
from typing import Any

import pytest

from tools.parity.envelope.registry import current_envelope
from tools.parity.recorder import vocabulary as ps
from tools.parity.schemas import Schema, validation_errors
from tools.parity.tier0_semantics import recording_requests as rr
from tools.parity.tier0_semantics import unreal_preset_control as control
from tools.parity.tier0_semantics.corpus import Golden


def test_processing_controls_preserve_defaults_and_isolate_tga() -> None:
    probes = control.probe_groups()[control.GROUP]
    assert len(probes) == 5
    assert "exportParameters" not in probes["unreal-own"]
    assert probes["unreal-padding"]["exportParameters"] == [
        {"parameters": {"paddingAlgorithm": "infinite"}}
    ]
    png = probes["unreal-png8"]["exportParameters"][0]["parameters"]
    tga = probes["unreal-tga8"]["exportParameters"][0]["parameters"]
    assert tga == {**png, "fileFormat": "tga"}
    assert png == {
        "fileFormat": "png",
        "bitDepth": "8",
        "paddingAlgorithm": "infinite",
        "dithering": False,
    }
    assert probes["unreal-pipeline"]["exportParameters"][0]["parameters"]["bitDepth"] == "16"
    assert all(p["defaultExportPreset"] == control.PRESET for p in probes.values())
    assert all("exportPresets" not in p for p in probes.values())


@pytest.mark.parametrize("ocio", [False, True])
def test_recording_reuses_distinct_authored_gltf_state(ocio: bool) -> None:
    golden = control.request(ocio)
    gltf = rr.export_presets_gltf(ocio, predefined=True)

    def state(g: Golden) -> list[dict[str, Any]]:
        return [
            s
            for s in g.sequence.steps
            if s["call"]
            not in (
                rr.PREDEFINED_PRESETS,
                rr.RESOURCE_PRESETS,
                rr.PREDEFINED_OUTPUT_MAPS,
                rr.RESOURCE_OUTPUT_MAPS,
                ps.LIST_TEXTURES,
            )
        ]

    assert state(golden) == state(gltf)
    assert golden.settings == gltf.settings
    assert golden.mesh == "bevelled-cube"
    assert golden.name.endswith("ocio" if ocio else "legacy")
    captures = [s for s in golden.sequence.steps if s["call"] == rr.RESOURCE_OUTPUT_MAPS]
    assert len(captures) == 1 and captures[0]["args"] == {"preset": control.PRESET}
    probes = [s["args"]["config"] for s in golden.sequence.steps if s["call"] == ps.LIST_TEXTURES]
    assert probes == list(control.input_fixtures())
    assert all(name in golden.inputs for name in probes)
    assert "shelf discovery completed" in golden.description


def test_recipe_inputs_are_deterministic_and_independent() -> None:
    fixtures = control.input_fixtures()
    for name, (kind, path, generate) in fixtures.items():
        assert kind == "recipe_json" and path.endswith(".json")
        assert generate() == fixtures[name][2]()
        assert json.loads(generate())["defaultExportPreset"] == control.PRESET
    probes = control.probe_groups()
    probes[control.GROUP]["unreal-pipeline"]["exportParameters"][0]["parameters"]["bitDepth"] = "8"
    assert (
        control.probe_groups()[control.GROUP]["unreal-pipeline"]["exportParameters"][0][
            "parameters"
        ]["bitDepth"]
        == "16"
    )


@pytest.mark.parametrize("ocio", [False, True])
def test_request_manifest_schema_without_registering(
    ocio: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixtures = {**rr.REQUEST_FIXTURES, **control.input_fixtures()}
    monkeypatch.setattr(rr, "REQUEST_FIXTURES", fixtures)
    golden = control.request(ocio)
    manifest = rr.request_manifest(
        golden, dict.fromkeys(golden.inputs, "a" * 64), current_envelope()
    )
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest["private_records"] == []
    assert manifest["instruction_sequence"]["author"] == "UzmiGames"
