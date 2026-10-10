"""Validation against the parity JSON schemas (`parity/schema/*.json`, `parity/CONTRACT.md` §7).

Schemas are JSON Schema draft 2020-12; the `date` format is checked by the validator. Rules a
schema cannot state are checked in Python: `register_problems` (exception register) and
`record_problems` (private records, including their `date-time` stamps).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "parity" / "schema"
REGISTER_PATH = REPO_ROOT / "parity" / "exceptions.json"
DECISIONS_DIR = REPO_ROOT / ".rulebook" / "decisions"


class Schema(StrEnum):
    GOLDEN_PUBLIC = "golden-public.json"
    GOLDEN_PRIVATE = "golden-private.json"
    EXCEPTIONS = "exceptions.json"
    COMPARISON_REPORT = "comparison-report.json"
    SEMANTICS = "semantics.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@cache
def load_schema(schema: Schema) -> dict[str, Any]:
    document: dict[str, Any] = load_json(SCHEMA_DIR / schema.value)
    Draft202012Validator.check_schema(document)
    return document


@cache
def _validator(schema: Schema) -> Draft202012Validator:
    return Draft202012Validator(load_schema(schema), format_checker=FormatChecker())


def validation_errors(document: Any, schema: Schema) -> list[str]:
    """Every violation of `schema` by `document`, as `path: message` lines (empty when valid)."""
    errors = sorted(_validator(schema).iter_errors(document), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]


def is_valid(document: Any, schema: Schema) -> bool:
    return not validation_errors(document, schema)


def register_problems(
    register: Mapping[str, Any], decisions_dir: Path = DECISIONS_DIR
) -> list[str]:
    """Schema violations plus the rules a schema cannot state.

    Each (exception_id, version) appears once, and every entry's decision_id names a decision
    recorded under `.rulebook/decisions/`.
    """
    problems = validation_errors(register, Schema.EXCEPTIONS)
    if problems:
        return problems
    seen: set[tuple[str, int]] = set()
    for index, entry in enumerate(register["entries"]):
        key = (entry["exception_id"], entry["version"])
        if key in seen:
            problems.append(f"entries/{index}: duplicate {key[0]} version {key[1]}")
        seen.add(key)
        if not any(decisions_dir.glob(f"{entry['decision_id']}-*.md")):
            problems.append(
                f"entries/{index}: decision {entry['decision_id']} is not recorded in "
                f"{decisions_dir.as_posix()}"
            )
    return problems


def _timestamp_problem(value: str) -> str | None:
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return f"recorded_at {value!r} is not an ISO 8601 date-time"
    return None if stamp.tzinfo is not None else f"recorded_at {value!r} has no UTC offset"


def record_problems(record: Mapping[str, Any]) -> list[str]:
    """Schema violations of a private record plus its cross-field rules (CONTRACT.md §4.1, §6.2).

    - `recorded_at` is an ISO 8601 date-time with a UTC offset.
    - An Iray reference converged on its sample count: iterations equal samples and the
      rendering time stayed below Max Time; its operator settings name an output of the record.
    - Tier 3: the two `separate_session` recordings come from different sessions, and the
      `k_times_samples` recording used k*S samples (k > 1) where S is the sessions' sample count.
    """
    problems = validation_errors(record, Schema.GOLDEN_PRIVATE)
    if problems:
        return problems
    output_ids = {o["output_id"] for rec in record["recordings"] for o in rec["outputs"]}
    session_samples: set[int] = set()
    k_samples: set[int] = set()
    sessions: list[str] = []
    for index, recording in enumerate(record["recordings"]):
        where = f"recordings/{index}"
        problem = _timestamp_problem(recording["recorded_at"])
        if problem:
            problems.append(f"{where}: {problem}")
        if recording["condition"] == "separate_session":
            sessions.append(recording["session_id"])
        for output in recording["outputs"]:
            if output["kind"] != "iray_reference":
                continue
            ref = f"{where}/{output['output_id']}"
            convergence = output["convergence"]
            if convergence["iterations"] != output["samples"]:
                problems.append(f"{ref}: iterations {convergence['iterations']} != samples")
            if convergence["rendering_time_s"] >= convergence["max_time_s"]:
                problems.append(f"{ref}: rendering time reached Max Time")
            if output["operator_settings_output_id"] not in output_ids:
                problems.append(f"{ref}: operator settings output is not in the record")
            if recording["condition"] == "separate_session":
                session_samples.add(output["samples"])
            elif recording["condition"] == "k_times_samples":
                k_samples.add(output["samples"])
    if record["tier"] == "3":
        if len(set(sessions)) != len(sessions):
            problems.append("separate_session recordings share a session_id")
        if len(session_samples) != 1:
            problems.append(f"separate_session references disagree on S: {sorted(session_samples)}")
        else:
            (s,) = session_samples
            for k in sorted(k_samples):
                if k <= s or k % s:
                    problems.append(
                        f"k_times_samples reference uses {k} samples, not k*{s} (k > 1)"
                    )
    return problems
