"""Generate `capabilities.json`, the capability manifest (docs/architecture/10-python-api.md §3).

Inputs: `painter-api-inventory.json` (documented Painter symbols, approved source A-PYDOC) and
`uzpainter-additions.json` (UzPainter-only modules and operations). Output: one entry per
qualified symbol and operation context, `{symbol, context, status, since, tier_evidence, notes,
evidence}`, sorted by symbol and context and written as indented JSON with sorted keys, so the
same inputs always give the same bytes.

Generation fails, naming the entry, when:
- a `supported` entry has no `tier_evidence`, names a golden that is not a Tier 0 public manifest
  under `parity/manifests/tier0/`, or has no `since` version;
- a `desktop-only-omitted` entry has no `justification`;
- a Painter entry cites no python-doc anchor of the symbol (or its owner) in `evidence`, or an
  addition cites no architecture section that exists;
- a symbol or context names a brush stroke (out of scope, decision 019);
- a (symbol, context) pair repeats, a field is unknown or malformed, or a symbol is outside its
  namespace (`substance_painter*` for the inventory, `uzpainter` for the additions);
- a release gap of `10-python-api.md` §3 (`RELEASE_GAPS`) is missing or not `release-gap`.

Standard library only: `zig build capabilities` runs this file as a script (`python -I`).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOL_DIR.parents[1]
INVENTORY_PATH = TOOL_DIR / "painter-api-inventory.json"
ADDITIONS_PATH = TOOL_DIR / "uzpainter-additions.json"
TIER0_DIR = REPO_ROOT / "parity" / "manifests" / "tier0"

SCHEMA_ID = "uzpainter/capabilities/1"
STATUSES = ("supported", "desktop-only-omitted", "release-gap")
PAINTER_ROOTS = ("substance_painter", "substance_painter_plugins")
NATIVE_ROOT = "uzpainter"

SYMBOL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
CONTEXT = re.compile(r"^[a-z0-9][a-z0-9_.:-]*$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
DOC_ANCHOR = re.compile(r"^python-doc/[A-Za-z0-9_/]+\.html(?:#([A-Za-z0-9_.-]+))?$")
ARCH_ANCHOR = re.compile(r"^(docs/[A-Za-z0-9_./-]+\.md)(?:#([a-z0-9_-]+))?$")
STROKE = re.compile(r"stroke", re.IGNORECASE)

ENTRY_FIELDS = frozenset(
    {"symbol", "context", "status", "since", "tier_evidence", "notes", "justification", "evidence"}
)
REQUIRED_FIELDS = ("symbol", "context", "status", "evidence")
INVENTORY_FIELDS = frozenset({"description", "source_id", "edition", "compat_profile", "entries"})
ADDITIONS_FIELDS = frozenset({"description", "entries"})

# The release gaps of docs/architecture/10-python-api.md §3, as (symbol, context). An entry
# leaves this list only together with that section, when the behaviour is supported.
RELEASE_GAPS: tuple[tuple[str, str], ...] = (
    # Paint layers and paint effects receiving bitmaps and projections
    ("substance_painter.layerstack.PaintLayerNode", "bitmap-or-projection-content"),
    ("substance_painter.layerstack.PaintEffectNode", "bitmap-or-projection-content"),
    # Warp and UV-set-to-UV-set projections
    ("substance_painter.layerstack.ProjectionMode.Warp", "any"),
    ("substance_painter.layerstack.WarpProjectionParams", "any"),
    ("substance_painter.layerstack.ProjectionMode.UVSetToUVSet", "any"),
    ("substance_painter.layerstack.UVSetToUVSetProjectionParams", "any"),
    # UV-tile workflow
    ("substance_painter.project.ProjectWorkflow.UVTile", "any"),
    ("substance_painter.project.ProjectWorkflow.TextureSetPerUVTile", "any"),
    # Auto-unwrap
    ("substance_painter.project.AutoUnwrapSettings", "any"),
    # Vector and font sources
    ("substance_painter.source.SourceVectorial", "any"),
    ("substance_painter.source.SourceFont", "any"),
    # Material layering
    ("substance_painter.textureset.TextureSet", "material-layering"),
    # USD export
    ("substance_painter.export.export_mesh", "file-format:usd"),
    # TIFF, PSD, WebP and JPEG 2000 export
    ("substance_painter.export.export_project_textures", "file-format:tiff"),
    ("substance_painter.export.export_project_textures", "file-format:psd"),
    ("substance_painter.export.export_project_textures", "file-format:webp"),
    ("substance_painter.export.export_project_textures", "file-format:j2k"),
    # Arbitrary .sbsar evaluation
    ("substance_painter.source.SourceSubstance", "arbitrary-sbsar"),
)


class GenerationError(Exception):
    """An input breaks a generation rule; the message names the entry."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise GenerationError(f"{path}: {error}") from error


