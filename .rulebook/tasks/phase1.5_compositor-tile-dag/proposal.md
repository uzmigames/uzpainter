# Proposal: phase1.5_compositor-tile-dag

## Why
Every channel of every stack is evaluated tile by tile; the DAG, its cache and invalidation, the memory admission that lets three 4K sets fit, and the documented evaluation order (base value, root layers bottom-up, groups, pass-through, disable) are the frame every kernel plugs into (NFR-03, PRJ-03, LAY-03, LAY-10). Implements D3 (decision 005: Painter-semantic document with a tile/channel evaluator and a measured quantisation profile) with owner answer Q1 (decision 017: exact equality, a divergence passes only through an owner-approved exception) in `docs/architecture/04-layer-stack-and-compositing.md`; formulas are written from public literature and fitted to Tier 0 goldens recorded through Painter's documented API (`docs/architecture/14-parity-testing.md` §2, §3; CLR-01, CLR-02; `docs/licensing-and-clean-room.md`). Child of `phase1.14_compositor-core` (P1-COMPOSITOR), covering `docs/architecture/04-layer-stack-and-compositing.md` §2 (steps 1–3, 6 ordering rule, 7) and §7, and the authored templates of `docs/architecture/03-project-model.md` §2.

## What Changes
- `src/evaluator/dag.{h,cpp}`: DAG keyed by `(stack, channel, tile)` with 1024×1024 tiles (a set resolution ≤ 1024 is one tile); node outputs cached by `(node uid, subtree hash, evaluator_profile, tile)`; invalidation by subtree hash on every revision; evaluation only on revision snapshots, submitted to the engine thread.
- `src/evaluator/admission.{h,cpp}`: live tiles × bytes/texel × channels bounded by the VRAM budget from the render-layer capability query; dependency-order evaluation; LRU eviction; texture-set creation above the budget fails explicitly (PRJ-03).
- `src/evaluator/order.{h,cpp}`: `acc := default(channel)`; root layers walked bottom-up (storage keeps Painter's top-first order); groups composite children from a transparent start and blend the result; `PassThrough` composites children directly into `acc`; `Disable` skips the node for that channel.
- `src/evaluator/kernelgen.{h,cpp}`: generated HLSL, one kernel per (node kind, blend mode, channel format), compiled through the kernel cache of `phase1.1_core-device-kernels`, arithmetic `precise`.
- `assets/templates/*.json`: project templates (channel sets, formats, stack base values) authored by UzmiGames from documented semantics, each entry with a provenance record (public source, or the hash of the private observation it must equal); never generated from a capture.

## Dependencies
- DAG inputs of the parent: `phase1.4_render-core-layer`, `phase1.3_document-model`, `phase0.8_tier0-goldens` (template channel sets/formats, base values, ordering goldens).
- Parent: `phase1.14_compositor-core`. Siblings building on this child: all other compositor children.

## Acceptance
Tier 0 goldens owned by this child are exact: stack base values per template (empty-project export, LAY-10), evaluation order with asymmetric blends, group `Normal` and `PassThrough` composition without masks, template channel sets and formats. Unit tests for cache, invalidation and admission pass.

## Impact
- Affected specs: `compositor`
- Affected code: `src/evaluator/dag.*`, `src/evaluator/admission.*`, `src/evaluator/order.*`, `src/evaluator/kernelgen.*`, `assets/templates/`, `tests/evaluator/`
- Breaking change: NO
- User benefit: Large projects evaluate within the VRAM budget, edits re-evaluate only what changed, and the stack order matches Painter.
