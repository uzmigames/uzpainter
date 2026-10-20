"""Input rewrites occur at the same remote-call boundary as the oracle recorder."""

from __future__ import annotations

import ast
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.python.observed_replay import REPLAY, step_payload
from tools.parity.recorder.probes import RELOAD_RESOURCES, SHELVES_ADD, ProbeStep


@pytest.mark.parametrize("distinct_after_reopen", [False, True])
def test_reload_sees_rewritten_input_in_both_recordings(
    tmp_path: Path, distinct_after_reopen: bool
) -> None:
    target, source = tmp_path / "texture.png", tmp_path / "mesh.obj"
    target.write_bytes(b"original texture")
    source.write_bytes(b"replacement mesh")
    reopened_source = tmp_path / "reopened.obj"
    reopened_source.write_bytes(b"new version after reopen")
    args = {"rewrite_input": "texture", "with_input": "mesh"}
    if distinct_after_reopen:
        args["with_input_after_reopen"] = "reopened"
    step = ProbeStep(
        24,
        RELOAD_RESOURCES,
        args,
        probe=True,
    )
    staged = {"texture": target, "mesh": source, "reopened": reopened_source}
    payloads = {
        condition: step_payload(step, staged, tmp_path, condition)
        for condition in ("same_session", "after_save_reopen")
    }
    assert target.read_bytes() == b"original texture", "preparation must not rewrite the input"
    observed: list[bytes] = []

    def call(operation: str, **kwargs: Any) -> None:
        assert operation == "probe_step" and kwargs["call"] == RELOAD_RESOURCES
        observed.append(target.read_bytes())

    namespace: dict[str, Any] = {
        "os": os,
        "shutil": shutil,
        "PAYLOAD": {"shelves_add": SHELVES_ADD},
        "mark": lambda _: None,
        "call": call,
    }
    # Execute the generated replay's actual call boundary without starting an embedded host.
    function = next(
        node
        for node in ast.parse(REPLAY).body
        if isinstance(node, ast.FunctionDef) and node.name == "run_step"
    )
    exec(compile(ast.Module(body=[function], type_ignores=[]), "replay", "exec"), namespace)
    for condition, payload in payloads.items():
        target.write_bytes(b"original texture")
        namespace["run_step"](payload, str(tmp_path / condition / "work-files"))
    expected_reopened = (
        b"new version after reopen" if distinct_after_reopen else b"replacement mesh"
    )
    assert observed == [b"replacement mesh", expected_reopened]
    assert source.read_bytes() == b"replacement mesh"
    assert reopened_source.read_bytes() == b"new version after reopen"
    assert step.args == args
