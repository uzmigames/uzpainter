"""Verbatim-span check of inventory prose against Painter's admitted public API documentation.

`phase5.5_clean-history` items 2.1 and 5.3: the description prose of the Substance API
inventory is written in UzmiGames' own words, so no prose cell may reproduce a span of the
public documentation (approved sources A-PYDOC and A-JSDOC, `docs/approved-sources.md`). The
documentation is read at run time from the local Painter install; no documentation text is
stored in the repository.

The comparison is deterministic and works on normalised words (lower case, runs of `[a-z0-9]`).
Inline code is cut out first, because module, symbol, signature, parameter and enum names are
documented API shape that the inventory keeps on purpose (licensing §1.4). A code span of one
token is code. In a code span of several tokens only the tokens that read as code are cut
(`is_code_token`: code punctuation such as brackets, `=`, `|`, `/` or `->`, a `snake_case`
or `dotted.name` identifier); its other words are checked as prose, so sentence punctuation
(a period, a comma, an apostrophe) never turns wrapped prose into code. A span that only lists
single-token names separated by commas (enum members, map names) is code (`is_name_list`).

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

Two kinds of text are not prose and are cut out like code spans (decision 304, amendment of
2026-10-19): the product and preset names of `NAME_ALLOWLIST`, which any text about the
product has to spell as Adobe does (the edition label "<product> 12.1.0 python-doc (Python API
0.3.5)" passes once its product name is cut), and runs made only of numbers (`(1.0, 1.0, 1.0)`,
`0 / 0 / 0`), which are measured facts, not wording. A window or short cell counts only when it
holds at least one word that is not a number.

Checked prose (`CHECKED_FILES`): every table cell of the Markdown files except the API-shape,
citation and UI-label columns (`KEPT_COLUMNS`), every paragraph and list line outside their
tables (headings are names), and the `notes` and `justification` text of each Painter symbol
entry of the capability inventory (`JSON_PROSE_FIELDS`). The Markdown files are the Substance
API inventory, the other substance-parity analyses (02 to 08), their Astra review and every
decision record.

The full gate (no `--doc-root`, no FILE) checks `CHECKED_FILES` and needs both documentation
families of the install, python-doc and javascript-doc, each with readable pages. A run given
`--doc-root` or FILE is a partial scan: it says so and never counts as the gate's approval.

A lexical pass is not provenance admission (the inventory's index entry stays quarantined,
QH-SP-INVENTORY) and does not prove independent authorship.

Run: `python -m tools.sources.doc_overlap [--doc-root DIR ...] [FILE ...]`. Exit status 0 when
the full gate finds no failing cell, 1 on findings, 2 when the documentation is missing or
unusable (an expected family absent, a root without readable pages), 3 when a partial scan
finds nothing (not an approval).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
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
SUBSTANCE_PARITY_DIR = INVENTORY_PATH.parent
REVIEW_PATH = REPO_ROOT / "docs" / "analysis" / "reviews" / "substance-parity-astra-review.md"
DECISIONS_DIR = REPO_ROOT / ".rulebook" / "decisions"
CHECKED_FILES = (
    *sorted(SUBSTANCE_PARITY_DIR.glob("0[1-8]-*.md")),
    REVIEW_PATH,
    *sorted(DECISIONS_DIR.glob("*.md")),
    CAPABILITY_INVENTORY_PATH,
)
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

# Columns that hold API shape (kept verbatim by design), citations or Painter's UI labels (names
# a description has to spell as the UI does, `03-baking.md`), not description prose.
KEPT_COLUMNS = frozenset(
    {
        "symbol",
        "kind",
        "signature / fields / members",
        "source",
        "label",
        "module",
        "item",
        "#",
        "likely ui label",
    }
)

# Names, not wording: each is cut out of the prose like a code span, so a run never bridges it.
# Every entry is a whole name; no generic phrase belongs here.
NAME_ALLOWLIST: dict[str, str] = {
    "Adobe Substance 3D Painter": "product name (approved sources, edition label, provenance)",
    "Substance 3D Painter": "product name without the vendor",
    "PBR Metallic Roughness": "name of a shipped export preset (`PredefinedExportPreset`)",
}

_CODE_SPAN = re.compile(r"`([^`]*)`")
# A token of a code span reads as code when it holds code punctuation or an identifier joint
# (`a_b`, `name.attr`); a period, comma, colon, apostrophe or hyphen alone is prose punctuation.
_CODE_TOKEN = re.compile(r"[()\[\]{}=<>|*/\\$#@]|->|\w_\w|[A-Za-z_]\w+\.\w")
_TAG = re.compile(r"<[^>]*>")
_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+")
_SEPARATOR_ROW = re.compile(r"^\|(\s*:?-+:?\s*\|)+\s*$")


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


_NAME_TOKENS = sorted((tuple(words(name)) for name in NAME_ALLOWLIST), key=len, reverse=True)


def is_prose(tokens: Sequence[str]) -> bool:
    """A window of words is prose unless every word is a number."""
    return not all(token.isdigit() for token in tokens)


def cut_names(tokens: Sequence[str]) -> list[list[str]]:
    """`tokens` split at each `NAME_ALLOWLIST` name, which is dropped."""
    segments: list[list[str]] = [[]]
    i = 0
    while i < len(tokens):
        name = next((n for n in _NAME_TOKENS if tuple(tokens[i : i + len(n)]) == n), None)
        if name is None:
            segments[-1].append(tokens[i])
            i += 1
        else:
            segments.append([])
            i += len(name)
    return [segment for segment in segments if segment]


class DocumentationError(Exception):
    """The documentation compared against is missing or unusable."""


def expected_doc_roots() -> dict[str, Path]:
    """The python-doc and javascript-doc folders the full gate compares against."""
    objects_inv = Path(os.environ.get(PYTHON_DOC_ENV, str(DEFAULT_OBJECTS_INV)))
    python_doc = objects_inv.parent
    return {"python-doc": python_doc, "javascript-doc": python_doc.parent / "javascript-doc"}


def default_doc_roots() -> list[Path]:
    """Both documentation families of the local install; `[]` where neither is installed.

    Raises `DocumentationError` when only one family is present: a run with one family must
    never approve text checked against the other.
    """
    expected = expected_doc_roots()
    missing = [family for family, root in expected.items() if not root.is_dir()]
    if len(missing) == len(expected):
        return []
    if missing:
        raise DocumentationError(f"documentation family missing: {', '.join(missing)}")
    return list(expected.values())


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
            readable = 0
            for path in sorted(root.rglob("*.html")):
                tokens = page_words(path)
                pages += 1
                if len(tokens) >= RUN_WORDS:
                    readable += 1
                streams.append(" " + " ".join(tokens) + " ")
                for i in range(len(tokens) - RUN_WORDS + 1):
                    grams.add(tuple(tokens[i : i + RUN_WORDS]))
                for i in range(len(tokens) - COVER_GRAM + 1):
                    cover_grams.add(tuple(tokens[i : i + COVER_GRAM]))
            if readable == 0:
                raise DocumentationError(f"no readable documentation pages under {root}")
        if pages == 0:
            raise DocumentationError("no documentation root given")
        return cls(grams, cover_grams, streams, pages)

    def longest_run(self, tokens: Sequence[str]) -> int:
        """Longest run of `tokens` whose every `RUN_WORDS`-word window occurs in the documentation.

        0 when no window occurs.
        """
        best = 0
        current = 0
        for i in range(len(tokens) - RUN_WORDS + 1):
            window = tuple(tokens[i : i + RUN_WORDS])
            if window in self.grams and is_prose(window):
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
            window = tuple(tokens[i : i + COVER_GRAM])
            if window in self.cover_grams and is_prose(window):
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


def is_code_token(token: str) -> bool:
    return bool(_CODE_TOKEN.search(token))


def is_name_list(span: str) -> bool:
    """A code span listing names: two or more comma-separated items, each a single token."""
    items = [item.strip() for item in span.split(",")]
    return len(items) > 1 and all(item and len(item.split()) == 1 for item in items)


def prose_parts(text: str) -> list[str]:
    """`text` split at its code spans, so that a run never bridges a removed symbol name.

    A one-token code span is dropped. In a longer span each code token is dropped and the
    words between them are kept, each run of them as its own part: prose wrapped in
    backticks stays prose.
    """
    parts: list[str] = []
    last = 0
    for match in _CODE_SPAN.finditer(text):
        parts.append(text[last : match.start()])
        tokens = match.group(1).split()
        if len(tokens) > 1 and not is_name_list(match.group(1)):
            current: list[str] = []
            for token in tokens:
                if is_code_token(token):
                    parts.append(" ".join(current))
                    current = []
                else:
                    current.append(token)
            parts.append(" ".join(current))
        last = match.end()
    parts.append(text[last:])
    return parts


def check_cells(cells: Iterable[Cell], corpus: DocCorpus) -> list[Finding]:
    findings: list[Finding] = []
    for cell in cells:
        segments = [seg for part in prose_parts(cell.text) for seg in cut_names(words(part))]
        run = max((corpus.longest_run(seg) for seg in segments), default=0)
        if run:
            findings.append(Finding(cell, f"shares a {run}-word run with the documentation"))
        elif (
            len(segments) == 1
            and SHORT_MIN_WORDS <= len(segments[0]) < RUN_WORDS
            and is_prose(segments[0])
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
    partial = args.doc_root is not None or bool(args.files)
    try:
        roots = args.doc_root if args.doc_root is not None else default_doc_roots()
        if not roots:
            raise DocumentationError(f"no documentation root found (set {PYTHON_DOC_ENV})")
        absent = [str(root) for root in roots if not root.is_dir()]
        if absent:
            raise DocumentationError(f"documentation root absent: {', '.join(absent)}")
        corpus = DocCorpus.load(roots)
    except DocumentationError as error:
        print(error, file=sys.stderr)
        return 2
    # Findings quote the checked text, which holds non-ASCII punctuation; a legacy console
    # code page must not abort the report.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors="backslashreplace")
    findings = check_files(args.files or CHECKED_FILES, corpus)
    for finding in findings:
        print(finding)
    scope = "partial scan (--doc-root or FILE), not the full gate" if partial else "full gate"
    print(
        f"{len(findings)} finding(s); {scope}; {corpus.pages} documentation pages, "
        f"sha256 {corpus.digest()}",
        file=sys.stderr,
    )
    if findings:
        return 1
    return 3 if partial else 0


if __name__ == "__main__":
    raise SystemExit(main())
