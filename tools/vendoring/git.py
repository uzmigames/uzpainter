"""Read-only git operations on the UzEngine repository.

Every command reads commit objects only (`rev-list`, `ls-tree`, `archive`, `log`, `cat-file`);
none changes the repository's state. `core.autocrlf` is forced off so exported bytes equal the
stored blobs.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommitInfo:
    """Full hash, committer date (ISO 8601) and subject of a commit."""

    hash: str
    date: str
    subject: str


def run_git(repo: Path, *args: str) -> bytes:
    """Run `git -C repo -c core.autocrlf=false <args>` and return stdout; raise on failure."""
    completed = subprocess.run(
        ["git", "-C", str(repo), "-c", "core.autocrlf=false", *args],
        check=True,
        capture_output=True,
    )
    return completed.stdout


def has_commit(repo: Path, commit: str) -> bool:
    """True if `repo` is a git repository that contains `commit`."""
    try:
        run_git(repo, "cat-file", "-e", f"{commit}^{{commit}}")
    except (subprocess.CalledProcessError, FileNotFoundError, NotADirectoryError):
        return False
    return True


def rev_list(repo: Path, ref: str, limit: int) -> list[str]:
    """Full hashes of the newest `limit` commits reachable from `ref`, newest first."""
    out = run_git(repo, "rev-list", f"--max-count={limit}", ref)
    return out.decode("ascii").split()


def commit_info(repo: Path, commit: str) -> CommitInfo:
    """Hash, committer date and subject of `commit`."""
    out = run_git(repo, "log", "-1", "--format=%H%x00%cI%x00%s", commit).decode("utf-8")
    hash_, date, subject = out.rstrip("\n").split("\0")
    return CommitInfo(hash=hash_, date=date, subject=subject)


def ls_tree_blobs(repo: Path, commit: str, paths: Sequence[str] = ()) -> dict[str, str]:
    """Map every blob path under `paths` (all paths if empty) at `commit` to its blob id."""
    out = run_git(repo, "ls-tree", "-r", "-z", commit, "--", *paths)
    blobs: dict[str, str] = {}
    for record in out.decode("utf-8").split("\0"):
        if not record:
            continue
        meta, path = record.split("\t", 1)
        _mode, kind, object_id = meta.split(" ")
        if kind == "blob":
            blobs[path] = object_id
    return blobs


def read_blobs(repo: Path, object_ids: Sequence[str]) -> dict[str, bytes]:
    """Raw contents of the given blob ids (`git cat-file --batch`), without any conversion."""
    if not object_ids:
        return {}
    completed = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch"],
        input="".join(f"{oid}\n" for oid in object_ids).encode("ascii"),
        check=True,
        capture_output=True,
    )
    out = completed.stdout
    blobs: dict[str, bytes] = {}
    pos = 0
    for oid in object_ids:
        end = out.index(b"\n", pos)
        header = out[pos:end].decode("ascii").split(" ")
        if len(header) != 3 or header[1] != "blob":
            raise ValueError(f"{oid}: not a blob ({' '.join(header)})")
        size = int(header[2])
        blobs[oid] = out[end + 1 : end + 1 + size]
        pos = end + 1 + size + 1
    return blobs


def export(repo: Path, commit: str, paths: Sequence[str], dest: Path) -> None:
    """Extract `paths` of `commit` into `dest` with `git archive` (never from a working tree)."""
    data = run_git(repo, "archive", "--format=tar", commit, "--", *paths)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        archive.extractall(dest, filter="data")
