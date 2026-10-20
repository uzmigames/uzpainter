"""Generate `capabilities.json`, the capability manifest (docs/architecture/10-python-api.md §3).

Inputs: `painter-api-inventory.json` (documented Painter symbols, approved source A-PYDOC),
`compositor-capabilities.json` (the compositor's support of those symbols, operation contexts
`compositor` and `compositor:<case>`, decision 081) and `uzpainter-additions.json` (UzPainter-only
modules and operations). Output: one entry per
qualified symbol and operation context, `{symbol, context, status, since, tier_evidence, notes,
evidence}`, sorted by symbol and context and written as indented JSON with sorted keys, so the
same inputs always give the same bytes.

Generation fails, naming the entry, when:
- a `supported` entry has no `tier_evidence`, names a golden that is not a Tier 0 public manifest
  of the current oracle envelope (`parity/envelopes/registry.json`, decision 037), or has no
  `since` version;
- a `desktop-only-omitted` entry has no `justification`;
- a `pending-evidence` entry (implemented, no Tier 0 evidence yet; decision 112) has no notes
  naming the task that owns its evidence (`phase<N>.<M>_<name>`);
- a Painter entry cites no python-doc anchor of the symbol (or its owner) in `evidence`, or an
  addition cites no architecture section that exists;
- a symbol or context names a brush stroke (out of scope, decision 019);
- a (symbol, context) pair repeats, a field is unknown or malformed, or a symbol is outside its
  namespace (`substance_painter*` for the inventory, `uzpainter` for the additions);
- a release gap of `10-python-api.md` §3 (`RELEASE_GAPS`) is missing or not `release-gap`;
- a compositor entry has a context outside `compositor` and `compositor:<case>`, has no notes, or
  is a `release-gap` whose notes name no owner task (`phase<N>.<M>_<name>`).

It also writes the requirement-to-typed-operation matrix (`operation_matrix`; 11-mcp-server.md
§2, task phase2.7_mcp-operation-matrix, decision 182) from `operation-matrix.json` and the build's
registered MCP tools, `mcp-tools.json`: one row per required operation (`REQUIRED_OPERATIONS`, the
INT-02 operations and the ARC-14 families), `{operation, requirements, tool, fixture, status,
gaps, notes}`. The status is derived: `capability gap` without a typed tool or while an operation
the call performs is a release gap or unlisted in the manifest, `needs Python` for `run_python`
(also a gap), `available` otherwise. Generation fails, naming the row, when a required operation
has no row, a row names an operation outside the list, a requirement that is not in docs/prd.md,
a tool that is not registered or an argument value its tool does not gate, an `available` row has
no conformance fixture (`tests/<file>.py::test_<name>`, defined there), or a gap row names no
owner task.

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
COMPOSITOR_PATH = TOOL_DIR / "compositor-capabilities.json"
TOOLS_PATH = TOOL_DIR / "mcp-tools.json"
MATRIX_PATH = TOOL_DIR / "operation-matrix.json"
PRD = Path("docs") / "prd.md"
REGISTRY = Path("parity") / "envelopes" / "registry.json"

SCHEMA_ID = "uzpainter/capabilities/1"
STATUSES = ("supported", "desktop-only-omitted", "release-gap", "pending-evidence")
PAINTER_ROOTS = ("substance_painter", "substance_painter_plugins")
NATIVE_ROOT = "uzpainter"

SYMBOL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
CONTEXT = re.compile(r"^[a-z0-9][a-z0-9_.:-]*$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
DOC_ANCHOR = re.compile(r"^python-doc/[A-Za-z0-9_/]+\.html(?:#([A-Za-z0-9_.-]+))?$")
ARCH_ANCHOR = re.compile(r"^(docs/[A-Za-z0-9_./-]+\.md)(?:#([a-z0-9_-]+))?$")
STROKE = re.compile(r"stroke", re.IGNORECASE)
COMPOSITOR_CONTEXT = re.compile(r"^compositor(?::[a-z0-9][a-z0-9_.-]*)?$")
OWNER_TASK = re.compile(r"\bphase[0-9]+\.[0-9]+_[a-z0-9-]+\b")

ENTRY_FIELDS = frozenset(
    {"symbol", "context", "status", "since", "tier_evidence", "notes", "justification", "evidence"}
)
REQUIRED_FIELDS = ("symbol", "context", "status", "evidence")
INVENTORY_FIELDS = frozenset({"description", "source_id", "edition", "compat_profile", "entries"})
ADDITIONS_FIELDS = frozenset({"description", "entries"})
COMPOSITOR_FIELDS = frozenset({"description", "entries"})
TOOLS_FIELDS = frozenset({"description", "tools"})
TOOL_FIELDS = frozenset({"name", "served_by", "opt_in", "operations", "values"})
MATRIX_FIELDS = frozenset({"description", "rows"})
ROW_FIELDS = frozenset(
    {"operation", "requirements", "tool", "arguments", "operations", "fixture", "notes"}
)
ROW_REQUIRED = ("operation", "requirements", "tool", "fixture")
PAINTER_ORIGINS = ("inventory", "compositor")

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
    # The Automatic bake cage
    ("substance_painter.baking.bake_async", "cage-mode:automatic"),
)


# The required operations of the requirement-to-typed-operation matrix (11-mcp-server.md §2, §7;
# decision 182), in matrix order, each with the requirement that makes it required: every INT-02
# operation, then the operations of the ARC-14 families the release conformance names (project
# lifecycle, texture sets, resources, the stack family with its later node, effect and source
# kinds and projections, recipes, native bake, mesh, every export file format, capture in each
# mode, the render state, diagnostics, jobs and lease). An operation leaves this list only together
# with those sections.
INT_02 = "INT-02"
ARC_14 = "ARC-14"
REQUIRED_OPERATIONS: tuple[tuple[str, str], ...] = (
    *(
        (operation, INT_02)
        for operation in (
            "status",
            "project.inspect",
            "project.create",
            "project.open",
            "project.close",
            "project.save",
            "project.save_as",
            "texture_set.list",
            "resource.import",
            "texture_set.mesh_maps",
            "stack.sync",
            "stack.smart_material",
            "stack.procedural",
            "layer.get",
            "layer.set",
            "resource.replace",
            "diagnostics.snapshot",
            "project.recipe",
            "export.preset",
            "export.config",
            "render.capture",
            "mesh.reload",
            "bake.start",
            "job.status",
            "diagnostics.isolate_layer",
        )
    ),
    *(
        (operation, ARC_14)
        for operation in (
            "project.revert",
            "project.workflow.uv_tile",
            "project.workflow.texture_set_per_uv_tile",
            "texture_set.resolution",
            "texture_set.rename",
            "texture_set.channels",
            "resource.list",
            "resource.search",
            "assets.search",
            "layer.insert_fill",
            "layer.insert_group",
            "layer.insert_paint",
            "layer.delete",
            "layer.instantiate",
            "layer.geometry_mask",
            "effect.insert_fill",
            "effect.insert_levels",
            "effect.insert_compare_mask",
            "effect.insert_color_selection",
            "effect.insert_generator",
            "effect.insert_filter",
            "effect.insert_anchor",
            "effect.insert_paint",
            "effect.set",
            "mask.set",
            "source.uniform_color",
            "source.bitmap",
            "source.reference",
            "source.material",
            "source.vector",
            "source.font",
            "projection.uv",
            "projection.triplanar",
            "projection.planar",
            "projection.spherical",
            "projection.cylindrical",
            "projection.warp",
            "projection.uv_set_to_uv_set",
            "anchor.list",
            "smart.mask_insert",
            "smart.export",
            "recipe.apply_smart",
            "batch",
            "bake.inspect",
            "bake.configure",
            "bake.set_mesh_inputs",
            "bake.capture_preset",
            "bake.apply_preset",
            "mesh.certificate",
            "export.presets_list",
            "export.format.png",
            "export.format.exr",
            "export.format.tga",
            "export.format.bmp",
            "export.format.jpeg",
            "export.format.dds",
            "export.format.tiff",
            "export.format.psd",
            "export.format.webp",
            "export.format.j2k",
            "capture.painter_iray",
            "capture.painter_viewport",
            "capture.base_color",
            "capture.channel",
            "capture.mask",
            "display.get",
            "display.set",
            "shader.get",
            "shader.set",
            "camera.get",
            "camera.set",
            "diagnostics.diff",
            "diagnostics.material_views",
            "diagnostics.region_stats",
            "job.result",
            "job.cancel",
            "job.list",
            "job.wait_idle",
            "lease.acquire",
            "lease.release",
            "lease.status",
        )
    ),
)
AVAILABLE, GAP, NEEDS_PYTHON = "available", "capability gap", "needs Python"
PYTHON_TOOL = "run_python"
# The manifest statuses of the operations a typed tool performs; the runtime gate refuses any
# other, and an unlisted operation, with `capability_gap` (registry.py).
REACHABLE = ("supported", "pending-evidence")
SERVED_BY = ("worker", "supervisor")
OPERATION_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
REQUIREMENT = re.compile(r"^[A-Z]{2,4}-[0-9]{2}$")
FIXTURE = re.compile(r"^(tests/[A-Za-z0-9_/]+\.py)::(test_[A-Za-z0-9_]+)$")


class GenerationError(Exception):
    """An input breaks a generation rule; the message names the entry."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise GenerationError(f"{path}: {error}") from error


