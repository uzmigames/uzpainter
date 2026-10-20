"""Input rewrites occur at the same remote-call boundary as the oracle recorder."""

from __future__ import annotations

import ast
import os
import shutil
from pathlib import Path
from typing import Any

from tests.python.observed_replay import REPLAY, step_payload
from tools.parity.recorder.probes import RELOAD_RESOURCES, SHELVES_ADD, ProbeStep


def test_reload_sees_rewritten_input_in_both_recordings(tmp_path: Path) -> None:
    target, source = tmp_path / "texture.png", tmp_path / "mesh.obj"
    target.write_bytes(b"original texture")
    source.write_bytes(b"replacement mesh")
    step = ProbeStep(
        24,
        RELOAD_RESOURCES,
        {"rewrite_input": "texture", "with_input": "mesh"},
        probe=True,
    )
    payload = step_payload(step, {"texture": target, "mesh": source}, tmp_path)
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
    for recording in ("r1", "r2"):
        target.write_bytes(b"original texture")
        namespace["run_step"](payload, str(tmp_path / recording / "work-files"))
    assert observed == [b"replacement mesh", b"replacement mesh"]
    assert source.read_bytes() == b"replacement mesh"
