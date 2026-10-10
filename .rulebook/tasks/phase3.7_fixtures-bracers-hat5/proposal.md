# Proposal: phase3.7_fixtures-bracers-hat5

## Why
OWN-03 (`docs/prd.md`) requires the corpus after the pilots — bracers first — to be reproduced with equal maps; MAT-04 requires the starter assets used by locked recipes to evaluate identically through UzPainter's own certified implementations (acceptance: Tier 2a and bracer r9 Tier 1); MAT-02/MAT-03 require the generators and procedural sources of recorded recipes to evaluate exactly; LAY-11 requires portable smart-material folders with identical parameters and resources (bracer fixture); NFR-03 measures the bracer layer workload separately; G-03 requires migration through Painter's documented API with equal maps. The roadmap's pilot order makes the locked bracers and the historical hat v5 the early procedural and native-bake fixtures of Phase 3, and its rule 7 with the DAG's corpus migration assumption governs stroke-painted content (owner decisions 019 and 020, Q5 and Q6; exact equality and exceptions per decision 017, Q1). This is DAG node P3-BRACERS (`docs/dag.md`), implementing D14 (`docs/roadmap.md`, `docs/dag.md`) with the tier rules of `docs/architecture/14-parity-testing.md` §2, §3 and §5, the procedural rules of `docs/architecture/05-procedural-content.md` §2, §4 and §6, and the bake rules of `docs/architecture/06-baking.md` §7.

## What Changes
- **Bracer r9 (locked)**: recipe rebuilt in Painter through the documented API (oracle recorded twice, stored privately) and in UzPainter from the same stack JSON and resources with identical external mesh maps; manifest `parity/manifests/tier1/bracer-r9.json`; every procedural evaluated by certified `HlslBackend` families (MAT-04) — a run served by `SnapshotBackend` is reported separately and does not satisfy MAT-04; the bracer smart-material folder ported with identical parameters and resources (LAY-11).
- **Hat v5 (historical, procedural relief)**: rebuilt the same way; manifest `parity/manifests/tier1/hat-v5.json`; its paint layer or Paint effect handled per the corpus migration assumption — imported as a bitmap when the documented export route preserves the required output (proven by equality), otherwise recorded `not_migratable` with the reason.
- **Native-bake leg**: the fixtures' mesh maps baked by `EmbreeBaker` from their low/high (and cage) sources; per-map Tier 2b comparisons against Painter's CPU bakes published; the Tier 1 runs keep identical external mesh maps in both tools.
- **Reports** in `parity/reports/phase3/` (numbers and hashes only): oracle stability, UzPainter repeatability and equality to Painter reported separately per fixture and map; Tier 2a status of every procedural asset the two recipes use; exceptions relied on; bracer layer-workload timing and memory recorded for P5-PERF.

## Dependencies
- DAG inputs: `phase3.5_embree-bakers` (P3-BAKER), `phase3.6_smart-presets-projections` (P3-SMART).
- Upstream through those inputs: `phase3.3_procedural-families` (certified families, snapshot backend, Tier 2a), `phase2.10_pilot-tunic-recovery`.
- Downstream: `phase3.8_gate-g3` (G3), `phase4.2_coverage-hat-v8` (P4-HAT8), `phase4.1_coverage-body-v6b` (P4-BODY).

## Acceptance
DAG gate of P3-BRACERS: required fixtures pass their applicable tiers through equality or approved output exceptions. An unavailable fixture blocks acceptance unless an explicit owner scope decision authorizes its exclusion or replacement. In substance: bracer r9 Tier 1 equal (a G3 criterion) with certified procedurals; hat v5 Tier 1/2 equal; every non-zero difference covered by an owner-approved entry in `parity/exceptions.json`; a fixture marked `not_migratable` without an owner scope decision recorded in the capability manifest and the gate report keeps this task and G3 blocked.

## Impact
- Affected specs: `parity` (bracer r9 and hat v5 fixtures)
- Affected code: `parity/manifests/tier1/`, `parity/manifests/tier2b/`, `parity/reports/phase3/`; smart-material folder assets under `assets/` with provenance records; no product-code change beyond defects these fixtures expose
- Breaking change: NO
- User benefit: the locked bracer recipe and the historical hat run in UzPainter with proven equal maps, including native-baked mesh maps
