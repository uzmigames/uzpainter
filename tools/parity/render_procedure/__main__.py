"""Command line of the Iray procedure qualification (no Painter needed).

    python -m tools.parity.render_procedure fixtures
    python -m tools.parity.render_procedure answers [--merge <probe directory>]
    python -m tools.parity.render_procedure references
    python -m tools.parity.render_procedure noise
    python -m tools.parity.render_procedure stability-admit

`fixtures` regenerates the committed fixtures. `answers` checks the answers block of
`parity/reports/phase0/iray-capture-procedure.md` (exit 1 on a structural problem) and lists the
rows still pending the probe; with `--merge` it first folds a finished probe's answers in and
rewrites the block and its summary table. `references` regenerates the Iray reference fixtures
and their manifests (`references.py`), and the manifest of the qualification sphere's
template-default material (decision 063), keeping the private records the store merged in.
`noise` checks the admission of every reference golden and writes the Iray noise terms into
`parity/reports/phase0/iray-references.md` (`noise.py`; exit 1 when one is not admitted).
`stability-admit` puts the staged captures of decision 052's capture request into the private
store under their stability manifests (`stability.py`, decision 062; exit 1 when one is incomplete).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from tools.parity.recorder.output import work_root
from tools.parity.render_procedure.answers import (
    load_answers,
    merge_probe,
    pending,
    problems,
    write_answers,
)
from tools.parity.render_procedure.fixtures import write_committed
from tools.parity.render_procedure.references import (
    STABILITY_FIXTURES,
    write_fixtures,
    write_manifests,
    write_template_default_manifest,
)
from tools.parity.render_procedure.report import write_noise_report
from tools.parity.render_procedure.stability import StabilityError, admit
from tools.parity.store.store import locate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.render_procedure")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fixtures")
    commands.add_parser("references")
    commands.add_parser("noise")
    commands.add_parser("stability-admit")
    answers = commands.add_parser("answers")
    answers.add_argument("--merge", type=Path, help="probe directory holding probe.json")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "fixtures":
        for path in write_committed():
            print(path)
        return 0
    if args.command == "noise":
        return write_noise_report()
    if args.command == "stability-admit":
        return admit_stability()
    if args.command == "references":
        for path in [*write_fixtures(), *write_manifests(), write_template_default_manifest()]:
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


def admit_stability() -> int:
    store = locate()
    if store is None:
        print("no private store (UZP_PARITY_STORE)", file=sys.stderr)
        return 1
    failed = 0
    for fixture in STABILITY_FIXTURES:
        try:
            written = admit(store, work_root(), fixture)
        except StabilityError as error:
            print(f"{fixture.name}: {error}", file=sys.stderr)
            failed += 1
            continue
        print(f"{fixture.name}: {len(written)} records")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
