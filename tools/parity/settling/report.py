"""The supervisor settling report, `parity/reports/phase2/supervisor-settling.json` (task
phase2.4_supervisor-worker items 2.3 and 4.1; `docs/architecture/02-runtime-topology.md` §7;
decision 150).

`tests/supervisor/` tags each test that settles a §7 case with `@pytest.mark.settling(<case>)`.
A run with `UZP_SETTLING_REPORT=<path>` merges what it ran into the report at that path: one
entry per case and backend (pass or fail, run time, the recoveries the supervisor reported, the
exe's SHA-256) and the per-call overhead of the MCP path against the single-process `run` path.
The CPU lane and the GPU run each merge their own backend. A case that has not run on a backend
is listed as `pending` (with the decision that defers it) or `not_run`, never as a pass.

The file holds numbers, booleans, identifiers, dates and SHA-256 digests only; the repository
guard checks it with `report_problems` (`tools/parity/guard/guard.py`).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_ID = "uzpainter/supervisor-settling/1"
TASK = "phase2.4_supervisor-worker"
REPORT = Path("parity") / "reports" / "phase2" / "supervisor-settling.json"
BACKENDS = ("dx12", "vulkan")

# The §7 cases and the backends each one must pass on. A case that needs a device is deferred on
# Vulkan until the Vulkan device exists (phase3.1_vulkan-compute-parity items 2.2 and 3.4,
# decision 121); `gpu_backend_unavailable` needs a backend without a device, which on this
# runtime is the Vulkan worker.
CASES: dict[str, tuple[str, ...]] = {
    "worker_killed_during_long_job": BACKENDS,
    "worker_killed_during_save": BACKENDS,
    "worker_killed_during_compaction": BACKENDS,
    "worker_killed_from_outside": BACKENDS,
    "native_abort": BACKENDS,
    "native_access_violation": BACKENDS,
    "commit_then_die_retry": BACKENDS,
    "replay_inside_window": BACKENDS,
    "replay_beyond_retention_lost_ledger": BACKENDS,
    "gpu_stall": BACKENDS,
    "device_lost": BACKENDS,
    "client_disconnect_reconnect": BACKENDS,
    "failure_comparison": BACKENDS,
    "python_disabled": BACKENDS,
    "gpu_backend_unavailable": ("vulkan",),
}
# Cases that need a GPU device: pending on Vulkan until it has one (decision 121).
DEVICE_CASES = frozenset({"gpu_stall", "device_lost"})
VULKAN_DEVICE_DECISION = 121
OVERHEAD_SNIPPETS = ("read", "mutation")

_ID = r"^[a-z0-9][a-z0-9_]{0,63}$"
_NUMBER = {"type": "number", "minimum": 0}
_SHA256 = {"type": "string", "pattern": r"^[0-9a-f]{64}$"}
_DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
_BACKEND = {"enum": list(BACKENDS)}

SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema", "task", "cases", "overhead"],
    "properties": {
        "schema": {"const": SCHEMA_ID},
        "task": {"const": TASK},
        "cases": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "backend", "result"],
                "properties": {
                    "id": {"enum": list(CASES)},
                    "backend": _BACKEND,
                    "result": {"enum": ["pass", "fail", "pending", "not_run"]},
                    "decision": {"type": "integer", "minimum": 1},
                    "date": _DATE,
                    "exe_sha256": _SHA256,
                    "gpu_status": {"enum": ["ready", "unavailable"]},
                    "seconds": _NUMBER,
                    "recoveries": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["cause", "recovery_ms", "attempts"],
                            "properties": {
                                "cause": {"type": "string", "pattern": _ID},
                                "recovery_ms": _NUMBER,
                                "attempts": {"type": "integer", "minimum": 1},
                            },
                        },
                    },
                    "metrics": {
                        "type": "object",
                        "propertyNames": {"pattern": _ID},
                        "additionalProperties": _NUMBER,
                    },
                },
            },
        },
        "overhead": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "backend",
                    "snippet",
                    "calls",
                    "mcp_median_ms",
                    "run_median_ms",
                    "overhead_median_ms",
                    "overhead_p90_ms",
                    "overhead_max_ms",
                    "date",
                    "exe_sha256",
                ],
                "properties": {
                    "backend": _BACKEND,
                    "snippet": {"enum": list(OVERHEAD_SNIPPETS)},
                    "calls": {"type": "integer", "minimum": 1},
                    "mcp_median_ms": _NUMBER,
                    "run_median_ms": _NUMBER,
                    "overhead_median_ms": {"type": "number"},
                    "overhead_p90_ms": {"type": "number"},
                    "overhead_max_ms": {"type": "number"},
                    "date": _DATE,
                    "exe_sha256": _SHA256,
                },
            },
        },
    },
}
_VALIDATOR = Draft202012Validator(SCHEMA)


class ReportError(Exception):
    """A settling report that would not pass the repository guard; nothing is written."""


def report_problems(document: Any) -> list[str]:
    """Why `document` is not a settling report (empty when it is one)."""
    problems = [
        f"{'/'.join(str(p) for p in error.absolute_path) or '(root)'}: {error.message}"
        for error in _VALIDATOR.iter_errors(document)
    ]
    if problems:
        return problems
    keys = [(case["id"], case["backend"]) for case in document["cases"]]
    problems += [f"cases: {key} is listed twice" for key in {k for k in keys if keys.count(k) > 1}]
    problems += [
        f"cases: {case['id']} on {case['backend']} is not a backend the case runs on"
        for case in document["cases"]
        if case["backend"] not in CASES[case["id"]]
    ]
    return problems


def _placeholder(case: str, backend: str) -> dict[str, Any]:
    if case in DEVICE_CASES and backend == "vulkan":
        return {
            "id": case,
            "backend": backend,
            "result": "pending",
            "decision": VULKAN_DEVICE_DECISION,
        }
    return {"id": case, "backend": backend, "result": "not_run"}


def merge(
    existing: Mapping[str, Any] | None,
    cases: Iterable[Mapping[str, Any]],
    overhead: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """The report `existing` with this run's case and overhead entries replacing those of the same
    case and backend (or snippet and backend); every case still missing on a backend is listed
    as `pending` or `not_run`."""
    by_case: dict[tuple[str, str], dict[str, Any]] = {}
    by_snippet: dict[tuple[str, str], dict[str, Any]] = {}
    if existing is not None:
        for case in existing.get("cases", []):
            if case["result"] in ("pass", "fail"):
                by_case[(case["id"], case["backend"])] = dict(case)
        for entry in existing.get("overhead", []):
            by_snippet[(entry["snippet"], entry["backend"])] = dict(entry)
    for case in cases:
        by_case[(case["id"], case["backend"])] = dict(case)
    for entry in overhead:
        by_snippet[(entry["snippet"], entry["backend"])] = dict(entry)
    listed = [
        by_case.get((case, backend)) or _placeholder(case, backend)
        for case, backends in CASES.items()
        for backend in backends
    ]
    return {
        "schema": SCHEMA_ID,
        "task": TASK,
        "cases": listed,
        "overhead": [by_snippet[key] for key in sorted(by_snippet, key=lambda k: (k[1], k[0]))],
    }


def write(
    path: Path, cases: Iterable[Mapping[str, Any]], overhead: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Merges a run into the report at `path` (validated first, then replaced atomically)."""
    existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    document = merge(existing, cases, overhead)
    problems = report_problems(document)
    if problems:
        raise ReportError(f"{path.name}: refusing to write an invalid report: {problems[:5]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    temporary.replace(path)
    return document


def identifier(text: str) -> str:
    """`text` as a report identifier (a recovery cause): lower case, `_` for anything else."""
    value = re.sub(r"[^a-z0-9_]", "_", text.lower())[:64]
    return value if re.match(_ID, value) else "unknown"