def current_tier0_dir(repo_root: Path) -> Path:
    """The Tier 0 manifests of the current oracle envelope (decision 037): `<manifest_root>/tier0`
    of the registry entry that `current` names."""
    registry = load_json(repo_root / REGISTRY)
    try:
        (entry,) = [e for e in registry["envelopes"] if e["envelope_id"] == registry["current"]]
        return repo_root / str(entry["manifest_root"]) / "tier0"
    except (KeyError, TypeError, ValueError) as error:
        raise GenerationError(f"{repo_root / REGISTRY}: no current envelope ({error})") from error


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
        if origin in PAINTER_ORIGINS:
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
        if status == "pending-evidence" and (notes is None or not OWNER_TASK.search(notes)):
            raise fail("a pending-evidence entry names the task that owns its evidence in notes")

        if origin == "compositor":
            if not COMPOSITOR_CONTEXT.match(context):
                raise fail("compositor entries have the context compositor or compositor:<case>")
            if notes is None:
                raise fail("a compositor entry states its scope in notes")
            if status == "release-gap" and not OWNER_TASK.search(notes):
                raise fail("a compositor release gap names its owner task in notes")

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


def check_top_level(
    document: Any, path: Path, fields: frozenset[str], items: str = "entries"
) -> dict[str, Any]:
    if not isinstance(document, dict) or set(document) != fields:
        raise GenerationError(f"{path}: top-level fields must be {sorted(fields)}")
    if not isinstance(document[items], list):
        raise GenerationError(f"{path}: {items} is not a list")
    return document


