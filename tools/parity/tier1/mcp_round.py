"""The report of a pilot's MCP-only round, `parity/reports/phase2/<pilot>-mcp-round.json` (task
phase2.9_pilot-belt item 2.5; `docs/architecture/11-mcp-server.md` §6, §7; decision 192).

The round runs a pilot's production round (project creation with the mesh, its settings and mesh
maps; the stack sync with its resources; save; export) through typed MCP tools against a
supervisor started without `--allow-python` (`tests/parity/tier1/mcp_round.py`). The report holds
the call log with each call's receipt, the round's outcome and, per exported map, its SHA-256 next
to the Tier 1 run's (the same pilot rebuilt through the pipeline adapter):

- `python`: `run_python` was not listed and the supervisor had no `--allow-python`;
- `calls`: one entry per tool call in order: the tool, whether it is a typed tool (never
  `run_python`), its outcome (`committed`, `no_op`, `returned` for a read, or `error` with its
  code), the receipt's admission and committed revision, and the SHA-256 of the canonical receipt;
- `outcome`: `completed` when every call succeeded, `refused` when the export refused before
  writing (a feature UzPainter does not support yet, named in `refusal`), `failed` otherwise;
- `maps` and `equal_to_tier1`: `equal` only when both runs wrote the same maps byte for byte,
  `different` when both wrote maps and the map sets or any map's bytes differ, `not_measured` when
  either run wrote nothing or the round did not complete (nothing was compared).

The file holds numbers, enums, identifiers, dates and SHA-256 digests only, and no oracle data
(both sides are UzPainter's outputs); the repository guard checks it with `report_problems`.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_ID = "uzpainter/pilot-mcp-round/1"
OUTCOMES = ("completed", "refused", "failed")
CALL_OUTCOMES = ("committed", "no_op", "returned", "error")
EQUALITY = ("equal", "different", "not_measured")

_SHA256 = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_ID = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._/:-]*$"}

SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema",
        "golden_id",
        "manifest_sha256",
        "run",
        "python",
        "calls",
        "outcome",
        "maps",
        "equal_to_tier1",
    ],
    "properties": {
        "schema": {"const": SCHEMA_ID},
        "golden_id": _ID,
        "manifest_sha256": _SHA256,
        "run": {
            "type": "object",
            "additionalProperties": False,
            "required": ["date", "exe_sha256", "backend", "tools_listed"],
            "properties": {
                "date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                "exe_sha256": _SHA256,
                "backend": {"enum": ["dx12", "vulkan"]},
                "tools_listed": {"type": "integer", "minimum": 1},
            },
        },
        "python": {
            "type": "object",
            "additionalProperties": False,
            "required": ["allow_python", "run_python_listed"],
            "properties": {
                "allow_python": {"const": False},
                "run_python_listed": {"const": False},
            },
        },
        "calls": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["step", "tool", "typed", "outcome", "receipt_sha256", "seconds"],
                "properties": {
                    "step": {"type": "integer", "minimum": 1},
                    "tool": _ID,
                    "typed": {"const": True},
                    "outcome": {"enum": list(CALL_OUTCOMES)},
                    "error_code": _ID,
                    "admission": _ID,
                    "committed_revision": {"type": ["integer", "null"], "minimum": 0},
                    "receipt_sha256": _SHA256,
                    "seconds": {"type": "number", "minimum": 0},
                },
            },
        },
        "outcome": {"enum": list(OUTCOMES)},
        "refusal": {
            "type": "object",
            "additionalProperties": False,
            "required": ["tool", "error_code"],
            "properties": {"tool": _ID, "error_code": _ID, "type": _ID},
        },
        "maps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["texture_set", "map", "sha256", "tier1_sha256"],
                "properties": {
                    "texture_set": _ID,
                    "map": _ID,
                    "sha256": {"anyOf": [_SHA256, {"type": "null"}]},
                    "tier1_sha256": {"anyOf": [_SHA256, {"type": "null"}]},
                },
            },
        },
        "equal_to_tier1": {"enum": list(EQUALITY)},
    },
}
_VALIDATOR = Draft202012Validator(SCHEMA)


class RoundReportError(ValueError):
    """A round report that breaks its schema or its rules."""


def report_problems(document: Any) -> list[str]:
    """Why `document` is not a pilot MCP-round report (empty when it is one)."""
    problems = [
        f"{'/'.join(str(p) for p in error.absolute_path) or '(root)'}: {error.message}"
        for error in _VALIDATOR.iter_errors(document)
    ]
    if problems:
        return problems
    calls, outcome = document["calls"], document["outcome"]
    if [call["step"] for call in calls] != list(range(1, len(calls) + 1)):
        problems.append("calls: steps must be numbered 1..n in order")
    errors = [call for call in calls if call["outcome"] == "error"]
    problems += [
        f"calls/{call['step'] - 1}: an error names its error_code"
        for call in errors
        if "error_code" not in call
    ]
    if outcome == "completed" and errors:
        problems.append("outcome: a completed round has no failed call")
    if outcome == "refused" and ("refusal" not in document or len(errors) != 1):
        problems.append("outcome: a refused round names its refusal, its one failed call")
    if outcome != "refused" and "refusal" in document:
        problems.append("refusal: only a refused round names one")
    maps = document["maps"]
    keys = [(m["texture_set"], m["map"]) for m in maps]
    problems += [f"maps: {key} is listed twice" for key in {k for k in keys if keys.count(k) > 1}]
    expected = equality(outcome, maps)
    if document["equal_to_tier1"] != expected:
        problems.append(f"equal_to_tier1: the maps listed make it {expected}")
    return problems


def equality(outcome: str, maps: list[dict[str, Any]]) -> str:
    """`equal_to_tier1` of a round with `outcome` and `maps` (the rule `report_problems` checks)."""
    wrote = any(m["sha256"] for m in maps) and any(m["tier1_sha256"] for m in maps)
    if outcome != "completed" or not wrote:
        return "not_measured"
    return "equal" if all(m["sha256"] == m["tier1_sha256"] for m in maps) else "different"


def write_report(document: dict[str, Any], path: Path) -> None:
    """Writes a valid report (validated first, then replaced atomically)."""
    problems = report_problems(document)
    if problems:
        raise RoundReportError(f"{path.name}: refusing to write an invalid report: {problems[:5]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    temporary.replace(path)
