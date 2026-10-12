r"""Command line of the Painter oracle recorder (operator guide: `parity/RECORDER.md`).

    python -m tools.parity.recorder record <manifest.json> [--operator console|ui]
    python -m tools.parity.recorder iray <manifest.json> --condition separate_session \
        --operator-id ID
    python -m tools.parity.recorder iray <manifest.json> --condition k_times_samples --k 4 \
        --operator-id ID
    python -m tools.parity.recorder iray <manifest or dir>... --condition C --launch \
        --operator ui --operator-id ID [--session-file <exr>]
    python -m tools.parity.recorder record-defaults <manifest.json>
    python -m tools.parity.recorder list-templates
    python -m tools.parity.recorder record-script <manifest.json> --assets-root <dir> [--launch]
    python -m tools.parity.recorder record-templates <manifest.json>
    python -m tools.parity.recorder check [--python-doc <objects.inv>]
    python -m tools.parity.recorder iray-probe --ref-match-hdri <exr> [--operator ui]
    python -m tools.parity.recorder iray-probe-analyse <probe directory>
    python -m tools.parity.recorder refresh [--launch]
    python -m tools.parity.recorder stability-study <manifest or dir>... [--launch] [--admit]
    python -m tools.parity.recorder canary [--launch]

Every recording command reads the running Painter build first: a build that is neither the
current nor the candidate envelope's starts the envelope refresh (decision 037; `refresh`, exit
status 3 once it ends). The last three commands are the oracle envelope's (`parity/RECORDER.md`
§10, `tools/parity/envelope/`).

`--operator ui` (iray, iray-probe, record) lets `painter_ui.UiOperator` operate Painter's panels
by Windows UI automation (decision 029) instead of a person at the console. `record` needs an
operator only for a golden whose settings sheet names values only the UI can set
(`texture_sheet.py`) and refuses such a golden without one.

`iray --launch` runs a series: for each manifest (a directory stands for its `*.json`) that still
needs the condition (`iray.reference_needed`), it starts a fresh Painter process, records one
reference and stops Painter, so every reference has its own session (procedure `iray-capture/1`
step 6). A refused reference is reported and the series goes on; the exit status is 2 when any
was refused. `--session-file` gives the files that session-environment steps name by SHA-256.
`--condition same_session` records the two renders of one session that the stability probe of
decision 062 needs (`iray.SAME_SESSION`).

`record-script` records a Tier 1 golden whose steps run UzmiGames pipeline scripts pinned by
SHA-256 (`script_run.py`, decision 099); its inputs are hash-checked under `--assets-root` before
Painter is touched, and `--launch` starts (and finally stops) Painter itself.

Painter must already run with `--enable-remote-scripting` and no project open (or `--launch`).
Records go to `UZP_ORACLE_INBOX` (default `%LOCALAPPDATA%\UzPainter\oracle-inbox`), working files to
`UZP_ORACLE_WORK` (default `%LOCALAPPDATA%\UzPainter\oracle-work`); both must lie outside
the repository.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from tools.parity.recorder.defaults import (
    list_shipped_templates,
    record_baking_defaults,
    record_project_templates,
)
from tools.parity.recorder.iray import (
    K_TIMES_SAMPLES,
    SAME_SESSION,
    SEPARATE_SESSION,
    ConsoleOperator,
    Operator,
    record_iray_reference,
    reference_needed,
)
from tools.parity.recorder.iray_probe import reanalyse, run_probe
from tools.parity.recorder.job import load_job
from tools.parity.recorder.launcher import PainterLauncher, default_painter_exe
from tools.parity.recorder.output import inbox_root, work_root
from tools.parity.recorder.provenance import check_files, inventory_problems, recorder_sources
from tools.parity.recorder.script_run import ScriptSession, load_script_job, record_script_golden
from tools.parity.recorder.session import (
    REMOTE_HOST,
    REMOTE_PORT,
    HttpTransport,
    PainterSession,
    RecorderError,
    UnseenBuild,
)
from tools.parity.recorder.texture import record_texture_golden


def parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.recorder")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("record", "record-defaults", "record-templates", "list-templates"):
        command = commands.add_parser(name)
        if name != "list-templates":
            command.add_argument("manifest", type=Path)
        command.add_argument("--host", default=REMOTE_HOST)
        command.add_argument("--port", type=int, default=REMOTE_PORT)
        if name == "record":
            command.add_argument("--operator", choices=["console", "ui"], default=None)
    iray = commands.add_parser("iray")
    iray.add_argument("manifests", type=Path, nargs="+", help="manifests or directories")
    iray.add_argument("--host", default=REMOTE_HOST)
    iray.add_argument("--port", type=int, default=REMOTE_PORT)
    iray.add_argument("--launch", action="store_true", help="a fresh Painter per reference")
    iray.add_argument("--painter-exe", type=Path, default=None, help="Painter executable")
    iray.add_argument("--session-file", type=Path, action="append", default=[])
    iray.add_argument(
        "--condition", choices=[SEPARATE_SESSION, K_TIMES_SAMPLES, SAME_SESSION], required=True
    )
    iray.add_argument("--k", type=int)
    iray.add_argument("--operator", choices=["console", "ui"], default="console")
    check = commands.add_parser("check")
    check.add_argument("--python-doc", type=Path, help="python-doc objects.inv to check against")
    probe = commands.add_parser("iray-probe", help="operator-assisted Iray procedure probe")
    probe.add_argument("--host", default=REMOTE_HOST)
    probe.add_argument("--port", type=int, default=REMOTE_PORT)
    probe.add_argument("--operator", choices=["console", "ui"], default="console")
    probe.add_argument(
        "--ref-match-hdri", type=Path, required=True, help="the ref_match preset's HDRI file"
    )
    analyse = commands.add_parser("iray-probe-analyse", help="re-run a probe's analysis")
    analyse.add_argument("directory", type=Path)
    iray.add_argument("--operator-id", required=True, help="who applies the settings sheet")
    from tools.parity.envelope.cli import add_painter_options

    refresh = commands.add_parser("refresh", help="detect the build; refresh the envelope")
    add_painter_options(refresh)
    study = commands.add_parser("stability-study", help="record the stability study (034 (b))")
    study.add_argument("manifests", type=Path, nargs="*")
    study.add_argument("--resume", type=Path, help="continue the study of this directory")
    study.add_argument("--admit", action="store_true", help="admit the runs to the private store")
    add_painter_options(study)
    canary = commands.add_parser("canary", help="re-record and diff the canary (034 (d))")
    add_painter_options(canary)
    script = commands.add_parser("record-script", help="record a pipeline-script golden (099)")
    script.add_argument("manifest", type=Path)
    script.add_argument("--assets-root", type=Path, required=True, help="the Assets3D root")
    add_painter_options(script)
    return parser.parse_args(argv)


def refresh_after_unseen_build(args: argparse.Namespace, error: UnseenBuild) -> int:
    """An unseen build starts the refresh with no human step (decision 037)."""
    from tools.parity.envelope.cli import run_refresh

    print(f"refused: {error}", file=sys.stderr)
    print("starting the envelope refresh", file=sys.stderr)
    try:
        run_refresh(args)
    except RecorderError as failure:
        print(f"refresh refused: {failure}", file=sys.stderr)
    return 3


def make_operator(kind: str) -> Operator:
    """The person at the console, or the UI automation of Painter's panels (decision 029)."""
    if kind == "console":
        return ConsoleOperator()
    from datetime import UTC, datetime

    from tools.parity.recorder.painter_ui import PainterUi, UiOperator

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return UiOperator(PainterUi(), work_root() / "ui-operator" / stamp)


