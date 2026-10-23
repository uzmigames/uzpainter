"""Mixed-colour refreshes on the fake Painter; no real application is launched."""

from __future__ import annotations

import copy
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.parity.test_oracle_envelope import FakeProcess, Painter, Repo, load_fake, world
from tools.parity.envelope import colour_sessions as colours
from tools.parity.envelope.refresh import (
    INCOMPLETE,
    PROMOTED,
    Candidate,
    check_run,
    consistency_problems,
    open_candidate,
)
from tools.parity.envelope.registry import envelope_directory, load_registry
from tools.parity.recorder.environment import envelope_sha256
from tools.parity.recorder.launcher import PainterLauncher
from tools.parity.recorder.output import RECORD_FILE
from tools.parity.recorder.session import IdentityChanged, PainterSession, RecorderError
from tools.parity.schemas import load_json


@pytest.fixture
def mixed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Repo, Path]:
    monkeypatch.delenv("OCIO", raising=False)
    monkeypatch.delenv("PAINTER_ACE_CONFIG", raising=False)
    repo = Repo(tmp_path, load_fake())
    config = tmp_path / "Painter" / "resources" / "test.ocio"
    config.parent.mkdir(parents=True)
    config.write_text("ocio_profile_version: 2\n", encoding="utf-8")
    manifest = load_json(repo.manifests[1])
    manifest["applied_settings"].append(
        {
            "name": "OCIO",
            "value": "resources/test.ocio",
            "applied_by": "environment_variable",
        }
    )
    repo.manifests[1].write_text(json.dumps(manifest), encoding="utf-8")
    return repo, config


def candidate(repo: Repo) -> Candidate:
    entry = load_registry(repo.root)["candidate"]
    folder = envelope_directory(entry["envelope_id"])
    work = repo.work / "envelopes" / folder
    return Candidate(
        entry, load_json(work / "candidate.json"), work, repo.inbox / "envelopes" / folder
    )


