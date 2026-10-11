# 01 — Dossier sent to the review panel

Sent verbatim on 2026-10-11 through the local 9router proxy (`POST /v1/chat/completions`) to each panel model. The models had no repository access; they judged the measured facts and the seven conclusions (C1–C7) of the project analysis made earlier that day in session uzpainter-12. Answers: files 02–05.

---

You are a senior graphics/engine architect giving an INDEPENDENT, ADVERSARIAL second opinion. Another AI reviewer produced the analysis below of a real project. Do not be agreeable: say where it is wrong, overstated, or missing something. You cannot read the repo; judge from the evidence given, and say when evidence is insufficient.

# Project
UzPainter: clean-room (Apache-2.0) reimplementation of Adobe Substance 3D Painter 12.1.0, operated 100% by AI agents (no human editing UI), headless-first, Windows DX12 primary + Vulkan second. C++23 built with Zig 0.15.2, Python tooling, embedded CPython + MCP server planned. Rendering code vendored (copied) from the owner's own engine.
ACCEPTANCE CRITERION (owner decision): OUTPUT PARITY — same instruction sequence must produce byte-identical textures AND the same render as Painter. Exact equality, no tolerances; any divergence needs an owner-approved entry in an exception register (currently EMPTY). "Render" means Painter's Iray path tracer output, to be matched by a clean-room path tracer on DXR + Vulkan RT.
Recorded oracle: Painter is driven through its documented Python API to record "goldens"; recorded Adobe output is kept outside the repo by a content-hash guard.

# Measured state
- Age: ~2 days, 41+ commits, all on 2026-10-10/11. 26k lines C++ in src/, 42k lines Python tooling, 1170 Python tests (1103 pass, 67 skip = GPU/oracle-store lanes by design), 11 native test exes. Zero TODO/stubs. mypy strict, -Wall -Wextra -Werror. Build and full suite green.
- Plan: 116 tasks, 1872 checklist items, 55 done (3%). Phases 0-5 with gates G0-G5, hypothesised 30-39 weeks. Observed pace: 19 tasks / 279 items archived in ~2 days.
- Built: project store (SQLite+zstd, ~90%), mesh import (OBJ/FBX/glTF, MikkTSpace, ~85%), DX12 render core (~70%, Vulkan absent), document model (~70%), compositor (~35%: tile DAG, 23 separable blend kernels; no masks/effects/procedurals/projections yet), Python API (~5%). Paper only: supervisor/worker IPC, MCP server, export, bakers, path tracer, procedurals.
- API capability manifest: 822 Painter API symbols, 807 "release-gap" (0 implemented), 15 desktop-only omitted.
- Parity fits (parity/semantics, 61 entries): 10 exact, 49 calibrated (non-zero residual = "never a pass" per contract), 2 gap. Of the 49 calibrated, worst-map/best-variant max residual in 16-bit codes: 24 entries <= 2 codes (blend normal/multiply/screen/overlay/softlight/hardlight/darken/lighten/divide/..., quantisation-end, quantisation-per-layer, height-to-normal, srgb8 store); 17 entries 5..257 codes (non-separable-ish and burn/dodge/linear modes, ao-mixed 257, srgb8-export 256); 9 entries > 5000 (two seeded-procedural prototypes 15k-65k = known NO-GO for exact parity; blend Saturation 14879 / Value 14011; tangent-frame entries 8-9k that INCLUDE deliberately-wrong control variants while the correct convention matches within 1 code; resample bilinear minification 5.9k-16k while magnification matches within 1 code).
- Painter itself is unstable on 6/59 Tier-0 goldens across save/reopen (e.g. 100% of texels differ by 257 on one quantisation case).
- Iray (Tier 3): contract says pixel equality is impossible (stochastic, seed not exposed); Tier 3 can only pass via owner exception from a measured noise floor. The capture procedure has 10/14 settings rows "pending_probe" that require the OWNER at Painter's UI panels.

# The reviewer's conclusions (check each)
C1. Highest-leverage task: find the single rounding/quantisation model behind the 24 near-exact (<=2 code) fits; one discovery could flip ~half the calibrated corpus to exact and halve the needed exception register.
C2. Sequencing defect: the Iray reference-capture leg feeds only the Phase-3 path tracer, but the DAG makes it a prerequisite of gate G0 (and G0 -> G1). No phase-1/2 work node depends on it; it only blocks gate records. Move it out of G0.
C3. Scope is overweighted to research: phases 3+4 hold ~52% of items; path tracer + Vulkan RT + DXR GPU baker ~205 items (11%) serve Tier 3, which cannot pass except by exception. The usable product is G2 (two pilot assets at Tier-1 parity, MCP-operable) + the asset-pipeline cutover, reachable at ~37% of the plan.
C4. Architecture debt: the compositor cache is a linear layer list with chained prefix hashes, but the design requires "anchors" forming a cross-layer, cross-channel dependency graph. Decide the graph shape before building mask effects, or the cache/hashing code gets rewritten.
C5. The evaluator profile id is persisted into every project and golden while still "provisional"; the experiment that decides it is still open. Wrong order: either run it now or version current goldens as profile-scoped.
C6. Determinism: -ffp-contract=off is set only on the evaluator; render/mesh/doc-model compile without it. Measured: 0 FMAs in the default baseline-x86_64 build, but -mcpu=x86_64_v3 yields 32 FMAs in tangents.cpp and 114 in certificate.cpp. Latent hazard; move the flag to global C++ flags.
C7. Code bugs found and fixed: tile cache key lacked grid size (stale tiles after a resolution change); lock-file race allowing two owners; bundle import set an idempotency horizon of 0 (could re-apply operations); unchecked id in a recursive delete; case-insensitive filename collision on NTFS.

# Answer, in this exact structure, max ~700 words
1. Verdict per conclusion C1-C7: AGREE / PARTLY / DISAGREE, with one or two sentences of reasoning each. Be specific about what would change your mind.
2. The 3 biggest risks the reviewer MISSED, ranked, each with why it matters and a concrete cheap test to de-risk it.
3. Is the acceptance criterion itself (byte-exact parity with a closed-source GPU app, empty exception register) a sound engineering target? If you would change it, say exactly how, in one paragraph.
4. Your own top-5 next actions, in order.