def run_iray_probe(args: argparse.Namespace) -> int:
    try:
        if args.command == "iray-probe-analyse":
            answers = reanalyse(args.directory)
            directory = args.directory
        else:
            session = PainterSession(HttpTransport(args.host, args.port))
            directory = run_probe(
                session, make_operator(args.operator), work_root(), args.ref_match_hdri
            )
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
        if row == "presets":
            for name, preset in value.items():
                print(f"preset {name}: applied and verified = {preset['applied_and_verified']}")
            continue
        print(f"{row}: [{value['status']}] {value['answer']}")
    print(f"probe evidence: {directory / 'probe.json'}")
    return 0


def iray_manifests(paths: Sequence[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        found += sorted(path.glob("*.json")) if path.is_dir() else [path]
    return found


class Launcher(Protocol):
    """Starts and stops one Painter process (`launcher.PainterLauncher`)."""

    def start(self) -> None: ...

    def stop(self, session: PainterSession | None = None) -> None: ...


def run_iray(args: argparse.Namespace, launcher: Launcher | None = None) -> int:
    """One reference in the running Painter; with `--launch`, a series with one fresh Painter
    process per reference."""
    manifests = iray_manifests(args.manifests)
    if len(manifests) != 1 and not args.launch:
        print("refused: several references need --launch (one Painter each)", file=sys.stderr)
        return 2
    if args.launch and launcher is None:
        launcher = PainterLauncher(
            args.painter_exe or default_painter_exe(), host=args.host, port=args.port
        )
    refused = 0
    for path in manifests:
        try:
            job = load_job(path)
            if args.launch and not reference_needed(job, args.condition, work_root()):
                print(f"{path}: {args.condition} already staged or admitted; skipped")
                continue
            session = PainterSession(HttpTransport(args.host, args.port))
            if launcher is not None:
                launcher.start()
            try:
                run = record_iray_reference(
                    session,
                    job,
                    args.condition,
                    make_operator(args.operator),
                    work_root(),
                    inbox_root(),
                    args.k,
                    operator_id=args.operator_id,
                    session_files=args.session_file,
                )
            finally:
                if launcher is not None:
                    launcher.stop(session)
        except UnseenBuild as error:
            return refresh_after_unseen_build(args, error)
        except RecorderError as error:
            print(f"{path}: refused: {error}", file=sys.stderr)
            refused += 1
            continue
        print(f"{path}: " + (f"recorded: {run}" if run else "reference staged"))
    return 2 if refused else 0


def run_record_script(args: argparse.Namespace, launcher: Launcher | None = None) -> int:
    """Record one pipeline-script golden; the job (every input's hash) is checked first."""
    try:
        job = load_script_job(args.manifest, args.assets_root)
        if args.launch and launcher is None:
            launcher = PainterLauncher(
                args.painter_exe or default_painter_exe(), host=args.host, port=args.port
            )
        session = ScriptSession(HttpTransport(args.host, args.port))
        if launcher is not None:
            launcher.start()
        try:
            run = record_script_golden(session, job, work_root(), inbox_root())
        finally:
            if launcher is not None:
                launcher.stop(session)
    except UnseenBuild as error:
        return refresh_after_unseen_build(args, error)
    except RecorderError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    print(f"recorded: {run}")
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
    if args.command in ("refresh", "stability-study", "canary"):
        from tools.parity.envelope import cli

        try:
            if args.command == "refresh":
                return cli.run_refresh(args)
            if args.command == "stability-study":
                return cli.run_stability_study(args)
            return cli.run_canary_command(args)
        except UnseenBuild as error:
            return refresh_after_unseen_build(args, error)
        except RecorderError as error:
            print(f"refused: {error}", file=sys.stderr)
            return 2
    if args.command == "iray":
        return run_iray(args)
    if args.command == "record-script":
        return run_record_script(args)
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
            operator = make_operator(args.operator) if args.operator else None
            run = record_texture_golden(session, job, work_root(), inbox_root(), operator=operator)
        elif args.command == "record-defaults":
            run = record_baking_defaults(session, job, work_root(), inbox_root())
        else:
            run = record_project_templates(session, job, work_root(), inbox_root())
    except UnseenBuild as error:
        return refresh_after_unseen_build(args, error)
    except RecorderError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    print(f"recorded: {run}" if run else "reference staged; the golden needs more references")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
