r"""Command line of the normal-convention fixture (P0-NORMAL).

    python -m tools.parity.normal_convention fixtures   # (re)write the authored OBJ pairs
    python -m tools.parity.normal_convention manifests  # (re)write the public manifests
    python -m tools.parity.normal_convention run [--prototype EXE]
        # bake with the prototype, compare with the recorded oracles; writes
        # parity/semantics/tangent-frame.json and parity/reports/phase0/normal-convention.md
    python -m tools.parity.normal_convention check [--prototype EXE]
        # re-run the comparison; exit 1 if any residual differs from the published semantics

Without `--prototype` the prototype is built with `zig build normal-prototype` into a temporary
prefix. `run` and `check` read the private oracles from this machine's store (owner's machine
only); a machine without them gets `oracle_unavailable` and exit status 2.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.normal_convention.cases import FIXTURE_DIR, write_manifests
from tools.parity.normal_convention.fixtures import pairs, write_fixtures
from tools.parity.normal_convention.prototype import build_prototype, run_prototype
from tools.parity.normal_convention.report import (
    REPORT_PATH,
    SEMANTICS_PATH,
    report_markdown,
    semantics_document,
)
from tools.parity.normal_convention.study import OracleUnavailable, run_study
from tools.parity.schemas import REPO_ROOT, load_json
from tools.parity.store.store import locate


def commit_hash() -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "unknown"


def study_with_prototype(executable: Path | None, work: Path) -> dict[str, Any]:
    exe = executable if executable is not None else build_prototype(work / "prefix")
    bakes = {pair: run_prototype(exe, pair, FIXTURE_DIR, work / "bakes") for pair in pairs()}
    return run_study(locate(), bakes)


def residual_numbers(semantics: dict[str, Any]) -> list[Any]:
    return [
        (entry["entry_id"], r["golden_id"], r["map"], r["compared_against"], r["difference"])
        for entry in semantics["entries"]
        for r in entry["residuals"]
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.normal_convention")
    parser.add_argument("command", choices=["fixtures", "manifests", "run", "check"])
    parser.add_argument("--prototype", type=Path, help="uzp-normal-prototype.exe to use")
    args = parser.parse_args(argv)
    if args.command == "fixtures":
        for path in write_fixtures(FIXTURE_DIR).values():
            print(path.relative_to(REPO_ROOT).as_posix())
        return 0
    if args.command == "manifests":
        for path in write_manifests():
            print(path.relative_to(REPO_ROOT).as_posix())
        return 0
    with tempfile.TemporaryDirectory(prefix="uzp-normal-") as temp:
        try:
            study = study_with_prototype(args.prototype, Path(temp))
        except OracleUnavailable as error:
            print(f"oracle_unavailable: {error}", file=sys.stderr)
            return 2
    semantics = semantics_document(study)
    if args.command == "check":
        published = load_json(SEMANTICS_PATH)
        if residual_numbers(published) != residual_numbers(semantics):
            print("residuals differ from parity/semantics/tangent-frame.json", file=sys.stderr)
            return 1
        print("residuals equal the published semantics")
        return 0
    environment = {
        "machine": platform.node(),
        "Python": platform.python_version(),
        "numpy": np.__version__,
        "repository commit": f"{commit_hash()} plus the working tree of this task",
        "Painter build of the oracles": semantics["painter_build_id"],
    }
    SEMANTICS_PATH.write_text(
        json.dumps(semantics, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    REPORT_PATH.write_text(report_markdown(study, environment), encoding="utf-8", newline="\n")
    print(SEMANTICS_PATH.relative_to(REPO_ROOT).as_posix())
    print(REPORT_PATH.relative_to(REPO_ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
