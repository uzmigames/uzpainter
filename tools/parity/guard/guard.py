"""Repository guard: no recorded Painter output enters the repository (`parity/GUARD.md`).

Checks the content of files, never only their names or signatures:

- `store-hash`: a file whose SHA-256 (also after CRLF/LF conversion of text) is in the private
  store index is a recorded output. Needs the index (the owner's store or `--index`); hosted CI
  has none (decision 028) and relies on the two rules below.
- `private-record`: a JSON file anywhere that holds a private oracle record (`record_class`
  `private_oracle_record` or a `golden-private` schema id, at any depth). Only the synthetic
  samples under `parity/schema/samples/private/` are exempt, and they have their own rule.
- `public-schema`: every JSON data file under `parity/` (by `.json` name or by content) must
  validate against the public schema its path assigns (`PATH_RULES`); a JSON file under
  `parity/` that no rule covers is rejected. The envelope registry and every envelope's
  manifests (`parity/envelopes/`) and the oracle-envelope results
  (`parity/reports/<phase>/oracle-envelope*.json`) have rules of their own. The store's size
  census (`parity/reports/<phase>/store-census.json`) is checked by a rule of its own: numbers, with
  text only in its identifier fields.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from tools.parity.schemas import Schema, record_problems, register_problems, validation_errors
from tools.parity.store.store import INDEX_SCHEMA

PRIVATE_SCHEMA_PREFIX = "uzpainter/parity/golden-private/"
PRIVATE_RECORD_CLASS = "private_oracle_record"
REGISTER_SCHEMA_ID = "uzpainter/parity/exceptions/1"
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SYNTHETIC_NOTE_PREFIX = "Synthetic sample"
SYNTHETIC_GOLDEN_PREFIX = "samples/"
SYNTHETIC_BUILD_ID = "synthetic-sample-build"
SYNTHETIC_DIR = "parity/schema/samples/private/"
MANIFEST_DIR = "parity/manifests/"
# A promoted envelope's manifests (decision 037): goldens first recorded under a later Painter
# build exist only there, and their authored inputs are declared there (decision 087).
ENVELOPE_MANIFEST = re.compile(r"^parity/envelopes/[^/]+/manifests/")
FIXTURE_DIR = "parity/fixtures/"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GITLINK_MODE = "160000"


class GuardError(Exception):
    """The guard could not run (git failure, unreadable index)."""


@dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: [{self.rule}] {self.message}"


@dataclass(frozen=True)
class Snapshot:
    """One state of a repository: every file in it, the files to check, and how to read one.

    `paths` is the whole state (public manifests are looked up in it); `checked` is the subset
    the guard judges.
    """

    paths: tuple[str, ...]
    checked: tuple[str, ...]
    read: Callable[[str], bytes]


# --- snapshots -------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    except OSError as error:
        raise GuardError(f"git is not available ({error})") from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise GuardError(f"git {' '.join(args)} failed in {repo}: {detail}")
    return result.stdout


def repository_root(start: Path) -> Path:
    """The git top level of `start`."""
    return Path(_git(start, "rev-parse", "--show-toplevel").decode("utf-8").strip())


def _entries(output: bytes) -> list[str]:
    return [entry.decode("utf-8") for entry in output.split(b"\0") if entry]


def _under(path: str, prefixes: Sequence[str]) -> bool:
    return any(
        p in ("", ".") or path == p or path.startswith(p.rstrip("/") + "/") for p in prefixes
    )


def worktree_snapshot(repo: Path, prefixes: Sequence[str] = ()) -> Snapshot:
    """Tracked and untracked, not ignored, files of the working tree (a CI checkout, or a
    local tree before staging); `prefixes` (repository-relative) narrows the checked files."""
    listed = _entries(_git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard"))
    paths = tuple(sorted({p for p in listed if (repo / p).is_file()}))
    checked = tuple(p for p in paths if _under(p, prefixes)) if prefixes else paths
    return Snapshot(paths, checked, lambda path: (repo / path).read_bytes())


def staged_snapshot(repo: Path) -> Snapshot:
    """The index (what a commit would record): checks the added, copied, modified, renamed or
    retyped files, read from the index rather than the working tree."""
    blobs: dict[str, str] = {}
    for entry in _entries(_git(repo, "ls-files", "-s", "-z")):
        meta, path = entry.split("\t", 1)
        mode, oid, _stage = meta.split()
        if mode != _GITLINK_MODE:
            blobs[path] = oid
    changed = _entries(_git(repo, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT"))
    checked = tuple(p for p in changed if p in blobs)
    return Snapshot(
        tuple(sorted(blobs)), checked, lambda path: _git(repo, "cat-file", "blob", blobs[path])
    )


# --- store index -----------------------------------------------------------------------------


def load_index(path: Path) -> frozenset[str]:
    """The SHA-256 list of a store `index.json` (`uzpainter/parity/store-index/1`)."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise GuardError(f"cannot read the store index {path} ({error})") from error
    hashes = document.get("sha256") if isinstance(document, dict) else None
    if (
        not isinstance(document, dict)
        or document.get("schema") != INDEX_SCHEMA
        or not isinstance(hashes, list)
        or not all(isinstance(h, str) and _SHA256.match(h) for h in hashes)
    ):
        raise GuardError(f"{path} is not a store index ({INDEX_SCHEMA})")
    return frozenset(hashes)


