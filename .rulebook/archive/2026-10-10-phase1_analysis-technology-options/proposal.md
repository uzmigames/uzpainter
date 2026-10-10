# Proposal: phase1_analysis-technology-options

## Why
UzPainter architecture decisions require concrete, sourced comparison of technology options for four critical systems: Python embedding (for scripting API), GPU texture compression (for export), project save format (for compact storage), and MCP server integration (for AI accessibility). This research enables the architect to make informed choices based on facts, not assumptions.

## What Changes
Four source-cited analysis documents delivered in `docs/analysis/technology-options/`:
- `01-python-embedding-and-packaging.md` — CPython embeddable, pybind11, nanobind, PyInstaller, Substance Painter approach
- `02-texture-compression-and-containers.md` — BC7 encoders, KTX2, DDS, PNG/TIFF, Unreal Engine ORM requirements
- `03-project-container-format.md` — SQLite (corrected from hypothesis), ZIP+JSON, Zstandard, OpenRaster, USDZ
- `04-mcp-server-options.md` — Official Python/TypeScript SDKs, C++ community options, tool/resource/prompt declarations, job handling

Each document includes comparison table (option | what it is | pros | cons | license | source), short trade-off summary (facts only, no recommendation), and all claims marked **Fact** (with URL) or **Hypothesis**.

## Impact
- Affected specs: `.rulebook/specs/` (if architecture spec exists) + new docs in `docs/analysis/technology-options/`
- Affected code: None (research only; no code changes)
- Breaking change: NO
- User benefit: Architect gains confidence in design trade-offs; decisions documented with sources for future reference and auditing
