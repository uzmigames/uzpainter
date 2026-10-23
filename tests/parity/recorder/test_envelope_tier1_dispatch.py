"""Refresh dispatch preserves Tier 1 pinned inputs and original recording procedures."""

from __future__ import annotations

import copy
import json
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.parity.recorder import test_migration as migration_fixtures
from tests.parity.recorder import test_script_run as script_fixtures
from tools.parity.envelope import corpus
from tools.parity.recorder import tunic
from tools.parity.recorder.script_run import wand_manifest
from tools.parity.recorder.session import PainterSession, RecorderError, UnseenBuild
from tools.parity.schemas import load_json, record_problems
from tools.parity.store.store import STORE_ENV, OracleStore


@pytest.fixture
def tier1(
    request: pytest.FixtureRequest,
    fake: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, dict[str, Any], Path, Path, PainterSession]:
    kind = str(request.param)
    assets, repo = tmp_path / "Assets3D", tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "no-store"))
    monkeypatch.setenv("OCIO", script_fixtures.OCIO)
    monkeypatch.delenv("PAINTER_ACE_CONFIG", raising=False)
    if kind == corpus.SCRIPT:
        script_fixtures.make_assets(assets)
        manifest = wand_manifest(assets)
    else:
        project = migration_fixtures.fake_project(fake)
        migration_fixtures.write(assets / tunic.TUNIC_PROJECT, project)
        migration_fixtures.write(
            assets / tunic.TUNIC_PIECE_MANIFEST,
            migration_fixtures.piece_manifest(migration_fixtures.sha256(project)),
        )
        migration_fixtures.write(
            repo / tunic.EXPORT_CONFIG, json.dumps(migration_fixtures.FAKE_CONFIG)
        )
        manifest = tunic.tunic_manifest(assets, repo)
    world = fake.FakeWorld()
    world.version, world.version_info = "12.1.5", (12, 1, 5)
    session = PainterSession(
        fake.LocalTransport(world),
        sleep=lambda seconds: None,
        allowed_builds=lambda: frozenset({script_fixtures.BUILD}),
        verify_calls=True,
    )
    return kind, manifest, assets, repo, session


@pytest.mark.parametrize("tier1", [corpus.SCRIPT, corpus.MIGRATION], indirect=True)
@pytest.mark.parametrize("from_store", [False, True])
def test_refresh_records_original_tier1_procedure(
    tier1: tuple[str, dict[str, Any], Path, Path, PainterSession],
    tmp_path: Path,
    from_store: bool,
) -> None:
    kind, manifest, assets, repo, session = tier1
    assert corpus.recorder_kind(manifest, repo) == kind
    original = copy.deepcopy(manifest)
    store = OracleStore.init(tmp_path / "store") if from_store else None
    # Corrupt the production copy after pinning: only the verified store bytes may run/open.
    if store is not None:
        for item in manifest["inputs"]:
            if "assets3d_path" in item:
                file = assets / item["assets3d_path"]
                store.add_input(file, item["sha256"], item["assets3d_path"])
                file.write_bytes(b"changed after pinning\n")
    before = script_fixtures.tree_state(assets)
    run = corpus.record_golden(
        session,
        manifest,
        tmp_path / "work",
        tmp_path / "inbox",
        lambda: datetime.now(UTC),
        "candidate-",
        repo,
        store=store,
    )  # default Assets3D root is the repository's sibling
    record = load_json(run / "record.json")
    assert record_problems(record) == []
    assert [r["recording_id"] for r in record["recordings"]] == ["r1", "r1-repeat", "r2"]
    assert record["key"]["painter_build"]["build_id"] == script_fixtures.BUILD
    assert all(any(o["kind"] == "exported_map" for o in r["outputs"]) for r in record["recordings"])
    public = load_json(run / "manifest.json")
    assert all(r["record_id"].startswith("candidate-") for r in public["private_records"])
    assert script_fixtures.tree_state(assets) == before
    assert manifest == original


@pytest.mark.parametrize("tier1", [corpus.SCRIPT, corpus.MIGRATION], indirect=True)
def test_refresh_refuses_wrong_pins_before_connecting(
    tier1: tuple[str, dict[str, Any], Path, Path, PainterSession],
    tmp_path: Path,
) -> None:
    _, manifest, assets, repo, session = tier1
    item = next(i for i in manifest["inputs"] if "assets3d_path" in i)
    (assets / item["assets3d_path"]).write_bytes(b"not the pinned input\n")
    with pytest.raises(RecorderError, match="not the pinned one"):
        corpus.record_golden(
            session,
            manifest,
            tmp_path / "work",
            tmp_path / "inbox",
            lambda: datetime.now(UTC),
            repo_root=repo,
            assets_root=assets,
        )
    assert session.identity is None
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("tier1", [corpus.SCRIPT, corpus.MIGRATION], indirect=True)
def test_refresh_keeps_build_guard(
    tier1: tuple[str, dict[str, Any], Path, Path, PainterSession],
    tmp_path: Path,
) -> None:
    _, manifest, assets, repo, session = tier1
    session.allowed_builds = lambda: frozenset({"unrecordable-build"})
    with pytest.raises(UnseenBuild):
        corpus.record_golden(
            session,
            manifest,
            tmp_path / "work",
            tmp_path / "inbox",
            lambda: datetime.now(UTC),
            repo_root=repo,
            assets_root=assets,
        )
    assert not (tmp_path / "work").exists()
