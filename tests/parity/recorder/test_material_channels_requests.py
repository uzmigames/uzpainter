"""The item-2.16 material channel requests (`tools/parity/tier0_semantics/material_channels.py`):
documented probes that author no asset name beyond the two material URLs."""

from __future__ import annotations

import json

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder.material_survey import MATERIAL_URLS
from tools.parity.recorder.probes import manifest_symbol_problems, probe_job_from_manifest
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.parity.tier0_semantics.material_channels import MAPS, PREFIX_NAME, STATES, requests


def test_requests_are_documented_probes_of_the_two_materials() -> None:
    built = requests()
    assert set(built) == {PREFIX_NAME + state for state in STATES}
    for name, manifest in built.items():
        assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == [], name
        assert manifest_symbol_problems(manifest) == [], name
        text = json.dumps(manifest)
        assert "preset_name" not in text
        assert sum(url in text for url in MATERIAL_URLS.values()) == 1, name
        job = probe_job_from_manifest(manifest)
        (export,) = job.exports
        assert [f"{m.map_type}/{m.name}:{m.channels}" for m in export.maps] == MAPS
        assert ("preset_index" in text) == name.endswith("-preset"), name


def test_committed_requests_match_their_generators() -> None:
    root = manifest_root(current_envelope()).parent / "requests/tier0/api-probes"
    for name, manifest in requests().items():
        committed = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
        assert committed == manifest, name
        for source in committed["inputs"]:
            assert (REPO_ROOT / source["path"]).is_file()
