"""Parser for the approved-source index (`docs/approved-sources.md`).

The index is Markdown. Its level-2 headings split it into the approved part (`## Approved ...`)
and the quarantine (`## Quarantine ...`). Every table row with an `ID` column is an entry; the
backticked tokens of its `Cited as` column (approved) or `Matches` column (quarantine) are the
keys a citation is matched against. Three tables carry extra structure:

- cleared analyses: columns `Path`, `Blob`, `Commit` in the approved part;
- uncleared analyses: column `Path` and no `Blob` in the quarantine part;
- uncleared historical revisions: columns `Path` and `Uncleared blobs` in the quarantine part;
- UzmiGames files: columns `Repository`, `Path`, `Commit`, `Object` in the approved part.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Status = Literal["approved", "quarantined"]

BACKTICK_RE = re.compile(r"`([^`]+)`")
SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")


@dataclass(frozen=True)
class Entry:
    entry_id: str
    status: Status
    section: str
    fields: Mapping[str, str]
    keys: tuple[str, ...]


@dataclass(frozen=True)
class AnalysisClearance:
    entry_id: str
    path: str
    blob: str
    commit: str


@dataclass(frozen=True)
class RepoObject:
    entry_id: str
    repository: str
    path: str
    commit: str
    object_id: str


@dataclass(frozen=True)
class SourceIndex:
    entries: tuple[Entry, ...]
    clearances: tuple[AnalysisClearance, ...]
    quarantined_analyses: tuple[str, ...]
    uncleared_revisions: Mapping[str, tuple[str, ...]]
    repo_objects: tuple[RepoObject, ...]
    problems: tuple[str, ...] = field(default=())

    def approved(self) -> Iterator[Entry]:
        return (e for e in self.entries if e.status == "approved")

    def quarantined(self) -> Iterator[Entry]:
        return (e for e in self.entries if e.status == "quarantined")

    def clearance_for(self, path: str) -> AnalysisClearance | None:
        for clearance in self.clearances:
            if clearance.path == path:
                return clearance
        return None


def split_row(line: str) -> list[str]:
    """Cells of a Markdown table row; a `|` inside backticks does not split."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells: list[str] = []
    current: list[str] = []
    in_code = False
    for char in body:
        if char == "`":
            in_code = not in_code
        if char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    cells.append("".join(current).strip())
    return cells


def is_separator(line: str) -> bool:
    cells = split_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def iter_tables(text: str) -> Iterator[tuple[str, str, list[dict[str, str]]]]:
    """Yield (level-2 heading, level-3 heading, rows) for every table in the document."""
    h2 = ""
    h3 = ""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            h2, h3 = line[3:].strip(), ""
        elif line.startswith("### "):
            h3 = line[4:].strip()
        elif line.lstrip().startswith("|") and i + 1 < len(lines) and is_separator(lines[i + 1]):
            header = split_row(line)
            rows: list[dict[str, str]] = []
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = split_row(lines[i])
                rows.append(dict(zip(header, cells, strict=False)))
                i += 1
            yield h2, h3, rows
            continue
        i += 1


def backticked(cell: str) -> tuple[str, ...]:
    return tuple(t.strip() for t in BACKTICK_RE.findall(cell) if t.strip())


def first_sha(cell: str) -> str:
    match = SHA_RE.search(cell)
    return match.group(0) if match else ""


def analysis_path(cell: str) -> str:
    """The `docs/analysis/...` path named in a cell, without the `docs/analysis/` prefix."""
    for token in backticked(cell) or (cell,):
        token = token.replace("\\", "/")
        if token.startswith("docs/analysis/"):
            return token[len("docs/analysis/") :]
    return ""


def parse_index(text: str) -> SourceIndex:
    entries: list[Entry] = []
    clearances: list[AnalysisClearance] = []
    quarantined_analyses: list[str] = []
    uncleared: dict[str, tuple[str, ...]] = {}
    repo_objects: list[RepoObject] = []
    problems: list[str] = []
    seen_ids: set[str] = set()

    for h2, h3, rows in iter_tables(text):
        lowered = h2.lower()
        if lowered.startswith("approved"):
            status: Status = "approved"
        elif lowered.startswith("quarantine"):
            status = "quarantined"
        else:
            continue
        for row in rows:
            if "Uncleared blobs" in row:
                path = analysis_path(row.get("Path", ""))
                blobs = tuple(SHA_RE.findall(row["Uncleared blobs"]))
                if not path:
                    problems.append(f"uncleared-revision row without a docs/analysis path: {row}")
                uncleared[path] = uncleared.get(path, ()) + blobs
                continue
            entry_id = row.get("ID", "").strip("`* ")
            if not entry_id:
                continue
            if entry_id in seen_ids:
                problems.append(f"duplicate entry id {entry_id}")
            seen_ids.add(entry_id)
            key_cell = row.get("Cited as", "") if status == "approved" else row.get("Matches", "")
            keys = list(backticked(key_cell))
            path = analysis_path(row.get("Path", ""))
            if path:
                keys.append(f"docs/analysis/{path}")
                if status == "approved" and "Blob" in row:
                    clearances.append(
                        AnalysisClearance(
                            entry_id, path, first_sha(row["Blob"]), first_sha(row.get("Commit", ""))
                        )
                    )
                elif status == "quarantined":
                    quarantined_analyses.append(path)
            if status == "approved" and "Repository" in row and "Object" in row:
                repo_cell = backticked(row["Repository"])
                path_cell = backticked(row.get("Path", ""))
                repo_objects.append(
                    RepoObject(
                        entry_id,
                        repo_cell[0] if repo_cell else row["Repository"],
                        path_cell[0] if path_cell else row.get("Path", ""),
                        first_sha(row.get("Commit", "")),
                        first_sha(row["Object"]),
                    )
                )
            entries.append(Entry(entry_id, status, h3 or h2, dict(row), tuple(keys)))

    return SourceIndex(
        tuple(entries),
        tuple(clearances),
        tuple(quarantined_analyses),
        uncleared,
        tuple(repo_objects),
        tuple(problems),
    )


def load_index(path: Path) -> SourceIndex:
    return parse_index(path.read_text(encoding="utf-8"))
