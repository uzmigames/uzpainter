"""R-314 default-format follow-up must override padding only."""

import pytest

from tools.parity.recorder.job import job_from_manifest
from tools.parity.schemas import REPO_ROOT, load_json
from tools.parity.tier0_semantics.recording_requests import request_dir


@pytest.mark.parametrize("mode", ["legacy", "ocio"])
def test_gltf_default_format_probe_overrides_only_required_padding(mode: str) -> None:
    manifest = load_json(
        request_dir(REPO_ROOT) / f"export-presets-gltf-predefined-padding-{mode}.json"
    )
    job = job_from_manifest(manifest, REPO_ROOT)
    assert not job.exports
    [probe] = job.export_probes
    assert probe.config["defaultExportPreset"] == "export-preset-generator://gltf"
    assert probe.config["exportParameters"] == [{"parameters": {"paddingAlgorithm": "infinite"}}]
    assert "exportPresets" not in probe.config
