# 47. The UI-only Tier 0 cases are the per-texture-set height-to-normal method, a height-amplitude sweep and UI-set Passthrough groups

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase0.7_tier0-semantics-ui-cases

## Context

Task phase0.7_tier0-semantics-ui-cases was written from the 12.1.0 observations of phase0.6: the "second height→normal method" was assumed to be a project setting, the height→normal strength a shader setting (04 §6, from older public help), and `BlendingMode.PassThrough` absent at runtime. Measured on Painter 12.1.5 on 2026-10-11 by reading the UI Automation tree out of process and hashing exports (decision 029, under the Assets3D Painter lock):

- The method is a per-texture-set combo in Texture Set Settings > Channels, "Height to normal method": `Sharp` (the default of a new project) and `Smooth (Sobel)`. A real click changes the exported `Normal_OpenGL` map; switching back restores it byte for byte; it survives save and reopen. No documented API reads or sets it. Project Configuration holds no such setting.
- No height→normal strength control exists: Texture Set Settings (every section; per-channel menus list only formats), Shader Settings of the default `open-pbr` instance and of `pbr-metal-rough-with-alpha-test`, Project Configuration, Edit > Settings and a Height fill's Properties were searched.
- The Layers panel's row menu offers "Passthrough" for a group. It applies to the channel chosen in the panel's channel selector only. The documented getter `Node.get_blending_mode` then returns a runtime member named `Passthrough` (value 25). The python-doc spells it `PassThrough`, which does not exist at runtime, and that is why phase0.6 found no member. The mode survives save and reopen.
- The Tier 0 texture corpus of the current envelope was recorded with Legacy colour management (no `OCIO`).

The model panel ruled on 2026-10-11 under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| Per-texture-set method, both methods recorded explicitly | PARTLY ×2, AGREE ×1. Fixes: name the texture set in each sheet entry, and verify that the active target is the one shown. |
| An amplitude sweep stands in for the strength sweep | DISAGREE ×1, PARTLY ×2. Accept only as a stated surrogate: record the absence of a setting as a fact of the inspected UI, use a spatially varying height, export the height, run it per method. |
| Passthrough set through the UI and verified by the widget and the documented getter | AGREE ×2, PARTLY ×1. Fixes: verify every node and channel, and verify the channel selector before the click. |
| Normal controls | PARTLY ×3. Add Normal controls for the group-only and child-only masks. |
| Legacy colour management | AGREE ×3 |
| Re-read after reopen | AGREE ×2, PARTLY ×1. Fix: compare r1 and r2 exports too. |
| Refresh and study use the UI operator; no operator means refusal | AGREE ×2, PARTLY ×1 |

## Decision

1. The sheet names the method per texture set as `Texture Set Settings/Height to normal method (<texture set>)`, valued `Sharp` or `Smooth (Sobel)`. Both methods are recorded explicitly on the sphere, the bevelled cube and a 4x2 plane grid. The existing default-method goldens stay as they are.
2. Painter 12.1.5 has no height→normal strength setting, so item 2.3 is met by a height-amplitude sweep per method on the 4x2 grid. The sweep is the authored height ramps at fill opacity 1 (default), 0.75, 0.5, 0.25 and 0.1, and as 2, 3 and 4 copies stacked in LinearDodge. Height (EXR 32f) is exported next to the normals. The manifests say that no strength setting exists, and this decision records the surrogate. It is not a claim that the two are the same thing.
3. A group's `Passthrough` is set in the Layers panel per channel. The sheet names it `Layers/Blending mode (step <n>, <channel>)` = `Passthrough`. Each value is verified twice: by the widget (`Pthr`, mapped to its menu label) after the channel selector reads back the channel, and by the documented `Node.get_blending_mode`. The recorder never sets the undocumented runtime spelling.
4. `group-passthrough-masks` uses the group-masks stack on a 4x2 grid. s0-s3 hold Passthrough with no mask, a group mask, a child mask and both masks. s4-s7 hold the same four stacks with the group in Normal, set through the API.
5. Texture goldens run without `OCIO` (Legacy), like the corpus they are compared with.
6. After the reopen, every UI value is read again, not applied. A mismatch refuses the golden. r1 against r2 export stability is reported per decision 032 (r1 is the exact target) and is not a refusal criterion.
7. `record` takes `--operator console|ui`. A golden with sheet entries is refused without an operator. The envelope's corpus dispatch (refresh, stability study, canary) gives it the UI operator, so no run ever records a default in place of a sheet value.

## Alternatives Considered

- Set `BlendingMode.Passthrough` through the API (rejected: undocumented spelling, outside the documented-API rule; decision 029 covers the UI route).
- Mark item 2.3 not applicable without a sweep (rejected: the scaling of the normal with the height gradient is what the fit needs, and the amplitude sweep measures it).
- Rely on the default method for Sharp (rejected: an explicit setting verifies the default, and the existing goldens stay as a cross-check).

## Consequences

The three UI-only cases leave the release-gap list once their fits are made. The 04 §6 statement about a shader strength is corrected. A future Painter version that adds a strength control re-opens item 2.3. The plane-strength goldens are save-reopen-unstable at opacities 0.75 and 0.1 (decision 032).
