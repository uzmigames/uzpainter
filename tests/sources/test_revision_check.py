"""Test 3.2 — revision check: cleared analysis revisions exist and match the audited content."""

from __future__ import annotations

from pathlib import Path

from tests.sources.conftest import IndexBuilder, Sandbox
from tools.sources.check import revision_check
from tools.sources.index import parse_index

ANALYSIS = "docs/analysis/topic/01-notes.md"
OTHER = "docs/analysis/topic/02-other.md"


def problems_for(sandbox: Sandbox, index_text: str) -> list[str]:
    return [str(p) for p in revision_check(sandbox.root, parse_index(index_text))]


def test_repository_revisions_are_valid(repo_root: Path) -> None:
    problems = revision_check(repo_root)
    assert problems == [], "\n".join(str(p) for p in problems)


def test_valid_clearance_passes(sandbox: Sandbox, build_index: IndexBuilder) -> None:
    sandbox.write(ANALYSIS, "v1\n")
    first = sandbox.commit()
    old_blob = sandbox.blob(ANALYSIS)
    sandbox.write(ANALYSIS, "v2\n")
    second = sandbox.commit()
    index_text = build_index(
        cleared=[(ANALYSIS, sandbox.blob(ANALYSIS), second)], uncleared=[(ANALYSIS, old_blob)]
    )
    assert problems_for(sandbox, index_text) == []
    assert first != second


def test_unknown_blob_fails(sandbox: Sandbox, build_index: IndexBuilder) -> None:
    sandbox.write(ANALYSIS, "v1\n")
    commit = sandbox.commit()
    index_text = build_index(cleared=[(ANALYSIS, "0" * 40, commit)])
    problems = problems_for(sandbox, index_text)
    assert any("does not exist" in p for p in problems)
    assert any("is " in p and "not 0000" in p for p in problems)


def test_blob_must_match_file_at_commit(sandbox: Sandbox, build_index: IndexBuilder) -> None:
    sandbox.write(ANALYSIS, "v1\n")
    first = sandbox.commit()
    old_blob = sandbox.blob(ANALYSIS)
    sandbox.write(ANALYSIS, "v2\n")
    sandbox.commit()
    # The old blob exists, but the cleared commit must hold exactly that content.
    index_text = build_index(cleared=[(ANALYSIS, sandbox.blob(ANALYSIS), first)])
    problems = problems_for(sandbox, index_text)
    assert len(problems) == 1 and old_blob in problems[0]


def test_commit_outside_history_fails(sandbox: Sandbox, build_index: IndexBuilder) -> None:
    sandbox.write(ANALYSIS, "v1\n")
    sandbox.commit()
    index_text = build_index(cleared=[(ANALYSIS, sandbox.blob(ANALYSIS), "1" * 40)])
    assert any("not in the history" in p for p in problems_for(sandbox, index_text))


def test_uncleared_revision_must_be_real_and_distinct(
    sandbox: Sandbox, build_index: IndexBuilder
) -> None:
    sandbox.write(ANALYSIS, "v1\n")
    commit = sandbox.commit()
    blob = sandbox.blob(ANALYSIS)
    index_text = build_index(
        cleared=[(ANALYSIS, blob, commit)],
        uncleared=[(ANALYSIS, blob), (ANALYSIS, "2" * 40)],
    )
    problems = problems_for(sandbox, index_text)
    assert any("both cleared and uncleared" in p for p in problems)
    assert any("is not a revision" in p for p in problems)


def test_every_analysis_file_is_cleared_or_quarantined(
    sandbox: Sandbox, build_index: IndexBuilder
) -> None:
    sandbox.write(ANALYSIS, "v1\n")
    sandbox.write(OTHER, "other\n")
    commit = sandbox.commit()
    index_text = build_index(cleared=[(ANALYSIS, sandbox.blob(ANALYSIS), commit)])
    problems = problems_for(sandbox, index_text)
    assert len(problems) == 1 and "02-other.md is neither cleared nor quarantined" in problems[0]
    index_text = build_index(
        cleared=[(ANALYSIS, sandbox.blob(ANALYSIS), commit)], quarantined_analyses=[OTHER]
    )
    assert problems_for(sandbox, index_text) == []


def test_cleared_and_quarantined_conflict(sandbox: Sandbox, build_index: IndexBuilder) -> None:
    sandbox.write(ANALYSIS, "v1\n")
    commit = sandbox.commit()
    index_text = build_index(
        cleared=[(ANALYSIS, sandbox.blob(ANALYSIS), commit)], quarantined_analyses=[ANALYSIS]
    )
    assert any("both cleared and quarantined" in p for p in problems_for(sandbox, index_text))
