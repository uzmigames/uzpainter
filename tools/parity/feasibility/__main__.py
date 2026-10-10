r"""Command line of the procedural feasibility study (P0-FEAS-PROC).

    python -m tools.parity.feasibility fixtures    # (re)write the authored fixtures
    python -m tools.parity.feasibility manifests   # (re)write the public manifests
    python -m tools.parity.feasibility run         # fit + compare; writes semantics and report
    python -m tools.parity.feasibility check       # re-run the comparison with the published
                                                   # fits; exit 1 if any number differs

`run` and `check` read the private oracles from this machine's store (owner's machine only); a
machine without the store gets `oracle_unavailable` and exit status 2.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from collections.abc import Sequence

import numpy as np

from tools.parity.feasibility.cases import FIXTURE_DIR, write_manifests
from tools.parity.feasibility.fixtures import write_fixtures
from tools.parity.feasibility.report import (
    REPORT_PATH,
    SEMANTICS_PATH,
    fits_from_semantics,
    report_markdown,
    semantics_document,
)
from tools.parity.feasibility.study import OracleUnavailable, run_study
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
    parser = argparse.ArgumentParser(prog="python -m tools.parity.feasibility")
    parser.add_argument("command", choices=["fixtures", "manifests", "run", "check"])
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "fixtures":
        for path in write_fixtures(FIXTURE_DIR).values():
            print(path.relative_to(REPO_ROOT).as_posix())
        return 0
    if args.command == "manifests":
        for path in write_manifests():
            print(path.relative_to(REPO_ROOT).as_posix())
        return 0
    store = locate()
    published = load_json(SEMANTICS_PATH) if args.command == "check" else None
    try:
        study = run_study(store, fits_from_semantics(published) if published else None)
    except OracleUnavailable as error:
        print(f"oracle_unavailable: {error}", file=sys.stderr)
        return 2
    document = semantics_document(study)
    if published is not None:
        if document != published:
            print("check: the comparison output differs from the published semantics")
            return 1
        print(f"check: {len(study.cases)} cases reproduce the published residuals")
        return 0
    SEMANTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEMANTICS_PATH.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    note = (
        f"machine {platform.node()}, Python {platform.python_version()}, numpy "
        f"{np.__version__}, repository commit {commit_hash()} plus the working "
        f"tree of this task, Painter build of the oracles `{document['painter_build_id']}`."
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report_markdown(study, note), encoding="utf-8", newline="\n")
    print(SEMANTICS_PATH.relative_to(REPO_ROOT).as_posix())
    print(REPORT_PATH.relative_to(REPO_ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
