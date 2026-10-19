"""Inventory prose against the admitted public API documentation (phase5.5_clean-history 2.1, 5.3).

The documentation is read at test time from the local Painter install (`UZP_PAINTER_PYTHON_DOC`
names python-doc's `objects.inv`; javascript-doc is its sibling); the tests that need it skip
where it is absent. No documentation text is stored in the repository: the detection cases
below cut their spans out of the local pages at run time.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.sources import doc_overlap
from tools.sources.doc_overlap import (
    CHECKED_FILES,
    COVER_GRAM,
    RUN_WORDS,
    Cell,
    DocCorpus,
    check_cells,
    check_files,
    page_words,
    prose_cells,
)


@pytest.fixture(scope="module")
def doc_roots() -> list[Path]:
    roots = doc_overlap.default_doc_roots()
    if not roots:
        pytest.skip(f"Painter's public API documentation is absent ({doc_overlap.PYTHON_DOC_ENV})")
    return roots


@pytest.fixture(scope="module")
def corpus(doc_roots: list[Path]) -> DocCorpus:
    return DocCorpus.load(doc_roots)


@pytest.fixture(scope="module")
def doc_window(doc_roots: list[Path]) -> list[str]:
    """Twelve consecutive words of the first python-doc API page long enough to hold them."""
    for path in sorted((doc_roots[0] / "substance_painter").rglob("*.html")):
        tokens = page_words(path)
        if len(tokens) >= 200:
            return tokens[100:112]
    pytest.skip("no python-doc API page with enough text")


def cell(text: str) -> Cell:
    return Cell("synthetic.md", 1, "purpose", text)


def test_inventory_prose_shares_no_span_with_the_documentation(corpus: DocCorpus) -> None:
    findings = check_files(CHECKED_FILES, corpus)
    assert [str(f) for f in findings] == []


def test_a_verbatim_documentation_span_is_detected(
    corpus: DocCorpus, doc_window: list[str]
) -> None:
    span = " ".join(doc_window[:RUN_WORDS])
    findings = check_cells([cell(f"Our own lead-in, then {span}.")], corpus)
    assert len(findings) == 1
    assert "word run" in findings[0].reason


def test_a_documentation_sentence_with_words_swapped_is_detected(
    corpus: DocCorpus, doc_window: list[str]
) -> None:
    # Every fifth word replaced: no six-word run is left, but most words still sit inside
    # four-word documentation phrases (a close paraphrase).
    step = COVER_GRAM + 1
    stitched = [w if i % step != COVER_GRAM else "qqzx" for i, w in enumerate(doc_window)]
    findings = check_cells([cell(" ".join(stitched))], corpus)
    assert len(findings) == 1
    assert "documentation phrases" in findings[0].reason


def test_a_short_cell_copied_whole_is_detected(corpus: DocCorpus, doc_window: list[str]) -> None:
    findings = check_cells([cell(" ".join(doc_window[:4]))], corpus)
    assert len(findings) == 1
    assert "verbatim" in findings[0].reason


def test_independent_wording_and_api_names_pass(corpus: DocCorpus, doc_window: list[str]) -> None:
    cells = [
        cell("Quietly folds the zebra ledger into a violet teacup before dawn."),
        # Documented names inside code spans are API shape, never prose.
        cell(f"Returns `{'_'.join(doc_window[: RUN_WORDS + 2])}` unchanged."),
    ]
    assert check_cells(cells, corpus) == []


def test_prose_wrapped_in_backticks_is_still_checked(
    corpus: DocCorpus, doc_window: list[str]
) -> None:
    findings = check_cells([cell(f"See `{' '.join(doc_window[:RUN_WORDS])}`.")], corpus)
    assert len(findings) == 1


def test_prose_cells_skip_api_shape_columns(tmp_path: Path) -> None:
    md = tmp_path / "inventory.md"
    md.write_text(
        "# Title\n\n"
        "Intro line.\n\n"
        "| Symbol | Kind | Signature / fields / members | Purpose |\n"
        "|---|---|---|---|\n"
        "| `a.b` | method | `f(x: int \\| None)` | Own words \\| still one cell. |\n",
        encoding="utf-8",
    )
    found = [(c.column, c.text) for c in prose_cells(md)]
    assert found == [("text", "Intro line."), ("purpose", "Own words \\| still one cell.")]


def test_cli_without_documentation_exits_2(tmp_path: Path) -> None:
    assert doc_overlap.main(["--doc-root", str(tmp_path / "absent")]) == 2
