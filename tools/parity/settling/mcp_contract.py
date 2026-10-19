"""The MCP contract report, `parity/reports/phase2/mcp-contract.json` (task phase2.8_mcp-server
items 2.3 and 4.1; `docs/architecture/11-mcp-server.md` §7 Phase 2; decision 186).

`tests/supervisor/` tags each test that runs a Phase 2 contract fixture with
`@pytest.mark.mcp_contract(<fixture>, transport=<stdio|http>)`: the children's tests are tagged,
never copied, and `test_mcp_contract.py` adds the fixtures and transports they do not cover. A run
with `UZP_MCP_CONTRACT_REPORT=<path>` merges what it ran into the report at that path: one entry
per fixture and transport (pass or fail, the number of tests and their run time, the exe's SHA-256
and the date). A fixture runs on the transports listed in `FIXTURES`; one that has not run there is
`not_run`, never a pass. Every fixture is GPU-free (Vulkan workers create no device).

The file holds numbers, enums, identifiers, dates and SHA-256 digests only, and no oracle data;
the repository guard checks it with `report_problems` (`tools/parity/guard/guard.py`). It shares
`ReportError` and the atomic replacement of the supervisor's report (`report.py`, decision 150).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from tools.parity.settling.report import ReportError

SCHEMA_ID = "uzpainter/mcp-contract/1"
TASK = "phase2.8_mcp-server"
REPORT = Path("parity") / "reports" / "phase2" / "mcp-contract.json"
TRANSPORTS = ("stdio", "http")

# The fixtures of 11 §7 (Phase 2, P2-MCP) and the transports each one runs on. A stdio supervisor
# has one client whose lease is implicit, so the second writer and the reconnect are HTTP's.
FIXTURES: dict[str, tuple[str, ...]] = {
    # 3.1: a second owner's mutating call is refused `lease_held {holder, since, active_job}`.
    "two_writers": ("http",),
    # 3.2: the client loses the reply of a committed mutation; its retry is the stored outcome.
    "lost_acknowledgement_retry": TRANSPORTS,
    # 3.2: killed after the durable commit, before the acknowledgement; the same request, then a
    # changed one with the same key (`idempotency_conflict`).
    "commit_then_die_retry": TRANSPORTS,
    # 3.3: a client disconnects during its long job and reconnects with its lease and job state.
    "http_reconnect": ("http",),
    # 3.4: a path outside the roots is refused before the worker sees it.
    "path_outside_roots": TRANSPORTS,
    # 3.4: a stale precondition is `stale_revision {expected, current}`.
    "stale_revision": TRANSPORTS,
    # 3.5: a known key inside the window after the revision advanced returns the stored result.
    "replay_inside_window": TRANSPORTS,
    # 3.5: beyond retention, compacted, ledger lost: neither replay creates a mutation.
    "replay_beyond_retention_lost_ledger": TRANSPORTS,
    # 3.6: every unavailable family and every operation still needing Python is a gap.
    "capability_gaps": TRANSPORTS,
}

_NUMBER = {"type": "number", "minimum": 0}

SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema", "task", "fixtures"],
    "properties": {
        "schema": {"const": SCHEMA_ID},
        "task": {"const": TASK},
        "fixtures": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "transport", "result"],
                "properties": {
                    "id": {"enum": list(FIXTURES)},
                    "transport": {"enum": list(TRANSPORTS)},
                    "result": {"enum": ["pass", "fail", "not_run"]},
                    "tests": {"type": "integer", "minimum": 1},
                    "seconds": _NUMBER,
                    "date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                    "exe_sha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
                },
            },
        },
    },
}
_VALIDATOR = Draft202012Validator(SCHEMA)


def report_problems(document: Any) -> list[str]:
    """Why `document` is not an MCP contract report (empty when it is one)."""
    problems = [
        f"{'/'.join(str(p) for p in error.absolute_path) or '(root)'}: {error.message}"
        for error in _VALIDATOR.iter_errors(document)
    ]
    if problems:
        return problems
    entries = document["fixtures"]
    keys = [(entry["id"], entry["transport"]) for entry in entries]
    problems += [
        f"fixtures: {key} is listed twice" for key in {k for k in keys if keys.count(k) > 1}
    ]
    problems += [
        f"fixtures: {entry['id']} does not run on {entry['transport']}"
        for entry in entries
        if entry["transport"] not in FIXTURES[entry["id"]]
    ]
    problems += [
        f"fixtures: {entry['id']} on {entry['transport']} ran without its tests, date and exe"
        for entry in entries
        if entry["result"] != "not_run" and not {"tests", "date", "exe_sha256"} <= entry.keys()
    ]
    return problems


def merge(
    existing: Mapping[str, Any] | None, entries: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """The report `existing` with this run's entries replacing those of the same fixture and
    transport; every fixture still missing on a transport is listed as `not_run`."""
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    if existing is not None:
        for entry in existing.get("fixtures", []):
            if entry["result"] != "not_run":
                by_key[(entry["id"], entry["transport"])] = dict(entry)
    for entry in entries:
        by_key[(entry["id"], entry["transport"])] = dict(entry)
    listed = [
        by_key.get((fixture, transport))
        or {"id": fixture, "transport": transport, "result": "not_run"}
        for fixture, transports in FIXTURES.items()
        for transport in transports
    ]
    return {"schema": SCHEMA_ID, "task": TASK, "fixtures": listed}


def write(path: Path, entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Merges a run into the report at `path` (validated first, then replaced atomically)."""
    existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    document = merge(existing, entries)
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
