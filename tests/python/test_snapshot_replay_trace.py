"""CPU-only checks of strict source replay evidence publication and output attribution."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tests.python import snapshot_replay_trace as helper
from tests.python.capability_trace import BOOKKEEPING
from tests.python.test_snapshot_capture_replay import probe_steps

NAME = "source-substance-held-property"
PRIVATE = "private readback sentinel"


def observations() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, list[str]]]:
    steps = probe_steps(NAME)
    values = {f"s{step['step']}": {"value": 1.0} for step in steps}
    recordings = [deepcopy(values), deepcopy(values)]
    trace = {
        f"r{condition}/{key}": [f"api.output_{condition}_{key}"]
        for condition in (1, 2)
        for key in values
    }
    trace.update(setup=["api.setup"], bookkeeping=["api.bookkeeping"])
    return steps, recordings, trace


@pytest.mark.parametrize("original,replacement", [(1.0, 1), (1, True), (1.0, PRIVATE), (0.0, -0.0)])
def test_a_typed_difference_never_publishes(
    monkeypatch: pytest.MonkeyPatch, original: Any, replacement: Any
) -> None:
    steps, recorded, trace = observations()
    recorded[1]["s12"] = {"value": original}
    observed = deepcopy(recorded)
    observed[1]["s12"] = {"value": replacement}
    publish = Mock()
    monkeypatch.setattr(helper, "check_trace", publish)
    monkeypatch.setenv("UZP_UPDATE_TIER0_TRACE", "1")
    with pytest.raises(pytest.fail.Exception, match="differs at r2/s12") as error:
        helper.finalize_trace(NAME, steps, recorded, observed, trace)
    assert PRIVATE not in str(error.value)
    publish.assert_not_called()


def test_only_all_compared_outputs_contribute_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    steps, recorded, trace = observations()
    publish = Mock()
    monkeypatch.setattr(helper, "check_trace", publish)
    symbols = helper.finalize_trace(NAME, steps, recorded, deepcopy(recorded), trace)
    expected = sorted(
        symbol for key, names in trace.items() if key.startswith("r") for symbol in names
    )
    assert symbols == expected
    publish.assert_called_once_with(
        f"facade/snapshot-v3/{NAME}", f"tier0/api-probes/{NAME}", expected
    )


@pytest.mark.parametrize("change", ["missing", "unknown", "malformed", "missing_recording_step"])
def test_invalid_marks_or_result_fail_without_private_values(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    steps, recorded, trace = observations()
    observed = deepcopy(recorded)
    if change == "missing":
        del trace["r2/s12"]
    elif change == "unknown":
        trace[PRIVATE] = [PRIVATE]
    elif change == "malformed":
        trace["r2/s12"] = PRIVATE  # type: ignore[assignment]
    else:
        del observed[1]["s12"]
        observed[1][PRIVATE] = {"value": PRIVATE}
    publish = Mock()
    monkeypatch.setattr(helper, "check_trace", publish)
    with pytest.raises(pytest.fail.Exception) as error:
        helper.finalize_trace(NAME, steps, recorded, observed, trace)
    assert PRIVATE not in str(error.value)
    publish.assert_not_called()


@pytest.mark.parametrize("result", [None, {}, [[], {}], [[{PRIVATE: PRIVATE}], {}]])
def test_malformed_runner_result_is_sanitized(result: Any) -> None:
    with pytest.raises(pytest.fail.Exception) as error:
        helper.replay_traced(lambda script: {"status": "ok", "result": result}, NAME)
    assert PRIVATE not in str(error.value)


def test_runner_failure_is_sanitized_and_saved_privately(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(helper, "private_dir", lambda: tmp_path)
    report = {"status": "failed", "error": {"type": "ValueError", "message": PRIVATE}}
    with pytest.raises(pytest.fail.Exception) as error:
        helper.replay_traced(lambda script: report, NAME)
    assert "details kept privately" in str(error.value)
    assert PRIVATE not in str(error.value)
    path = tmp_path / f"source-replay-trace-failure-{NAME}.json"
    assert json.loads(path.read_text(encoding="utf-8")) == report
    assert list(tmp_path.iterdir()) == [path]


def test_private_diagnostic_write_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(helper, "private_dir", lambda: tmp_path)

    def refuse_write(path: Path, data: str, **kwargs: Any) -> int:
        raise PermissionError(PRIVATE)

    monkeypatch.setattr(Path, "write_text", refuse_write)
    with pytest.raises(pytest.fail.Exception) as error:
        helper.replay_traced(lambda script: {"status": "failed", "error": PRIVATE}, NAME)
    assert "private diagnostic could not be written" in str(error.value)
    assert error.value.__context__ is None
    assert error.value.pytrace is False
    assert "details kept privately" not in str(error.value)
    assert PRIVATE not in str(error.value)
    assert list(tmp_path.iterdir()) == []


def test_replay_preserves_two_recordings_and_trace() -> None:
    steps, recorded, trace = observations()
    scripts: list[str] = []

    def run(script: str) -> dict[str, Any]:
        scripts.append(script)
        return {"status": "ok", "result": [recorded, trace]}

    assert helper.replay_traced(run, NAME) == (recorded, steps, trace)
    assert len(scripts) == 1
    compile(scripts[0], "authored-replay", "exec")


@pytest.mark.parametrize("fail_locator", [False, True])
def test_driver_excludes_lifecycle_and_locator_calls_and_restores_marks(fail_locator: bool) -> None:
    marked = [BOOKKEEPING]
    calls: list[tuple[str, str]] = []

    def mark(output: str) -> None:
        marked[0] = output

    def note(operation: str) -> None:
        calls.append((operation, marked[0]))

    def locate(stack: Any) -> list[Any]:
        note("locate")
        if fail_locator:
            raise ValueError("authored locator failure")
        return [SimpleNamespace(uid=lambda: 6)]

    namespace: dict[str, Any] = {
        "BOOKKEEPING": BOOKKEEPING,
        "_TRACE": {"mark": mark},
        "NODE_STEP": 3,
        "FILL_UID": 6,
        "WORK": "authored",
        "steps": [{"step": 6, "call": "authored.get", "args": {}}],
        "ls": SimpleNamespace(get_root_layer_nodes=locate),
        "ts": SimpleNamespace(get_active_stack=lambda: note("stack")),
        "uzpainter": SimpleNamespace(
            project=SimpleNamespace(
                open=lambda path: note("open"),
                save=lambda: note("save"),
                close=lambda: note("close"),
            )
        ),
        "describe": lambda value: value,
    }

    def read(call: str, args: dict[str, Any]) -> int:
        try:
            namespace["fresh"](3)
        finally:
            note("source")
        return 7

    namespace["substance_read"] = read
    exec(helper._ADAPTATION + helper._DRIVER, namespace)
    assert [output for operation, output in calls if operation == "source"] == ["r1/s6", "r2/s6"]
    assert all(output == BOOKKEEPING for operation, output in calls if operation != "source")
    assert marked == [BOOKKEEPING]
    assert len(namespace["result"]) == 2
    if fail_locator:
        assert namespace["result"][0]["s6"]["raised"]["type"] == "ValueError"
