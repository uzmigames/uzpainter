"""Trace only strictly compared outputs of the private metadata /3 source replay."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.python.capability_trace import BOOKKEEPING, check_trace, exercised, traced
from tests.python.conftest import Run
from tests.python.test_snapshot_capture_replay import (
    FILL_UID,
    NODE_STEP,
    PRELUDE,
    PROBES,
    REPLAYED,
    private_dir,
    probe_steps,
    recorder_code,
    typed,
)

_ADAPTATION = """
CURRENT_OUTPUT = BOOKKEEPING

def fresh(step):
    _TRACE['mark'](BOOKKEEPING)
    try:
        assert int(step) == NODE_STEP
        node = ls.get_root_layer_nodes(ts.get_active_stack())[0]
        assert node.uid() == FILL_UID
        return node
    finally:
        _TRACE['mark'](CURRENT_OUTPUT)

def channel_arg(args):
    return getattr(ts.ChannelType, args['channel'])
"""

_DRIVER = """
def replay_recording(condition):
    global CURRENT_OUTPUT
    observed = {}
    for step in steps:
        key = 's' + str(step['step'])
        call, args = step['call'], dict(step['args'])
        read = 'roundtrip' not in args
        CURRENT_OUTPUT = condition + '/' + key
        _TRACE['mark'](CURRENT_OUTPUT)
        try:
            value = substance_read(call, args) if read else substance_edit(call, args)
            observed[key] = {'value': describe(value)}
        except Exception as error:
            observed[key] = {
                'raised': {'type': type(error).__name__, 'message': str(error)}
            }
        finally:
            CURRENT_OUTPUT = BOOKKEEPING
            _TRACE['mark'](BOOKKEEPING)
    return observed

uzpainter.project.open(WORK + '/captured.uzp')
first = replay_recording('r1')
uzpainter.project.save()
uzpainter.project.close()
uzpainter.project.open(WORK + '/captured.uzp')
second = replay_recording('r2')
uzpainter.project.close()
result = [first, second]
"""


def _keys(steps: list[dict[str, Any]]) -> set[str]:
    if not steps or any(type(step.get("step")) is not int for step in steps):
        pytest.fail("invalid replay step identities", pytrace=False)
    keys = {f"s{step['step']}" for step in steps}
    if len(keys) != len(steps):
        pytest.fail("duplicate replay step identities", pytrace=False)
    return keys


def _recordings(value: Any, keys: set[str]) -> list[dict[str, Any]]:
    if not (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(recording, dict) and set(recording) == keys for recording in value)
    ):
        pytest.fail("replay result is not two recordings of the probe's steps", pytrace=False)
    return value


def _trace(value: Any, keys: set[str]) -> dict[str, list[str]]:
    compared = {f"r{recording}/{key}" for recording in (1, 2) for key in keys}
    if not (
        isinstance(value, dict)
        and compared <= set(value) <= compared | {"setup", BOOKKEEPING}
        and all(
            isinstance(symbols, list) and all(isinstance(symbol, str) for symbol in symbols)
            for symbols in value.values()
        )
    ):
        pytest.fail("replay trace has missing, unknown or malformed output marks", pytrace=False)
    return value


def replay_traced(
    private_facade: Run, name: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, list[str]]]:
    """Run the recorder's serializers with per-recording output marks, using the private runner."""
    if name not in PROBES:
        pytest.fail("unknown source replay probe", pytrace=False)
    steps = probe_steps(name)
    body = (
        f"BOOKKEEPING = {BOOKKEEPING!r}\n_TRACE['mark'](BOOKKEEPING)\n"
        + PRELUDE
        + recorder_code(REPLAYED)
        + _ADAPTATION
        + f"\nNODE_STEP = {NODE_STEP}\nFILL_UID = {FILL_UID}\nsteps = {steps!r}\n"
        + _DRIVER
    )
    report = private_facade(traced(body))
    if report.get("status") != "ok":
        saved = False
        try:
            path = private_dir() / f"source-replay-trace-failure-{name}.json"
            path.write_text(json.dumps(report, indent=1), encoding="utf-8")
            saved = True
        except (OSError, TypeError, ValueError):
            pass
        if not saved:
            pytest.fail(
                "traced source replay failed; private diagnostic could not be written",
                pytrace=False,
            )
        pytest.fail("traced source replay failed (details kept privately)", pytrace=False)
    result = report.get("result")
    if not isinstance(result, list) or len(result) != 2:
        pytest.fail("traced source replay returned a malformed envelope", pytrace=False)
    keys = _keys(steps)
    return _recordings(result[0], keys), steps, _trace(result[1], keys)


def finalize_trace(
    name: str,
    steps: list[dict[str, Any]],
    recorded: Any,
    observed: Any,
    trace: Any,
) -> list[str]:
    """Validate every typed output before checking or updating any capability evidence."""
    if name not in PROBES or steps != probe_steps(name):
        pytest.fail("source replay steps do not match the declared probe", pytrace=False)
    keys = _keys(steps)
    expected = _recordings(recorded, keys)
    actual = _recordings(observed, keys)
    checked_trace = _trace(trace, keys)
    for condition, (wanted, got) in enumerate(zip(expected, actual, strict=True), 1):
        for key in sorted(keys):
            if typed(wanted[key]) != typed(got[key]):
                pytest.fail(f"source replay differs at r{condition}/{key}", pytrace=False)
    selected = {
        key: value for key, value in checked_trace.items() if key not in {"setup", BOOKKEEPING}
    }
    symbols = exercised(selected)
    check_trace(f"facade/snapshot-v3/{name}", f"tier0/api-probes/{name}", symbols)
    return symbols
