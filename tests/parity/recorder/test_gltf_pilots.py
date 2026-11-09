"""Painter's glTF PBR Metal Roughness export on the pilots (phase3.1 item 3.1): the requests are
their admitted pilot golden plus one closing configuration export of the predefined glTF preset."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.parity.recorder.gltf_pilots import CONFIG_ID, GLTF_URL, PILOT_GOLDENS, gltf_manifest
from tools.parity.recorder.script_run import CONFIG_EXPORT, NativeJob, pipeline_job_from_manifest
from tools.parity.schemas import REPO_ROOT, load_json
from tools.parity.store.store import locate
from tools.parity.verdict import resolve_golden

ASSETS = Path(r"E:\UzmiGames\Assets3D")
SIZES = {"wand-v1": 11, "sash-v5": 11, "tunic-v10": 12}


def committed(golden_id: str) -> Path:
    found = resolve_golden(golden_id)
    if found is not None:
        return found.manifest_path
    registry = load_json(REPO_ROOT / "parity/envelopes/registry.json")
    current = str(registry["current"]).replace("+", "_")
    return REPO_ROOT / "parity/envelopes" / current / "requests" / f"{golden_id}.json"


@pytest.mark.parametrize("pilot", sorted(PILOT_GOLDENS))
def test_the_gltf_request_is_its_pilot_golden_closed_by_the_gltf_preset(pilot: str) -> None:
    base_id, golden_id, _ = PILOT_GOLDENS[pilot]
    request = load_json(committed(golden_id))
    base = load_json(committed(base_id))
    steps, base_steps = (m["instruction_sequence"]["steps"] for m in (request, base))
    config = next(i for i in request["inputs"] if i["input_id"] == CONFIG_ID)
    native = base_steps[-1]["call"] == CONFIG_EXPORT
    kept = base_steps[:-1] if native else base_steps
    assert steps[: len(kept)] == kept and len(steps) == len(base_steps) + (0 if native else 1)
    assert steps[-1] == {"step": len(steps), "call": CONFIG_EXPORT, "args": {"config": CONFIG_ID}}
    replaced = {base_steps[-1]["args"]["config"]} if native else set()
    assert [i for i in base["inputs"] if i["input_id"] not in replaced] == request["inputs"][:-1]
    assert request["applied_settings"] == base["applied_settings"]
    data = load_json(REPO_ROOT / config["path"])
    assert data == {
        "exportShaderParams": False,
        "defaultExportPreset": GLTF_URL,
        "exportList": [{"rootPath": data["exportList"][0]["rootPath"]}],
        "exportParameters": [
            {
                "parameters": {
                    "fileFormat": "png",
                    "bitDepth": "16",
                    "sizeLog2": SIZES[pilot],
                    "paddingAlgorithm": "infinite",
                    "dithering": False,
                }
            }
        ],
    }


@pytest.mark.parametrize("pilot", sorted(PILOT_GOLDENS))
def test_the_committed_gltf_request_is_the_generator_s(pilot: str) -> None:
    """The generator rebuilds the committed request over the pinned inputs (Assets3D or the
    owner's private store); a native pilot stays a native job."""
    if not (ASSETS / "AGENTS.md").is_file() or locate() is None:
        pytest.skip("the asset repository or the private store is not on this machine")
    _, golden_id, _ = PILOT_GOLDENS[pilot]
    request = load_json(committed(golden_id))
    assert {**request, "private_records": []} == gltf_manifest(pilot, ASSETS)
    job = pipeline_job_from_manifest(request, ASSETS)
    assert job.config_export is not None and job.config_export.config_id == CONFIG_ID
    assert isinstance(job, NativeJob) == (pilot == "tunic-v10")
