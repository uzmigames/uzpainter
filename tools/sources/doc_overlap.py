"""Verbatim-span check of inventory prose against Painter's admitted public API documentation.

`phase5.5_clean-history` items 2.1 and 5.3: the description prose of the Substance API
inventory is written in UzmiGames' own words, so no prose cell may reproduce a span of the
public documentation (approved sources A-PYDOC and A-JSDOC, `docs/approved-sources.md`). The
documentation is read at run time from the local Painter install; no documentation text is
stored in the repository.

The comparison is deterministic and works on normalised words (lower case, runs of `[a-z0-9]`).
Inline code spans that read as code (one token, or code punctuation) are cut out first, because
module, symbol, signature, parameter and enum names are documented API shape that the inventory
keeps on purpose (licensing §1.4); a code span of plain words is checked as prose.

- verbatim span: a prose cell fails when it holds a run of `RUN_WORDS` or more consecutive
  words that occurs in a documentation page;
- verbatim short cell: a cell of `SHORT_MIN_WORDS` to `RUN_WORDS - 1` words fails when the
  whole cell occurs as a contiguous run in one page;
- close paraphrase: a cell of `COVER_MIN_WORDS` or more words fails when `COVER_LIMIT` or more
  of its words lie inside `COVER_GRAM`-word phrases that occur in the documentation (a
  sentence stitched from documentation phrases with a few words changed).

On the pre-sanitisation revision of the inventory these rules flag 487 of its cells; the
thresholds leave room for the short domain phrases ("of the Texture Set") that any
description of the same API shares with the documentation.

Checked prose: every table cell of the Markdown inventory except the API-shape and citation
columns (`KEPT_COLUMNS`), every paragraph and list line outside its tables (headings are
names), and the `notes` and `justification` text of each Painter symbol entry of the
capability inventory (`JSON_PROSE_FIELDS`).

Run: `python -m tools.sources.doc_overlap [--doc-root DIR ...] [FILE ...]`. Exit status 0 when
no cell fails, 1 on findings, 2 when no documentation root is available.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = REPO_ROOT / "docs" / "analysis" / "substance-parity" / "01-python-api-inventory.md"
CAPABILITY_INVENTORY_PATH = REPO_ROOT / "tools" / "capabilities" / "painter-api-inventory.json"
CHECKED_FILES = (INVENTORY_PATH, CAPABILITY_INVENTORY_PATH)
JSON_PROSE_FIELDS = ("notes", "justification")

# Same convention as tests/capabilities and tests/parity/recorder: the variable names the
# python-doc `objects.inv`; javascript-doc is its sibling folder in the install.
PYTHON_DOC_ENV = "UZP_PAINTER_PYTHON_DOC"
DEFAULT_OBJECTS_INV = Path(
    r"C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\python-doc\objects.inv"
)

RUN_WORDS = 6
SHORT_MIN_WORDS = 3
COVER_GRAM = 4
COVER_MIN_WORDS = 8
COVER_LIMIT = 0.6

# Columns that hold API shape (kept verbatim by design) or citations, not description prose.
KEPT_COLUMNS = frozenset(
    {"symbol", "kind", "signature / fields / members", "source", "label", "module", "item", "#"}
)

_CODE_SPAN = re.compile(r"`([^`]*)`")
# A code span is API shape when it reads as code: one token, or any code punctuation.
_CODE_LIKE = re.compile(r"^\S*$|[()\[\]{}:=_./\\<>*|,'\"-]")
_TAG = re.compile(r"<[^>]*>")
_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+")
_SEPARATOR_ROW = re.compile(r"^\|(\s*:?-+:?\s*\|)+\s*$")


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def default_doc_roots() -> list[Path]:
    """The python-doc and javascript-doc folders of the local install, where present."""
    objects_inv = Path(os.environ.get(PYTHON_DOC_ENV, str(DEFAULT_OBJECTS_INV)))
    python_doc = objects_inv.parent
    candidates = (python_doc, python_doc.parent / "javascript-doc")
    return [root for root in candidates if root.is_dir()]


def page_words(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    raw = _SCRIPT_STYLE.sub(" ", raw)
    return words(html.unescape(_TAG.sub(" ", raw)))


@dataclass
class DocCorpus:
    """The `RUN_WORDS`- and `COVER_GRAM`-word windows of the pages and each page's word stream."""

    grams: set[tuple[str, ...]]
    cover_grams: set[tuple[str, ...]]
    streams: list[str]
    pages: int

    @classmethod
    def load(cls, roots: Iterable[Path]) -> DocCorpus:
        grams: set[tuple[str, ...]] = set()
        cover_grams: set[tuple[str, ...]] = set()
        streams: list[str] = []
        pages = 0
        for root in roots:
            for path in sorted(root.rglob("*.html")):
                tokens = page_words(path)
                pages += 1
                streams.append(" " + " ".join(tokens) + " ")
                for i in range(len(tokens) - RUN_WORDS + 1):
                    grams.add(tuple(tokens[i : i + RUN_WORDS]))
                for i in range(len(tokens) - COVER_GRAM + 1):
                    cover_grams.add(tuple(tokens[i : i + COVER_GRAM]))
        return cls(grams, cover_grams, streams, pages)

    def longest_run(self, tokens: Sequence[str]) -> int:
        """Longest run of `tokens` whose every `RUN_WORDS`-word window occurs in the documentation.

        0 when no window occurs.
        """
        best = 0
        current = 0
        for i in range(len(tokens) - RUN_WORDS + 1):
            if tuple(tokens[i : i + RUN_WORDS]) in self.grams:
                current = RUN_WORDS if current == 0 else current + 1
                best = max(best, current)
            else:
                current = 0
        return best

    def digest(self) -> str:
        """SHA-256 of the normalised pages, identifying the documentation compared against."""
        return hashlib.sha256("\n".join(self.streams).encode("utf-8")).hexdigest()

    def contains(self, tokens: Sequence[str]) -> bool:
        needle = " " + " ".join(tokens) + " "
        return any(needle in stream for stream in self.streams)

    def covered(self, tokens: Sequence[str]) -> int:
        """How many of `tokens` lie inside a `COVER_GRAM`-word window found in the documentation."""
        inside = [False] * len(tokens)
        for i in range(len(tokens) - COVER_GRAM + 1):
            if tuple(tokens[i : i + COVER_GRAM]) in self.cover_grams:
                inside[i : i + COVER_GRAM] = [True] * COVER_GRAM
        return sum(inside)


