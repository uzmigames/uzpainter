"""A native job (decision 300 item 7, the Tunic current round) through the batch preflight
(`tools/parity/recorder/batch.py`) and the envelope corpus (`tools/parity/envelope/corpus.py`):
a valid one is accepted under `record-script`'s own loader and records like `record-script`, an
invalid one is refused with the loader's reason, and script jobs are checked as before. No
Painter: the corpus records against the fake Painter.
"""

from __future__ import annotations

import copy
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.parity.recorder import test_script_run as script_fixtures
from tools.parity.envelope import corpus
from tools.parity.recorder import batch
from tools.parity.recorder.script_run import wand_manifest
from tools.parity.recorder.session import PainterSession, RecorderError
from tools.parity.schemas import load_json, record_problems
from tools.parity.store.store import STORE_ENV


@pytest.fixture(autouse=True)
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "no-store"))
    monkeypatch.setenv("OCIO", script_fixtures.OCIO)
    monkeypatch.delenv("PAINTER_ACE_CONFIG", raising=False)


@pytest.fixture
def assets(tmp_path: Path) -> Path:
    return script_fixtures.make_assets(tmp_path / "Assets3D")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return tmp_path / "repo"


@pytest.fixture
def native(assets: Path, repo: Path) -> dict[str, Any]:
    return script_fixtures.native_manifest(assets, repo)


def broken(native: dict[str, Any]) -> dict[str, Any]:
    changed = copy.deepcopy(native)
    changed["instruction_sequence"]["steps"][0]["args"]["mesh_unit_scale"] = 0
    return changed


def problems(manifest: dict[str, Any], repo: Path, assets: Path) -> list[str]:
    request = batch.Request(Path("phase2/tier1/tunic-v10-current.json"), "x", manifest)
    item = batch.Item(request, kind=batch.kind_of(request))
    assert item.kind == batch.SCRIPT
    return batch.job_problems(item, repo, assets, None)


# --- the batch preflight -----------------------------------------------------------------------


def test_the_batch_accepts_a_valid_native_job_and_refuses_an_invalid_one(
    native: dict[str, Any], repo: Path, assets: Path
) -> None:
    assert problems(native, repo, assets) == []
    assert problems(broken(native), repo, assets) == [
        "recorder job check: step 1: `mesh_unit_scale` is not a value the recorder passes"
    ]


def test_the_batch_checks_a_script_job_as_before(assets: Path, repo: Path) -> None:
    """A script job still loads as a script job: valid, and refused on an unknown step."""
    manifest = wand_manifest(assets)
    assert problems(manifest, repo, assets) == []
    changed = copy.deepcopy(manifest)
    changed["instruction_sequence"]["steps"][0]["args"]["extra"] = "x"
    (problem,) = problems(changed, repo, assets)
    assert problem.startswith("recorder job check: step 1: arguments [")
    assert problem.endswith("are no create, sync or export")


# --- the envelope corpus -----------------------------------------------------------------------


def session_of(fake: types.ModuleType) -> tuple[Any, PainterSession]:
    world = fake.FakeWorld()
    world.version, world.version_info = "12.1.5", (12, 1, 5)
    world.texture_set = world.imported_texture_set = script_fixtures.TUNIC_SET
    return world, PainterSession(
        fake.LocalTransport(world),
        sleep=lambda seconds: None,
        allowed_builds=lambda: frozenset({script_fixtures.BUILD}),
        verify_calls=True,
    )


def test_the_corpus_records_a_native_job_as_record_script_does(
    fake: types.ModuleType, native: dict[str, Any], assets: Path, repo: Path, tmp_path: Path
) -> None:
    """The native create, the sync and only the configuration in r1, r1-repeat and r2."""
    _, session = session_of(fake)
    assert corpus.recorder_kind(native, repo) == corpus.SCRIPT
    run = corpus.record_golden(
        session,
        native,
        tmp_path / "work",
        tmp_path / "inbox",
        lambda: datetime.now(UTC),
        repo_root=repo,
        assets_root=assets,
    )
    record = load_json(run / "record.json")
    assert record_problems(record) == []
    assert [r["recording_id"] for r in record["recordings"]] == ["r1", "r1-repeat", "r2"]
    for recorded in record["recordings"]:
        maps = [o["map"] for o in recorded["outputs"] if o["kind"] == "exported_map"]
        assert maps == ["DefaultMaterial_Displacement_Raw"]
    outputs = {o["output_id"]: o for o in record["recordings"][0]["outputs"]}
    assert outputs["create/s1"]["call"] == "substance_painter.project.create"


def test_the_corpus_refuses_an_invalid_native_job_before_connecting(
    fake: types.ModuleType, native: dict[str, Any], assets: Path, repo: Path, tmp_path: Path
) -> None:
    _, session = session_of(fake)
    with pytest.raises(RecorderError, match="`mesh_unit_scale`"):
        corpus.record_golden(
            session,
            broken(native),
            tmp_path / "work",
            tmp_path / "inbox",
            lambda: datetime.now(UTC),
            repo_root=repo,
            assets_root=assets,
        )
    assert session.identity is None
    assert not (tmp_path / "work").exists()
