"""Authored transport tests of the decision-413 requests P413-C, P413-D and P413-E; fakes assert
nothing about Painter's behaviour."""

from __future__ import annotations

import json
import types
from pathlib import Path
from typing import Any

from tests.parity.recorder.test_source_substance_presets import AUTHORED_URL, material_session
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder.probes import (
    manifest_symbol_problems,
    probe_job_from_manifest,
    record_probe_golden,
)
from tools.parity.schemas import REPO_ROOT, Schema, record_problems, validation_errors
from tools.parity.tier0_semantics.source_substance_channels import MAPS
from tools.parity.tier0_semantics.source_substance_separation import (
    ACCESS_NAME,
    MASKED,
    MASKED_PREFIX,
    SPLIT,
    SPLIT_PREFIX,
    access_request,
    masked_request,
    requests,
    split_request,
)


def test_requests_are_documented_probes_that_author_no_asset_names() -> None:
    built = requests(AUTHORED_URL)
    assert set(built) == (
        {MASKED_PREFIX + name for name in MASKED}
        | {SPLIT_PREFIX + name for name in SPLIT}
        | {ACCESS_NAME}
    )
    for name, manifest in built.items():
        assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == [], name
        assert manifest_symbol_problems(manifest) == [], name
        assert "preset_name" not in json.dumps(manifest)
        job = probe_job_from_manifest(manifest)
        assert not any(step.probe for step in job.state_steps)
        if name == ACCESS_NAME:
            assert job.exports == ()
            continue
        (export,) = job.exports
        assert [f"{m.map_type}/{m.name}:{m.channels}" for m in export.maps] == MAPS
        reopens = [s for s in manifest["applied_settings"] if s["name"] == "recorder.reopen_count"]
        assert reopens == ([{**reopens[0], "value": 2}] if name.startswith(MASKED_PREFIX) else [])


def test_committed_requests_match_their_generators() -> None:
    root = manifest_root(current_envelope()).parent / "requests/tier0/api-probes"
    for name, manifest in requests().items():
        committed = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
        assert committed == manifest, name
        for source in committed["inputs"]:
            assert (REPO_ROOT / source["path"]).is_file()


def recorded(session: Any, manifest: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    job = probe_job_from_manifest(manifest)
    run = record_probe_golden(session, job, tmp_path / "work", tmp_path / "inbox")
    record: dict[str, Any] = json.loads((run / "record.json").read_text())
    assert record_problems(record) == []
    return record


def test_a_masked_golden_records_two_reopens(fake: types.ModuleType, tmp_path: Path) -> None:
    session = material_session(fake)
    record = recorded(session, masked_request("by-height-swap", AUTHORED_URL), tmp_path)
    assert [r["recording_id"] for r in record["recordings"]] == ["r1", "r2", "r3"]
    assert [r["condition"] for r in record["recordings"]] == [
        "same_session",
        "after_save_reopen",
        "after_save_reopen",
    ]
    for recording in record["recordings"]:
        ids = {o["output_id"] for o in recording["outputs"]}
        assert {"uzp_plane/basecolor", "uzp_plane/height", "uzp_plane/normal"} <= ids


def test_a_split_golden_sets_the_other_output(fake: types.ModuleType, tmp_path: Path) -> None:
    session = material_session(fake)
    substance = fake_module(session, "substance_painter.source").SourceSubstance
    # The fake rebuilds split sources on reads, so the authored choice is kept here.
    chosen = {"output": "authored_a"}

    def write(_: Any, value: str) -> None:
        chosen["output"] = value

    substance.active_output = property(lambda _: chosen["output"], write)
    record = recorded(session, split_request("basecolor-second-bitmap", AUTHORED_URL), tmp_path)
    for recording in record["recordings"]:
        reads = [o for o in recording["outputs"] if o["output_id"].endswith("/active_output")]
        assert reads[-1]["value"] == "authored_b"


def fake_module(session: Any, name: str) -> Any:
    return session.transport.world.modules[name]


def test_mapping_accesses_are_separate_steps(fake: types.ModuleType, tmp_path: Path) -> None:
    record = recorded(material_session(fake), access_request(AUTHORED_URL), tmp_path)
    for recording in record["recordings"]:
        reads = {
            o["output_id"]: o.get("value", o.get("raised"))
            for o in recording["outputs"]
            if o.get("call", "").endswith("output_mapping")
        }
        values = list(reads.values())
        assert "dict" in values or "Mapping" in values
        assert {"value": "authored_b", "class": "str"} in values
        assert 2 in values