def tier0_golden_ids(tier0_dir: Path) -> frozenset[str]:
    """Golden ids of the Tier 0 public manifests (`parity/CONTRACT.md` §6)."""
    ids: set[str] = set()
    for path in sorted(tier0_dir.rglob("*.json")):
        record = load_json(path)
        if (
            isinstance(record, dict)
            and record.get("record_class") == "public_manifest"
            and record.get("tier") == "0"
            and isinstance(record.get("golden_id"), str)
        ):
            ids.add(record["golden_id"])
    return frozenset(ids)


def heading_slugs(markdown: Path) -> frozenset[str]:
    """Anchors of the Markdown headings of a file, as a Markdown renderer derives them."""
    slugs: set[str] = set()
    for line in markdown.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            title = line.lstrip("#").strip().lower()
            slugs.add(re.sub(r"[^\w\- ]", "", title).replace(" ", "-"))
    return frozenset(slugs)


def anchors_symbol(symbol: str, fragment: str | None) -> bool:
    """A python-doc anchor documents `symbol`: a page anchor, or the symbol or its owner."""
    if fragment is None:
        return True
    target = fragment.removeprefix("module-")
    return symbol == target or symbol.startswith(target + ".")


def string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def optional_text(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() != "")


class Builder:
    def __init__(self, golden_ids: frozenset[str], repo_root: Path) -> None:
        self.golden_ids = golden_ids
        self.repo_root = repo_root
        self.slugs: dict[Path, frozenset[str]] = {}

    def architecture_anchor_exists(self, anchor: str) -> bool:
        match = ARCH_ANCHOR.match(anchor)
        if match is None:
            return False
        path = self.repo_root / match.group(1)
        if not path.is_file():
            return False
        if match.group(2) is None:
            return True
        if path not in self.slugs:
            self.slugs[path] = heading_slugs(path)
        return match.group(2) in self.slugs[path]

    def entry(self, raw: Any, origin: str) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise GenerationError(f"{origin}: entry {raw!r} is not an object")
        name = f"{origin} entry {raw.get('symbol')!r} (context {raw.get('context')!r})"

        def fail(message: str) -> GenerationError:
            return GenerationError(f"{name}: {message}")

        unknown = sorted(set(raw) - ENTRY_FIELDS)
        if unknown:
            raise fail(f"unknown fields {unknown}")
        missing = [f for f in REQUIRED_FIELDS if f not in raw]
        if missing:
            raise fail(f"missing fields {missing}")
        symbol, context, status = raw["symbol"], raw["context"], raw["status"]
        if not isinstance(symbol, str) or not SYMBOL.match(symbol):
            raise fail("symbol is not a qualified Python name")
        if not isinstance(context, str) or not CONTEXT.match(context):
            raise fail("context is not a lower-case operation context name")
        if STROKE.search(symbol) or STROKE.search(context):
            raise fail("brush strokes are out of scope (decision 019): no stroke symbol exists")
        if status not in STATUSES:
            raise fail(f"status {status!r} is not one of {list(STATUSES)}")

        root = symbol.split(".", 1)[0]
        evidence = raw["evidence"]
        if not string_list(evidence) or not evidence:
            raise fail("evidence is not a non-empty list of strings")
        if origin == "inventory":
            if root not in PAINTER_ROOTS:
                raise fail(f"the inventory lists documented Painter symbols only ({PAINTER_ROOTS})")
            anchors = [DOC_ANCHOR.match(e) for e in evidence]
            if not any(m is not None and anchors_symbol(symbol, m.group(1)) for m in anchors):
                raise fail("evidence cites no public API documentation anchor (python-doc/...)")
        else:
            if root != NATIVE_ROOT:
                raise fail(f"additions are UzPainter-only symbols of `{NATIVE_ROOT}`")
            if not all(self.architecture_anchor_exists(e) for e in evidence):
                raise fail("evidence must cite existing sections (docs/<file>.md#<heading>)")

        since = raw.get("since")
        tier_evidence = raw.get("tier_evidence", [])
        notes = raw.get("notes")
        justification = raw.get("justification")
        if since is not None and (not isinstance(since, str) or not SEMVER.match(since)):
            raise fail("since is not a semantic version")
        if not string_list(tier_evidence):
            raise fail("tier_evidence is not a list of Tier 0 golden ids")
        unknown_goldens = sorted(set(tier_evidence) - self.golden_ids)
        if unknown_goldens:
            raise fail(f"tier_evidence names no Tier 0 public manifest: {unknown_goldens}")
        if not optional_text(notes) or not optional_text(justification):
            raise fail("notes and justification are non-empty strings when present")

        if status == "supported":
            if not tier_evidence:
                raise fail("a supported entry requires Tier 0 evidence (tier_evidence)")
            if since is None:
                raise fail("a supported entry requires the version it is supported since")
        elif since is not None:
            raise fail(f"since is set only on supported entries, not {status}")
        if status == "desktop-only-omitted":
            if justification is None:
                raise fail("a desktop-only-omitted entry requires its justification")
        elif justification is not None:
            raise fail(f"justification belongs to desktop-only-omitted entries, not {status}")

        text = " ".join(t for t in (justification, notes) if t is not None)
        return {
            "symbol": symbol,
            "context": context,
            "status": status,
            "since": since,
            "tier_evidence": list(tier_evidence),
            "notes": text or None,
            "evidence": list(evidence),
        }


