# Capability manifest (`tools/capabilities/`)

Task `phase1.2_docmodel-capability-manifest` (P1-DOCMODEL). Implements the capability manifest of
`docs/architecture/10-python-api.md` §3 (decision 004, amended by decision 019: brush strokes are
out of scope). Every documented Painter symbol and every UzPainter-only operation carries one of
three statuses, so nothing in UzPainter is silently a no-op.

## Files

| File | Content |
|---|---|
| `painter-api-inventory.json` | Documented Painter symbols (approved source A-PYDOC): every Python object of the Painter 12.1.0 python-doc inventory plus the enum members and constructor parameters recorded in `tools/parity/recorder/documented_symbols.json`. One entry per line. |
| `compositor-capabilities.json` | The compositor's support of documented Painter symbols (`phase1.14_compositor-core` item 2.8, decision 081): every Phase 1 node kind, source, projection, sampling mode and blend mode in the operation context `compositor` or a narrower `compositor:<case>` (`compositor:minification`, `compositor:mask-stack`, `compositor:height`, ...). |
| `uzpainter-additions.json` | UzPainter-only modules, operations and errors of `uzpainter` (`10-…` §1, §5, §7; capture modes of `07-…` §5). |
| `capabilities.schema.json` | JSON Schema (draft 2020-12) of `capabilities.json`. |
| `generate_capabilities.py` | The generator (standard library only). |

`zig build capabilities` writes `zig-out/bin/capabilities.json`; `zig build painter` ships it
beside `UzPainter.exe`. The build runs Python from PATH, or `-Dpython=<exe>`. By hand:
`python -m tools.capabilities.generate_capabilities --output capabilities.json`.

## Entries

Input entries have `symbol`, `context`, `status` and `evidence`, and optionally `since`,
`tier_evidence`, `notes` and `justification`. Output entries always have `symbol`, `context`,
`status`, `since`, `tier_evidence`, `notes` and `evidence`; a justification becomes the start of
`notes`. Entries are sorted by symbol and context and written with sorted keys and a two-space
indent, so the same inputs always give the same bytes.

- `context` is `any` or a narrower operation context such as `mask-stack`, `file-format:tiff`,
  `material-layering` or `mode:painter_iray`. A symbol may have several.
- `evidence` of a Painter symbol includes its documentation anchor,
  `python-doc/<page>#<object>`, where the object is the symbol, its owner (an enum member is
  documented on its class) or `module-<symbol>`; a module documented only by a page cites the
  page. Additions cite the defining section, `docs/<file>.md#<heading>`, which must exist.
- `tier_evidence` lists `golden_id`s of the Tier 0 public manifests of the current oracle envelope
  (`<manifest_root>/tier0/` of the `current` entry of `parity/envelopes/registry.json`, decision
  037); `--tier0 <dir>` names another directory.
- Compositor entries (decision 081) say whether the compositor reproduces the symbol's effect on
  the channel maps; the `any` entry of the same symbol (the Python API call) stays a release gap
  until the API tasks prove its set → get readback. A compositor entry always has `notes`; a
  `supported` one names the goldens it equals exactly (r1, and r2 where stable or covered by an
  exception); a `release-gap` one names its owner task (`phase<N>.<M>_<name>`). Requesting a
  compositor release gap raises `NotYetSupported` before any mutation (decision 082).

## Statuses and rules

| Status | Meaning | Required |
|---|---|---|
| `supported` | Implemented and proven | `tier_evidence` naming at least one existing Tier 0 golden, and `since` (the UzPainter version) |
| `desktop-only-omitted` | Changes no texture, render or script-visible state in Painter; calling it raises `UnsupportedInUzPainter` | `justification` |
| `release-gap` | Not implemented yet; using it raises `NotYetSupported` before any mutation | nothing; `since` stays null |

Generation also fails on: a Painter entry without a documentation anchor of its symbol; a
symbol outside its namespace (`substance_painter`/`substance_painter_plugins` in the inventory
and the compositor file, `uzpainter` in the additions); any symbol or context naming a stroke; a
repeated (symbol, context) pair; unknown or malformed fields; a missing release gap of `10-…` §3
(`RELEASE_GAPS` in the generator); a compositor entry outside the `compositor` contexts, without
notes, or a compositor release gap naming no owner task. Each error names the entry.

The release gaps of §3 are seeded as their own entries with a note (paint layers and effects
receiving bitmaps or projections, warp and UV-set-to-UV-set projections, the UV-tile workflows,
auto-unwrap, vector and font sources, material layering, USD export, TIFF/PSD/WebP/JPEG 2000
export, arbitrary `.sbsar` evaluation). The desktop-only members are the Qt-facing members of
`ui` named in §3, `Resource.show_in_ui`, `show_resources_in_ui` and
`GraphicalUserInterfaceStarted`. Every other entry starts as `release-gap`; tasks that implement
a symbol change its entry to `supported` with its Tier 0 evidence (first:
`phase1.22_pyapi-cli-capabilities`). A gap leaves `RELEASE_GAPS` only together with §3.

## Tests

`python -m pytest tests/capabilities` checks determinism (two processes, and the `zig build`
step when `zig` is on PATH), schema validity, the evidence rules, the release gaps, the
desktop-only list, documentation anchors, the absence of stroke symbols and that every symbol of
`documented_symbols.json` has an entry. Where Painter's python-doc is available
(`UZP_PAINTER_PYTHON_DOC` or the default install path), it also checks that every Python object
of its `objects.inv` has an entry and that every anchor exists there.
