r"""Commands of the oracle envelope (operator guide: `parity/RECORDER.md` §10).

Painter-driving commands run through `python -m tools.parity.recorder` (they share its options):

    python -m tools.parity.recorder refresh [--launch]
    python -m tools.parity.recorder stability-study <manifest or dir>... [--launch] [--admit]
                                    [--resume <study dir>]
    python -m tools.parity.recorder canary [--launch]

Offline commands, and the build check of the local parity gate:

    python -m tools.parity.envelope check            exit 0 current, 3 refresh needed,
                                                     4 superseded build, 2 Painter unreachable
    python -m tools.parity.envelope status
    python -m tools.parity.envelope report
    python -m tools.parity.envelope study-analyse <study dir>
    python -m tools.parity.envelope backfill <manifest or dir>... [--known field=value] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from tools.parity.envelope import refresh as refreshing
from tools.parity.envelope.backfill import BackfillError, backfill
from tools.parity.envelope.canary import drift_free, run_canary
from tools.parity.envelope.corpus import manifests_under
from tools.parity.envelope.registry import (
    RegistryError,
    current_envelope,
    load_registry,
    manifest_root,
    recordable_builds,
)
from tools.parity.envelope.report import drift_path, write_json, write_report
from tools.parity.envelope.study import admit, load_study, new_study, publish, run_study
from tools.parity.recorder.environment import capture_host_environment, envelope_sha256
from tools.parity.recorder.launcher import PainterLauncher, default_painter_exe
from tools.parity.recorder.output import inbox_root, work_root
from tools.parity.recorder.probes import ProbeSession
from tools.parity.recorder.session import (
    REMOTE_HOST,
    REMOTE_PORT,
    BuildPolicy,
    HttpTransport,
    PainterSession,
    RecorderError,
)
from tools.parity.schemas import load_json
from tools.parity.store.store import OracleStore, StoreError, locate

EXIT_CURRENT, EXIT_UNREACHABLE, EXIT_REFRESH, EXIT_SUPERSEDED, EXIT_DRIFT = 0, 2, 3, 4, 4


def add_painter_options(parser: argparse.ArgumentParser, launch: bool = True) -> None:
    parser.add_argument("--host", default=REMOTE_HOST)
    parser.add_argument("--port", type=int, default=REMOTE_PORT)
    if launch:
        parser.add_argument(
            "--launch",
            action="store_true",
            help="start (and finally stop) Painter itself with --enable-remote-scripting",
        )
        parser.add_argument("--painter-exe", type=Path, default=None, help="Painter executable")


def session_factory(args: argparse.Namespace) -> refreshing.SessionFactory:
    def make(builds: BuildPolicy, verify: bool) -> PainterSession:
        return ProbeSession(
            HttpTransport(args.host, args.port),
            allowed_builds=builds,
            host_environment=capture_host_environment,
            verify_calls=verify,
        )

    return make


def launcher_of(args: argparse.Namespace) -> PainterLauncher | None:
    if not getattr(args, "launch", False):
        return None
    return PainterLauncher(
        args.painter_exe or default_painter_exe(), host=args.host, port=args.port
    )


def store_or_none() -> OracleStore | None:
    try:
        return locate()
    except StoreError:
        return None


def print_outcome(outcome: refreshing.Outcome) -> int:
    print(f"{outcome.outcome}: {outcome.envelope_id}: {outcome.message}")
    if outcome.drift_report is not None:
        print(f"drift report: {outcome.drift_report}")
    return (
        0
        if outcome.outcome
        in (refreshing.CURRENT_OUTCOME, refreshing.EQUIVALENT, refreshing.PROMOTED)
        else 1
    )


def run_refresh(args: argparse.Namespace) -> int:
    """Detect the running build and refresh the envelope when it is unseen (decision 037)."""
    launcher = launcher_of(args)
    if launcher is not None:
        launcher.start()
    try:
        outcome = refreshing.ensure_current(
            session_factory(args), store_or_none(), work_root(), inbox_root(), launcher=launcher
        )
    finally:
        if launcher is not None:
            launcher.stop()
    return print_outcome(outcome)


def run_stability_study(args: argparse.Namespace) -> int:
    launcher = launcher_of(args)
    current = current_envelope()
    if args.resume:
        study = load_study(args.resume)
    else:
        named = list(args.manifests) or [manifest_root(current) / "tier0"]
        manifests = manifests_under(named)
        foreign = [
            p
            for p in manifests
            if load_json(p)["software"]["painter"]["build_id"] != current["painter_build"]
        ]
        if foreign:
            raise RecorderError(
                f"{len(foreign)} manifest(s) are not of the current envelope "
                f"{current['envelope_id']} (e.g. {foreign[0]}); the study runs on the current "
                "envelope only"
            )
        study = new_study(manifests, work_root(), current, datetime.now(UTC))
    print(f"study ledger: {study.ledger_path}")
    build = current["painter_build"]
    factory = session_factory(args)
    run_study(study, launcher, lambda: factory(lambda: frozenset({build}), True), inbox_root())
    results = publish(study, datetime.now(UTC).date())
    print("classification: " + ", ".join(f"{k} {v}" for k, v in results["summary"].items()))
    if args.admit:
        store = locate()
        if store is None:
            print(
                "refused: no private store on this machine; runs stay in the inbox", file=sys.stderr
            )
            return 1
        print(f"admitted {len(admit(study, store))} run(s) under {study.directory / 'manifests'}")
    return 0


def run_canary_command(args: argparse.Namespace) -> int:
    """Canary on the running Painter: an unseen build or another environment goes to the
    refresh; on the current envelope the canary is re-recorded and diffed as a check."""
    launcher = launcher_of(args)
    if launcher is not None:
        launcher.start()
    try:
        factory = session_factory(args)
        session = factory(lambda: recordable_builds(), True)
        found = refreshing.detect(session)
        if found.state != refreshing.CURRENT_OUTCOME:
            outcome = refreshing.ensure_current(
                factory, store_or_none(), work_root(), inbox_root(), launcher=launcher
            )
            return print_outcome(outcome)
        now = datetime.now(UTC)
        document, _runs = run_canary(
            session,
            found.current,
            store_or_none(),
            work_root(),
            inbox_root(),
            lambda: datetime.now(UTC),
            now.date(),
        )
        assert found.identity.environment is not None
        envelope_hash = envelope_sha256(found.identity.environment)
        document["envelope_id"] = f"{found.current['envelope_id']}-env-{envelope_hash[:12]}"
        path = drift_path("canary", str(document["envelope_id"]))
        write_json(path, document)
        write_report()
    finally:
        if launcher is not None:
            launcher.stop()
    print(f"canary: {document['summary']}; report {path}")
    if not drift_free(document):
        print(
            "the canary differs from the current envelope's goldens under the same envelope: the "
            "oracle does not reproduce itself (see the report); nothing was replaced",
            file=sys.stderr,
        )
        return EXIT_DRIFT
    return 0


def check(args: argparse.Namespace) -> int:
    session = session_factory(args)(lambda: recordable_builds(), False)
    try:
        found = refreshing.detect(session)
    except (RecorderError, OSError) as error:
        print(f"unreachable: {error}", file=sys.stderr)
        return EXIT_UNREACHABLE
    print(
        f"{found.state}: running {found.identity.build_id}; current {found.current['envelope_id']}"
    )
    if found.state == refreshing.CURRENT_OUTCOME:
        return EXIT_CURRENT
    return EXIT_SUPERSEDED if found.state == refreshing.SUPERSEDED_BUILD else EXIT_REFRESH


def status() -> int:
    registry = load_registry()
    print(f"current: {registry['current']}")
    candidate = registry["candidate"]
    print(f"candidate: {candidate['envelope_id'] if candidate else 'none'}")
    for entry in registry["envelopes"]:
        print(f"  {entry['envelope_id']}  {entry['status']}  {entry['manifest_root']}")
    for item in registry["quarantine"]:
        print(f"  quarantined {item['envelope_id']} ({item['quarantined_on']}): {item['reason']}")
    return 0


def parse_known(values: Sequence[str]) -> dict[str, str]:
    known: dict[str, str] = {}
    for value in values:
        name, sep, text = value.partition("=")
        if not sep or not text:
            raise BackfillError(f"--known takes field=value, not {value!r}")
        known[name] = text
    return known


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.envelope")
    commands = parser.add_subparsers(dest="command", required=True)
    add_painter_options(
        commands.add_parser("check", help="where the running Painter stands"), False
    )
    commands.add_parser("status", help="print the envelope registry")
    commands.add_parser("report", help="regenerate parity/reports/phase0/oracle-envelope.md")
    analyse = commands.add_parser("study-analyse", help="re-analyse a study from its ledger")
    analyse.add_argument("directory", type=Path)
    fill = commands.add_parser("backfill", help="back-fill environment records")
    fill.add_argument("paths", type=Path, nargs="+")
    fill.add_argument("--known", action="append", default=[], metavar="FIELD=VALUE")
    fill.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "check":
            return check(args)
        if args.command == "status":
            return status()
        if args.command == "report":
            print(f"report: {write_report()}")
            return 0
        if args.command == "study-analyse":
            results = publish(load_study(args.directory), datetime.now(UTC).date())
            print("classification: " + ", ".join(f"{k} {v}" for k, v in results["summary"].items()))
            return 0
        store = locate()
        if store is None:
            print("refused: no private store on this machine", file=sys.stderr)
            return 1
        done = backfill(
            store, manifests_under(list(args.paths)), parse_known(args.known), dry_run=args.dry_run
        )
        for path, environment in done:
            unknown = sorted(k for k, v in environment.items() if v == "unknown")
            print(
                f"{path.as_posix()}: {'would back-fill' if args.dry_run else 'back-filled'} "
                f"(unknown: {', '.join(unknown)})"
            )
        print(f"{len(done)} manifest(s)")
        return 0
    except (RecorderError, RegistryError, BackfillError, StoreError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