def test_without_launcher_records_only_declared_running_colour(
    mixed: tuple[Repo, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, config = mixed
    transport = repo.fake.LocalTransport(world(repo.fake, "12.2.0"))
    outcome = repo.ensure(transport)
    assert outcome.outcome == INCOMPLETE
    before = candidate(repo)
    rows = list(before.ledger["goldens"].values())
    assert [r["status"] for r in rows] == ["recorded", "pending"]
    assert "--launch" in rows[1]["error"]
    legacy_run = Path(rows[0]["run"]).joinpath(RECORD_FILE).read_bytes()
    anchor = before.entry["envelope_sha256"]
    monkeypatch.setenv("OCIO", str(config))
    outcome = repo.ensure(repo.fake.LocalTransport(world(repo.fake, "12.2.0")))
    assert outcome.outcome == PROMOTED
    registry = load_registry(repo.root)
    current = registry["envelopes"][-1]
    assert current["envelope_sha256"] == anchor
    assert current["equivalent_envelopes"] == []
    assert Path(rows[0]["run"]).joinpath(RECORD_FILE).read_bytes() == legacy_run
    ledger = load_json(before.ledger_path)
    assert set(ledger["colour_sessions"]) == {"legacy", "ocio:resources/test.ocio"}
    assert ledger["colour_sessions"]["ocio:resources/test.ocio"]["configuration_sha256"]


def test_owned_launcher_switches_groups_and_restores_legacy(
    mixed: tuple[Repo, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, config = mixed
    painter = Painter(repo.fake, lambda _: world(repo.fake, "12.2.0"))

    class Launcher(PainterLauncher):
        def start(self, environment: dict[str, str | None] | None = None) -> None:
            for key, value in (environment or {}).items():
                if value is None:
                    monkeypatch.delenv(key, raising=False)
                else:
                    monkeypatch.setenv(key, value)
            super().start()

    launcher = Launcher(
        exe=config.parents[1] / "Painter.exe",
        popen=painter.start_process,
        answers=painter.answers,
        sleep=lambda _: None,
    )
    launcher.start()
    assert repo.ensure(painter, launcher=launcher).outcome == PROMOTED
    assert painter.starts == 3
    assert "OCIO" not in os.environ and "PAINTER_ACE_CONFIG" not in os.environ
    assert repo.session(painter.world).read_identity().colour_management["mode"] == "legacy"


@pytest.mark.parametrize("field", ["painter_build", "gpu_model", "driver_version", "os_build"])
def test_colour_change_never_changes_host(mixed: tuple[Repo, Path], field: str) -> None:
    repo, _ = mixed
    identity = repo.session(world(repo.fake, "12.2.0")).read_identity()
    assert identity.environment is not None
    ledger = {"anchor_environment": identity.environment, "colour_sessions": {}}
    changed = {**identity.environment, field: "different"}
    with pytest.raises(IdentityChanged, match="build or host"):
        colours.bind(ledger, replace(identity, environment=changed), "legacy")
    with pytest.raises(IdentityChanged, match="unknown"):
        colours.bind(ledger, replace(identity, environment={**changed, field: "unknown"}), "legacy")


def test_configuration_bytes_are_pinned(
    mixed: tuple[Repo, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, config = mixed
    identity = repo.session(world(repo.fake, "12.2.0")).read_identity()
    ledger = {"anchor_environment": identity.environment, "colour_sessions": {}}
    monkeypatch.setenv("OCIO", str(config))
    ocio = repo.session(world(repo.fake, "12.2.0")).read_identity()
    colours.bind(ledger, ocio, "ocio:resources/test.ocio")
    config.write_text("different contents", encoding="utf-8")
    with pytest.raises(IdentityChanged, match="session changed"):
        colours.bind(ledger, ocio, "ocio:resources/test.ocio")
    with pytest.raises(RecorderError, match="does not match"):
        colours.bind(ledger, ocio, "legacy")


def test_run_cannot_borrow_another_colours_slot(mixed: tuple[Repo, Path]) -> None:
    repo, _ = mixed
    assert repo.ensure(repo.fake.LocalTransport(world(repo.fake, "12.2.0"))).outcome == INCOMPLETE
    item = candidate(repo)
    golden, info = next(iter(item.ledger["goldens"].items()))
    info["colour"] = "ocio:resources/test.ocio"
    item.ledger["colour_sessions"][info["colour"]] = copy.deepcopy(
        item.ledger["colour_sessions"]["legacy"]
    )
    with pytest.raises(IdentityChanged, match="another colour declaration"):
        check_run(Path(info["run"]), golden, item)
    assert any("declaration" in p for p in consistency_problems(item, repo.root))


def test_v1_candidate_upgrades_existing_evidence_without_rewriting_runs(
    mixed: tuple[Repo, Path],
) -> None:
    repo, _ = mixed
    transport = repo.fake.LocalTransport(world(repo.fake, "12.2.0"))
    assert repo.ensure(transport).outcome == INCOMPLETE
    item = candidate(repo)
    item.ledger.pop("anchor_environment")
    item.ledger.pop("colour_sessions")
    for row in item.ledger["goldens"].values():
        row.pop("colour")
    item.save()
    identity = repo.session(transport.world).read_identity()
    resumed = open_candidate(identity, repo.work, repo.inbox, repo.clock().date(), repo.root)
    assert resumed.entry == item.entry
    assert envelope_sha256(resumed.ledger["anchor_environment"]) == item.entry["envelope_sha256"]
    assert next(iter(resumed.ledger["goldens"].values()))["status"] == "recorded"


@pytest.mark.parametrize("change", ["bytes", "build", "process", "process-restart"])
def test_abort_in_second_colour_closes_current_project_and_keeps_previous(
    mixed: tuple[Repo, Path],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    repo, config = mixed
    original_current = load_registry(repo.root)["current"]
    seen: list[Any] = []
    cleanup_guards: list[bool] = []

    def make_world(number: int) -> Any:
        state = world(repo.fake, "12.2.0")
        seen.append(state)
        if number == 2:

            def mutate(_: Path) -> None:
                if change == "bytes":
                    config.write_text("altered during recording", encoding="utf-8")
                elif change == "build":
                    state.version, state.version_info = "12.2.1", (12, 2, 1)
                else:
                    painter.transport.namespace["uzp_recorder"]["session_id"] = (
                        "replacement-process"
                    )

            state.export_hook = mutate
        return state

    painter = Painter(repo.fake, make_world)

    class Launcher(PainterLauncher):
        def start(self, environment: dict[str, str | None] | None = None) -> None:
            for key, value in (environment or {}).items():
                if value is None:
                    monkeypatch.delenv(key, raising=False)
                else:
                    monkeypatch.setenv(key, value)
            super().start()

        def stop(self, session: PainterSession | None = None) -> None:
            if len(seen) == 2 and session is not None:
                cleanup_guards.append(session.verify_calls)
            super().stop(session)

    launcher = Launcher(
        exe=config.parents[1] / "Painter.exe",
        popen=painter.start_process,
        answers=painter.answers,
        sleep=lambda _: None,
    )
    launcher.start()
    if change == "process-restart":
        assert repo.ensure(painter, launcher=launcher, max_restarts=1).outcome == PROMOTED
        assert cleanup_guards == [True]
        assert seen[1].project_open  # stop must not close the replacement endpoint's project
        assert len(load_registry(repo.root)["quarantine"]) == 1
        return
    with pytest.raises(RecorderError, match="refresh aborted"):
        repo.ensure(painter, launcher=launcher, max_restarts=0)
    registry = load_registry(repo.root)
    assert registry["current"] == original_current and registry["candidate"] is None
    assert registry["quarantine"]
    if change != "process":
        assert not seen[-1].project_open
    else:
        assert seen[-1].project_open  # a replacement process's project is not ours to close


def test_changed_declared_config_on_resume_does_not_reassociate_hashes(
    mixed: tuple[Repo, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, config = mixed
    assert repo.ensure(repo.fake.LocalTransport(world(repo.fake, "12.2.0"))).outcome == INCOMPLETE
    item = candidate(repo)
    monkeypatch.setenv("OCIO", str(config))
    identity = repo.session(world(repo.fake, "12.2.0")).read_identity()
    colours.bind(item.ledger, identity, "ocio:resources/test.ocio")
    item.save()
    config.write_text("different on resume", encoding="utf-8")
    with pytest.raises(RecorderError, match="refresh aborted"):
        repo.ensure(repo.fake.LocalTransport(world(repo.fake, "12.2.0")), max_restarts=0)
    registry = load_registry(repo.root)
    assert registry["candidate"] is None
    assert registry["current"] == item.entry["previous"]


def test_launcher_child_environment_isolated_and_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "Painter.exe"
    executable.write_bytes(b"fake")
    monkeypatch.setenv("OCIO", "parent-config")
    monkeypatch.setenv("PAINTER_ACE_CONFIG", "parent-ace")
    captured: list[dict[str, Any]] = []
    process = FakeProcess()

    def spawn(command: list[str], **kwargs: Any) -> FakeProcess:
        captured.append(kwargs)
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)
    launcher = PainterLauncher(exe=executable, answers=lambda: bool(captured) and process.alive)
    launcher.start({"OCIO": "child-config", "PAINTER_ACE_CONFIG": None})
    assert captured[0]["env"]["OCIO"] == "child-config"
    assert "PAINTER_ACE_CONFIG" not in captured[0]["env"]
    assert os.environ["OCIO"] == "parent-config"
    assert os.environ["PAINTER_ACE_CONFIG"] == "parent-ace"
    launcher.stop()
    foreign = PainterLauncher(exe=executable, answers=lambda: True)
    with pytest.raises(RecorderError, match="already answers"):
        foreign.start({"OCIO": "child-config"})
    assert len(captured) == 1


def test_launcher_verifies_endpoint_even_without_per_call_guard(mixed: tuple[Repo, Path]) -> None:
    repo, config = mixed
    painter = Painter(repo.fake, lambda _: world(repo.fake))
    launcher = PainterLauncher(
        exe=config.parents[1] / "Painter.exe",
        popen=painter.start_process,
        answers=painter.answers,
        sleep=lambda _: None,
    )
    launcher.start()
    session = repo.factory(
        painter, lambda: dict(repo.session(painter.world).read_host_environment())
    )(
        lambda: frozenset({"12.1.0+js-api.1.1.20"}),
        False,
    )
    session.connect()
    painter.world.project_open = True
    painter.transport.namespace["uzp_recorder"]["session_id"] = "unrelated-endpoint"
    launcher.stop(session)
    assert painter.world.project_open
    assert painter.process.terminated
