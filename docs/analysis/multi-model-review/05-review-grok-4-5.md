# 05 — Review by Grok 4.5 (`xai/grok-4.5`)

Answer to the dossier of `01-dossier.md`, unedited.

---

1. Verdict per conclusion
C1. PARTLY. Near-exact cluster real; “single” rounding model overclaim. Blends, height-to-normal, sRGB store, per-layer quant often differ stage-by-stage. Evidence of shared residual bound ≠ shared root. Change mind if one instrumented dump shows identical round/bit-depth/premult order on all 24.

C2. AGREE. Tier-3 Iray capture blocks gate paper only; phase-1/2 nodes lack edge to it. Stochastic + owner UI probes make it G0 poison. Keep capture work; drop from G0 predicate.

C3. PARTLY. Item mass on path tracer/RT real; Tier-3 cannot hit empty-register exactness. “Usable = G2 at 37%” second-guesses owner OUTPUT PARITY incl. Iray. Valid cut only if owner rewrites acceptance.

C4. AGREE. Linear prefix-hash list fights anchor/cross-channel DAG. Masks/effects will force rewrite. Freeze graph schema (nodes, channel edges, invalidation) before more compositor surface.

C5. AGREE. Provisional profile id in every project/golden = corpus poison. Run deciding experiment now or namespace goldens by profile version. Else silent invalidation later.

C6. AGREE. Evaluator-only `-ffp-contract=off` while tangents/certificate grow FMAs under x86_64_v3 = latent non-byte-identical builds. Global C++ flag + locked microarch for oracle and runtime. Measured 0 FMA baseline does not clear v3 path.

C7. AGREE on substance. Tile-key/grid, lock race, idempotency horizon 0, unchecked recursive id, NTFS case clash = real young-system bugs. Fixes good; pattern says more cache/identity hazards remain. Need proof tests locked in suite, not narrative.

2. Biggest risks reviewer missed
R1. Unstable oracle. Painter flips 6/59 Tier-0 goldens on save/reopen (one case 100% texels ±257). Byte-identical + empty exception register vs non-stable closed app is undefined. Cheap test: script N save/reopen cycles on all Tier-0; histogram residuals; freeze only stable subset as legal goldens; rest forced exceptions.

R2. Seeded procedurals + non-separable blends already structural NO-GO (15k–65k, Sat/Val ~14k). Empty register cannot survive. Cheap test: classify every residual family as (fixable model) vs (API/seed/black-box); pre-size exception budget before more kernels.

R3. Velocity mirage. 19 tasks/2 days, 3% plan, path tracer/bakers/MCP/Vulkan still paper; AI-agent-only, no human UI edit. Graphics parity work collapses at RT/proc/export. Cheap test: time-box one end-to-end pilot asset to Tier-1 byte match; measure wall-clock and exception count; re-forecast from that, not checklist burn.

3. Acceptance criterion soundness
Not sound as stated. Exact byte match to closed-source GPU app with empty exception register fails when oracle itself unstable, Iray stochastic (seed hidden), and seeded procedurals diverge by tens of k codes. Change to: (a) Tier-0/1 document+compositor parity with explicit per-op tolerance table and versioned exception register as first-class deliverable (budget >0); (b) Iray/Tier-3 = statistical noise-floor match + owner-signed waiver, never pixel-exact gate; (c) lock Painter build hash + capture script + profile id into golden metadata; (d) dual-backend (DX12/VK) parity as separate gate, not assumed. Exact equality kept only where Painter proven bit-stable.

4. Top-5 next actions
1. Quantify Painter stability: N-cycle save/reopen on full Tier-0; quarantine unstable goldens; write stability report into exception policy.
2. Run evaluator-profile experiment now; freeze profile id; re-tag or re-record goldens as profile-scoped; stop persisting “provisional”.
3. Spec compositor dependency graph (anchors, cross-layer/channel edges, cache keys) and land schema before any mask/effect/procedural work; reject further linear-list cache features.
4. Promote `-ffp-contract=off` (and denorm/RTN policy) to global C++ flags; pin oracle and CI to one microarch; add FMA/disasm check in CI.
5. Owner decision gate: either shrink acceptance (tolerances + Tier-3 waiver) or pre-approve exception families for procs/non-separable/Iray; block new calibrated “never pass” entries until policy exists.