@dataclass(frozen=True)
class Cell:
    path: str
    line: int
    column: str
    text: str


@dataclass(frozen=True)
class Finding:
    cell: Cell
    reason: str

    def __str__(self) -> str:
        where = f"{self.cell.path}:{self.cell.line} [{self.cell.column}]"
        return f"{where} {self.reason}: {self.cell.text}"


def _split_row(line: str) -> list[str]:
    body = line.strip()[1:]
    if body.endswith("|"):
        body = body[:-1]
    # A `|` inside a code span (for example a union type) or escaped as `\|` is not a separator.
    cells: list[str] = []
    current: list[str] = []
    in_code = False
    previous = ""
    for ch in body:
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code and previous != "\\":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        previous = ch
    cells.append("".join(current).strip())
    return cells


def prose_cells(path: Path, label: str | None = None) -> Iterator[Cell]:
    """The description prose of a Markdown file: table cells outside `KEPT_COLUMNS`, other lines."""
    name = label or path.as_posix()
    header: list[str] | None = None
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            header = None
            if stripped and not stripped.startswith("#"):
                yield Cell(name, number, "text", stripped)
            continue
        if _SEPARATOR_ROW.match(stripped):
            continue
        cells = _split_row(stripped)
        if header is None:
            header = [c.lower() for c in cells]
            continue
        for column, cell in zip(header, cells, strict=False):
            if column not in KEPT_COLUMNS and cell:
                yield Cell(name, number, column, cell)


def json_prose_cells(path: Path, label: str | None = None) -> Iterator[Cell]:
    """The `JSON_PROSE_FIELDS` text of each entry of a capability inventory (`entries` list)."""
    name = label or path.as_posix()
    data = json.loads(path.read_text(encoding="utf-8"))
    for index, entry in enumerate(data["entries"]):
        for field in JSON_PROSE_FIELDS:
            text = entry.get(field)
            if isinstance(text, str) and text:
                yield Cell(name, index, f"{entry['symbol']}.{field}", text)


def prose_parts(text: str) -> list[str]:
    """`text` split at its code spans, so that a run never bridges a removed symbol name.

    A code span that does not read as code (several plain words, no code punctuation) is
    prose wrapped in backticks and is kept as its own part.
    """
    parts: list[str] = []
    last = 0
    for match in _CODE_SPAN.finditer(text):
        parts.append(text[last : match.start()])
        if not _CODE_LIKE.search(match.group(1).strip()):
            parts.append(match.group(1))
        last = match.end()
    parts.append(text[last:])
    return parts


def check_cells(cells: Iterable[Cell], corpus: DocCorpus) -> list[Finding]:
    findings: list[Finding] = []
    for cell in cells:
        segments = [seg for seg in (words(part) for part in prose_parts(cell.text)) if seg]
        run = max((corpus.longest_run(seg) for seg in segments), default=0)
        if run:
            findings.append(Finding(cell, f"shares a {run}-word run with the documentation"))
        elif (
            len(segments) == 1
            and SHORT_MIN_WORDS <= len(segments[0]) < RUN_WORDS
            and corpus.contains(segments[0])
        ):
            findings.append(Finding(cell, "whole cell occurs verbatim in the documentation"))
        else:
            total = sum(len(seg) for seg in segments)
            inside = sum(corpus.covered(seg) for seg in segments)
            if total >= COVER_MIN_WORDS and inside >= COVER_LIMIT * total:
                findings.append(
                    Finding(cell, f"{inside} of {total} words lie in documentation phrases")
                )
    return findings


def check_files(paths: Iterable[Path], corpus: DocCorpus) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        try:
            label = path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            label = path.as_posix()
        reader = json_prose_cells if path.suffix == ".json" else prose_cells
        cells = reader(path, label)
        findings.extend(check_cells(cells, corpus))
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "files", nargs="*", type=Path, help="Markdown or capability-inventory JSON files"
    )
    parser.add_argument("--doc-root", action="append", type=Path, default=None)
    args = parser.parse_args(argv)
    roots = args.doc_root or default_doc_roots()
    roots = [root for root in roots if root.is_dir()]
    if not roots:
        print("no documentation root found (set UZP_PAINTER_PYTHON_DOC)", file=sys.stderr)
        return 2
    corpus = DocCorpus.load(roots)
    findings = check_files(args.files or CHECKED_FILES, corpus)
    for finding in findings:
        print(finding)
    print(
        f"{len(findings)} finding(s); {corpus.pages} documentation pages, sha256 {corpus.digest()}",
        file=sys.stderr,
    )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
