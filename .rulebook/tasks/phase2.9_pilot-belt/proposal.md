# Proposal: phase2.9_pilot-belt

## Why
P2-BELT in `docs/dag.md` (critical path), the second pilot of the owner's order Wand v1 → Belt v5 → Tunic v10 (owner Q7; `docs/roadmap.md` Phase 2), implementing D14 and the Phase 2 integration evidence of D10 (`docs/architecture/11-mcp-server.md` §6, §7: the Belt round with Python disabled). Belt v5 adds bitmap BaseColor swatches (`base_tex`) in final-UV space, and it proves that a complete production round runs through typed MCP tools with `--allow-python` off (owner Q12). Requirements: OWN-03, OWN-04, LAY-02, INT-02, ARC-14, ACC-01, EXP-05 (`docs/prd.md`); tier rules of `docs/architecture/14-parity-testing.md` §1–§4.

## What Changes
- Belt v5 rebuilt in UzPainter from the pipeline's stack JSON and resources with identical external mesh maps, including the `base_tex` swatch fills (bitmap BaseColor fill in final-UV space: sRGB, UV projection, scale 1, no repeat, BilinearHQ).
- Belt v5 Tier 1 goldens recorded on the owner's machine with `tools/parity/recorder/*.py` through Painter's documented API (rebuilt from the same stack JSON and resources), at least twice with oracle stability classified; blobs in the private store, hashes in `parity/manifests/`.
- Tier 1 report `parity/reports/phase2/belt-v5-tier1.json`: every exported map per set compared on decoded native values, save/reopen, the three separate results (oracle stability, UzPainter repeatability, equality), the diagnostics of `14-…` §4 and the exceptions relied on (numbers only).
- MCP-only round: the full belt round (project creation with mesh, settings and mesh maps, resource import, stack sync, save, export) driven through typed MCP tools by a supervisor started without `--allow-python`, with the call log and receipts recorded in `parity/reports/phase2/belt-v5-mcp-round.json`.

- Before input-dependent work, publish one bounded input inventory and preserve available or recovered bytes by verified hash in the private store. Reuse documented searches; another sweep needs a newly identified source. Original restoration does not change scope. If a reference must be recreated, replaced or excluded, prepare one owner decision package and reuse any pending question; only an explicit recorded owner scope decision authorizes that route. Missing inputs or an unanswered scope choice never count as a parity pass.

## Dependencies
- DAG inputs: `phase1.25_pilot-wand` (P1-WAND), `phase2.8_mcp-server` (P2-MCP).
- Consumer: `phase2.10_pilot-tunic-recovery` (P2-TUNIC); evidence joined by `phase2.11_gate-g2`.

## Acceptance
DAG gate: equal maps; Python-disabled MCP integration round completed; input inventory and preservation complete, with the reference baseline explicitly identified. Every Belt v5 map equals the private golden in native decoded values (or is covered by an owner-approved exception in `parity/exceptions.json`); two UzPainter runs are byte-identical; the MCP-only round with `--allow-python` off completes and its maps equal those of the Tier 1 run.

## Impact
- Affected specs: `pilots` (Belt v5)
- Affected code: none beyond fixes the pilot exposes; fixture manifests, reports
- Breaking change: NO
- User benefit: the second production asset reproduced, and proof that operation needs no Python
