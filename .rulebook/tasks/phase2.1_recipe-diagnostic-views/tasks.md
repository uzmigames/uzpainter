## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand

## 2. Implementation
- [ ] 2.1 `isolate(layer)` evaluating on a revision snapshot with one node hidden; visibility restored atomically; no committed change
- [ ] 2.2 `contribution(layer)` difference map
- [ ] 2.3 `material_views(mask)` per-channel views for ID, BaseColor, Height, Normal, Roughness, Metallic
- [ ] 2.4 `region_stats {mask, map}`
- [ ] 2.5 `snapshot_layer_tree` and `diff_snapshots`
- [ ] 2.6 Diagnostic export sources (`08-…` §6) shared by all views; worker handlers for the MCP Diagnostics tools

## 3. Tests
- [ ] 3.1 `isolate`: document revision and every visibility flag identical before and after; isolated export equals an export with the node hidden by hand
- [ ] 3.2 `contribution`: equals the decoded difference of the two exports
- [ ] 3.3 `material_views`: a synthetic fixture with a seeded leak in Roughness is detected; a clean fixture reports none
- [ ] 3.4 `region_stats`: values equal those computed from the exported map and mask at native precision
- [ ] 3.5 Snapshot/diff: added, removed and modified nodes and parameters reported exactly; identical snapshots give an empty diff
- [ ] 3.6 Each diagnostic output equals the export of the same diagnostic source

## 4. Acceptance
- [ ] 4.1 Every §3 test green; results attached to `phase2.2_recipe-and-diagnostics`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
