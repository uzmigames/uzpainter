"""Select a clean UzEngine commit and vendor the render-core subset (`13-engine-integration.md`
§3.1-§3.3).

Usage:
    python -m tools.vendoring.import_core --uzengine E:/UzmiGames/UzEngine --staging <dir>
        [--ref main] [--max-candidates 20] [--commit <hash>] [--repo-root .] [--dry-run]

Candidates are the newest commits of `--ref` (or the single `--commit`), newest first. Each is
exported with `git archive` into `<staging>/<hash>/` and checked: exported bytes equal the commit's
blobs, (a) no conflict markers in the subset, (b) the include closure equals the subset with only
allowed external includes, (d) every cited upstream behaviour holds. The newest passing candidate
is copied into `thirdparty/uzengine-render-core/` with `LICENSE` and `MANIFEST.json`, and the
evidence is written to `<staging>/evidence.json`. `ORIGIN.md` and the root `NOTICE` entry are
written by the importer from that evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tools.vendoring import git
from tools.vendoring.checks import ConflictMarker, closure_problems, conflict_markers
from tools.vendoring.citations import CITATIONS, Citation, failing_citations
from tools.vendoring.hashing import git_blob_sha1
from tools.vendoring.manifest import Manifest, save, verbatim_entry
from tools.vendoring.subset import UPSTREAM_PREFIX, VENDORED_DIR, expand_seeds

EXPORT_PATHS = ("LICENSE", "runtime/engine", "runtime/platform")
NOTICE_FOLDERS = ("", "runtime/", "runtime/engine/", "runtime/platform/")


@dataclass
class CandidateReport:
    """Outcome of the selection checks for one commit."""

    commit: str
    export_mismatches: list[str] = field(default_factory=list)
    markers: list[ConflictMarker] = field(default_factory=list)
    closure: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not (self.export_mismatches or self.markers or self.closure or self.citations)


def check_tree(commit: str, runtime_root: Path, blobs: dict[str, str]) -> CandidateReport:
    """Run the selection checks on an exported `runtime/` tree of `commit`.

    `blobs` maps upstream paths (`runtime/...`) to blob ids from the commit's tree."""
    report = CandidateReport(commit=commit)
    files = expand_seeds(runtime_root)
    report.files = files
    for rel in files:
        upstream = UPSTREAM_PREFIX + rel
        actual = git_blob_sha1((runtime_root / rel).read_bytes())
        if blobs.get(upstream) != actual:
            report.export_mismatches.append(
                f"{upstream}: exported blob {actual} != tree {blobs.get(upstream)}"
            )
    report.markers = conflict_markers(runtime_root, files)
    report.closure = closure_problems(runtime_root, files)
    report.citations = failing_citations(runtime_root, CITATIONS)
    return report


def select_newest(
    candidates: Sequence[str], evaluate: Callable[[str], CandidateReport]
) -> tuple[CandidateReport | None, list[CandidateReport]]:
    """Evaluate `candidates` newest first and return the first that passes, with every report
    produced up to and including it."""
    reports: list[CandidateReport] = []
    for commit in candidates:
        report = evaluate(commit)
        reports.append(report)
        if report.passed:
            return report, reports
    return None, reports


def upstream_notices(uzengine: Path, commit: str) -> list[str]:
    """`NOTICE*` files at the repository root, `runtime/`, `runtime/engine`, `runtime/platform`."""
    tree = git.ls_tree_blobs(uzengine, commit)
    found: list[str] = []
    for path in tree:
        folder, _, name = path.rpartition("/")
        prefix = f"{folder}/" if folder else ""
        if prefix in NOTICE_FOLDERS and name.upper().startswith("NOTICE"):
            found.append(path)
    return sorted(found)


def write_vendored(
    report: CandidateReport, runtime_root: Path, license_bytes: bytes, repo_root: Path
) -> Manifest:
    """Copy the subset, `LICENSE` and `MANIFEST.json` into the vendored folder."""
    dest = repo_root / VENDORED_DIR
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"{dest} is not empty; a later import follows §3.5")
    entries = []
    for rel in report.files:
        data = (runtime_root / rel).read_bytes()
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        entries.append(
            verbatim_entry(UPSTREAM_PREFIX + rel, f"{VENDORED_DIR}/{rel}", report.commit, data)
        )
    (dest / "LICENSE").write_bytes(license_bytes)
    manifest = Manifest(
        upstream_repository="UzEngine (UzmiGames)", upstream_root=UPSTREAM_PREFIX, files=entries
    )
    save(dest / "MANIFEST.json", manifest)
    return manifest


def _report_json(report: CandidateReport, info: git.CommitInfo) -> dict[str, object]:
    return {
        "commit": info.hash,
        "date": info.date,
        "subject": info.subject,
        "passed": report.passed,
        "export_mismatches": report.export_mismatches,
        "conflict_markers": [f"{m.path}:{m.line}: {m.text}" for m in report.markers],
        "closure_problems": report.closure,
        "failing_citations": [f"{c.location} ({c.behaviour})" for c in report.citations],
        "file_count": len(report.files),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--uzengine", type=Path, required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--ref", default="main")
    parser.add_argument("--max-candidates", type=int, default=20)
    parser.add_argument("--commit")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    uzengine: Path = args.uzengine
    staging: Path = args.staging
    candidates = (
        [args.commit] if args.commit else git.rev_list(uzengine, args.ref, args.max_candidates)
    )
    candidates = [git.commit_info(uzengine, c).hash for c in candidates]

    def evaluate(commit: str) -> CandidateReport:
        export_root = staging / commit
        if not export_root.exists():
            git.export(uzengine, commit, EXPORT_PATHS, export_root)
        blobs = git.ls_tree_blobs(uzengine, commit, ("runtime/engine", "runtime/platform"))
        return check_tree(commit, export_root / "runtime", blobs)

    selected, reports = select_newest(candidates, evaluate)
    evidence: dict[str, object] = {
        "candidates": [_report_json(r, git.commit_info(uzengine, r.commit)) for r in reports],
        "selected": selected.commit if selected else None,
    }
    if selected is not None:
        root_tree = git.ls_tree_blobs(uzengine, selected.commit, ("LICENSE", "runtime/LICENSE"))
        evidence["license_blobs"] = root_tree
        evidence["upstream_notices"] = upstream_notices(uzengine, selected.commit)
        if not args.dry_run:
            license_bytes = (staging / selected.commit / "LICENSE").read_bytes()
            write_vendored(
                selected, staging / selected.commit / "runtime", license_bytes, args.repo_root
            )
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0 if selected is not None else 1


if __name__ == "__main__":
    sys.exit(main())
