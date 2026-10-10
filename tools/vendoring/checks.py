"""Reusable vendoring checks (`13-engine-integration.md` §3.1 and §3.3).

Byte equality against the manifest, include closure, exclusion denylist, conflict markers and
files outside the manifest. Each check returns a list of problems; an empty list means it passed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from tools.vendoring.closure import ClosureResult, Include, compute_closure
from tools.vendoring.hashing import git_blob_sha1, sha256_hex
from tools.vendoring.manifest import Manifest
from tools.vendoring.subset import (
    HEADER_ONLY,
    INCLUDE_DIRS,
    METADATA_FILES,
    PLANNED_CUTS,
    denylisted,
    expand_seeds,
    external_origin,
)

# A git merge-conflict marker: seven `<`, `|` or `>` followed by a space or the line end, or
# exactly seven `=` on their own line.
CONFLICT_RE = re.compile(r"^(?:(?:<{7}|\|{7}|>{7})(?: |$)|={7}$)", re.MULTILINE)


@dataclass(frozen=True)
class ConflictMarker:
    path: str
    line: int
    text: str


def list_files(root: Path) -> list[str]:
    """Every file under `root`, root-relative with `/` separators, sorted."""
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def conflict_markers(root: Path, files: Iterable[str]) -> list[ConflictMarker]:
    """Conflict markers in `files` (root-relative)."""
    found: list[ConflictMarker] = []
    for rel in files:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        for match in CONFLICT_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            end = text.find("\n", match.start())
            snippet = text[match.start() : end if end != -1 else len(text)].rstrip("\r")
            found.append(ConflictMarker(path=rel, line=line, text=snippet))
    return found


def denylist_violations(root: Path) -> list[str]:
    """Files under the vendored `root` that match the §2.4 denylist."""
    return denylisted(list_files(root))


def subset_closure(root: Path) -> ClosureResult:
    """Include closure of the declared subset found under `root` (an exported `runtime/` tree
    or the vendored folder), with the planned cuts applied."""
    return compute_closure(root, expand_seeds(root), INCLUDE_DIRS, PLANNED_CUTS, HEADER_ONLY)


def closure_problems(root: Path, expected: Iterable[str]) -> list[str]:
    """Check (b): the closure under `root` equals `expected` (root-relative paths) and every
    unresolved include is an allowed third-party, standard or system header."""
    result = subset_closure(root)
    expected_set = set(expected)
    problems = [
        f"closure reaches {p}, which is not in the expected set"
        for p in sorted(result.files - expected_set)
    ]
    problems += [
        f"expected file {p} is not reached by the closure"
        for p in sorted(expected_set - result.files)
    ]
    problems += [
        f"unresolved include {_spell(i)} in {i.source} has no allowed origin"
        for i in result.unresolved
        if external_origin(i.spelling) is None
    ]
    return problems


def _spell(include: Include) -> str:
    return f"<{include.spelling}>" if include.angled else f'"{include.spelling}"'


def manifest_problems(repo_root: Path, vendored_dir: str, manifest: Manifest) -> list[str]:
    """Byte equality and completeness of the vendored folder against its manifest.

    For every entry the vendored file must hash to `vendored_sha256`; a verbatim entry must also
    have `vendored_sha256 == upstream_sha256` and a blob id equal to `upstream_blob_sha1`, and
    no modification ids. Files under the folder outside the manifest and the metadata files
    are reported."""
    problems: list[str] = []
    listed: set[str] = set()
    for entry in manifest.files:
        listed.add(entry.vendored_path)
        path = repo_root / entry.vendored_path
        if not path.is_file():
            problems.append(f"{entry.vendored_path}: missing")
            continue
        data = path.read_bytes()
        digest = sha256_hex(data)
        if digest != entry.vendored_sha256:
            problems.append(
                f"{entry.vendored_path}: sha256 {digest} != manifest {entry.vendored_sha256}"
            )
        if entry.status == "verbatim":
            if entry.vendored_sha256 != entry.upstream_sha256:
                problems.append(
                    f"{entry.vendored_path}: verbatim but vendored_sha256 != upstream_sha256"
                )
            blob = git_blob_sha1(data)
            if blob != entry.upstream_blob_sha1:
                problems.append(
                    f"{entry.vendored_path}: blob {blob} != manifest {entry.upstream_blob_sha1}"
                )
            if entry.modifications:
                problems.append(f"{entry.vendored_path}: verbatim with modifications")
        elif not entry.modifications:
            problems.append(f"{entry.vendored_path}: modified without modification ids")
    root = repo_root / vendored_dir
    for rel in list_files(root):
        if rel in METADATA_FILES:
            continue
        if f"{vendored_dir}/{rel}" not in listed:
            problems.append(f"{vendored_dir}/{rel}: not in the manifest")
    return problems


def upstream_blob_problems(manifest: Manifest, blobs: dict[str, dict[str, str]]) -> list[str]:
    """Compare each entry's `upstream_blob_sha1` with the commit's tree entry.

    `blobs` maps a commit hash to `{upstream_path: blob id}` (from `git ls-tree -r`)."""
    problems: list[str] = []
    for entry in manifest.files:
        tree = blobs.get(entry.upstream_commit)
        if tree is None:
            problems.append(f"{entry.vendored_path}: no tree listing for {entry.upstream_commit}")
            continue
        actual = tree.get(entry.upstream_path)
        if actual != entry.upstream_blob_sha1:
            problems.append(
                f"{entry.vendored_path}: upstream blob {actual} at "
                f"{entry.upstream_commit[:12]} != manifest {entry.upstream_blob_sha1}"
            )
    return problems
