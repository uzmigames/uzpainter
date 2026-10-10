# Proposal: phase4.2_coverage-hat-v8

## Why
OWN-03 (`docs/prd.md`) requires hat v8 to be reproduced with equal maps; PRJ-06 (channels incl. SpecularWeight) is accepted by hat v8 Tier 1; BAK-08 (one corrected AO per set feeding generators, delivery and albedo layers, exported for glTF occlusion) is accepted by the hat v8 fixture; NFR-03 measures the hat v8 workloads (30–45-layer stacks, up to seven delivered maps per set) separately; INT-11 requires the hat consumers to run unchanged on the UzPainter delivery; OWN-06/EXP-08 require SpecularWeight to be exported and reported as a consumer gap (owner decision 023, Q10). Stroke-painted content follows the corpus migration assumption (decisions 019 and 020). This is DAG node P4-HAT8 (`docs/dag.md`), implementing D14 (`docs/roadmap.md` Phase 4 row and pilot order) with `docs/architecture/14-parity-testing.md` §2–§3 (Tier 1 rules, `not_migratable`), `docs/architecture/08-export.md` §4 and §5.1 rows 2, 3, 5, 7, 8 and 9, and `docs/architecture/06-baking.md` (AO binding).

This task is the parent integration and acceptance task, split into two child tasks because the Sharpen filter in mask stacks and the SpecularWeight channel/export are independently testable artifacts.

## What Changes
- `phase4.1_hat8-sharpen-filter`: Sharpen as a filter effect in mask and content stacks with hat v8's recorded parameters, on the certified Sharpen family of P3-PROC; Tier 0 mask goldens for sharpen (LAY-04).
- `phase4.1_hat8-specular-weight-export`: SpecularWeight channel per set (PRJ-06) with its measured storage format, the hat v8 variant of the Assets3D inline preset (five maps + SpecularWeight + 16-bit AO) with provenance, and consumer-gap reporting across presets.
- Parent: hat v8 rebuilt in Painter (oracle, documented API, recorded twice) and in UzPainter from the same stack JSON and resources with identical external mesh maps — the 43-layer stack and its seven delivered maps; manifest `parity/manifests/tier1/hat-v8.json`; Tier 1 report in `parity/reports/phase4/`; one corrected AO per set bound by usage and exported for glTF occlusion (BAK-08); consumer-matrix rows 2, 3, 5 and 7 run on the hat v8 delivery and on the Painter delivery with identical bindings and outputs; the hat v8 runs of rows 8 (UE 5.6) and 9 (UzEngine); NFR-03 timing and memory for the 43-layer stack and seven maps recorded for P5-PERF; stroke-painted content imported as bitmaps when the documented export route preserves the output, otherwise `not_migratable` with the reason.

## Dependencies
- DAG inputs: `phase3.7_fixtures-bracers-hat5` (P3-BRACERS), `phase3.4_uzengine-preset` (P3-UZE).
- Children (mandatory, independent of each other): `phase4.1_hat8-sharpen-filter`, `phase4.1_hat8-specular-weight-export`.
- Item-level prerequisite for the row 8 hat v8 run only: `phase3.3_unreal-gltf-presets` (a G3 input, therefore accepted before G4).
- Downstream: `phase4.6_gate-g4` (G4).

## Acceptance
DAG gate of P4-HAT8: equal maps. In substance: both children accepted; every hat v8 map exported by UzPainter equals the private Painter goldens at native depth, or each difference is covered by an owner-approved exception; consumer rows 2, 3, 5 and 7 produce identical bindings and outputs on both deliveries and rows 8 and 9 pass on their expected bindings with SpecularWeight reported as a gap; a fixture marked `not_migratable` without an owner scope decision blocks acceptance.

## Impact
- Affected specs: `parity` (hat v8 fixture)
- Affected code: `parity/manifests/tier1/hat-v8.json`, consumer fixture manifests for rows 2, 3, 5, 7, 8 and 9 on hat v8, `parity/reports/phase4/`; product code only through the two children and defects the fixture exposes
- Breaking change: NO
- User benefit: hat v8, the largest current stack, is delivered by UzPainter with proven equal maps to every current consumer
