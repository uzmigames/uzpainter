# 81. The compositor registers its Phase 1 support in the `compositor` context, with current-envelope goldens as evidence

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.14_compositor-core, phase1.2_docmodel-capability-manifest, phase1.22_pyapi-cli-capabilities

## Context

Item 2.8 of phase1.14 asks that every Phase 1 node kind, source, projection and blend mode be in the capability manifest: `supported` with its Tier 0 evidence, or `release-gap`.

- The manifest has one entry per documented Painter symbol and operation context. All 769 Painter entries were `release-gap`, plus 15 desktop-only entries.
- The architecture (`10-python-api.md` §3) asks more of a `supported` entry than a golden comparison: set → get readback through a freshly resolved handle, and persistence after save and reopen. The Python API that would provide those does not exist yet (phase1.19-1.24).
- The generator checked `tier_evidence` against `parity/manifests/tier0`, the manifest root of the superseded 12.1.0 envelope (59 golden ids). Decision 037 makes the goldens those of the current envelope. Its root holds 87 ids, among them `group-coverage-order`, `semantics-ui/group-passthrough-masks`, `blend-component-hue`, and the `height-normal-*` and `resample-uv-*` goldens.

The model panel was consulted: cx/gpt-6-astra and xai/grok-4.5. kimi/kimi-k3 answered HTTP 503 twice.

| Claim | gpt-6-astra | grok-4.5 |
|---|---|---|
| C1 Register the compositor's support in a new operation context `compositor` (narrower `compositor:<case>`), and leave the `any` entry (the API symbol) a release gap | PARTLY | PARTLY |
| C2 Put the entries in a separate generator input, `compositor-capabilities.json` | AGREE | AGREE |
| C3 Validate `tier_evidence` against the current envelope's manifests, resolved from the registry | AGREE | AGREE |

Both PARTLY verdicts ask for the same thing: state that a compositor entry's evidence bar is the golden comparison of the channel maps, so that no reader takes it for an API promise. GPT also warned about:

- scope leakage: White and Black masks do not prove every mask;
- vacuous support;
- `release-gap` entries whose paths still run (instances, one-axis wrap, Mesh geometry masks). Decision 082 makes the check before mutation refuse those.

## Decision

1. `tools/capabilities/compositor-capabilities.json` is a third generator input. It follows the inventory's rules for Painter symbols, including the symbol's documentation anchor.
   - Its entries use only the context `compositor` or a narrower `compositor:<case>`: `compositor:minification`, `compositor:mask-stack`, `compositor:content-stack`, `compositor:height`, `compositor:normal-directx`, `compositor:material`, `compositor:ocio`.
   - A (symbol, context) pair repeated across the inputs fails generation.
2. A compositor entry says whether the compositor reproduces the symbol's effect on the channel maps. Its evidence bar is the golden comparison only.
   - The set → get and persistence bar belongs to the API context `any`.
   - `any` stays `release-gap` until the API tasks prove it. phase1.22 changes it.
3. A compositor entry is `supported` only when it names the current-envelope goldens it reproduces exactly: r1, and r2 where r2 is stable or covered by an exception. Its notes state its scope.
   - A case those goldens do not cover becomes a narrower `release-gap` context: bilinear minification, content-stack fill effects, mask-stack levels, SignedAddition and uniform colours on Height, and DirectX Normal bitmaps.
   - Every compositor `release-gap` names its owner task (`phase<N>.<M>_<name>`), or generation fails. The test suite checks that the task exists, open or archived.
4. Release gaps and their owners on 2026-10-11:

   | Owner | Release gaps |
   |---|---|
   | phase3.4_smart-projections | 3D projections and their parameters, symmetry, CustomPhysicalSize |
   | phase4.1_nodes-projections | Warp, UVSetToUVSet |
   | phase1.9_compositor-resample-gaps | Bilinear minification |
   | phase3.2_proc-material-families | Material source mode, MaterialPhysicalSize |
   | phase3.2_proc-filter-families | Filter effects (Blur, decision 069), content-stack fill effects |
   | phase3.2_proc-generator-families | Generator effects |
   | phase3.3_procedural-families | Procedural sources |
   | phase4.1_nodes-vector-font-sources | Vector and font sources |
   | phase4.1_nodes-paint-layers | Paint layers and paint effects |
   | phase4.1_nodes-instances-anchors | Instance layers, anchors, reference sources |
   | phase4.1_nodes-mask-effects | Compare-mask and colour-selection effects |
   | phase4.5_uv-tiles | UVTile geometry masks |
   | phase4.2_remaining-nodes | Implemented but no golden: Mesh geometry masks, mask-stack levels, RepeatHorizontally and RepeatVertically |
   | phase1.20_pyapi-facade | OCIO colour management |
   | phase1.12_compositor-height-normal | SignedAddition and uniform colours on Height, DirectX Normal bitmaps |

5. `tier_evidence` resolves through the current envelope: `<manifest_root>/tier0` of the registry entry `current`. `zig build capabilities` no longer passes the superseded directory. `--tier0` still names another directory when needed.
6. `since` is the package version that first supports the entry, from `build.zig.zon`. Today that is `0.0.0`. A release raises it for the entries it adds.

## Consequences

- 54 compositor entries are `supported` and 42 are `release-gap`.
- Registered: all 32 blend modes, the 8 projection modes, the 3 filtering, 4 wrap and 3 scale modes, and 20 node and source classes.
- A child that lifts a gap moves its entry to `supported`, with its goldens, in the same change: phase1.9 for minification, phase1.12 for the Height cases.
- Until the API lands, readers of `capabilities.json` see two statuses per symbol: `compositor` (does the evaluator reproduce it) and `any` (can a script call it).
