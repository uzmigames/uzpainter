"""Phase 0 prototype of `uzpainter parity init|record|fetch|verify` (`parity/STORE.md`).

Run: `python -m tools.parity.store [--store PATH] <command> ...`. The store is `--store`, else
`UZP_PARITY_STORE`, else `%LOCALAPPDATA%\\UzPainter\\parity-store`. Exit status: 0 when every
blob resolves, 1 when any is `oracle_unavailable` or an operation is refused, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from tools.parity.schemas import Schema, is_valid, load_json, load_schema
from tools.parity.store.manifest import fetch, load_manifest, record_file, record_run, verify
from tools.parity.store.snapshot_capture import admit_snapshot_capture
from tools.parity.store.store import (
    OracleStore,
    Resolution,
    Status,
    StoreError,
    default_root,
    locate,
    sha256_file,
)

RECORD_KINDS: list[str] = load_schema(Schema.GOLDEN_PUBLIC)["$defs"]["private_record_ref"][
    "properties"
]["kind"]["enum"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uzpainter parity", description="Private oracle store (P0-STORE prototype)."
    )
    parser.add_argument("--store", type=Path, help="store root (default: UZP_PARITY_STORE)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create the store layout (owner's machine only)")
    record = commands.add_parser(
        "record", help="store recorded oracles and write their hashes into a manifest"
    )
    record.add_argument("manifest", type=Path, help="public manifest to update")
    record.add_argument("--run", type=Path, help="a READY recorder run from the oracle inbox")
    record.add_argument("--record-id", help="record id of a single file")
    record.add_argument("--kind", choices=RECORD_KINDS, help="kind of the single file")
    record.add_argument("--file", type=Path, help="the recorded file")
    stored_input = commands.add_parser(
        "input", help="store an authored input a manifest pins by hash (owner's machine only)"
    )
    stored_input.add_argument("file", type=Path)
    stored_input.add_argument("--path", required=True, help="the path the manifest pins it at")
    snapshot = commands.add_parser(
        "admit-snapshot-capture", help="validate and admit a private snapshot capture"
    )
    snapshot.add_argument("work", type=Path)
    snapshot.add_argument("--producer-policy", type=Path, required=True)
    snapshot.add_argument("--approved-policy-sha256", required=True)
    snapshot.add_argument("--approved-policy-revision", type=int, required=True)
    snapshot.add_argument("--validator-binary", type=Path, required=True)
    snapshot.add_argument("--approved-binary-sha256", required=True)
    snapshot.add_argument("--approved-code-sha256", required=True)
    fetch_parser = commands.add_parser("fetch", help="copy the blobs a manifest names")
    fetch_parser.add_argument("manifest", type=Path)
    fetch_parser.add_argument(
        "--out", type=Path, required=True, help="destination outside the repo"
    )
    verify_parser = commands.add_parser(
        "verify", help="re-hash the blobs manifests name (no path: check the whole store)"
    )
    verify_parser.add_argument("paths", type=Path, nargs="*", help="manifests or directories")
    return parser


def _manifests(paths: Sequence[Path]) -> list[Path]:
    """The manifests named, a directory standing for every JSON file under it. A directory's glTF
    consumer fixture (`parity/manifests/consumers/gltf/`) names no store blob and is validated by
    the guard under its own schema, so it is left out; any other file is verified as a manifest."""
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found.extend(
                p
                for p in sorted(path.rglob("*.json"))
                if not is_valid(load_json(p), Schema.GLTF_CONSUMER_FIXTURE)
            )
        elif path.is_file():
            found.append(path)
        else:
            raise StoreError(f"{path} does not exist")
    return found


def _report(manifest: Path, results: Sequence[Resolution]) -> bool:
    print(f"{manifest.as_posix()}:")
    for result in results:
        detail = f" ({result.reason})" if result.reason else ""
        print(f"  {result.record_id}  {result.sha256[:12]}  {result.status}{detail}")
    return all(result.status is Status.AVAILABLE for result in results)


def _run(args: argparse.Namespace) -> int:
    configured: Path | None = args.store or default_root()
    if args.command == "init":
        if configured is None:
            raise StoreError("no store root: pass --store or set UZP_PARITY_STORE")
        store = OracleStore.init(configured)
        print(f"store ready at {store.root}")
        return 0
    found = OracleStore.open(args.store) if args.store else locate()
    if args.command == "admit-snapshot-capture":
        if found is None:
            raise StoreError("no initialised store on this machine")
        try:
            policy_bytes = args.producer_policy.read_bytes()
        except OSError as error:
            raise StoreError("cannot read approved producer policy") from error
        admitted = admit_snapshot_capture(
            found,
            args.work,
            binary=args.validator_binary,
            approved_binary_sha256=args.approved_binary_sha256,
            approved_code_sha256=args.approved_code_sha256,
            policy_bytes=policy_bytes,
            approved_policy_sha256=args.approved_policy_sha256,
            approved_policy_revision=args.approved_policy_revision,
        )
        print(f"snapshot capture {admitted['capture_id']} admitted")
        return 0
    if args.command == "record":
        if found is None:
            raise StoreError("no initialised store on this machine; `record` runs only there")
        single = (args.record_id, args.kind, args.file)
        if args.run is not None and not any(single):
            updated = record_run(found, args.manifest, args.run)
        elif args.run is None and all(single):
            updated = record_file(found, args.manifest, args.record_id, args.kind, args.file)
        else:
            raise StoreError("pass either --run DIR or all of --record-id, --kind and --file")
        print(f"{args.manifest.as_posix()}: {len(updated['private_records'])} private record(s)")
        return 0
    if args.command == "input":
        if found is None:
            raise StoreError("no initialised store on this machine; `input` runs only there")
        sha256, _ = sha256_file(args.file)
        size = found.add_input(args.file, sha256, args.path)
        print(f"{sha256}  {size}  {args.path}")
        return 0
    if args.command == "fetch":
        results = fetch(found, load_manifest(args.manifest), args.out)
        return 0 if _report(args.manifest, results) else 1
    if not args.paths:
        if found is None:
            raise StoreError("no initialised store on this machine")
        problems = found.check()
        print(f"store {found.root}: {'ok' if not problems else 'FAIL'}")
        for problem in problems:
            print(f"  {problem}")
        return 1 if problems else 0
    ok = True
    for manifest in _manifests(args.paths):
        ok = _report(manifest, verify(found, load_manifest(manifest))) and ok
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except StoreError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
