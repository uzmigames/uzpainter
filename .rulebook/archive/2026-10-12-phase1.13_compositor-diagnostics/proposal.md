# Proposal: phase1.13_compositor-diagnostics

## Why
Agents and paint gates need per-layer isolation, contribution maps, material-isolation views and region statistics that are exports of the general engine, never separate code paths (LAY-09, LAY-14, EXP-04, DIA-01, QG-01). Implements D3 (decision 005: Painter-semantic document with a tile/channel evaluator and a measured quantisation profile) with owner answer Q1 (decision 017: exact equality, a divergence passes only through an owner-approved exception) in `docs/architecture/04-layer-stack-and-compositing.md`; formulas are written from public literature and fitted to Tier 0 goldens recorded through Painter's documented API (`docs/architecture/14-parity-testing.md` §2, §3; CLR-01, CLR-02; `docs/licensing-and-clean-room.md`). Child of `phase1.14_compositor-core` (P1-COMPOSITOR), covering `docs/architecture/04-layer-stack-and-compositing.md` §8 and `docs/architecture/10-python-api.md` §7 (`uzpainter.diagnostics`).

## What Changes
- `src/evaluator/diagnostics.{h,cpp}`: `isolate(layer)` evaluates with one node hidden and restores visibility atomically; `contribution(layer)` returns the difference map; `material_views(mask)` returns per-channel values under a material mask for ID/BaseColor/Height/Normal/Roughness/Metallic leak checks; `region_stats(map, mask)` returns statistics of a map inside mask regions.
- All diagnostics run through the general evaluator and are available to the export plan as diagnostic sources (EXP-04); no separate evaluation path.

## Dependencies
- DAG inputs of the parent: `phase1.3_document-model` (transactional visibility restore).
- Sibling prerequisites: `phase1.11_compositor-mask-effects`, `phase1.12_compositor-height-normal`.
- Parent: `phase1.14_compositor-core`. Consumers: `phase1.15_export-plan-compiler` (diagnostic sources), `phase1.19_pyapi-native-module` (`uzpainter.diagnostics`).

## Acceptance
Diagnostics tests pass (LAY-09, LAY-14): isolation restores prior state exactly, contribution equals full minus isolated evaluation, material views and region statistics equal independently computed values; repeatable bytes.

## Impact
- Affected specs: `compositor`
- Affected code: `src/evaluator/diagnostics.*`, `tests/evaluator/`
- Breaking change: NO
- User benefit: Cheap, faithful evidence for paint gates and leak checks without touching the document.
