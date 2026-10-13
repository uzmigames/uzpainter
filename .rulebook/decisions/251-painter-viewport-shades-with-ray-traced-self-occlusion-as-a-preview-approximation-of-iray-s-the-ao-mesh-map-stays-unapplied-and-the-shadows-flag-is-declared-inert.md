# 251. `painter_viewport` shades with ray-traced self-occlusion as a preview approximation of Iray's; the AO mesh map stays unapplied and the `shadows` flag is declared inert

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase2.3_realtime-preview, phase2.1_preview-viewport-window, phase2.2_preview-capture, phase3.4_path-tracer-transport, phase3.5_path-tracer-materials

## Context

The owner looked at a `painter_viewport` capture of the Wand (e2e s3, revision 168, 1700 × 1250, fitted camera from +Z, the `common` preset's clear colour, lit by the shipped CC0 `studio-small-09` default environment of decision 212) and said: "interessante mas totalmente sem sombra" ("interesting but completely without shadows"). He delegates technical choices to the model panel (memory note *decide with a model panel*).

### What the fixed render standard contains (decision 038)

`E:\UzmiGames\Assets3D\Pipeline\render\Render-Comparison-Standard.json`, SHA-256 `2ec4281f…be5`, unchanged since decisions 038 and 132:

- **v2 `common`** sets Painter's realtime-viewport shadow controls: `checks.shadows` false (line 29), `shadowmode` "Lightweight" (25), `shadowopacity` 100 (17), `ground_shadow` 1.0 (21) with `ground_enabled` false (33). Exposure 0, rotation 0, environment opacity 0, blur 0, infinite sphere.
- **`ref_match` v3** is identical except `checks.shadows` true (304) and clear colour 141,142,148. Its status is "documented equivalent, NOT live-verified". Its limits say "Realtime viewport uses prefiltered IBL and its own shadow approximation; Iray is the closer match to Cycles" (319), and "no floor/contact shadow" (328).
- **These shadow controls act only on Painter's realtime viewport.** Recorded on Painter 12.1.5: "Environment opacity 0, blur 0 and shadows off act only on the realtime viewport, and Painter disables them in Iray mode" (`parity/reports/phase0/iray-capture-procedure.md` §2). Adobe's Environment-settings help page agrees ("Enable / Disable rendering of shadows in the viewport"). It does not document the algorithm.
- **The lit comparison pass is Iray**, 256 samples at 1200 × 1200 (lines 36, 52-66, 148-152). Iray is a path tracer, so every Iray reference contains the mesh's own geometric occlusion, in both presets: diffuse and specular self-shadowing from the whole environment, the brightest region included. With the ground off there is never a shadow on a floor. The `base_color` pass is Painter's unlit Base-color view, where shadows play no part.
- **The standard pins no AO setting**: no AO intensity, no AO mesh-map toggle, no specular occlusion, no horizon fading. The hashed read-back of the open-pbr shader panel has no such parameter either (`iray-references.md` §5).
- **The AO mesh map is unrecorded as a shading input.** The Wand's Painter project binds a Blender AO bake as its AO mesh map (`wand11-v1/painter_create.py`). Adobe documents only that the baked AO and the AO channel are mixed by Multiply or Replace. It does not say which renderer applies the result to shading. A 2022 community reply about the older Adobe Standard Material says Iray ignores the AO texture. The repo records AO only as the export map `AO_Mixed` (`parity/semantics/ao-mixed.json`; decision 131). The Wand's albedo already carries painted occlusion (mask `M_ao_albedo`, `wand_masks_v3.py:172`).
- **No reference can check occlusion today.** All 23 Iray goldens are single convex meshes with no ground and no mesh maps; `iray-noise-floor.md` §5 defers concavity to the Phase 3 production references (phase3.6 items 2.1-2.2, not captured). No lit Painter realtime-viewport image exists, and no capture route for one is qualified (decision 039).

### What `painter_viewport` computes today (main 265c5d6)

- **One ray per pixel.** `src/preview/shaders/viewport.hlsl` casts one camera ray per pixel against screen-space tile bins (lines 216-261; built in `viewport.cpp` 374-429). Those bins answer camera rays only. Coverage is watertight (decision 178).
- **Unoccluded image-based lighting.** The pass then shades the hit (lines 263-326) with `colour = (specular + diffuse) · 2^exposure · 1.01919`:
  - specular is the prefiltered environment times `F0·A + B` of the split sum;
  - diffuse is Burley's albedo times the SH9 irradiance, scaled by one minus the dielectric specular albedo.
- **No second ray of any kind.** There is no shadow or occlusion ray, no world-space acceleration structure, no AO multiply, no specular occlusion and no horizon clamp. The only visibility term is the microfacet Smith masking inside the BRDF table.
- **Four material slots, no AO.** The slots are base colour, metalness, roughness and the combined `Normal_OpenGL` (`preview.h:53`, `scene.cpp:89-105`). The AO mesh map and the AO channel are never read.
- **The `shadows` flag has no effect.** The display state stores `environment.shadows` per preset and accepts only the active preset's value (`display.cpp:485-490`). `SceneOf` never reads it, the capture's render-state digest omits it (`capture.cpp:501-515`), and no doc or capability note says so. Decision 042 §1 says nothing may be silently ignored (ARC-03).

**Root cause of the owner's remark:** every hit point is lit by the whole environment as if nothing blocked it. The rings, the pommel, the grip's seams and its contact with the ferrules are lit like open surfaces. 07 §6 lists only split-sum IBL and SH irradiance, so this is by design, not a bug. It is also an undeclared gap.

### Model panel (one round; cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5)

Kimi's first attempts failed with an upstream connect timeout on 9router. It answered on a streaming retry with the same dossier. Grok answered on a retry after a 503.

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 Diagnosis: the standard's parity target shows Iray's path-traced self-occlusion; there is no floor shadow (ground off); the `shadows` flag is Painter-realtime-only and inert in Iray; no AO setting is pinned; the viewport has no occlusion | PARTLY | AGREE | AGREE |
| C2 Implement now: ray-traced visibility in `painter_viewport` as ratio estimators on the existing diffuse and specular terms (environment-importance + cosine samples for diffuse, GGX VNDF samples for specular), unoccluded pixels unchanged | DISAGREE | PARTLY | PARTLY |
| C3 A deterministic CPU-built BVH traversed in the same compute pass, reusing decision 178's watertight test; no DXR/Vulkan ray queries now | PARTLY | PARTLY | PARTLY |
| C4 Fixed per-pixel sample counts (proposed 32 diffuse, 16 specular), pixel-keyed scramble, captures keep `samples = 1`, no accumulation | PARTLY | PARTLY | PARTLY |
| C5 The AO mesh map is not applied now; an Iray recording settles it | PARTLY | AGREE | AGREE |
| C6 The `shadows` flag stays inert in `painter_viewport`, and that is declared | PARTLY | PARTLY | PARTLY |
| C7 No parity claim; faithful occlusion stays `painter_iray`'s | PARTLY | AGREE | AGREE |
| C8 Owner item phase2.3 2.4; convex goldens byte-identical, closed box renders 0, a wall test, a concave golden, the Wand for the eye, the time | DISAGREE | PARTLY | PARTLY |

**Adopted:**

- **C1 (GPT).** The precise wording is "no secondary geometric visibility for environment lighting". Primary visibility, Smith masking and occlusion painted into the albedo do exist. Contact shadows between the mesh's own parts are in scope; only floor shadows are absent.
- **C2, ratio terms (GPT, Kimi).**
  - Ratios are per RGB channel, so coloured occlusion is kept.
  - The specular weights are the estimator's own `f_r·cos/p` (Fresnel and `G2/G1` for VNDF), not radiance alone.
  - Each ratio is clamped to [0, 1]. A zero or non-finite denominator gives 1.
  - The estimator is biased, because a ratio of two Monte-Carlo sums is, though it converges. This is stated in the docs.
  - Excluding directions below the geometric facet is an approximation that can keep light the geometry would block near the terminator. It does not remove the shadow-terminator problem; it is documented and tested as an approximation.
- **C2, byte identity (GPT).** That the unchanged pixels stay byte-identical is verified by comparing images, not inferred from `x/x = 1`.
- **C3 (all three).**
  - The BVH's depth is capped when it is built and the traversal stack is sized to the cap, so the stack cannot overflow.
  - Hits on both faces count, as for camera rays.
  - The BVH is rebuilt only when the mesh changes.
  - Thin gaps, shared edges and extreme scales get their own tests.
  - The software choice rests on scope and portability, not on any claim that hardware ray tracing is non-repeatable (GPT).
- **C4 (all three).** The counts are not fixed by this decision. They are chosen by measurement: time and noise against a high-count reference, both reported. `samples` keeps its meaning of one camera sample per pixel. The visibility ray counts are internal, and the receipt states them.
- **C5 (GPT).** The settling recording is factorial: neither input, AO mesh map only, AO channel only, both, and Multiply against Replace. It uses a constant albedo with no painted occlusion and distinct AO patterns.
- **C6 (GPT, Kimi).** The flag's lack of effect is declared at runtime, not only in docs:
  - the capture receipt records the requested flag and that it has no effect in `painter_viewport`;
  - `render.display.state()` reports the same;
  - the capability notes say so.
- **C7 (GPT).** The aim is better depth cues in the preview. That it brings the preview quantitatively closer to Iray is not claimed.
- **C8 (all three).**
  - The convex control includes the normal-mapped plane.
  - The closed-box test must prove its samples were valid. An exact 0 does that, because the ratio-1 fallback would not give 0.
  - The finite-wall "exactly 1/2" claim is replaced by two checks: a CPU brute-force visibility reference of the same rays, and a high-count numerical reference with a declared tolerance.
  - New tests: a thin-gap pair at 2× and 0.5× the ray-origin offset, rays through a shared edge, a coloured environment, and occlusion across texture sets.

**Not adopted:**

- **Screen-space or horizon AO, or cosine-only AO (Grok).** Neither gives shadows from the environment's bright regions, which is what the owner misses. Screen-space AO also misses occluders off screen or behind the hit, and changes with the view. Grok's underlying concern, that the cost is unproven, is met by choosing the counts by measurement (C4).
- **Honouring `shadows` as a preview toggle, off giving today's image (Grok, one vote).**
  - The flag is off under `common`, so the owner's default view would stay shadowless.
  - It would also model Painter's realtime viewport, which 07 §6 says the preview does not model.
  - GPT and Kimi kept visibility always on, with the flag's lack of effect declared at runtime.
- **A `NoEffect` return value from `set_shadows` (Kimi).** The setter's signature mirrors the rest of the display API. The receipt and `state()` carry the declaration instead.
- **Half-resolution visibility, or different counts for the window and for captures (Kimi).** The window and the captures share `SceneOf` and the kernel. If the time budget is missed, the counts drop for both.

## Decision

1. **What UzPainter lacks.** Under the standard, the parity target (Iray) shows the mesh's own geometric occlusion of environment light: self-shadowing of diffuse and specular, the soft shadows of the environment's bright regions, and contact darkening between the mesh's parts. `painter_viewport` has none of it. The standard has no ground, so there is no floor shadow to add. Painter's realtime `shadows`, `shadowmode` and `shadowopacity` act only on Painter's realtime viewport, which is not a target (07 §6). No AO or specular-occlusion setting is pinned.

2. **Implemented now in `painter_viewport`: ray-traced visibility, approximating Iray's occlusion in the preview.**
   - **Rays.** Each camera hit casts visibility rays against every triangle of the scene, all texture sets included. There is one bounce and no interreflection: this is visibility only, not light transport. Camera-ray visibility (the tile bins, decision 178) is unchanged.
   - **Diffuse.** The existing SH-irradiance diffuse term is multiplied, per RGB channel, by `R_d = Σ V_i·w_i·L_i / Σ w_i·L_i`.
     - The directions are drawn from a balance-heuristic mixture of cosine-weighted sampling about the shading normal and environment-luminance importance sampling. The importance distribution is piecewise-constant 2D (PBRT 4th ed.) and built deterministically on the CPU with the rest of `PrecomputeLighting`.
     - `w_i = cos_i / p_mix(ω_i)`.
     - This resolves the bright regions' shadows that cosine samples alone would miss.
   - **Specular.** The existing split-sum specular is multiplied, per RGB channel, by `R_s = Σ V_j·w_j·L_j / Σ w_j·L_j`.
     - The directions are the view direction reflected about GGX visible normals (Heitz 2018) sampled about the shading normal.
     - `w_j = F(ω_j)·G2/G1`, the VNDF estimator weight, with Schlick's Fresnel and the height-correlated Smith masking of the existing lobe.
   - **Exclusions and guards.**
     - Directions below the geometric facet are left out of both sums.
     - A zero or non-finite denominator gives a ratio of 1, and each ratio is clamped to [0, 1].
     - Where nothing is occluded, the numerator is computed by the same operations in the same order as the denominator, so the ratio is exactly 1 and the pixel is unchanged. This is verified by comparing images (Consequences).
   - **Properties.** The estimators are consistent but biased, an approximation for the preview. Their sources are Pharr, Jakob and Humphreys (PBRT 4th ed.), Veach 1997 and Heitz 2018, all already listed for `painter_iray` in 07 §3.1. Nothing comes from Painter, whose shader library is quarantined.

3. **How the rays are traced: a software BVH in the same compute pass.**
   - **Building.** The CPU builds a BVH of world-space triangles with binned SAH in a deterministic order: small leaves, and a depth cap at which the build makes a leaf. It is cached by mesh reference and transform, rebuilt only when the mesh changes, and uploaded as a raw buffer like the pass's other inputs.
   - **Traversing.** The kernel walks the BVH with a stack sized to the depth cap, so the stack cannot overflow. It stops at the first hit.
   - **Hit test.** The test is decision 178's watertight edge-function test, `precise`, with hits on both faces. Ray origins are offset along the geometric normal by the integer-ulp method of Wächter and Binder (Ray Tracing Gems, 2019, ch. 6), and the originating triangle is skipped.
   - **Why not hardware ray tracing.** DXR and Vulkan inline ray queries are not used here. BLAS/TLAS building is Phase 3 infrastructure (phase3.4 items 2.3 and 2.7, phase3.2/3.3 for Vulkan) that does not exist yet, and the plain compute pass already runs wherever the viewport runs. 07 §3.5's "no software path tracer" concerns `painter_iray` and is unaffected: the viewport traces visibility, not paths.

4. **Sampling, counts and determinism.**
   - **Sequence.** A low-discrepancy sequence per pixel, scrambled by a hash of the pixel coordinates only. The same scene, build, adapter and driver give the same bytes, and the goldens keep working.
   - **No accumulation.** No progressive accumulation across frames in this decision.
   - **Counts.** The diffuse and specular ray counts are kernel constants chosen by measurement.
     - On the Wand, rendered at the window's default size and at 1700 × 1250 on the RTX 4090, the implementing agent measures the ladder (8, 4), (16, 8) and (32, 16).
     - It takes the largest pair whose window-size render stays within the window's 200 ms cadence.
     - It reports, per pair, the time, the BVH build time separately, and the noise as RMSE against a 1024-sample render of the same estimator.
   - **`samples`.** It keeps its meaning: one camera sample per pixel, and it must still be 1.

5. **The AO mesh map and the AO channel are not applied.**
   - **Why.**
     - Whether Painter's realtime viewport or Iray (open-pbr) darkens shading with them is unrecorded.
     - A baked AO of the same mesh, multiplied on top of ray-traced visibility, would count the occlusion twice.
     - The standard pins no AO setting.
     - The Wand's albedo already carries its painted occlusion.
   - **No new slot.** No fifth material slot is added.
   - **The settling recording.** It is owned by phase3.5_path-tracer-materials item 3.3, the single-channel perturbations.
     - It is an Iray Save Render of a UzmiGames-authored concave fixture under the fixed pipeline, with a constant albedo and no painted occlusion, and spatially distinct AO patterns.
     - It is factorial: neither input, AO mesh map only, AO channel only, both, under Multiply and under Replace.
     - If Iray applies AO, `painter_iray` models it and `painter_viewport` follows in a new decision.

6. **The `shadows` flag stays inert in `painter_viewport`, and this is declared, not silent.**
   - **Why inert.** `painter_viewport` approximates `painter_iray` (07 §6), and Painter disables the flag in Iray mode. Visibility is therefore always on, under `common` and under `ref_match`.
   - **Setter and getter.** `set_shadows` keeps accepting only the active preset's value (decisions 042, 132). `render.display.state()` reports that the flag has no effect on `painter_viewport`.
   - **Receipt.**
     - The receipt records the requested flag and its effect (none) outside `render_state_digest`.
     - The digest gains a `visibility` record: model, diffuse ray count, specular ray count. The model changes the image, so captures from before and after this decision are told apart.
     - `src/python/capture-receipt.schema.json` follows.
   - **Notes.** The capability notes of `uzpainter.render.display.set_shadows` and `uzpainter.render.capture` say the same, closing the ARC-03 gap.

7. **Relation to render parity: no claim.**
   - **Status unchanged.** `painter_viewport` stays non-parity, never acceptance evidence (decisions 018, 148, 212). No tier, capability status, release gap or gate changes.
   - **What it is for.** The visibility term is meant to give the preview its depth cues. That it brings the preview quantitatively closer to Iray is not claimed: bias, noise, painted occlusion and the split-sum lobes can all keep it apart.
   - **Where faithful occlusion comes from.** It remains `painter_iray`'s: phase3.4 item 2.6 (environment importance sampling), item 2.7 (next-event estimation with MIS over BLAS/TLAS ray queries) and the Phase 3 production Iray references (phase3.6 items 2.1-2.2).
   - **Shared code.** Phase 3 may reuse the preview's environment distribution code, but it keeps its own evidence.
   - **Not a target.** Painter's own realtime shadow approximation (the Lightweight mode and the rest) is not reproduced and is not a target.

8. **Owner.**
   - **The task.** The work is a new item 2.4 of `phase2.3_realtime-preview`, the open P2-PREVIEW parent, which already took decision 148's orthographic gap as item 2.3. It is built on branch `wt/viewport-shadows` (worktree `E:\UzmiGames\UzPainter-wt\shadows`).
   - **The gate.** Item 2.4 is preview quality. It leaves the DAG gate (captures window-independent, preview never pauses evaluation) and G2, which excludes render parity, unchanged.
   - **Docs to update.** `src/preview/PREVIEW.md` (Lighting, Pass, Captures, Regression goldens), 07 §6 (the list of approximations, with the bias), and the capability notes above.

## Alternatives Considered

- **Leave the viewport unoccluded until `painter_iray`.** Rejected. The owner's preview would stay flat for all of Phase 3, and the gap was undeclared.
- **Multiply the AO mesh map into the SH diffuse (cheapest).** Rejected for now. Its semantics in Painter's renderers are unrecorded, and it double-counts with ray-traced visibility (item 5 of this decision settles it by a recording).
- **Hardware inline ray queries now.** Rejected. That pulls Phase 3 BLAS/TLAS infrastructure forward, ahead of the task sequence.
- **Screen-space or cosine-only AO, and honouring `shadows` as a toggle.** Rejected; see "Not adopted" above.

## Consequences

The evidence for item 2.4. These are UzPainter-against-UzPainter checks, never parity:

- **Negative control.** The three convex goldens (sphere, normal-mapped plane, bevelled metal cube) keep their display and linear hashes under the new kernel key. This is checked pixel by pixel against the previous key's renders before the old entries are removed, as in decisions 163 and 178.
- **Closed box.** A camera inside a closed UzmiGames-authored box, under a positive constant environment, renders exactly 0 on every hit pixel. Only blocked, valid samples give that; the ratio-1 fallback would not.
- **Correctness of the traversal.** On a small concave fixture, the BVH's visibility of every ray equals a CPU brute-force cast of the same rays against all triangles. Any disagreement is reported with its ray.
- **Accuracy of the estimator.** On the same fixture, `R_d` and `R_s` are compared with a high-count reference of the same estimator, with a declared tolerance.
- **Edge cases.**
  - A thin-gap pair at 2× and 0.5× the origin offset: occluded at 2×, and the leak below the offset documented.
  - Rays through a shared edge of the box are blocked.
  - A two-colour environment gives per-channel ratios.
  - One texture set's mesh shadows another's.
- **New golden.** A concave golden, a cube resting on a plane, keyed by kernel, adapter and driver.
- **For the owner's eye.** The Wand capture before and after, under the same state as the owner's image. It is preview evidence only.
- **Time.** The ladder's times and noise, as in item 4 of this decision.

Owner-only action: none. The AO recording of decision 5 is a Painter recording for phase3.5 (owner at Painter's UI), not needed for item 2.4.

## Amendment (review of item 2.4, 2026-10-13)

The review of branch `wt/viewport-shadows` found that the specular estimator of item 2 was too noisy. It amends items 2 and 4:

- **Specular directions (item 2).** The specular ratio uses the same balance-heuristic mixture as the diffuse one. Half its rays are GGX visible-normal reflections and half are environment-importance directions, with `w_j = f·cos / p_mix = F·D·G2 / (4·n·v·p_mix)` and the visible-normal density `G1·D / (4·n·v)`. With VNDF rays alone, a bright light that the lobe only grazed rested on one heavy ray. When that ray was blocked, the highlight was zeroed. On metal, which has no diffuse term to fall back on, the pixel went black:
  - the 3/4 close view of the Wand had three pure-black pixels, which a 1024-ray render shows at 113-144;
  - its RMSE on the concave fixture was 0.217 at 16 rays.
- **Not self-hits.** In the 1024-ray render no pixel has a ratio of 0, and the darkened pixels' diffuse ratios were 0.97-1.0, so no ray origin is buried in a shell.
- **Counts (item 4).** The ladder is extended to (64, 32), (128, 64) and (256, 128). The counts are the smallest pair that meets the `0.5 / sqrt(N)` noise bound for both ratios on the concave fixture, provided its window-size render of the Wand fits the 200 ms period. That pair is (128, 64): specular 0.051 at 64 rays (bound 0.0625), diffuse 0.028 at 128 rays (bound 0.044), 170 ms at 660 × 600 in the Debug build. The bound is not loosened (an interim `N_eff = N / 4` was removed).
- **Unchanged.** There is still no accumulation across frames and no filter. The samples stay keyed by the pixel alone, and unoccluded pixels stay byte-identical. The receipt's `visibility` record now states 128 and 64.
- **The owner's remark.** This item gives self-occlusion only. Under the standard there is no floor to cast on, and the AO mesh map stays unapplied (item 5). The full-frame Wand therefore looks almost unchanged; the darkening is visible in close crops of the ferrule and pommel steps. Whether the crevice darkening of Painter's realtime viewport, which comes from the AO map, belongs in UzPainter's renderers stays item 5's recording (phase3.5 item 3.3).
