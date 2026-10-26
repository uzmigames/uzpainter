"""Opt-in readback preparation; no changes to recipe A or recorder lifecycle."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Protocol

from tools.parity.filter_context_contract import CONDITIONS, SCHEMA, SPEC, parse_context_readback

PAINTER_FILTER_CONTEXT = Path(__file__).with_name("painter_filter_context.py")


class ContextSession(Protocol):
    def call(self, operation: str, **args: Any) -> Any: ...


def extension_code(source: str) -> str:
    """Install next to probes; only the shared dispatch dictionary gains an operation."""
    payload = base64.b64encode(source.encode()).decode("ascii")
    configuration = base64.b64encode(
        json.dumps(
            {
                "FILTER_CONTEXT_SCHEMA": SCHEMA,
                "FILTER_CONTEXT_SPEC": SPEC,
                "FILTER_CONTEXT_CONDITIONS": CONDITIONS,
            }
        ).encode()
    ).decode("ascii")
    return (
        "import base64, json\n"
        "uzp_filter_context = dict(uzp_probes)\n"
        f"uzp_filter_context.update(json.loads(base64.b64decode('{configuration}')))\n"
        f"exec(base64.b64decode('{payload}').decode('utf-8'), uzp_filter_context)\n"
    )


def context_readback(session: ContextSession, boundary: str) -> dict[str, Any]:
    if boundary not in CONDITIONS:
        raise ValueError("unknown F context boundary")
    value = session.call("filter_context_read", boundary=boundary, condition=CONDITIONS[boundary])
    frame = parse_context_readback(json.dumps(value, ensure_ascii=False, allow_nan=False).encode())
    if frame["boundary"] != boundary:
        raise ValueError("F context returned another boundary")
    return frame


def context_outputs(session: ContextSession, boundary: str) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = context_readback(session, boundary)["outputs"]
    return outputs


def step_trace(condition: str, step: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
    """Keep an actual operation outcome; documented refusals remain observations."""
    result = {"value": outcome.get("value")}
    if "raised" in outcome:
        result["raised"] = outcome["raised"]
    return {
        "kind": "step",
        "condition": condition,
        "step": step["step"],
        "call": step["call"],
        "args": step["args"],
        "outcome": result,
    }
