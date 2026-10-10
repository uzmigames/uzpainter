"""Checks of the approved-source index (`.rulebook/tasks/phase0.1_approved-source-index` §3).

- Citation check (3.1): every source cited by the checked documents resolves to an approved
  entry, and no cited source is on the quarantine list. A quarantined source may be named only
  in a sentence that forbids it; an analysis file that is not cleared in its current revision
  may be named only as `historical context`.
- Revision check (3.2): every cleared `docs/analysis/` entry names a blob that exists in the
  repository history and equals the audited file at the named commit; the quarantine's
  uncleared revisions are real earlier revisions; every analysis file is either cleared or
  quarantined; UzmiGames file entries resolve in their repositories when those are present.

Run: `python -m tools.sources.check [--root PATH]`. Exit status 0 when both checks pass.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from tools.sources import git
from tools.sources.citations import (
    Citation,
    analysis_index,
    extract_citations,
    key_matches,
    unique,
)
from tools.sources.index import SourceIndex, load_index

INDEX_PATH = "docs/approved-sources.md"
ANALYSIS_DIR = "docs/analysis"
CHECKED_DOCS = ("docs/architecture/*.md", "docs/prd.md", "docs/roadmap.md", "docs/dag.md")


@dataclass(frozen=True)
class Problem:
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


def checked_documents(root: Path, patterns: Sequence[str] = CHECKED_DOCS) -> list[Path]:
    docs: list[Path] = []
    for pattern in patterns:
        docs.extend(sorted(root.glob(pattern)))
    return docs


def collect_citations(root: Path, docs: Sequence[Path]) -> list[Citation]:
    names = analysis_index(root / ANALYSIS_DIR)
    citations: list[Citation] = []
    for doc in docs:
        citations.extend(extract_citations(doc, doc.relative_to(root).as_posix(), names))
    return unique(citations)


def judge(citation: Citation, index: SourceIndex, root: Path) -> str | None:
    """Return None when the citation is acceptable, else the reason it is not."""
    if citation.kind == "analysis":
        path = citation.text[len(ANALYSIS_DIR) + 1 :]
        clearance = index.clearance_for(path)
        if clearance is not None:
            if git.worktree_blob(root, citation.text) == clearance.blob:
                return None
            if citation.historical:
                return None
            return f"{citation.text} differs from its cleared revision {clearance.blob}"
        if citation.historical:
            return None
        if path in index.quarantined_analyses:
            return f"{citation.text} is quarantined; cite it only as historical context"
        return f"{citation.text} is not in the approved-source index"

    approved = [
        e.entry_id for e in index.approved() if any(key_matches(citation, k) for k in e.keys)
    ]
    banned = [
        e.entry_id for e in index.quarantined() if any(key_matches(citation, k) for k in e.keys)
    ]
    if banned:
        if citation.prohibited:
            return None
        return f"{citation.text!r} is quarantined ({', '.join(banned)})"
    if approved:
        return None
    return f"{citation.kind} citation {citation.text!r} matches no approved entry"


def citation_check(
    root: Path, index: SourceIndex | None = None, docs: Sequence[Path] | None = None
) -> list[Problem]:
    index = index if index is not None else load_index(root / INDEX_PATH)
    documents = list(docs) if docs is not None else checked_documents(root)
    problems = [Problem(INDEX_PATH, p) for p in index.problems]
    for citation in collect_citations(root, documents):
        reason = judge(citation, index, root)
        if reason is not None:
            problems.append(Problem(f"{citation.doc}:{citation.line}", reason))
    return problems


def revision_check(
    root: Path, index: SourceIndex | None = None, check_external: bool = True
) -> list[Problem]:
    index = index if index is not None else load_index(root / INDEX_PATH)
    problems = [Problem(INDEX_PATH, p) for p in index.problems]

    cleared: dict[str, str] = {}
    for c in index.clearances:
        where = f"{INDEX_PATH} {c.entry_id}"
        repo_path = f"{ANALYSIS_DIR}/{c.path}"
        if c.path in cleared:
            problems.append(Problem(where, f"{c.path} is cleared twice"))
        cleared[c.path] = c.blob
        if not c.blob or not c.commit:
            problems.append(Problem(where, "a cleared analysis needs a blob and a commit hash"))
            continue
        if git.object_type(root, c.blob) != "blob":
            problems.append(Problem(where, f"blob {c.blob} does not exist in the repository"))
        if git.object_type(root, c.commit) != "commit" or not git.is_ancestor_of_head(
            root, c.commit
        ):
            problems.append(Problem(where, f"commit {c.commit} is not in the history of HEAD"))
            continue
        at_commit = git.object_at(root, c.commit, repo_path)
        if at_commit != c.blob:
            problems.append(
                Problem(where, f"{repo_path} at {c.commit[:12]} is {at_commit}, not {c.blob}")
            )

    for path, blobs in index.uncleared_revisions.items():
        where = f"{INDEX_PATH} uncleared revisions of {path}"
        history = git.path_revisions(root, f"{ANALYSIS_DIR}/{path}")
        for blob in blobs:
            if blob == cleared.get(path):
                problems.append(Problem(where, f"{blob} is both cleared and uncleared"))
            elif blob not in history:
                problems.append(Problem(where, f"{blob} is not a revision of {path}"))

    quarantined = set(index.quarantined_analyses)
    for path in sorted(set(cleared) & quarantined):
        problems.append(Problem(INDEX_PATH, f"{path} is both cleared and quarantined"))
    analysis_root = root / ANALYSIS_DIR
    if analysis_root.is_dir():
        for file in sorted(analysis_root.rglob("*.md")):
            rel = file.relative_to(analysis_root).as_posix()
            if rel not in cleared and rel not in quarantined:
                problems.append(
                    Problem(INDEX_PATH, f"docs/analysis/{rel} is neither cleared nor quarantined")
                )

    if check_external:
        for obj in index.repo_objects:
            repo = Path(obj.repository)
            where = f"{INDEX_PATH} {obj.entry_id}"
            if not obj.commit or not obj.object_id:
                problems.append(
                    Problem(where, "a UzmiGames file entry needs a commit and an object hash")
                )
                continue
            if not (repo / ".git").exists():
                continue
            found = git.object_at(repo, obj.commit, obj.path)
            if found != obj.object_id:
                problems.append(
                    Problem(
                        where, f"{obj.path} at {obj.commit[:12]} is {found}, not {obj.object_id}"
                    )
                )
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="UzPainter repository root")
    args = parser.parse_args(argv)
    root: Path = args.root.resolve()
    index = load_index(root / INDEX_PATH)
    failed = False
    for name, problems in (
        ("citation check", citation_check(root, index)),
        ("revision check", revision_check(root, index)),
    ):
        status = "FAIL" if problems else "ok"
        print(f"{name}: {status} ({len(problems)} problem(s))")
        for problem in problems:
            print(f"  {problem}")
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
