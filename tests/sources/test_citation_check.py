"""Test 3.1 — citation check: every cited source matches an approved entry, none is quarantined."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.sources.conftest import IndexBuilder, Sandbox
from tools.sources.check import checked_documents, citation_check, collect_citations
from tools.sources.citations import Citation, Kind, key_matches, normalize_path
from tools.sources.index import parse_index

ANALYSIS = "docs/analysis/topic/01-notes.md"


def test_architecture_cites_only_approved_sources(repo_root: Path) -> None:
    problems = citation_check(repo_root)
    assert problems == [], "\n".join(str(p) for p in problems)


def test_architecture_documents_are_checked(repo_root: Path) -> None:
    docs = {d.relative_to(repo_root).as_posix() for d in checked_documents(repo_root)}
    assert "docs/architecture/07-preview-and-render-parity.md" in docs
    assert {"docs/prd.md", "docs/roadmap.md", "docs/dag.md"} <= docs
    kinds = {c.kind for c in collect_citations(repo_root, checked_documents(repo_root))}
    assert {"analysis", "path", "url", "author-year", "title", "named"} <= kinds


@pytest.mark.parametrize(
    ("kind", "text", "key", "expected"),
    [
        ("path", r"A3D\...\18-Tunica\report.json", "A3D/Creatures/M/18-Tunica/report.json", True),
        ("path", r"PAINTER\resources\mdl\\", "PAINTER/resources/mdl/**", True),
        (
            "path",
            r"PAINTER\resources\python-doc\**\*.html",
            "PAINTER/resources/python-doc/**",
            True,
        ),
        ("path", "runtime/build.zig:1-12", "UzEngine/runtime/**", True),
        ("path", r"E:\UzmiGames\UzEngine", "E:/UzmiGames/UzEngine", True),
        ("path", r"PAINTER\resources\shader-doc\lib-pbr.html", "PAINTER/resources/mdl/**", False),
        ("url", "https://www.sqlite.org/atomiccommit.html", "https://www.sqlite.org/", True),
        ("author-year", "Kajiya 1986", "Kajiya 1986", True),
        ("named", "the BSD-3 MDL SDK", "MDL SDK", True),
        ("title", "Iray Settings", "Iray SDK", False),
    ],
)
def test_key_matching(kind: Kind, text: str, key: str, expected: bool) -> None:
    assert key_matches(Citation("d.md", 1, kind, text, text), key) is expected


def test_normalize_path_aliases() -> None:
    assert normalize_path(r"E:\UzmiGames\Assets3D\Docs") == "a3d/docs"
    assert normalize_path("runtime\\") == "uzengine/runtime"


def cleared_sandbox(sandbox: Sandbox, build_index: IndexBuilder) -> str:
    sandbox.write(ANALYSIS, "# Notes\n")
    commit = sandbox.commit()
    blob = sandbox.blob(ANALYSIS)
    return build_index(cleared=[(ANALYSIS, blob, commit)])


def check_doc(sandbox: Sandbox, index_text: str, body: str) -> list[str]:
    doc = sandbox.write("docs/architecture/01-doc.md", body + "\n")
    return [str(p) for p in citation_check(sandbox.root, parse_index(index_text), [doc])]


def test_cleared_analysis_citation_passes(sandbox: Sandbox, build_index: IndexBuilder) -> None:
    index_text = cleared_sandbox(sandbox, build_index)
    assert check_doc(sandbox, index_text, f"Facts: `{ANALYSIS}`.") == []
    assert check_doc(sandbox, index_text, "Facts: `01-notes.md` §2.") == []


def test_cleared_revision_is_pinned(sandbox: Sandbox, build_index: IndexBuilder) -> None:
    # Spec scenario: once the file changes, only the audited blob is approved.
    index_text = cleared_sandbox(sandbox, build_index)
    sandbox.write(ANALYSIS, "# Notes\n\nNew unaudited text.\n")
    problems = check_doc(sandbox, index_text, f"Facts: `{ANALYSIS}`.")
    assert len(problems) == 1
    assert "differs from its cleared revision" in problems[0]
    sandbox.commit()
    assert len(check_doc(sandbox, index_text, f"Facts: `{ANALYSIS}`.")) == 1
    assert check_doc(sandbox, index_text, f"Earlier: `{ANALYSIS}` (historical context).") == []


def test_uncleared_analysis_stays_restricted(sandbox: Sandbox, build_index: IndexBuilder) -> None:
    # Spec scenario: an unaudited analysis is quarantined and cannot be cited as input.
    sandbox.write(ANALYSIS, "# Notes\n")
    sandbox.commit()
    index_text = build_index(quarantined_analyses=[ANALYSIS])
    problems = check_doc(sandbox, index_text, f"Painter facts: `{ANALYSIS}`.")
    assert len(problems) == 1
    assert "quarantined" in problems[0]
    assert check_doc(sandbox, index_text, f"See `{ANALYSIS}`, historical context only.") == []


def test_analysis_missing_from_index_fails(sandbox: Sandbox, build_index: IndexBuilder) -> None:
    sandbox.write(ANALYSIS, "# Notes\n")
    sandbox.commit()
    problems = check_doc(sandbox, build_index(), f"Facts: `{ANALYSIS}`.")
    assert problems and "not in the approved-source index" in problems[0]


def test_quarantined_path_only_in_prohibition(sandbox: Sandbox, build_index: IndexBuilder) -> None:
    index_text = build_index(quarantined=[("Q-MDL", "`PAINTER/resources/mdl/**`")])
    used = check_doc(sandbox, index_text, "Lobes come from `PAINTER\\resources\\mdl\\x.mdl`.")
    assert len(used) == 1 and "quarantined" in used[0]
    forbidden = "Painter's MDL files (`PAINTER\\resources\\mdl\\`) are never opened."
    assert check_doc(sandbox, index_text, forbidden) == []


def test_unindexed_sources_fail(sandbox: Sandbox, build_index: IndexBuilder) -> None:
    index_text = build_index(approved=[("P-KAJIYA", "`Kajiya 1986`")])
    assert check_doc(sandbox, index_text, "Light transport: Kajiya 1986.") == []
    body = "Sampling: Smith 1999 and the *Secret Handbook*; see https://example.com/x."
    problems = check_doc(sandbox, index_text, body)
    assert len(problems) == 3
    assert all("matches no approved entry" in p for p in problems)


def test_code_fences_are_ignored(sandbox: Sandbox, build_index: IndexBuilder) -> None:
    body = "```\nSmith 1999 https://example.com\n```"
    assert check_doc(sandbox, build_index(), body) == []
