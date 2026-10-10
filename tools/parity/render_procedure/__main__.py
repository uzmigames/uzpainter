"""Command line of the Iray procedure qualification (no Painter needed).

    python -m tools.parity.render_procedure fixtures
    python -m tools.parity.render_procedure answers [--merge <probe directory>]

`fixtures` regenerates the committed fixtures. `answers` checks the answers block of
`parity/reports/phase0/iray-capture-procedure.md` (exit 1 on a structural problem) and lists the
rows still pending the probe; with `--merge` it first folds a finished probe's answers in and
rewrites the block and its summary table.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from tools.parity.render_procedure.answers import (
    load_answers,
    merge_probe,
    pending,
    problems,
    write_answers,
)
from tools.parity.render_procedure.fixtures import write_committed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.render_procedure")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fixtures")
    answers = commands.add_parser("answers")
    answers.add_argument("--merge", type=Path, help="probe directory holding probe.json")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "fixtures":
        for path in write_committed():
            print(path)
        return 0
    data = load_answers()
    if args.merge:
        data = merge_probe(data, args.merge / "probe.json")
        write_answers(data)
    found = problems(data)
    for problem in found:
        print(f"problem: {problem}")
    open_rows = pending(data)
    print(f"pending probe: {', '.join(open_rows)}" if open_rows else "every row answered")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
