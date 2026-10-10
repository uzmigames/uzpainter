"""Repository guard command (`parity/GUARD.md`).

Run from the repository: `python -m tools.parity.guard [--staged] [--index FILE | --no-store]
[PATH ...]`. Without `--staged` it checks the working tree (tracked and untracked, not ignored
files; PATHs narrow it); `--staged` checks what the next commit would record (the pre-commit
hook). The hash rule uses `--index`, else the index of this machine's store (`UZP_PARITY_STORE`,
else `%LOCALAPPDATA%\\UzPainter\\parity-store`); without either it is skipped and said so.
Exit status: 0 nothing blocked, 1 a file is blocked, 2 the guard could not run.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from tools.parity.guard.guard import (
    GuardError,
    load_index,
    repository_root,
    run_guard,
    staged_snapshot,
    worktree_snapshot,
)
from tools.parity.store.store import StoreError, locate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.parity.guard",
        description="Block recorded Painter outputs: store-index hash match, private-record "
        "content and public-schema validation under parity/.",
    )
    parser.add_argument(
        "--repo", type=Path, help="repository root (default: the git top level of the cwd)"
    )
    parser.add_argument(
        "--staged", action="store_true", help="check the staged files (pre-commit hook)"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--index", type=Path, help="a store index.json to match hashes against")
    source.add_argument(
        "--no-store", action="store_true", help="do not look for this machine's store"
    )
    parser.add_argument("paths", type=Path, nargs="*", help="narrow the working-tree check")
    return parser


def _index(args: argparse.Namespace) -> tuple[frozenset[str] | None, str]:
    if args.index is not None:
        return load_index(args.index), f"index {args.index}"
    if args.no_store:
        return None, "--no-store"
    store = locate()
    if store is None:
        return None, "no private store on this machine"
    return load_index(store.root / "index.json"), f"store {store.root}"


def _relative(repo: Path, paths: Sequence[Path]) -> list[str]:
    root = repo.resolve()
    relative: list[str] = []
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise GuardError(f"{path} is outside the repository {root}")
        relative.append(resolved.relative_to(root).as_posix())
    return relative


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.staged and args.paths:
        parser.error("--staged checks the staged files; it takes no PATH")
    try:
        repo: Path = args.repo or repository_root(Path.cwd())
        index, source = _index(args)
        snapshot = (
            staged_snapshot(repo)
            if args.staged
            else worktree_snapshot(repo, _relative(repo, args.paths))
        )
        findings = run_guard(repo, snapshot, index)
    except (GuardError, StoreError) as error:
        print(f"guard: error: {error}", file=sys.stderr)
        return 2
    if index is None:
        print(f"guard: store-hash rule skipped ({source}); content and schema rules only")
    else:
        print(f"guard: store-hash rule against {source} ({len(index)} hashes)")
    for finding in findings:
        print(f"BLOCKED {finding}")
    blocked = len({f.path for f in findings})
    print(f"guard: {len(snapshot.checked)} files checked, {blocked} blocked")
    return 1 if findings else 0
