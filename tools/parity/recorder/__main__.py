r"""Command line of the Painter oracle recorder (operator guide: `parity/RECORDER.md`).

    python -m tools.parity.recorder record <manifest.json>
    python -m tools.parity.recorder iray <manifest.json> --condition separate_session
    python -m tools.parity.recorder iray <manifest.json> --condition k_times_samples --k 4
    python -m tools.parity.recorder check [--python-doc <objects.inv>]

Painter must already run with `--enable-remote-scripting` and no project open. Records go to
`UZP_ORACLE_INBOX` (default `%LOCALAPPDATA%\UzPainter\oracle-inbox`), working files to
`UZP_ORACLE_WORK` (default `%LOCALAPPDATA%\UzPainter\oracle-work`); both must lie outside
the repository.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from tools.parity.recorder.iray import (
    K_TIMES_SAMPLES,
    SEPARATE_SESSION,
    ConsoleOperator,
    record_iray_reference,
)
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
    for name in ("record", "iray"):
        command = commands.add_parser(name)
        command.add_argument("manifest", type=Path)
        command.add_argument("--host", default=REMOTE_HOST)
        command.add_argument("--port", type=int, default=REMOTE_PORT)
    iray = commands.choices["iray"]
    iray.add_argument("--condition", choices=[SEPARATE_SESSION, K_TIMES_SAMPLES], required=True)
    iray.add_argument("--k", type=int)
    check = commands.add_parser("check")
    check.add_argument("--python-doc", type=Path, help="python-doc objects.inv to check against")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse(sys.argv[1:] if argv is None else argv)
    if args.command == "check":
        problems = [str(p) for p in check_files(recorder_sources())]
        if args.python_doc:
            problems += inventory_problems(args.python_doc)
        print("\n".join(problems) or "provenance: ok")
        return 1 if problems else 0
    run: Path | None
    try:
        job = load_job(args.manifest)
        session = PainterSession(HttpTransport(args.host, args.port))
        if args.command == "record":
            run = record_texture_golden(session, job, work_root(), inbox_root())
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
