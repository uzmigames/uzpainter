# Proposal: phase5.2_parity-report-tiers

## Why
Child of `phase5.4_parity-report` (P5-REPORT in `docs/dag.md`), implementing D13 as specified in `docs/architecture/14-parity-testing.md` §1, §3–§5 and §8, with the Tier 3 comparison of `docs/architecture/07-preview-and-render-parity.md` §3.5 and §4 (decisions 017 and 018). Release criterion 1 of `docs/prd.md` §18 requires Tiers 0–2 equal on the self-hosted GPU runner for the certified corpus, Tier 3 compared with converged Iray references, every divergence (every Tier 3 residual included) covered by a recorded owner exception, and the exception register published. Requirements: G-04, ARC-06, ARC-09, ARC-10, VIS-06, EXP-05, NFR-02, CLR-05. This child delivers the full Tier 0–3 report on DX12 and Vulkan and the published exception register.

## What Changes
- Full comparison run on the frozen release build (the build hash and dependency lock shared with `phase5.2_packaging`) on the self-hosted GPU runner, on DX12 and on Vulkan:
  - Tier 0 semantics over the corpus of 14 §3, including the node kinds and UV-tile fixtures added in Phase 4;
  - Tier 1 recipes for the certified corpus (wand v1, belt v5, tunic v10, bracer r9, hat v8, body v6b) and every other Tier 1 fixture of 14 §3: every exported map per set, save/reopen and dump-and-rebuild;
  - Tier 2a per certified procedural asset and Tier 2b for the ten bakers (hit/coverage evidence first, then maps);
  - Tier 3: `painter_iray` against the converged Iray references, per fixture and material region, next to the noise floor (07 §4), plus the DXR-versus-Vulkan cross-backend report (07 §3.5).
- Vulkan Tier 0–2 outputs compared byte for byte with DX12 (14 §3).
- Three results reported separately for every comparison: oracle stability, UzPainter repeatability and equality to Painter, with the diagnostics of 14 §4 (max, mean and p99 |Δ|, differing texel counts, per-region breakdown, normal angular statistics, FLIP as a diagnostic only); every result carries hardware, driver, backend, build hash, resource hashes and the exception entries it relied on (14 §8).
- Public report `parity/reports/phase5/tiers.json` (numbers and hashes only); difference maps and region crops stay in the private store (14 §6).
- Exception register `parity/exceptions.json` published: every entry versioned, owner-approved, recorded as a decision under `.rulebook/decisions/`, with its domain, metric, bound, evidence hashes and defect-detection test re-run on the frozen build.
- Fixture status per gate: a fixture marked `not_migratable` without an owner scope decision is reported as failing its gate.

## Dependencies
- Parent: `phase5.4_parity-report` (integration and acceptance of P5-REPORT).
- Prerequisites (DAG inputs of P5-REPORT): `phase4.6_gate-g4`, `phase3.7_path-tracer`, `phase5.1_performance-budgets` (the release build is frozen after its budgets are accepted).
- Siblings: `phase5.2_parity-report-mcp-conformance`, `phase5.3_parity-report-capability-gaps`; all three report on the same build hash.

## Acceptance
- Tiers 0–2 green on DX12 and Vulkan, or each difference covered by an approved exception listed in the report.
- Tier 3 passed only through approved exception entries; any Tier 3 comparison without one is reported blocked, which blocks P5-REPORT.
- Exception register published; every entry's defect-detection test passes on the frozen build.
- The report names the frozen build hash and dependency lock, equal to those of `phase5.2_packaging`.

## Impact
- Affected specs: `parity` (tier report, exception register)
- Affected code: comparison tool and report generator, CI job on the self-hosted GPU runner, `parity/exceptions.json`, `parity/reports/phase5/`
- Breaking change: NO
- User benefit: one evidence record that shows, per asset, map, backend and render fixture, whether UzPainter equals Painter and which owner exceptions that relies on
