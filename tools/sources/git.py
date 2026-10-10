"""Read-only git queries used by the source checks. Nothing here changes repository state."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git(repo: Path, *args: str) -> str | None:
    """Run `git -C repo args` and return stripped stdout, or None when git reports an error."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def object_type(repo: Path, sha: str) -> str | None:
    """Type of an object (`blob`, `tree`, `commit`), or None when the object does not exist."""
    return git(repo, "cat-file", "-t", sha)


def object_at(repo: Path, commit: str, path: str) -> str | None:
    """Hash of the object at `commit:path` (`.` is the root tree), or None when absent."""
    spec = f"{commit}^{{tree}}" if path in {"", "."} else f"{commit}:{path}"
    return git(repo, "rev-parse", "--verify", "--quiet", spec)


def is_ancestor_of_head(repo: Path, commit: str) -> bool:
    """True when `commit` is reachable from HEAD (part of the repository history)."""
    result = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", commit, "HEAD"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def path_revisions(repo: Path, path: str) -> set[str]:
    """Every blob hash the path has had in the commits reachable from HEAD."""
    commits = git(repo, "log", "--format=%H", "--", path)
    if not commits:
        return set()
    blobs: set[str] = set()
    for commit in commits.splitlines():
        blob = object_at(repo, commit, path)
        if blob is not None:
            blobs.add(blob)
    return blobs


def worktree_blob(repo: Path, path: str) -> str | None:
    """Blob hash of the working-tree file as git would store it (clean filters applied)."""
    if not (repo / path).is_file():
        return None
    return git(repo, "hash-object", "--", path)
