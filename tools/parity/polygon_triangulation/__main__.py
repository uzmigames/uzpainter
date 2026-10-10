r"""Command line of the Tier 0 polygon-triangulation comparison (phase1.4_mesh-importers, 3.3).

    python -m tools.parity.polygon_triangulation fixture    # (re)write the authored OBJ
    python -m tools.parity.polygon_triangulation manifest   # (re)write the public manifest
    python -m tools.parity.polygon_triangulation run [--mesh-tests EXE]
        # compare the recorded oracle with UzPainter's importer; writes
        # parity/semantics/polygon-triangulation.json and
        # parity/reports/phase1/polygon-triangulation.md
    python -m tools.parity.polygon_triangulation check [--mesh-tests EXE]
        # re-run the comparison; exit 1 if it differs from the published semantics

Without `--mesh-tests` the importer is built with `zig build mesh-tests` into a temporary prefix.
`run` and `check` read the private oracle from this machine's store (owner's machine only); a
machine without it gets `oracle_unavailable` and exit status 2.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from tools.parity.polygon_triangulation.core import (
    REPORT_PATH,
    SEMANTICS_PATH,
    OracleUnavailable,
    oracle_recordings,
    report_markdown,
    run_study,
    semantics_document,
    uzpainter_triangulations,
    write_fixture,
    write_manifest,
)
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.polygon_triangulation")
    parser.add_argument("command", choices=["fixture", "manifest", "run", "check"])
    parser.add_argument("--mesh-tests", type=Path, help="uzp-mesh-tests.exe to use")
    args = parser.parse_args(argv)
    if args.command == "fixture":
        print(write_fixture().relative_to(REPO_ROOT).as_posix())
        return 0
    if args.command == "manifest":
        print(write_manifest().relative_to(REPO_ROOT).as_posix())
        return 0
    try:
        maps = oracle_recordings(locate())
    except OracleUnavailable as error:
        print(f"oracle_unavailable: {error}", file=sys.stderr)
        return 2
    study = run_study(maps, uzpainter_triangulations(args.mesh_tests))
    semantics = semantics_document(study)
    if args.command == "check":
        if load_json(SEMANTICS_PATH) != json.loads(json.dumps(semantics)):
            print(
                "the comparison differs from parity/semantics/polygon-triangulation.json",
                file=sys.stderr,
            )
            return 1
        print("the comparison equals the published semantics")
        return 0
    environment = {
        "machine": platform.node(),
        "Python": platform.python_version(),
        "numpy": np.__version__,
        "repository commit": f"{commit_hash()} plus the working tree of this task",
        "Painter build of the oracle": semantics["painter_build_id"],
    }
    SEMANTICS_PATH.write_text(
        json.dumps(semantics, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report_markdown(study, environment), encoding="utf-8", newline="\n")
    print(SEMANTICS_PATH.relative_to(REPO_ROOT).as_posix())
    print(REPORT_PATH.relative_to(REPO_ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
