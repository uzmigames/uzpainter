# Proposal: phase4.4_tiles-export-filters

## Why
P4-TILES (`docs/dag.md`) delivers tile export filters as part of the UV-tile workflow, a release gap under OWN-01 and owner decision 019 (Q5) until Phase 4. `docs/architecture/08-export.md` §1 already accepts Painter's export dictionary verbatim, including `exportList[].filter.uvTiles`, `exportParameters[].filter.uvTiles` and the wildcards `$udim` and `$uvTileName` with `( … )` optional groups, and compiles it into a typed export plan before any GPU work; until a tile workflow exists these fields can only address the single tile 1001. EXP-03 (`docs/prd.md`) requires configurable naming with collision checks, EXP-05 byte determinism and EXP-06 generational publication; ARC-11 and INT-21 require complete receipts. Child of P4-TILES (`phase4.5_uv-tiles`), implementing D3 and D11 through the export engine of D7.

## What Changes
- **Plan compiler**: resolves `filter.uvTiles` in `exportList` entries and in `exportParameters` rules (rule order as in `08-…` §1: preset parameters, then `exportParameters` in list order), producing one planned file per selected `(set, stack, output map, UV tile)`; an unknown tile is rejected at compile time with the valid tiles.
- **Wildcards**: `$udim` and `$uvTileName` expanded per tile, including the `( … )` optional groups that vanish when a wildcard is empty (for example under the `Default` workflow); naming collisions between tiles are rejected at compile time (EXP-03).
- **Receipts**: each file record names its UV tile; `list_project_textures` and the MCP `export` dry run list per-tile files exactly (QG-03).
- **Publication**: per-tile files are written into the generation directory and published by the same atomic pointer update (`08-…` §5, EXP-06).
- **Capability manifest**: tile filters and wildcards move to `supported` with their Tier 0 evidence.

## Dependencies
- DAG input (through the parent): `phase4.2_remaining-nodes`.
- Delivered upstream and used here: `phase1.18_export-engine` (plan compiler, receipts, generational publication).
- Prior child: `phase4.3_tiles-workflow`. Parent: `phase4.5_uv-tiles`. Independent of `phase4.4_tiles-per-tile-resolution`.

## Acceptance
Part of the P4-TILES gate (Tier 0/1 on a UDIM fixture). This child is accepted when, on the UDIM fixture, the Tier 0 export goldens for tile filters and naming are exact: the file list Painter writes for each recorded configuration (a `filter.uvTiles` subset in `exportList`, a per-tile parameter rule in `exportParameters`, `$udim` and `$uvTileName` names with optional groups) equals the compiled plan, and every written map equals its golden; per-tile collisions are rejected before writing; and two runs produce identical bytes.

## Impact
- Affected specs: `uv-tiles` (export filters)
- Affected code: export plan compiler, naming and wildcard expansion, receipts, dry run (`list_project_textures`, MCP `export`), capability manifest
- Breaking change: NO
- User benefit: Painter export configurations that select or name UDIM tiles run unchanged
