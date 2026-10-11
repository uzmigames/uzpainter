"""Command line of the render feasibility fits (owner's machine: private store, environments).

    python -m tools.parity.render_fits measure --work <dir> [--no-flip]
    python -m tools.parity.render_fits write --work <dir> [--selftest-report <json>]

`measure` reads the admitted Iray references from the private store, renders the prototype
(renders cached in `<dir>/renders`, outside the repository) and writes every number to
`<dir>/results.json`. `write` turns that file into `parity/semantics/iray.json` and the
generated blocks of `parity/reports/phase0/iray-noise-floor.md`; with `--selftest-report` it
also records the ray-tracing probes of a `UzPainter.exe selftest` run (task item 2.8).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from tools.parity.render_fits import pipeline, report, semantics
from tools.parity.store.store import locate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.render_fits")
    commands = parser.add_subparsers(dest="command", required=True)
    measure = commands.add_parser("measure")
    measure.add_argument("--work", type=Path, required=True)
    measure.add_argument("--no-flip", action="store_true")
    write = commands.add_parser("write")
    write.add_argument("--work", type=Path, required=True)
    write.add_argument("--selftest-report", type=Path)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    results_path = args.work / "results.json"
    if args.command == "measure":
        args.work.mkdir(parents=True, exist_ok=True)
        results = pipeline.run(locate(), args.work, flip=not args.no_flip)
        results_path.write_text(json.dumps(results, indent=1, sort_keys=True), encoding="utf-8")
        print(f"results written to {results_path}")
        return 0
    results = json.loads(results_path.read_text(encoding="utf-8"))
    probes = None
    if args.selftest_report is not None:
        probes = json.loads(args.selftest_report.read_text(encoding="utf-8"))
    print(semantics.write(results))
    print(report.write(results, probes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