def operation_list(value: Any) -> bool:
    """A list of capability-manifest operations `{symbol, context}`."""
    return isinstance(value, list) and all(
        isinstance(op, dict)
        and set(op) == {"symbol", "context"}
        and isinstance(op["symbol"], str)
        and SYMBOL.match(op["symbol"]) is not None
        and isinstance(op["context"], str)
        and CONTEXT.match(op["context"]) is not None
        for op in value
    )


def load_tools(path: Path) -> dict[str, dict[str, Any]]:
    """The build's registered MCP tools (`mcp-tools.json`) by name: who serves each, the option
    that registers it (`opt_in`, null when always registered), the operations it declares and the
    operations of each argument value it gates (`values`, by JSON pointer; the schema's
    `x-uzpainter-capability` maps)."""
    document = check_top_level(load_json(path), path, TOOLS_FIELDS, "tools")
    tools: dict[str, dict[str, Any]] = {}
    for raw in document["tools"]:
        name = raw.get("name") if isinstance(raw, dict) else None
        where = f"{path.name} tool {name!r}"
        if not isinstance(raw, dict) or set(raw) != TOOL_FIELDS:
            raise GenerationError(f"{where}: fields must be {sorted(TOOL_FIELDS)}")
        if not isinstance(name, str) or not re.match(r"^[a-z][a-z0-9_]*$", name):
            raise GenerationError(f"{where}: name is not a tool name")
        if name in tools:
            raise GenerationError(f"{where}: listed twice")
        if raw["served_by"] not in SERVED_BY:
            raise GenerationError(f"{where}: served_by is not one of {list(SERVED_BY)}")
        opt_in = raw["opt_in"]
        if opt_in is not None and (not isinstance(opt_in, str) or not opt_in.startswith("--")):
            raise GenerationError(f"{where}: opt_in is null or the option that registers it")
        values = raw["values"]
        if not operation_list(raw["operations"]) or not (
            isinstance(values, dict)
            and all(
                isinstance(pointer, str)
                and pointer.startswith("/")
                and isinstance(mapping, dict)
                and all(operation_list(ops) for ops in mapping.values())
                for pointer, mapping in values.items()
            )
        ):
            raise GenerationError(f"{where}: operations or values are malformed")
        tools[name] = raw
    return tools


