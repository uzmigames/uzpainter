"""Citation extraction and matching against the approved-source index.

A citation is a mention of a source in a document: a `docs/analysis/` file, an Adobe install
path (`PAINTER\\...`), an Assets3D path (`A3D\\...`), a UzEngine path (`runtime/...` or
`E:\\UzmiGames\\UzEngine`), a URL, an author-year reference (`Kajiya 1986`), an italic title
(`*Iray Settings*`) or a named specification or SDK (`OpenPBR Surface specification`).

Two kinds of mention are not uses of a source:
- a prohibition: the sentence forbids the source (`never`, `not`, `off-limits`, ...);
- a history pointer: the sentence marks the mention as `historical context`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Kind = Literal["analysis", "path", "url", "author-year", "title", "named"]

FENCE_RE = re.compile(r"^\s*```")
CODE_SPAN_RE = re.compile(r"`[^`]*`")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;!?])\s+(?=[A-Z(`*\"])|\s\|\s|^\||\|$")
PROHIBITION_RE = re.compile(
    r"\b(never|not|no|nothing|off-limits|forbidden|without|excluded|quarantined?)\b", re.I
)
HISTORICAL_RE = re.compile(r"historical context", re.I)

ANALYSIS_RE = re.compile(
    r"(?<![\w/-])((?:docs/)?analysis/[\w./-]+\.md"
    r"|[a-z0-9-]+/[0-9]{2}-[\w-]+\.md"
    r"|[0-9]{2}-[\w-]+\.md"
    r"|[\w-]+-astra-(?:review|verification)\.md"
    r"|clean-room-redactions\.md)"
)
PAINTER_RE = re.compile(r"PAINTER(?:\\\\|\\|/)[^\s`)|,;\"']*")
A3D_RE = re.compile(r"A3D(?:\\\\|\\|/)[^\s`)|,;\"']*")
UZENGINE_ROOT_RE = re.compile(r"E:(?:\\\\|\\|/)UzmiGames(?:\\\\|\\|/)UzEngine[^\s`)|,;\"']*", re.I)
ASSETS3D_ROOT_RE = re.compile(r"E:(?:\\\\|\\|/)UzmiGames(?:\\\\|\\|/)Assets3D[^\s`)|,;\"']*", re.I)
UZENGINE_PATH_RE = re.compile(r"`(runtime(?:\\|/)[^`]*)`")
URL_RE = re.compile(r"https?://[^\s)>\]`|\"']+")
NAME = r"[A-Z][A-Za-z\u00C0-\u017F'\u2019-]+"
AUTHOR_YEAR_RE = re.compile(
    rf"\b({NAME}(?: et al\.|(?:, {NAME})*,? and {NAME})?),? ((?:19|20)[0-9]{{2}})\b"
)
NOT_AUTHORS = {"Copyright", "Owner", "Windows", "Studio", "Server", "Office"}
TITLE_RE = re.compile(r"(?<![*\w])\*(?![*\s])([A-Z][^*\n]*?)(?<![*\s])\*(?![*\w])")
NAMED_RE = re.compile(
    r"((?:\b[A-Za-z0-9]*[A-Z0-9][\w.+-]*\s+){1,4})(specifications?|SDK|appendix)\b"
)

PATH_KINDS = ("analysis", "path")


@dataclass(frozen=True)
class Citation:
    doc: str
    line: int
    kind: Kind
    text: str
    sentence: str

    @property
    def prohibited(self) -> bool:
        return PROHIBITION_RE.search(self.sentence) is not None

    @property
    def historical(self) -> bool:
        return HISTORICAL_RE.search(self.sentence) is not None


def normalize_path(raw: str) -> str:
    """Canonical lower-case form with `/` separators and repository aliases."""
    path = raw.strip().strip("`").replace("\\\\", "\\").replace("\\", "/")
    path = re.sub(r"/+", "/", path).rstrip("/.").lower()
    for prefix, alias in (("e:/uzmigames/assets3d", "a3d"), ("e:/uzmigames/uzengine", "uzengine")):
        if path == prefix or path.startswith(prefix + "/"):
            path = alias + path[len(prefix) :]
    if path == "runtime" or path.startswith("runtime/"):
        path = "uzengine/" + path
    return path


def glob_regex(pattern: str) -> re.Pattern[str]:
    """Regex for a normalised path pattern: `**`, `*`, `...`, `{a,b}` and `<name>` wildcards."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("/**", i) and i + 3 == len(pattern):
            out.append("(?:/.*)?")
            i += 3
        elif pattern.startswith("**", i) or pattern.startswith("...", i):
            out.append(".*")
            i += 2 if pattern.startswith("**", i) else 3
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "{":
            end = pattern.find("}", i)
            if end == -1:
                out.append(re.escape(pattern[i]))
                i += 1
            else:
                options = pattern[i + 1 : end].split(",")
                out.append("(?:" + "|".join(re.escape(o) for o in options) + ")")
                i = end + 1
        elif pattern[i] == "<":
            end = pattern.find(">", i)
            if end == -1:
                out.append(re.escape(pattern[i]))
                i += 1
            else:
                out.append("[^/]+")
                i = end + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))


def is_path_key(key: str) -> bool:
    if key.startswith(("http://", "https://")):
        return False
    return "/" in key or "\\" in key or key.lower() in {"a3d", "uzengine"}


def key_matches(citation: Citation, key: str) -> bool:
    """True when the citation names the source the key identifies."""
    if citation.kind in PATH_KINDS:
        if not is_path_key(key):
            return False
        cited = normalize_path(citation.text)
        wanted = normalize_path(key)
        return bool(glob_regex(wanted).fullmatch(cited) or glob_regex(cited).fullmatch(wanted))
    if citation.kind == "url":
        return key.startswith("http") and citation.text.startswith(key)
    if is_path_key(key) or key.startswith("http"):
        return False
    return " ".join(key.lower().split()) in " ".join(citation.text.lower().split())


def mask_code(line: str) -> str:
    return CODE_SPAN_RE.sub(lambda m: " " * len(m.group(0)), line)


def sentences(line: str) -> list[tuple[int, str]]:
    """(start offset, text) of each sentence or table cell in a line."""
    parts: list[tuple[int, str]] = []
    start = 0
    for match in SENTENCE_SPLIT_RE.finditer(line):
        parts.append((start, line[start : match.start()]))
        start = match.end()
    parts.append((start, line[start:]))
    return [(s, t) for s, t in parts if t.strip()]


def analysis_index(analysis_root: Path) -> dict[str, list[str]]:
    """Map from basename and `folder/basename` to analysis paths relative to the root."""
    names: dict[str, list[str]] = {}
    for file in sorted(analysis_root.rglob("*.md")):
        rel = file.relative_to(analysis_root).as_posix()
        names.setdefault(file.name, []).append(rel)
        if "/" in rel:
            names.setdefault(rel, []).append(rel)
    return names


def resolve_analysis(token: str, names: dict[str, list[str]]) -> list[str]:
    token = token.replace("\\", "/")
    if token.startswith("docs/"):
        token = token[len("docs/") :]
    if token.startswith("analysis/"):
        return [token[len("analysis/") :]]
    return names.get(token, [])


def extract_line(
    doc: str, number: int, line: str, names: dict[str, list[str]]
) -> Iterator[Citation]:
    masked = mask_code(line)
    for offset, sentence in sentences(line):
        raw = line[offset : offset + len(sentence)]
        plain = masked[offset : offset + len(sentence)]

        def cite(kind: Kind, text: str, sentence: str = sentence) -> Citation:
            return Citation(doc, number, kind, text, sentence)

        for match in ANALYSIS_RE.finditer(raw):
            for resolved in resolve_analysis(match.group(1), names):
                yield cite("analysis", "docs/analysis/" + resolved)
        for regex in (PAINTER_RE, A3D_RE, UZENGINE_ROOT_RE, ASSETS3D_ROOT_RE):
            for match in regex.finditer(raw):
                yield cite("path", match.group(0))
        for match in UZENGINE_PATH_RE.finditer(raw):
            yield cite("path", match.group(1))
        for match in URL_RE.finditer(raw):
            yield cite("url", match.group(0).rstrip(".,;:"))
        for match in AUTHOR_YEAR_RE.finditer(plain):
            if match.group(1).split()[0].rstrip(",") not in NOT_AUTHORS:
                yield cite("author-year", f"{match.group(1)} {match.group(2)}")
        for match in TITLE_RE.finditer(plain):
            yield cite("title", match.group(1).strip())
        for match in NAMED_RE.finditer(plain):
            yield cite("named", " ".join(match.group(0).split()))


def extract_citations(doc_path: Path, doc_name: str, names: dict[str, list[str]]) -> list[Citation]:
    citations: list[Citation] = []
    in_fence = False
    for number, line in enumerate(doc_path.read_text(encoding="utf-8").splitlines(), start=1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        citations.extend(extract_line(doc_name, number, line, names))
    return citations


def unique(citations: Iterable[Citation]) -> list[Citation]:
    seen: set[tuple[str, int, str, str]] = set()
    out: list[Citation] = []
    for c in citations:
        key = (c.doc, c.line, c.kind, c.text)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out
