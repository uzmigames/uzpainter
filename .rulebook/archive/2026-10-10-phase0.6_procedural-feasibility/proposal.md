# Proposal: phase0.6_procedural-feasibility

## Why
Painter's generators, grunges and smart materials are `.sbsar` graphs run by Adobe's engine; UzPainter cannot execute them and ships no Adobe runtime or content (decision 002; D4 decision 006). Recorded recipes (locked bracers, hat, body) depend on them, so UzPainter must reimplement certified families from public literature and calibrate them black-box against private Painter oracles (`docs/architecture/05-procedural-content.md` §1–§3, §6). Under Q1 (decision 017) a non-zero residual passes only through an owner-approved exception, so Phase 3's procedural scope must be decided on measured residuals, not hopes (PRD MAT-03, ARC-05, CLR-01, CLR-06, OWN-01; `docs/roadmap.md` rule 1: feasibility starts in Phase 0; `docs/dag.md` P0-FEAS-PROC, implements D4).

## What Changes
- Feasibility prototypes of two mesh-map generators from the `05-…` §3 family list (chosen among those the recorded recipes use and named in the report) and of Leather Damaged expanded into the families it references, written from the public sources of `05-…` §3 (procedural noise, edge/cavity detection from curvature and AO maps, morphological and blur operators) and the parameter semantics discovered through the documented `Property` and `SourceSubstance` API.
- UzmiGames-authored fixtures: unit sphere and bevelled cube with their mesh maps; public fixture manifests in `parity/manifests/phase0/procedural-feasibility.json`.
- Private oracles recorded through the recorder (documented API: `get/set_parameters`, presets, image inputs, export) and admitted to the store; the observed Leather Damaged structure stays private (05 §3 publication rule).
- Residual report `parity/reports/phase0/procedural-feasibility.md` (numbers only): per asset, mesh, resolution, parameter set and seed — max/mean/p99 |Δ| and affected-texel counts; the evaluated subset of the `05-…` §6 matrix named; a go/no-go per family for `phase3.3_procedural-families` (P3-PROC).
- Fitted parameters with public source and residual in `parity/semantics/procedural-feasibility.json`.

## Dependencies
- Prerequisites: `phase0.3_painter-oracle-recorder` (P0-RECORDER), `phase0.5_private-oracle-store` (P0-STORE).
- Successors: `phase3.3_procedural-families` (P3-PROC) and gate `phase0.10_gate-g0` (G0).

## Acceptance
Residuals published; go/no-go for Phase 3 scope (`docs/dag.md`, P0-FEAS-PROC). Contributes to G0: "feasibility reports published" (`docs/roadmap.md`). A pilot success never closes a feasibility gap (`docs/roadmap.md` rule 1).

## Impact
- Affected specs: procedural
- Affected code: feasibility prototypes (not shipped), `parity/manifests/`, `parity/reports/phase0/`, `parity/semantics/`
- Breaking change: NO
- User benefit: Phase 3 procedural scope is set by evidence; gaps stay visible in the capability manifest
