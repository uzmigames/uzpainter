"""The rebuild-from-dump report (phase2.2_recipe-and-diagnostics item 2.2; P2-RECIPE).

A project built through the pipeline is dumped (`uzpainter.project.dump_recipe`), rebuilt into a
new project from the dump and its stored resources (`rebuild_from_recipe`), and both projects are
exported with the same configuration. `report` compares the two sides and returns the
`recipe-rebuild-report.json` document (`parity/schema/`); `write_report` validates and writes it.
UzPainter is compared with itself: the report holds recipe digests, file names, SHA-256 and sizes,
never a pixel or an oracle record.

The outcome is `pass` when the digests are equal and both exports wrote the same file names with
the same bytes, `export_refused` when the digests are equal and both exports were refused before
writing (the gate is not met), and `fail` otherwise.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.parity.schemas import Schema, validation_errors

SCHEMA_ID = "uzpainter/parity/recipe-rebuild-report/1"


@dataclass(frozen=True)
class Side:
    """One project: its recipe dump and its export's files by name, or the export's refusal."""

    dump: Mapping[str, Any]
    files: Mapping[str, Path] | None
    refusal: str | None = None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _side(side: Side) -> dict[str, Any]:
    export: dict[str, Any]
    if side.files is None:
        export = {"status": "refused", "refusal": side.refusal}
    else:
        export = {
            "status": "written",
            "files": [
                {"name": name, "sha256": sha256_of(path), "bytes": path.stat().st_size}
                for name, path in sorted(side.files.items())
            ],
        }
    return {
        "recipe_digest": side.dump["digest"],
        "revision": side.dump["revision"],
        "export": export,
    }


def _equality(original: dict[str, Any], rebuilt: dict[str, Any]) -> dict[str, Any]:
    digests_equal = original["recipe_digest"] == rebuilt["recipe_digest"]
    a, b = original["export"], rebuilt["export"]
    differing: list[str] = []
    missing: list[str] = []
    extra: list[str] = []
    if a["status"] == "written" and b["status"] == "written":
        left = {f["name"]: f["sha256"] for f in a["files"]}
        right = {f["name"]: f["sha256"] for f in b["files"]}
        differing = sorted(n for n in left.keys() & right.keys() if left[n] != right[n])
        missing = sorted(left.keys() - right.keys())
        extra = sorted(right.keys() - left.keys())
        files = "identical" if not (differing or missing or extra) else "different"
    else:
        files = "not_exported"
    both_refused = a["status"] == b["status"] == "refused" and a["refusal"] == b["refusal"]
    if digests_equal and files == "identical":
        outcome = "pass"
    elif digests_equal and both_refused:
        outcome = "export_refused"
    else:
        outcome = "fail"
    return {
        "digests_equal": digests_equal,
        "files": files,
        "differing": differing,
        "missing": missing,
        "extra": extra,
        "outcome": outcome,
    }


def report(
    golden_id: str,
    manifest_sha256: str,
    build_hash: str,
    original: Side,
    rebuilt: Side,
) -> dict[str, Any]:
    """The report of `original` and its rebuild `rebuilt`, built from the job of `golden_id`
    (its manifest's SHA-256) by the UzPainter executable of SHA-256 `build_hash`."""
    first, second = _side(original), _side(rebuilt)
    resources: Sequence[str] = sorted(original.dump["resource_hashes"])
    return {
        "schema": SCHEMA_ID,
        "golden_id": golden_id,
        "manifest_sha256": manifest_sha256,
        "run": {
            "uzpainter_build_hash": build_hash,
            "compat_profile": original.dump["compat_profile"],
            "app_version": original.dump["app_version"],
        },
        "resources": list(resources),
        "original": first,
        "rebuilt": second,
        "equality": _equality(first, second),
    }


def write_report(document: Mapping[str, Any], path: Path) -> None:
    """Validate the report against its schema and write it."""
    problems = validation_errors(document, Schema.RECIPE_REBUILD_REPORT)
    if problems:
        raise ValueError(f"the rebuild-from-dump report is invalid: {problems}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
