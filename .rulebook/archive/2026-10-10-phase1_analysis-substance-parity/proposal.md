# Proposal: phase1_analysis-substance-parity

## Why
UzPainter must replace Adobe Substance 3D Painter for an AI-only workflow (Python scripting + native MCP). Before any design work, the architect needs a precise, source-backed inventory of what Substance 3D Painter 12.1 exposes to Python, how its layer stack, baking, export and project formats work, and what the existing SubstancePainterMCP bridge (79 tools + local patch) actually covers. Without it, parity decisions would rest on guesses.

## What Changes
- Add seven analysis documents under `docs/analysis/substance-parity/` (English, Markdown, one theme per file):
  - `01-python-api-inventory.md` — every public symbol of the shipped `substance_painter` Python API (module by module).
  - `02-layer-stack-model.md` — layer/effect kinds, masks, blending, channels/formats, sources, smart assets, resources, geometry masks, UV tiles.
  - `03-baking.md` — bakers, exposed baking parameters, high-poly/cage workflow, how baked mesh maps feed the stack.
  - `04-export.md` — export config JSON, presets and their decoded channel packing, formats/bit depths, padding, UDIM naming, mesh export.
  - `05-project-and-spp.md` — project creation/save/reload settings, metadata, `.spp` facts vs hypotheses.
  - `06-mcp-tools-inventory.md` — every SubstancePainterMCP tool, the Painter API it calls, the local patch and recipes.
  - `07-parity-matrix.md` — capability-by-capability parity matrix (no inclusion decisions).
- No code, tests or build changes; nothing outside `E:\UzmiGames\UzPainter` is modified.

## Impact
- Affected specs: none
- Affected code: none (documentation only)
- Breaking change: NO
- User benefit: the architect can decide UzPainter scope from cited facts instead of assumptions.
