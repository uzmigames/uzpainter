# Proposal: phase0.2_parity-contract

## Why
Acceptance is output parity with Painter 12.1.0 (decision 001), and the owner fixed the equality rule under Q1: exact equality, divergence only through an owner-approved, versioned exception with evidence, no preset tolerances, diagnostics never grant an exception (decision 017). Q2 made converged Iray references the render target (decision 018) and Q9b put every recorded Painter output in the private store on the owner's machine (decision 022). No written contract or schema exists yet, so recorder, store, comparison tool and every tier would each invent their own record shape (PRD ACC-01, G-04, ARC-09, ARC-10, CLR-05, NFR-02; `docs/architecture/14-parity-testing.md` §1–§6 and §9; `docs/dag.md` P0-CONTRACT, implements D13).

## What Changes
- `parity/CONTRACT.md`: the binding acceptance sentence (14 §1); the three separately reported results (oracle stability, UzPainter repeatability, equality to Painter); tiers 0, 1, 2a, 2b, 3 with corpus, compared quantities and gate (14 §3); comparison on decoded pixels at native depth with channels classified by measured storage format; the exception register rule (14 §5); the `not_migratable` rule and `oracle_unavailable` result (14 §2, §6); and the comparison-tool specification (14 §4: per-map max/mean/p99 |Δ|, differing-texel count and percentage, per-region breakdown, normal angular statistics, exact ID/alpha checks, render statistics of `07-…` §4, FLIP pinned by version and hash as a diagnostic only, difference maps kept private).
- `parity/schema/golden-public.json`: independently authored inputs, UzmiGames instruction sequences, settings a test applies, public-documentation-derived expectations, software identities (Painter build id, UzPainter build hash) and the SHA-256 of every private oracle record.
- `parity/schema/golden-private.json`: every recorded Painter output — exported maps, API readbacks (JSON included), effective-default and template captures, Iray references with their settings sheet and operator-recorded settings — with the golden shape `{inputs, instruction sequence, effective defaults, Painter build, project settings, resource hashes, bake backend, render state} → {outputs}` and the two-recording rule (14 §2).
- `parity/schema/exceptions.json` (schema of the register) and `parity/exceptions.json` (empty register that validates): domain, metric and bound, evidence (oracle instability or irreducibility; for Tier 3 the noise floor and every `uncontrolled` setting), defect-detection test, approving decision id, version.
- Sample documents under `parity/schema/samples/` used by the schema tests (authored public samples, a synthetic private-shaped sample, an exception entry).

## Dependencies
- Prerequisites: `phase0_owner-decisions` (P0-OWNER, archived), `phase0.1_approved-source-index` (P0-SOURCES).
- Successors: `phase0.3_painter-oracle-recorder` (P0-RECORDER), `phase0.5_private-oracle-store` (P0-STORE), `phase1.3_document-model` (P1-DOCMODEL).

## Acceptance
Reviewed; schemas validate samples; no recorded output fits the public schema (`docs/dag.md`, P0-CONTRACT).

## Impact
- Affected specs: parity
- Affected code: `parity/` (contract, JSON schemas, samples, schema tests)
- Breaking change: NO
- User benefit: one contract and one record shape for every tier; private oracle data cannot be mistaken for public data