def prd_requirements(repo_root: Path) -> frozenset[str]:
    """The requirement ids of docs/prd.md (its table rows `| <ID> | ...`)."""
    text = (repo_root / PRD).read_text(encoding="utf-8")
    return frozenset(re.findall(r"^\| ([A-Z]{2,4}-[0-9]{2}) \|", text, re.MULTILINE))


def fixture_defined(repo_root: Path, fixture: str) -> bool:
    """A pytest node id `tests/<file>.py::test_<name>` whose file defines that test."""
    match = FIXTURE.match(fixture)
    if match is None:
        return False
    path = repo_root / match.group(1)
    if not path.is_file():
        return False
    test = re.escape(match.group(2))
    return re.search(rf"^def {test}\(", path.read_text(encoding="utf-8"), re.MULTILINE) is not None


def matrix_row(
    raw: Any,
    tools: dict[str, dict[str, Any]],
    statuses: dict[tuple[str, str], str],
    requirements: frozenset[str],
    repo_root: Path,
) -> dict[str, Any]:
    """One matrix row with its derived status (decision 182)."""
    required = dict(REQUIRED_OPERATIONS)
    operation = raw.get("operation") if isinstance(raw, dict) else None
    name = f"operation matrix row {operation!r}"

    def fail(message: str) -> GenerationError:
        return GenerationError(f"{name}: {message}")

    if not isinstance(raw, dict):
        raise fail("is not an object")
    unknown = sorted(set(raw) - ROW_FIELDS)
    if unknown:
        raise fail(f"unknown fields {unknown}")
    missing = [f for f in ROW_REQUIRED if f not in raw]
    if missing:
        raise fail(f"missing fields {missing}")
    if not isinstance(operation, str) or operation not in required:
        raise fail("is not a required operation (REQUIRED_OPERATIONS)")
    cited = raw["requirements"]
    if not string_list(cited) or not cited:
        raise fail("requirements is not a non-empty list of requirement ids")
    unknown_ids = sorted(r for r in cited if not REQUIREMENT.match(r) or r not in requirements)
    if unknown_ids:
        raise fail(f"requirements {unknown_ids} are not requirements of docs/prd.md")
    if required[operation] not in cited:
        raise fail(f"does not cite {required[operation]}, the requirement that requires it")
    notes = raw.get("notes")
    if not optional_text(notes):
        raise fail("notes is a non-empty string when present")
    fixture = raw["fixture"]
    if fixture is not None and (
        not isinstance(fixture, str) or not fixture_defined(repo_root, fixture)
    ):
        raise fail(f"fixture {fixture!r} is not a test its file defines (tests/<file>.py::test_*)")

    tool = raw["tool"]
    arguments = raw.get("arguments", {})
    extra = raw.get("operations", [])
    if not isinstance(arguments, dict) or not all(isinstance(v, str) for v in arguments.values()):
        raise fail("arguments maps argument pointers to values")
    if not operation_list(extra):
        raise fail("operations is not a list of {symbol, context}")
    if tool is None:
        if arguments or extra:
            raise fail("a row without a tool names no arguments or operations")
        status, performed = GAP, []
    elif not isinstance(tool, str) or tool not in tools:
        raise fail(f"names the tool {tool!r}, which the build does not register (mcp-tools.json)")
    else:
        declared = tools[tool]
        performed = list(declared["operations"])
        for pointer, value in sorted(arguments.items()):
            mapping = declared["values"].get(pointer)
            ops = None if mapping is None else mapping.get(value, mapping.get("*"))
            if ops is None:
                raise fail(f"{tool} does not gate the argument value {pointer} = {value!r}")
            performed += ops
        performed += extra
        status = NEEDS_PYTHON if tool == PYTHON_TOOL else AVAILABLE
    gaps = []
    for op in performed:
        found = statuses.get((op["symbol"], op["context"]), "unlisted")
        if found not in REACHABLE:
            gaps.append({"symbol": op["symbol"], "context": op["context"], "status": found})
    if status == AVAILABLE and gaps:
        status = GAP
    if status == AVAILABLE and fixture is None:
        raise fail("an available row needs its Python-disabled conformance fixture id")
    if status != AVAILABLE and (notes is None or not OWNER_TASK.search(notes)):
        raise fail(f"a {status} row names the task that owns the operation in notes")
    return {
        "operation": operation,
        "requirements": list(cited),
        "tool": tool,
        "fixture": fixture,
        "status": status,
        "gaps": gaps,
        "notes": notes,
    }