def check_top_level(document: Any, path: Path, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(document, dict) or set(document) != fields:
        raise GenerationError(f"{path}: top-level fields must be {sorted(fields)}")
    if not isinstance(document["entries"], list):
        raise GenerationError(f"{path}: entries is not a list")
    return document


def check_release_gaps(entries: Iterable[dict[str, Any]]) -> None:
    status = {(e["symbol"], e["context"]): e["status"] for e in entries}
    for symbol, context in RELEASE_GAPS:
        if status.get((symbol, context)) != "release-gap":
            raise GenerationError(
                f"release gap {symbol!r} (context {context!r}) of 10-python-api.md §3 must be "
                f"listed with status release-gap, found {status.get((symbol, context))!r}"
            )


def generate(
    inventory_path: Path = INVENTORY_PATH,
    additions_path: Path = ADDITIONS_PATH,
    tier0_dir: Path = TIER0_DIR,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """The capability manifest of the inputs; raises `GenerationError` naming a bad entry."""
    inventory = check_top_level(load_json(inventory_path), inventory_path, INVENTORY_FIELDS)
    additions = check_top_level(load_json(additions_path), additions_path, ADDITIONS_FIELDS)
    if inventory["source_id"] != "A-PYDOC":
        raise GenerationError(f"{inventory_path}: source_id must be A-PYDOC (approved source)")
    builder = Builder(tier0_golden_ids(tier0_dir), repo_root)
    entries = [builder.entry(raw, "inventory") for raw in inventory["entries"]]
    entries += [builder.entry(raw, "additions") for raw in additions["entries"]]
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry["symbol"], entry["context"])
        if key in seen:
            raise GenerationError(f"entry {key[0]!r} (context {key[1]!r}) is listed twice")
        seen.add(key)
    check_release_gaps(entries)
    entries.sort(key=lambda e: (e["symbol"], e["context"]))
    return {
        "schema": SCHEMA_ID,
        "compat_profile": inventory["compat_profile"],
        "documentation": inventory["edition"],
        "entries": entries,
    }


def render(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--output", type=Path, required=True, help="capabilities.json to write")
    parser.add_argument("--inventory", type=Path, default=INVENTORY_PATH)
    parser.add_argument("--additions", type=Path, default=ADDITIONS_PATH)
    parser.add_argument("--tier0", type=Path, default=TIER0_DIR, help="Tier 0 public manifests")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    try:
        manifest = generate(args.inventory, args.additions, args.tier0, args.repo_root)
    except GenerationError as error:
        print(f"capabilities: {error}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(render(manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
