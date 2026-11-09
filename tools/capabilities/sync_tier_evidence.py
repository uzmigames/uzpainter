"""Bring the capability inputs in line with `tier0-trace.json` (decision 112).

`python -m tools.capabilities.sync_tier_evidence [--check]`

A symbol a compared Tier 0 replay exercises (or a member of it, for a module or a class) is
`supported` (context `any`) and cites exactly the goldens of those replays
(`tests/python/test_capability_conformance.py::test_supported_entries_equal_the_tier0_trace`).
After the Tier 0 tests rewrite the trace (`UZP_UPDATE_TIER0_TRACE=1`), this script:

- rewrites the `tier_evidence` of every exercised `supported` entry;
- promotes an exercised `release-gap` or `pending-evidence` entry to `supported` (`since`
  "0.0.0", its status notes dropped);
- reports, and never changes, a `supported` entry no replay exercises: a downgrade is a decision.

Only the lines of changed entries are rewritten; every other byte is kept. `--check` changes
nothing and exits 1 when an entry would change. Run it after reviewing the trace diff (decision
403: every added symbol must be read by a compared output).
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
TRACE = ROOT / "tier0-trace.json"
INPUTS = (ROOT / "painter-api-inventory.json", ROOT / "uzpainter-additions.json")
ORDER = ("symbol", "context", "status", "since", "tier_evidence", "notes", "justification")


def exercised() -> dict[str, set[str]]:
    """Each exercised symbol and each of its owners, with the goldens that exercised it."""
    result: dict[str, set[str]] = defaultdict(set)
    for replay in json.loads(TRACE.read_text(encoding="utf-8")).values():
        for symbol in replay["symbols"]:
            parts = symbol.split(".")
            for i in range(1, len(parts) + 1):
                result[".".join(parts[:i])].add(replay["golden"])
    return result


def ordered(entry: dict[str, Any]) -> dict[str, Any]:
    keys = [k for k in ORDER if k in entry] + [k for k in entry if k not in ORDER]
    return {k: entry[k] for k in keys}


def synced(entry: dict[str, Any], goldens: dict[str, set[str]]) -> dict[str, Any] | None:
    """The entry as the trace requires it, or None when it is unchanged."""
    if entry["context"] != "any" or entry["symbol"] not in goldens:
        return None
    wanted = sorted(goldens[entry["symbol"]])
    if entry["status"] == "supported":
        if entry.get("tier_evidence") == wanted:
            return None
        return ordered({**entry, "tier_evidence": wanted})
    if entry["status"] in ("release-gap", "pending-evidence"):
        promoted = {k: v for k, v in entry.items() if k not in ("notes", "justification", "status")}
        promoted.update(status="supported", since="0.0.0", tier_evidence=wanted)
        return ordered(promoted)
    return None


def sync(path: Path, goldens: dict[str, set[str]], check: bool) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    changes: list[str] = []
    for index, line in enumerate(lines):
        text = line.rstrip("\r\n")
        body = text.strip()
        if not body.startswith('{"symbol"'):
            continue
        comma = body.endswith(",")
        entry = json.loads(body[:-1] if comma else body)
        new = synced(entry, goldens)
        unsupported = entry["context"] == "any" and entry["symbol"] not in goldens
        if entry["status"] == "supported" and unsupported:
            changes.append(f"{path.name}: {entry['symbol']} supported without a replay (kept)")
        if new is None:
            continue
        changes.append(
            f"{path.name}: {entry['symbol']} {entry['status']} -> supported "
            f"({len(new['tier_evidence'])} goldens)"
        )
        indent = text[: len(text) - len(text.lstrip())]
        ending = line[len(text) :]
        rendered = json.dumps(new, ensure_ascii=False)
        lines[index] = indent + rendered + ("," if comma else "") + ending
    if not check:
        path.write_text("".join(lines), encoding="utf-8", newline="")
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.capabilities.sync_tier_evidence")
    parser.add_argument("--check", action="store_true", help="change nothing; exit 1 on a change")
    args = parser.parse_args()
    goldens = exercised()
    changes = [c for path in INPUTS for c in sync(path, goldens, args.check)]
    for change in changes:
        print(change)
    return 1 if args.check and any("->" in c for c in changes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