def operation_matrix(
    matrix_path: Path,
    tools: dict[str, dict[str, Any]],
    entries: Iterable[dict[str, Any]],
    repo_root: Path,
) -> list[dict[str, Any]]:
    """The rows of `operation-matrix.json`, one per required operation, in `REQUIRED_OPERATIONS`
    order; raises `GenerationError` naming a missing, unknown, repeated or invalid row."""
    document = check_top_level(load_json(matrix_path), matrix_path, MATRIX_FIELDS, "rows")
    statuses = {(e["symbol"], e["context"]): e["status"] for e in entries}
    requirements = prd_requirements(repo_root)
    rows: dict[str, dict[str, Any]] = {}
    for raw in document["rows"]:
        row = matrix_row(raw, tools, statuses, requirements, repo_root)
        if row["operation"] in rows:
            raise GenerationError(f"operation matrix row {row['operation']!r} is listed twice")
        rows[row["operation"]] = row
    for operation, requirement in REQUIRED_OPERATIONS:
        if operation not in rows:
            raise GenerationError(
                f"required operation {operation!r} ({requirement}) has no operation matrix row"
            )
    return [rows[operation] for operation, _ in REQUIRED_OPERATIONS]


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
    tier0_dir: Path | None = None,
    repo_root: Path = REPO_ROOT,
    compositor_path: Path = COMPOSITOR_PATH,
    tools_path: Path = TOOLS_PATH,
    matrix_path: Path = MATRIX_PATH,
) -> dict[str, Any]:
    """The capability manifest of the inputs; raises `GenerationError` naming a bad entry or
    operation matrix row.

    `tier0_dir` defaults to the Tier 0 manifests of the current oracle envelope."""
    inventory = check_top_level(load_json(inventory_path), inventory_path, INVENTORY_FIELDS)
    additions = check_top_level(load_json(additions_path), additions_path, ADDITIONS_FIELDS)
    compositor = check_top_level(load_json(compositor_path), compositor_path, COMPOSITOR_FIELDS)
    if inventory["source_id"] != "A-PYDOC":
        raise GenerationError(f"{inventory_path}: source_id must be A-PYDOC (approved source)")
    tier0 = tier0_dir if tier0_dir is not None else current_tier0_dir(repo_root)
    builder = Builder(tier0_golden_ids(tier0), repo_root)
    entries = [builder.entry(raw, "inventory") for raw in inventory["entries"]]
    entries += [builder.entry(raw, "compositor") for raw in compositor["entries"]]
    entries += [builder.entry(raw, "additions") for raw in additions["entries"]]
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry["symbol"], entry["context"])
        if key in seen:
            raise GenerationError(f"entry {key[0]!r} (context {key[1]!r}) is listed twice")
        seen.add(key)
    check_release_gaps(entries)
    entries.sort(key=lambda e: (e["symbol"], e["context"]))
    matrix = operation_matrix(matrix_path, load_tools(tools_path), entries, repo_root)
    return {
        "schema": SCHEMA_ID,
        "compat_profile": inventory["compat_profile"],
        "documentation": inventory["edition"],
        "entries": entries,
        "operation_matrix": matrix,
    }


def render(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--output", type=Path, required=True, help="capabilities.json to write")
    parser.add_argument("--inventory", type=Path, default=INVENTORY_PATH)
    parser.add_argument("--additions", type=Path, default=ADDITIONS_PATH)
    parser.add_argument("--compositor", type=Path, default=COMPOSITOR_PATH)
    parser.add_argument(
        "--tier0",
        type=Path,
        default=None,
        help="Tier 0 public manifests (default: the current oracle envelope's)",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--tools", type=Path, default=TOOLS_PATH, help="mcp-tools.json")
    parser.add_argument("--matrix", type=Path, default=MATRIX_PATH, help="operation-matrix.json")
    args = parser.parse_args(argv)
    try:
        manifest = generate(
            args.inventory,
            args.additions,
            args.tier0,
            args.repo_root,
            args.compositor,
            args.tools,
            args.matrix,
        )
    except GenerationError as error:
        print(f"capabilities: {error}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(render(manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
