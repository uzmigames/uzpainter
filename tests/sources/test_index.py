"""The published index: structure, the spec scenarios and the javascript-doc decision."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.sources.check import INDEX_PATH
from tools.sources.citations import Citation, key_matches
from tools.sources.index import SourceIndex, load_index, parse_index


@pytest.fixture
def index(repo_root: Path) -> SourceIndex:
    return load_index(repo_root / INDEX_PATH)


def path_citation(text: str, sentence: str = "Source: it.") -> Citation:
    return Citation("doc.md", 1, "path", text, sentence)


def test_index_parses_without_problems(index: SourceIndex) -> None:
    assert index.problems == ()
    ids = [e.entry_id for e in index.entries]
    assert len(ids) == len(set(ids))


def test_every_approved_entry_states_scope_and_reviewer(index: SourceIndex) -> None:
    for entry in index.approved():
        assert entry.fields.get("Cleared scope", "").strip(" —"), entry.entry_id
        assert entry.fields.get("Reviewer", "").strip(" —"), entry.entry_id


def test_public_specification_is_admitted(index: SourceIndex) -> None:
    # Spec scenario: OpenPBR, cited by 07-preview-and-render-parity.md, has an entry.
    openpbr = [e for e in index.approved() if "OpenPBR" in e.keys]
    assert len(openpbr) == 1
    entry = openpbr[0]
    assert entry.entry_id
    assert entry.fields["Category"].strip()
    assert entry.fields["Cleared scope"].strip()
    assert "OpenPBR Surface specification" in entry.fields["Source"]


@pytest.mark.parametrize(
    "off_limits",
    [
        r"PAINTER\resources\starter_assets\shaders\pbr-metal-rough.glsl",
        r"PAINTER\resources\shader-doc\lib-pbr.html",
        r"PAINTER\resources\mdl\painter.mdl",
        r"PAINTER\resources\python\modules\substance_painter\project.py",
        r"PAINTER\resources\python\modules\substance_painter_tests\test_export.py",
    ],
)
def test_off_limits_adobe_file_is_quarantined(index: SourceIndex, off_limits: str) -> None:
    # Spec scenario: the quarantine names the source and no approved entry covers it.
    citation = path_citation(off_limits)
    assert any(key_matches(citation, k) for e in index.quarantined() for k in e.keys)
    assert not any(key_matches(citation, k) for e in index.approved() for k in e.keys)


def test_public_python_doc_is_approved(index: SourceIndex) -> None:
    citation = path_citation(r"PAINTER\resources\python-doc\substance_painter\display.html")
    approved = [
        e.entry_id for e in index.approved() if any(key_matches(citation, k) for k in e.keys)
    ]
    assert approved == ["A-PYDOC"]


def test_javascript_doc_decision_is_recorded(index: SourceIndex) -> None:
    entry = next(e for e in index.entries if e.entry_id == "A-JSDOC")
    assert entry.status == "approved"
    assert "Decision: admitted" in entry.fields["Source"]


def test_mdl_and_flip_are_admitted(index: SourceIndex) -> None:
    keys = {k for e in index.approved() for k in e.keys}
    assert {"MDL specification", "MDL SDK", "NVlabs/flip"} <= keys


def test_cleared_and_quarantined_analyses_are_disjoint(index: SourceIndex) -> None:
    cleared = {c.path for c in index.clearances}
    assert cleared
    assert not cleared & set(index.quarantined_analyses)


def test_quarantined_analysis_is_listed(index: SourceIndex) -> None:
    assert "substance-parity/02-layer-stack-model.md" in index.quarantined_analyses
    assert "architecture-discussion/04-astra-critique.md" in index.quarantined_analyses


def test_parser_reads_tables_by_section() -> None:
    text = "\n".join(
        [
            "## Approved sources",
            "| ID | Source | Category | Revision / hash | Licence | Cleared scope | Cited as "
            "| Reviewer |",
            "|---|---|---|---|---|---|---|---|",
            "| S-1 | a `b|c` | Paper | — | — | scope | `Kajiya 1986`; `Veach 1997` | r |",
            "## Quarantine",
            "| ID | Source | Reason | Matches |",
            "|---|---|---|---|",
            "| Q-1 | x | y | `PAINTER/resources/mdl/**` |",
            "| Q-1 | x | y | `z` |",
        ]
    )
    parsed = parse_index(text)
    assert [(e.entry_id, e.status) for e in parsed.entries] == [
        ("S-1", "approved"),
        ("Q-1", "quarantined"),
        ("Q-1", "quarantined"),
    ]
    assert parsed.entries[0].keys == ("Kajiya 1986", "Veach 1997")
    assert parsed.problems == ("duplicate entry id Q-1",)
