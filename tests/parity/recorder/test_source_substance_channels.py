"""Authored transport tests of the decision-413 requests P413-A and P413-B; fakes assert nothing
about Painter's behaviour."""

from __future__ import annotations

import json
import types
from pathlib import Path

from tests.parity.recorder.test_source_substance_presets import AUTHORED_URL, material_session
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder.probes import (
    manifest_symbol_problems,
    probe_job_from_manifest,
    record_probe_golden,
)
from tools.parity.schemas import REPO_ROOT, Schema, record_problems, validation_errors
from tools.parity.tier0_semantics.source_substance_channels import (
    CHANNELS_PREFIX,
    CONTEXT_FILLS,
    CONTEXT_GETTERS,
    CONTEXTS_NAME,
    MAPS,
    R1_EDITS,
    R2_EDITS,
    STATES,
    requests,
    state_request,
)


def test_requests_are_documented_probes_that_author_no_asset_names() -> None:
    built = requests(AUTHORED_URL)
    assert set(built) == {CHANNELS_PREFIX + s for s in STATES} | {
        CHANNELS_PREFIX + "material-only",
        CHANNELS_PREFIX + "split-only",
        CONTEXTS_NAME,
    }
    for name, manifest in built.items():
        assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == [], name
        assert manifest_symbol_problems(manifest) == [], name
        assert "preset_name" not in json.dumps(manifest)
        job = probe_job_from_manifest(manifest)
        if name == CONTEXTS_NAME:
            assert job.exports == ()
            sourced = sum(len(channels) for _, channels in CONTEXT_FILLS)
            assert len(job.probe_steps) == len(CONTEXT_FILLS) + sourced * len(CONTEXT_GETTERS)
            continue
        (export,) = job.exports
        assert [f"{m.map_type}/{m.name}:{m.channels}" for m in export.maps] == MAPS


def test_states_apply_the_probes_effective_edits_as_state_steps() -> None:
    assert STATES["mask-second"] == R1_EDITS
    assert STATES["reopen-reset"] == R1_EDITS + R2_EDITS
    for state, edits in STATES.items():
        job = probe_job_from_manifest(state_request(state, AUTHORED_URL))
        applied = [step for step in job.state_steps if step.args.get("material") is True]
        assert [(s.call.rsplit(".", 1)[1], s.args) for s in applied] == [
            (call, {"node_step": 2, "material": True, **args}) for call, args in edits
        ]
        assert not any(step.probe for step in job.state_steps)


def test_committed_requests_match_their_generators() -> None:
    entry = current_envelope()
    root = manifest_root(entry).parent / "requests/tier0/api-probes"
    for name, manifest in requests().items():
        committed = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
        assert committed == manifest, name
        for source in committed["inputs"]:
            assert (REPO_ROOT / source["path"]).is_file()


def test_a_state_golden_goes_through_the_recorder(fake: types.ModuleType, tmp_path: Path) -> None:
    """Every edit as a state step, the reads in both recordings and the three channel exports."""
    session = material_session(fake)
    job = probe_job_from_manifest(state_request("reopen-reset", AUTHORED_URL))
    run = record_probe_golden(session, job, tmp_path / "work", tmp_path / "inbox")
    record = json.loads((run / "record.json").read_text())
    assert record_problems(record) == []
    for recording in record["recordings"]:
        ids = {o["output_id"] for o in recording["outputs"]}
        assert {f"s{step.step}/{step.call.rsplit('.', 1)[1]}" for step in job.probe_steps} <= ids
        assert {"uzp_plane/basecolor", "uzp_plane/height", "uzp_plane/normal"} <= ids
