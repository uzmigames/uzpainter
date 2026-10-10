# Proposal: phase2.1_recipe-diagnostic-views

## Why
Child of `phase2.2_recipe-and-diagnostics` (P2-RECIPE in `docs/dag.md`), implementing the diagnostics of D3 (`docs/architecture/04-layer-stack-and-compositing.md` §8) with their native API (`docs/architecture/10-python-api.md` §7), MCP tools (`docs/architecture/11-mcp-server.md` §2) and export route (`docs/architecture/08-export.md` §6). Paint gates and agents need per-layer isolation, contribution maps, material-leak views, region statistics and layer-tree snapshots with diffs, all produced by the general evaluation engine so they cannot disagree with exports. Requirements: LAY-09, LAY-14, EXP-04, DIA-01, QG-01, QG-04 (`docs/prd.md`).

## What Changes
- `uzpainter.diagnostics.isolate(layer)`: evaluates with one node hidden and restores visibility atomically, leaving no change in the document.
- `contribution(layer)`: the difference map between evaluation with and without the layer.
- `material_views(mask)`: per-channel values under a material mask for ID, BaseColor, Height, Normal, Roughness and Metallic leak checks.
- `region_stats {mask, map}` (DIA-01): statistics of a map under a mask from faithful maps and masks.
- Layer-tree snapshot and diff (`snapshot_layer_tree`, `diff_snapshots`): ids, names, kinds, visibility and parameters, and a structural diff between two snapshots.
- All diagnostics are exports of the general engine with the diagnostic sources of `08-…` §6; worker handlers back the MCP Diagnostics tools. Diagnostics record technical facts only and grant no approval (QG-04).

## Dependencies
- Parent: `phase2.2_recipe-and-diagnostics`.
- Prerequisite: `phase1.25_pilot-wand` (DAG input of P2-RECIPE).
- Sibling (independent): `phase2.1_recipe-dump-manifest-blocks`.

## Acceptance
- `isolate` leaves revision and visibility unchanged; `contribution` equals the decoded difference between the two exports; `material_views` detects a seeded leak and reports none on a clean fixture; `region_stats` matches values computed from the exported map and mask; snapshot/diff reports exactly the seeded changes.
- Each diagnostic output equals the export of the same diagnostic source.

## Impact
- Affected specs: `recipe` (diagnostic views)
- Affected code: `uzpainter.diagnostics`, export diagnostic sources, worker command handlers
- Breaking change: NO
- User benefit: cheap, faithful paint-gate evidence
