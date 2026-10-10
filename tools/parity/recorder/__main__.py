r"""Command line of the Painter oracle recorder (operator guide: `parity/RECORDER.md`).

    python -m tools.parity.recorder record <manifest.json>
    python -m tools.parity.recorder iray <manifest.json> --condition separate_session
    python -m tools.parity.recorder iray <manifest.json> --condition k_times_samples --k 4
    python -m tools.parity.recorder record-defaults <manifest.json>
    python -m tools.parity.recorder list-templates
    python -m tools.parity.recorder record-templates <manifest.json>
    python -m tools.parity.recorder check [--python-doc <objects.inv>]
    python -m tools.parity.recorder iray-probe
    python -m tools.parity.recorder iray-probe-analyse <probe directory>

Painter must already run with `--enable-remote-scripting` and no project open. Records go to
`UZP_ORACLE_INBOX` (default `%LOCALAPPDATA%\UzPainter\oracle-inbox`), working files to
`UZP_ORACLE_WORK` (default `%LOCALAPPDATA%\UzPainter\oracle-work`); both must lie outside
the repository.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from tools.parity.recorder.defaults import (
    list_shipped_templates,
    record_baking_defaults,
    record_project_templates,
)
from tools.parity.recorder.iray import (
    K_TIMES_SAMPLES,
    SEPARATE_SESSION,
    ConsoleOperator,
    record_iray_reference,
)
from tools.parity.recorder.iray_probe import reanalyse, run_probe
from tools.parity.recorder.job import load_job
from tools.parity.recorder.output import inbox_root, work_root
from tools.parity.recorder.provenance import check_files, inventory_problems, recorder_sources
from tools.parity.recorder.session import (
    REMOTE_HOST,
    REMOTE_PORT,
    HttpTransport,
    PainterSession,
    RecorderError,
)
from tools.parity.recorder.texture import record_texture_golden


def parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.recorder")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("record", "iray", "record-defaults", "record-templates", "list-templates"):
        command = commands.add_parser(name)
        if name != "list-templates":
            command.add_argument("manifest", type=Path)
        command.add_argument("--host", default=REMOTE_HOST)
        command.add_argument("--port", type=int, default=REMOTE_PORT)
    iray = commands.choices["iray"]
    iray.add_argument("--condition", choices=[SEPARATE_SESSION, K_TIMES_SAMPLES], required=True)
    iray.add_argument("--k", type=int)
    check = commands.add_parser("check")
    check.add_argument("--python-doc", type=Path, help="python-doc objects.inv to check against")
    probe = commands.add_parser("iray-probe", help="operator-assisted Iray procedure probe")
    probe.add_argument("--host", default=REMOTE_HOST)
    probe.add_argument("--port", type=int, default=REMOTE_PORT)
    analyse = commands.add_parser("iray-probe-analyse", help="re-run a probe's analysis")
    analyse.add_argument("directory", type=Path)
    return parser.parse_args(argv)


def run_iray_probe(args: argparse.Namespace) -> int:
    try:
        if args.command == "iray-probe-analyse":
            answers = reanalyse(args.directory)
            directory = args.directory
        else:
            session = PainterSession(HttpTransport(args.host, args.port))
            directory = run_probe(session, ConsoleOperator(), work_root())
            data = json.loads((directory / "probe.json").read_text(encoding="utf-8"))
            if "answers" not in data:
                print(f"analysis failed: {data['analysis_error']}", file=sys.stderr)
                print(f"probe evidence kept: {directory / 'probe.json'}")
                return 1
            answers = data["answers"]
    except RecorderError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    for row, value in answers.items():
        print(f"{row}: [{value['status']}] {value['answer']}")
    print(f"probe evidence: {directory / 'probe.json'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse(sys.argv[1:] if argv is None else argv)
    if args.command == "check":
        problems = [str(p) for p in check_files(recorder_sources())]
        if args.python_doc:
            problems += inventory_problems(args.python_doc)
        print("\n".join(problems) or "provenance: ok")
        return 1 if problems else 0
    if args.command in ("iray-probe", "iray-probe-analyse"):
        return run_iray_probe(args)
    run: Path | None
    try:
        session = PainterSession(HttpTransport(args.host, args.port))
        if args.command == "list-templates":
            session.connect()
            for template in list_shipped_templates(session):
                print(template)
            return 0
        job = load_job(args.manifest)
        if args.command == "record":
            run = record_texture_golden(session, job, work_root(), inbox_root())
        elif args.command == "record-defaults":
            run = record_baking_defaults(session, job, work_root(), inbox_root())
        elif args.command == "record-templates":
            run = record_project_templates(session, job, work_root(), inbox_root())
        else:
            run = record_iray_reference(
                session, job, args.condition, ConsoleOperator(), work_root(), inbox_root(), args.k
            )
    except RecorderError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    print(f"recorded: {run}" if run else "reference staged; the golden needs more references")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