def content_hashes(data: bytes) -> set[str]:
    """SHA-256 of the bytes and, for text (no NUL byte), of their LF and CRLF forms, so a copy
    whose line endings git or an editor converted still matches the index."""
    variants = {data}
    if b"\0" not in data:
        lf = data.replace(b"\r\n", b"\n")
        variants |= {lf, lf.replace(b"\n", b"\r\n")}
    return {hashlib.sha256(v).hexdigest() for v in variants}


# --- JSON content ----------------------------------------------------------------------------


class _NotJson:
    pass


NOT_JSON = _NotJson()


def parse_json(path: str, data: bytes) -> Any:
    """The JSON document a file holds, or `NOT_JSON`.

    A `.json` name must hold UTF-8 JSON (`ValueError` otherwise). Any other file counts as JSON
    when its content starts with `{` or `[` and parses: a readback renamed to `.txt` is still
    judged by its content.
    """
    named_json = path.lower().endswith(".json")
    if not named_json and data.lstrip(b" \t\r\n\xef\xbb\xbf")[:1] not in (b"{", b"["):
        return NOT_JSON
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as error:
        if named_json:
            raise ValueError(f"not valid UTF-8 JSON ({error})") from error
        return NOT_JSON


def _private_markers(node: Any, where: str = "") -> Iterator[str]:
    if isinstance(node, dict):
        if node.get("record_class") == PRIVATE_RECORD_CLASS:
            yield f"{where or '<root>'}: record_class {PRIVATE_RECORD_CLASS}"
        schema = node.get("schema")
        if isinstance(schema, str) and schema.startswith(PRIVATE_SCHEMA_PREFIX):
            yield f"{where or '<root>'}: schema {schema}"
        for key, value in node.items():
            yield from _private_markers(value, f"{where}/{key}" if where else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _private_markers(value, f"{where}/{index}" if where else str(index))


# --- public-schema rules by path -------------------------------------------------------------


@dataclass(frozen=True)
class _Context:
    repo: Path
    declared_inputs: Callable[[], frozenset[tuple[str, str]]]


def _schema_file(path: str, document: Any, data: bytes, ctx: _Context) -> list[str]:
    name = path.removeprefix("parity/schema/")
    if name not in {s.value for s in Schema}:
        return [f"{name} is not one of the parity schemas {sorted(s.value for s in Schema)}"]
    if not isinstance(document, dict) or document.get("$schema") != JSON_SCHEMA_DIALECT:
        return [f"not a JSON Schema declaring {JSON_SCHEMA_DIALECT}"]
    try:
        Draft202012Validator.check_schema(document)
    except SchemaError as error:
        return [f"not a valid JSON Schema ({error.message})"]
    return []


def _public_manifest(path: str, document: Any, data: bytes, ctx: _Context) -> list[str]:
    return validation_errors(document, Schema.GOLDEN_PUBLIC)


def _synthetic_sample(path: str, document: Any, data: bytes, ctx: _Context) -> list[str]:
    """A synthetic private-shaped sample (CONTRACT.md §7): a valid private record that carries
    every synthetic mark: the note, a `samples/` golden id and the synthetic build id."""
    problems = record_problems(document) if isinstance(document, dict) else ["not an object"]
    if problems:
        return problems
    note = document.get("note")
    if not isinstance(note, str) or not note.startswith(SYNTHETIC_NOTE_PREFIX):
        problems.append(f"note does not start with {SYNTHETIC_NOTE_PREFIX!r}")
    if not document["golden_id"].startswith(SYNTHETIC_GOLDEN_PREFIX):
        problems.append(f"golden_id is not under {SYNTHETIC_GOLDEN_PREFIX!r}")
    if document["key"]["painter_build"]["build_id"] != SYNTHETIC_BUILD_ID:
        problems.append(f"painter build_id is not {SYNTHETIC_BUILD_ID!r}")
    return [f"not a synthetic sample: {p}" for p in problems]


def _exception_sample(path: str, document: Any, data: bytes, ctx: _Context) -> list[str]:
    return validation_errors(
        {"schema": REGISTER_SCHEMA_ID, "entries": [document]}, Schema.EXCEPTIONS
    )


def _report_sample(path: str, document: Any, data: bytes, ctx: _Context) -> list[str]:
    return validation_errors(document, Schema.COMPARISON_REPORT)


def _semantics(path: str, document: Any, data: bytes, ctx: _Context) -> list[str]:
    return validation_errors(document, Schema.SEMANTICS)


def _register(path: str, document: Any, data: bytes, ctx: _Context) -> list[str]:
    if not isinstance(document, Mapping):
        return validation_errors(document, Schema.EXCEPTIONS)
    return register_problems(document, ctx.repo / ".rulebook" / "decisions")


def _fixture(path: str, document: Any, data: bytes, ctx: _Context) -> list[str]:
    """A JSON fixture (fixture description, authored recipe) is public only as an authored
    input that a valid manifest under `parity/manifests/` or an envelope's manifests names by
    this path and SHA-256."""
    if (path, hashlib.sha256(data).hexdigest()) in ctx.declared_inputs():
        return []
    return [
        "no valid public manifest under parity/manifests/ or an envelope's manifests declares "
        "this file (path and SHA-256) as an authored input"
    ]


STORE_CENSUS_SCHEMA = "uzpainter/store-census/1"
# The only places a store census report may hold text: identifiers, never paths or content.
_CENSUS_TEXT_KEYS = frozenset({"schema", "task", "date", "id", "format", "raster_plane_format"})
_CENSUS_LIST_TEXT_KEYS = frozenset({"not_measured"})
_CENSUS_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$")


def _census_text(node: Any, key: str, where: str) -> Iterator[str]:
    if isinstance(node, dict):
        for name, value in node.items():
            yield from _census_text(value, name, f"{where}/{name}" if where else name)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            item_key = key if key in _CENSUS_LIST_TEXT_KEYS else f"{key}[]"
            yield from _census_text(value, item_key, f"{where}/{index}")
    elif isinstance(node, str):
        if key not in _CENSUS_TEXT_KEYS | _CENSUS_LIST_TEXT_KEYS:
            yield f"{where}: text outside the identifier fields (numbers only)"
        elif not _CENSUS_TEXT.match(node) or (key != "schema" and "/" in node):
            yield f"{where}: {node!r} is not an identifier"


def _store_census(path: str, document: Any, data: bytes, ctx: _Context) -> list[str]:
    """The store's size census (`src/store/census.h`): numbers and identifiers only."""
    if not isinstance(document, dict) or document.get("schema") != STORE_CENSUS_SCHEMA:
        return [f"schema is not {STORE_CENSUS_SCHEMA}"]
    projects = document.get("projects")
    if not isinstance(projects, list) or not projects:
        return ["projects is not a non-empty list"]
    problems = [
        f"projects/{i}: not an object with an id"
        for i, p in enumerate(projects)
        if not isinstance(p, dict) or not isinstance(p.get("id"), str)
    ]
    return problems + list(_census_text(document, "", ""))


def _envelope_registry(path: str, document: Any, data: bytes, ctx: _Context) -> list[str]:
    from tools.parity.envelope.registry import registry_problems

    return registry_problems(document)


def _oracle_envelope_result(path: str, document: Any, data: bytes, ctx: _Context) -> list[str]:
    from tools.parity.envelope.report import result_problems

    return result_problems(document)


_Rule = Callable[[str, Any, bytes, _Context], list[str]]

# First match wins: (path pattern, schema it assigns, check).
PATH_RULES: tuple[tuple[re.Pattern[str], str, _Rule], ...] = (
    (re.compile(r"^parity/schema/[^/]+$"), "JSON Schema draft 2020-12", _schema_file),
    (re.compile(r"^parity/schema/samples/public/[^/]+$"), "golden-public.json", _public_manifest),
    (
        re.compile(r"^parity/schema/samples/private/[^/]+$"),
        "golden-private.json (synthetic samples only)",
        _synthetic_sample,
    ),
    (
        re.compile(r"^parity/schema/samples/exceptions/[^/]+$"),
        "exceptions.json entry",
        _exception_sample,
    ),
    (
        re.compile(r"^parity/schema/samples/reports/[^/]+$"),
        "comparison-report.json",
        _report_sample,
    ),
    (re.compile(r"^parity/exceptions\.json$"), "exceptions.json", _register),
    (re.compile(r"^parity/manifests/.+$"), "golden-public.json", _public_manifest),
    (
        re.compile(r"^parity/envelopes/registry\.json$"),
        "envelope-registry.json",
        _envelope_registry,
    ),
    (
        re.compile(r"^parity/envelopes/[^/]+/manifests/.+$"),
        "golden-public.json (an envelope's manifests)",
        _public_manifest,
    ),
    (
        re.compile(r"^parity/reports/[^/]+/oracle-envelope[^/]*\.json$"),
        "oracle-envelope.json (study, drift, prepared register entries)",
        _oracle_envelope_result,
    ),
    (re.compile(r"^parity/semantics/[^/]+$"), "semantics.json", _semantics),
    (re.compile(r"^parity/fixtures/.+$"), "authored input of a manifest", _fixture),
    (
        re.compile(r"^parity/reports/[^/]+/store-census\.json$"),
        "store census report (numbers only)",
        _store_census,
    ),
)


def _declared_inputs(snapshot: Snapshot) -> frozenset[tuple[str, str]]:
    declared: set[tuple[str, str]] = set()
    for path in snapshot.paths:
        if not path.startswith(MANIFEST_DIR) and not ENVELOPE_MANIFEST.match(path):
            continue
        try:
            document = parse_json(path, snapshot.read(path))
        except ValueError:
            continue
        if document is NOT_JSON or validation_errors(document, Schema.GOLDEN_PUBLIC):
            continue
        declared.update(
            (item["path"], item["sha256"]) for item in document["inputs"] if "path" in item
        )
    return frozenset(declared)


# --- the guard -------------------------------------------------------------------------------


def check_file(
    path: str, data: bytes, index: frozenset[str] | None, ctx: _Context
) -> list[Finding]:
    findings: list[Finding] = []
    if index is not None and (matched := content_hashes(data) & index):
        findings.append(
            Finding(path, "store-hash", f"SHA-256 {min(matched)} is in the private store index")
        )
    try:
        document = parse_json(path, data)
    except ValueError as error:
        if path.startswith("parity/"):
            findings.append(Finding(path, "public-schema", str(error)))
        return findings
    if document is NOT_JSON:
        return findings
    if not path.startswith(SYNTHETIC_DIR):
        findings.extend(
            Finding(path, "private-record", f"holds a private oracle record ({marker})")
            for marker in _private_markers(document)
        )
    if not path.startswith("parity/"):
        return findings
    for pattern, schema, rule in PATH_RULES:
        if pattern.match(path):
            findings.extend(
                Finding(path, "public-schema", f"fails {schema}: {problem}")
                for problem in rule(path, document, data, ctx)
            )
            return findings
    findings.append(
        Finding(path, "public-schema", "JSON data under parity/ that no public schema covers")
    )
    return findings


def run_guard(repo: Path, snapshot: Snapshot, index: frozenset[str] | None) -> list[Finding]:
    """Every finding over the checked files of `snapshot`; `index` None skips `store-hash`."""
    ctx = _Context(repo, functools.cache(lambda: _declared_inputs(snapshot)))
    findings: list[Finding] = []
    for path in snapshot.checked:
        findings.extend(check_file(path, snapshot.read(path), index, ctx))
    return findings
