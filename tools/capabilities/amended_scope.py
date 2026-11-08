"""The scope of the Assets3D painting amendment, derived from a capability manifest (task
phase3.1_assets3d-cutover item 2.1; `docs/analysis/assets3d-cutover/`).

    python -m tools.capabilities.amended_scope --manifest zig-out/bin/capabilities.json \
        --output docs/analysis/assets3d-cutover/02-amended-scope.json

The rule is the adapter's (`adapters/assets3d/scope.py`, `MIGRATIONS.md` M13): a symbol is in the
amended scope when its `any` entry is `supported`. The output lists, per module, the symbols in
scope and the count of the others by status; the operation-matrix rows by availability, the gap
rows with their owners; and the operation contexts a supported symbol still refuses (file formats,
compositor cases), which the facade rejects before any mutation where they are reached. It reads
the manifest only; it grants nothing and signs nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCHEMA = "uzpainter/assets3d-amended-scope/1"
IN_SCOPE = "supported"


def module_of(symbol: str, parents: set[str]) -> str:
    """The symbol's module: `<package>.<module>` when that names a lowercase module with members,
    else the package (its top-level classes and functions)."""
    parts = symbol.split(".")
    if len(parts) > 1 and parts[1].islower() and ".".join(parts[:2]) in parents:
        return ".".join(parts[:2])
    return parts[0]


def derive(raw: bytes, source: str) -> dict[str, Any]:
    manifest = json.loads(raw)
    if manifest.get("schema") != "uzpainter/capabilities/1":
        raise ValueError(f"{source} is not a capability manifest")
    entries: list[dict[str, Any]] = manifest["entries"]
    any_status = {e["symbol"]: e["status"] for e in entries if e["context"] == "any"}
    modules: dict[str, dict[str, Any]] = defaultdict(lambda: {"in_scope": [], "outside": Counter()})
    parents = {s.rsplit(".", 1)[0] for s in any_status if "." in s}
    for symbol in sorted(any_status):
        family = modules[module_of(symbol, parents)]
        if any_status[symbol] == IN_SCOPE:
            family["in_scope"].append(symbol)
        else:
            family["outside"][any_status[symbol]] += 1
    context_gaps = sorted(
        (
            {"symbol": e["symbol"], "context": e["context"], "status": e["status"]}
            for e in entries
            if e["context"] != "any"
            and e["status"] != IN_SCOPE
            and any_status.get(e["symbol"]) == IN_SCOPE
        ),
        key=lambda g: (g["symbol"], g["context"]),
    )
    matrix = manifest.get("operation_matrix", [])
    return {
        "schema": SCHEMA,
        "rule": "in scope: the symbol's `any` entry is `supported`; every other status, and a "
        "symbol the manifest does not list, stays with Adobe Substance 3D Painter",
        "manifest": {
            "path": source,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "compat_profile": manifest.get("compat_profile"),
            "entries_by_status": dict(sorted(Counter(e["status"] for e in entries).items())),
            "any_symbols_by_status": dict(sorted(Counter(any_status.values()).items())),
        },
        "modules": {
            name: {
                "in_scope_count": len(family["in_scope"]),
                "outside_by_status": dict(sorted(family["outside"].items())),
                "in_scope": family["in_scope"],
            }
            for name, family in sorted(modules.items())
        },
        "operation_matrix": {
            "available": sorted(
                f"{r['tool']}: {r['operation']}" for r in matrix if r["status"] == "available"
            ),
            "capability_gap": [
                {
                    "tool": r["tool"],
                    "operation": r["operation"],
                    "symbols": [g["symbol"] + " (" + g["context"] + ")" for g in r["gaps"]],
                    "notes": r["notes"],
                }
                for r in sorted(matrix, key=lambda r: (r["tool"], r["operation"]))
                if r["status"] != "available"
            ],
        },
        "refused_contexts_of_in_scope_symbols": context_gaps,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = args.manifest.read_bytes()
    scope = derive(raw, args.manifest.as_posix())
    args.output.write_text(json.dumps(scope, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
