# 257. `painter_viewport` applies the AO mesh map as a visibility cone inside its ray-traced occlusion, and adds no cavity or horizon term

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase2.3_realtime-preview, phase3.5_path-tracer-materials, phase1.25_pilot-wand, phase3.2_proc-generator-families

## Context

After decision 251 the owner looked at `painter_viewport` renders of the Wand and asked: "cadê as cavidades? microshadow? AO bem definido?" ("where are the cavities? micro-shadows? well-defined AO?"). Decision 251's rays trace the low-poly mesh. They darken only the few spots the low-poly itself encloses, such as the pommel's inner ring. The leather wraps, the ring grooves and the engravings are not in the low-poly geometry. They are in the baked AO mesh map and in the baked normal map, and the viewport reads neither for occlusion.

This decision amends item 5 of decision 251 for `painter_viewport` only. It does not change `painter_iray`, whose use of AO stays owed to the recording of decision 251 item 5.

### What Painter's standard, API and settings expose (recorded vs unrecorded)

| Item | Source | What it says | Status |
|---|---|---|---|
| Fixed render standard, v2 `common` and `ref_match` v3 | `E:\UzmiGames\Assets3D\Pipeline\render\Render-Comparison-Standard.json`, SHA-256 `2ec4281f…25be5`, unchanged (decisions 038, 132) | It sets the environment, exposure, rotation, opacity, blur and the realtime-viewport shadow controls. It pins **no** AO intensity, AO toggle, specular occlusion, horizon fading, cavity or micro-shadow setting. Its `texture_contract` reads AO as Non-Color / Raw and Height as Raw "avoid applying height twice when it is already combined into the exported normal". The Blender side renders with Cycles and wires no AO input. | Recorded: nothing pinned |
| Default shader panel | `parity/reports/phase0/iray-references.md` §5, hashed read-back of Painter 12.1.5's `open-pbr` instance under OCIO (decision 042) | Displacement on, source Height, scale amount 0, so a painted height acts as bump and nothing is displaced; Tessellation uniform 1; Emission 0; Opacity off. The panel shows **no** AO, specular-occlusion or horizon parameter. | Recorded |
| Python API | `tools/capabilities/painter-api-inventory.json` | `substance_painter.display` has only camera, environment, colour LUT and tone mapping. `textureset.MeshMapUsage.AO` (supported), `MeshMapUsage.Curvature` (supported), `MeshMapUsage.Height` and `ChannelType.AO`, `ChannelType.Height`, `ChannelType.Displacement` set inputs. No symbol sets an AO strength, a specular occlusion, a horizon fade or a cavity. | Documented |
| JavaScript API documentation | `PAINTER/resources/javascript-doc/**` (A-JSDOC) | `alg.texturesets` shows a texture-set field `additionalAmbientOcclusionMapBlending` (`DataBlendingMode_Multiply` in its example), the documented Multiply/Replace mix of the AO mesh map and the AO channel. The custom-shader UI sample names an "Ambient occlusion intensity" shader parameter. Its default and its effect are not documented there and were not read further. It does not appear in the `open-pbr` read-back above. | Names documented; behaviour unrecorded |
| Whether Iray darkens shading with the AO mesh map or the AO channel, and how strongly | decision 251 item 5 | Not recorded. The factorial Iray recording (neither input, mesh map only, channel only, both, under Multiply and under Replace) is owed to phase3.5 item 3.3. | **Unrecorded** |
| Painter's realtime viewport | decisions 039, 251; 07 §6 | Not a target, and no capture route for it is qualified. | Not a target |

Decision 251 §Context says the same: the AO intensity is not pinned, and the AO recording belongs to phase3.5 item 3.3.

### What UzPainter has (main `9e57199`)

- **Viewport slots.** Four slots: base colour, metalness, roughness, and the combined `Normal_OpenGL` (`src/preview/preview.h` `MaterialSlot`, `scene.cpp`). The combined normal already contains the painted Height as bump. Maps are sampled bilinearly with wrapping (`viewport.hlsl` `SampleMap`).
- **Occlusion.** Decision 251's visibility ratios `R_d` (128 rays) and `R_s` (64 rays) are traced against a BVH of the low-poly mesh. Directions below the shading normal or the geometric facet are left out of both sums. Decision 256 fades the shading normal before the rays are cast. Nothing reads the AO mesh map for shading.
- **The AO mesh map.** `exporter::PassThroughMeshMap` (`src/export/virtual_maps.h`) already reads the AO mesh map bound to a texture set at the set's resolution, as UNORM grey (decision 103). Curvature and Position go through the same reader.
- **The Wand** (`parity/envelopes/…/phase1/tier1/wand-v1.json`). It binds two mesh maps: Normal (`11-Varinha-Madeira_Normal_OpenGL_v1.png`, `071a7123…`) and AO (`11-Varinha-Madeira_AO_v1.png`, `1dd1ed01…`), both high-to-low bakes (`wand11-v1/painter_create.py`). It has **no Curvature mesh map**. Its painted Height is flat except the iron dimples (`I02`, height −0.003). Its albedo already carries painted occlusion (`M_ao_albedo = clip((0.97 − ao)/0.8)^0.85`, `wand_masks_v3.py:172`).
- **The owner's pipeline requirement.** BAK-08 (MUST): one corrected AO per texture set feeds "the AO mesh map used by generators and preview", the delivered AO map and the albedo occlusion layers, and the AO map is exported for glTF's occlusion slot. The pipeline therefore paints some occlusion into the albedo and also expects consumers to apply the AO map again.

### Model panel (one round; cx/gpt-6-astra, kimi/k3, xai/grok-4.5)

The dossier is in scratch (`aocav/dossier.md`). `kimi/kimi-k3` returned 503 three times, so the same dossier went to `kimi/k3` on the same router, streamed.

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 Nothing in the standard or API pins any AO, cavity, micro-shadow or horizon parameter; only Iray's use of AO is recordable (phase3.5 3.3); the viewport stays non-parity | PARTLY | AGREE | AGREE |
| C2 A fifth `occlusion` slot from the AO mesh map; the AO channel not applied (decision 131); glTF strength `a = 1 + s(ao − 1)`, `s = 1`, a fixed declared constant shown in `state()` and the receipt, not a settable knob | PARTLY | PARTLY | PARTLY |
| C3 One directional model: a visibility cone about the shading normal with `sin²α = a` (Oat and Sander 2007), multiplied per ray into decision 251's existing estimators, giving AO, specular occlusion and micro-shadows from one input | PARTLY | PARTLY | PARTLY |
| C4 No double counting: per-direction products plus dividing out the low-poly occlusion, `a_d = a / A_low` | DISAGREE | PARTLY | PARTLY |
| C5 A cavity term from the divergence of the combined normal's slope field, combined by `min` | DISAGREE | PARTLY | DISAGREE |
| C6 No separate horizon term; decisions 251 and 256 already cover reflections below the horizon | PARTLY | AGREE | AGREE |
| C7 The `occlusion` receipt record, the negative control and the new checks | PARTLY | PARTLY | PARTLY |
| C8 Approved-source entries before code; owner item phase2.3 2.5 | PARTLY | AGREE | PARTLY |

**Adopted:**

- **C1 (GPT's wording).** The recording targets Iray's use of AO. A recording informs a later decision; it does not set a preview constant by itself. The preview's constants stay UzPainter's choices, not values derived from a reference.
- **C2 (all three).**
  - The strength `s = 1` is UzPainter's provisional preview default. It changes only by a decision. A phase3.5 result that pins Iray's AO use feeds that decision but does not set `s` automatically (GPT, Kimi).
  - The extra darkening on top of the painted occlusion in the albedo is stated as intended: BAK-08 expects the AO map to be applied again by the preview and by glTF consumers. The receipt names it (GPT, Kimi).
  - The input contract is written down: decoding, filtering and resolution (Grok, GPT); see item 2 of the Decision.
- **C3 (all three).**
  - The cone is hard: a ray passes when `dot(s, d) ≥ sqrt(1 − a)`. That makes both ends exact. At `a = 1` the threshold is 0, so every ray both loops already keep passes, and the pixel is unchanged without any special case. At `a = 0` every ray is blocked. This removes the smoothstep band and its calibration constant (Kimi's blocker, Grok's item 1). An explicit `a == 1` early return is kept anyway and tested on its own (Kimi).
  - The model is named an **assumed directional AO** (GPT). It puts the bake's occlusion in a symmetric cone about the shading normal. It does not recover where the real occluders are.
  - The order is fixed (Grok): decision 256's fade, then the cone about the faded shading normal, then the rays.
  - The measures differ (Grok, GPT). The cone equals `a` only for the cosine measure under uniform light, before facet clipping. Under the actual environment it differs on purpose: that difference is what gives the directional cue. This is declared as a bias, and no equality is claimed under other lighting.
- **C4: the division is not adopted, and so is the claim of no double counting (GPT's DISAGREE; Kimi's and Grok's defects).**
  - `A_low` would be estimated from about 64 cosine rays. Dividing a smooth bake by it would put per-pixel noise into the bake, and `a / A_low` blows up where `A_low → 0`, the darkest concavities (Kimi).
  - Which rays would estimate `A_low` was undefined (Grok).
  - The quantity needed, `E[V_low · V_cone]`, cannot be recovered from the two means (GPT).
  - What is adopted is the per-direction product alone, declared as a heuristic: a direction blocked by both the low-poly and the cone is removed once. The remaining double darkening is declared, and it is measured as a report, not a pass condition (Consequences).
- **C5: not adopted (GPT and Grok DISAGREE, Kimi PARTLY).**
  - The divergence of the slope field in UV texels depends on texel density, UV distortion, the tangent frame and mirrored islands. A constant `k` tuned on the Wand would not transfer.
  - The AO bake already holds the baked crevices, and the albedo holds painted ones.
  - On the Wand the cavities the owner misses come from the AO mesh map through the cone.
  - A cavity term is left to a later decision. It would need analytic fixtures and texel-density normalisation, and it would take its source from a bound Curvature mesh map, not from the normal (Grok).
  - The dossier's claim that Iray applies bump "without such darkening" is withdrawn as unsupported (GPT).
- **C6 (Kimi, Grok; GPT's narrowing).** No additional horizon term is justified for the present preview. This is not a claim that one would duplicate decisions 251 and 256 in every case. The continuity near the facet horizon stays covered by decision 256's swept-tilt test, and the cone checks below add grazing-view cases.
- **C7 (all three).**
  - Every choice that changes the output is recorded in the receipt (item 5).
  - The endpoints are asserted exactly, not only through goldens.
  - Tolerances come from high-count references of the same estimator, not from a Bernoulli bound alone (GPT).
  - The Wand renders are for the owner's eye and are not a gate (Grok).
  - New tests: a set with an AO channel and no AO mesh map; a roughness sweep on metal; partial-overlap and disjoint-blocker fixtures; mirrored and scaled UVs; times stated with resolution, ray counts and machine (Kimi, Grok, GPT).
- **C8 (GPT, Grok).**
  - The index rows carry exact bibliographic data and the equations used.
  - Each row separates the published method from UzPainter's adaptation. Applying the cone per ray inside decision 251's ratio estimator is UzPainter's own construction.
  - The rejected formulas are not implementation inputs, so they need no rows.

**Not adopted:**

- **A settable owner knob for `s` (not raised by the panel).** Under decision 042, the display API accepts only pinned values. `s` is shown read-only.
- **Grok's display-only cavity overlay.** Nobody asked for it, and it is not needed once the AO map is applied.
- **Indexing Lagarde and de Rousiers 2014 although it is rejected (Grok).** A source that does not enter the implementation needs no approval row.
- **A temporal or spatial filter on `A_low` (Kimi).** The division it would have stabilised is dropped.

## Decision

1. **What is recorded.** The standard, the `open-pbr` read-back and the Python API pin no AO, specular-occlusion, horizon, cavity or micro-shadow parameter. The JavaScript documentation names an AO-mix field and a custom-shader "Ambient occlusion intensity" parameter without documenting what they do to shading. The only open question a recording can answer is whether Iray applies the AO mesh map or the AO channel, and how (phase3.5 item 3.3, decision 251 item 5). Everything this decision adds is a `painter_viewport` approximation. It is not render parity, the viewport stays never-parity evidence (decisions 018, 148, 212), and no tier, capability status, release gap or gate changes.

2. **Input: an `occlusion` slot from the AO mesh map.**
   - **The slot.** `MaterialSlot` gains a fifth member, `Occlusion`. It is fed by `exporter::PassThroughMeshMap` for `MeshMapUsage::AO` of each texture set.
   - **Decoding and sampling.** The map is one channel, UNORM code divided by the code maximum, linear (the standard's Non-Color / Raw). It is at the set's resolution and sampled by the pass's bilinear wrap like the other slots.
   - **Gaps.** A set without an AO mesh map reads `ao = 1`. Any other image layout fails as the pass-through does (`evaluator:unsupported_source`); it is not silently treated as 1.
   - **Not applied.**
     - The painted `AO` channel is not applied, nor is its mix with the mesh map, because decision 131's rule is unrecorded. The receipt says `ao_channel: "not_applied"`.
     - The `Curvature` and `Height` mesh maps are not read.
     - Height enters only as the bump already in the combined normal, so it is never applied twice. Displacement stays pinned at the default's 0 (decision 042).
   - **Strength.** `a = 1 + s · (ao − 1)` (glTF 2.0, `material.occlusionTexture.strength`), with `s = 1.0`. `s` is UzPainter's provisional preview default, a fixed constant that changes only by a decision. `render.display.state()` reports it read-only, and the capture receipt states it (item 5).
   - **Painted occlusion.** On assets whose albedo already carries painted occlusion, as the Wand's does, the preview darkens those regions again. BAK-08 intends this, and the receipt names it.

3. **Model: an assumed directional AO as a hard visibility cone inside decision 251's estimators.**
   - **The cone.** Its axis is the shading normal `s` after decision 256's fade. Its half-angle `α` satisfies `sin²α = a`, so under uniform light, before facet clipping, the cosine-weighted visible fraction is exactly `a` (Oat and Sander 2007).
   - **The rays.** Every ray of decision 251's diffuse and specular loops gets `V(d) = V_bvh(d) · [dot(s, d) ≥ sqrt(1 − a)]`.
     - The weights, mixture densities, exclusions, clamps and the zero-denominator rule of decision 251 are unchanged.
     - A ray removed by the cone counts as blocked: its weight stays in the denominator, and the ratio's "blocked" path is taken.
   - **The ends.**
     - `a == 1` returns before the cone test, so the pixel is byte-identical to the kernel before this decision. The threshold-0 test would give the same result.
     - `a == 0` blocks every ray, so the ratio is exactly 0 wherever the denominator is valid.
   - **What it gives.**
     - Diffuse AO.
     - Specular occlusion as the intersection of the cone with the sampled lobe, so it depends on view and roughness (the principle of Jimenez et al. 2016; the per-ray form is UzPainter's adaptation).
     - Micro-shadows: in a low-`a` groove the environment's bright regions at grazing angles to `s` are blocked, and light along `s` passes.
     - No new rays.
   - **Declared biases.**
     - The cone is symmetric and centred on `s`, while real occluders are not. It assumes where the occluders are; it does not recover them.
     - The calibration `sin²α = a` holds only for the cosine measure under uniform light. Facet clipping and the actual environment move it.
     - The bake's own settings (cage, maximum ray distance, high-poly normals) differ from the BVH's unbounded rays on the low-poly.

4. **Combination with decision 251, and what is not added.**
   - **Per direction, not per scalar.** The cone and the BVH meet per ray. A direction both block is removed once. The bake's low-poly-scale occlusion is not divided out, so where the low-poly blocks directions outside the cone (one-sided occluders) the darkening counts twice. That residual is declared and measured (Consequences).
   - **No cavity term.** No cavity from the normal's divergence or from the Height, and no Curvature mesh map. A cavity term needs its own decision, with analytic fixtures, texel-density normalisation and a bound Curvature mesh map as its source.
   - **No horizon or specular-occlusion formula.** No separate horizon-occlusion term, no separate specular-occlusion fit, and no punctual-light micro-shadow formula. The cone and decisions 251 and 256 cover these for the present preview.

5. **Declared, not silent.**
   - **The digest.** The capture receipt gains an `occlusion` record inside `render_state_digest`, like decision 251's `visibility`, and null for the diagnostic modes:
     - `model: "aperture_cone"`;
     - `ao_source: "mesh_map" | "none"` per texture set, with the SHA-256 of the bound AO image;
     - `ao_strength: 1.0`;
     - `ao_channel: "not_applied"`;
     - `cone_axis: "shading_normal_after_fade"`;
     - `cavity: null`;
     - `painted_occlusion: "may_compound"`.
   - **Schema and state.** `src/python/capture-receipt.schema.json` follows. `render.display.state()` reports `ao_strength` and `ao_channel` read-only.
   - **Notes and docs.** The capability notes of `uzpainter.render.capture` and `uzpainter.render.display.state` say so. `src/preview/PREVIEW.md` and 07 §6 (the list of approximations, with the biases of item 3) follow.
   - **Kernel key.** The kernel key changes.

6. **What would pin each parameter later.**

   | Parameter | Value now | What could settle it |
   |---|---|---|
   | Whether AO darkens Iray's shading, and with which input and mix | not applied in `painter_iray`; applied in the preview by this decision | phase3.5 item 3.3's factorial Iray Save Render (decision 251 item 5); a positive result goes to `painter_iray` first, and the preview follows by a new decision |
   | AO strength `s` | 1.0, UzPainter's | the same recording, if Iray applies AO with a fitted strength; a new decision then adopts it or keeps 1.0 |
   | AO channel and its Multiply/Replace mix | not applied | the same recording, plus decision 131's `AO_Mixed` fit (phase3.2, Unreal packed preset) |
   | Cone model and its axis | hard cone, `sin²α = a`, shading normal | none: no Painter or Iray counterpart is a target; UzPainter's own preview choice |
   | Cavity | none | none; a later decision with analytic fixtures and a Curvature mesh map |
   | Horizon term | none | none; only a demonstrated defect reopens it |

7. **Sources and clean room.**
   - **New rows first.** Before any code, the implementing item adds rows to `docs/approved-sources.md` with a clean-room review, each separating the published method from UzPainter's adaptation:
     - Oat and Sander 2007, *Ambient Aperture Lighting*, Proc. I3D 2007: the visibility cone and its solid-angle relation.
     - Jimenez, Wu, Pesce and Jarabo 2016, *Practical Real-Time Strategies for Accurate Indirect Occlusion*, SIGGRAPH 2016 course *Physically Based Shading in Theory and Practice*: the principle of specular occlusion as a cone and lobe intersection. Its GTAO screen-space method is not used.
     - S-GLTF's cleared scope extended to the occlusion strength formula.
   - **Nothing from Painter or Iray.** Nothing comes from Painter's shader library (Q-SHADERS, Q-SHADERDOC), its MDL files or any description of Iray (Q-IRAY). The JavaScript documentation was used only for the two names in the Context table. The custom-shader sample was not read past its parameter label.

8. **Owner.**
   - **The task.** The work is a new item 2.5 of `phase2.3_realtime-preview`, built on branch `wt/viewport-ao` (worktree `E:\UzmiGames\UzPainter-wt\aocav`). This commit records the decision only; the implementing agent adds item 2.5 to `tasks.md`.
   - **The gate.** Like item 2.4, it is preview quality and leaves the DAG gate and G2 unchanged.
   - **Owner actions.** None. The phase3.5 item 3.3 recording is a Painter recording at the owner's UI and is not needed for item 2.5.

## Alternatives Considered

- **Keep the AO map unapplied (decision 251 item 5 as written).** Rejected for the preview. The owner's request and BAK-08 both want the AO map in the preview, and the preview makes no parity claim. `painter_iray` keeps waiting for the recording.
- **Scalar combination:**
  - `diffuse · min(R_d, a)`;
  - `specular · min(R_s, SO(a, n·v, roughness))` with Lagarde and de Rousiers 2014's fit;
  - the Brinck–Maximov 2016 / Chan 2018 punctual-light micro-shadow `saturate(|n·l| + 2a² − 1)`.
  
  Rejected. The viewport has no punctual light. Applied to environment samples, that formula gives about 0.21 at `a = 0.5` under uniform light (cosine-weighted mean, checked by the panel). Scalar `min` cannot give directional micro-shadows.
- **A smooth cone edge.** Rejected. It needs a calibrated band constant, and it breaks byte identity at `a = 1` unless that case is special-cased.
- **Dividing out the low-poly occlusion (`a / A_low`).** Rejected; see C4.
- **A cavity term from the normal's divergence.** Rejected for now; see C5.
- **A settable AO strength.** Rejected under decision 042's fixed pipeline.

## Consequences

The evidence for item 2.5. These are UzPainter-against-UzPainter checks, never parity:

- **Negative control.** The three convex goldens have no AO mesh map, so `a = 1`. They keep their display and linear bytes, compared pixel by pixel against the previous kernel's renders before the old keys are removed (decisions 163, 178, 256). A separate case asserts that `a == 1` takes the early return and that the threshold-0 cone passes every kept ray.
- **Endpoints.** On an open plane with a constant AO map, `a = 0` gives an exact 0 on every valid pixel.
- **Calibration.** On an open plane under a uniform environment, with a constant AO map at `a` ∈ {0.25, 0.5, 0.75}, the 1024-ray render of the same estimator gives a diffuse ratio within 0.01 of `a`. The 128-ray render stays within the RMSE bound decision 251 measured against that reference. The bound is stated in the test, never loosened silently.
- **Directional.** Under a two-region environment, a grazing bright region is blocked at low `a` and a normal-incidence one is kept. A grazing-view case covers decision 256's fade.
- **Specular occlusion.** On a metal plane with a constant `a < 1`, the specular ratio is monotonic in roughness and in view angle, against a 1024-ray reference.
- **Overlap, reported, not a pass condition.** On a concave fixture whose AO map is its own bake (UzmiGames-authored, generated by the test), and on fixtures with partial and with disjoint blockers, the test reports the ratio under BVH only, cone only and both, as the measured size of the declared double darkening.
- **Inputs.**
  - A set with an `AO` channel and no AO mesh map reads 1, and its receipt says `ao_channel: "not_applied"`.
  - Mirrored and scaled UVs sample the map like the other slots.
  - Island edges add nothing beyond the bake's own content.
- **Receipt.** The `occlusion` record, the schema and the kernel key are as in item 5.
- **The Wand, for the owner's eye.** Captures before and after, under the owner's state and the four planned views, as preview evidence only and not a gate. A close crop of the leather wraps and the ring grooves is included.
- **Time.** At the window's default size (660 × 600, Debug) and at 1700 × 1250 on the RTX 4090 with 128 and 64 rays, the frame time before and after is reported. The window size stays within the 200 ms cadence. The AO slot's upload is cached with the other material maps and rebuilt only when the revision changes.

## Amendment at implementation (phase2.3 item 2.5, 2026-10-13)

The implementing item changed two parts of this decision and found three of its Consequences untrue as first built. The coordinator rules on the amendment; it may renumber it as its own decision. Model panel, one round (cx/gpt-6-astra, kimi/k3, xai/grok-4.5; dossier `aofix/panel/dossier.md` in scratch): GPT AGREE on C2 and C6 and PARTLY on the rest, Kimi and Grok AGREE on all six.

### A1. The hard cone of items 3 and 4 is replaced by a cosine-power weight

- **Defects found by review, deterministic.** On the Wand, view 02, the hard cone produced (1) a torn, near-black smear with ragged tendrils on the tip-side ferrule: a smooth metal's narrow lobe sits just outside the cone, the normal map moves it in and out, and the specular ratio becomes a step of the shading normal; and (2) AO darkening on the last leather wrap that ends in a straight line along a triangle edge: the cone puts all of its occlusion near the horizon of the shading normal, exactly the band that decision 251's facet clip removes differently on each side of an edge. Both are in (1024, 1024) renders too, so they are not noise. The bake is not the cause: it is smooth there and padded 4 texels beyond every UV island (partly to 8, measured against the rasterised UV layout). The 7075 pixels of view 02 that got brighter were the 256-against-64 specular ray counts sampling differently, not the AO.
- **The change.** A ray of either ratio that no triangle blocks counts with the weight `V_ao(d) = μ^k`, `μ = dot(s, d)` about the faded shading normal and `k = 2(1 − a)/a`. With `t = μ²` uniform under the cosine-weighted measure, its mean is `∫₀¹ t^(k/2) dt = 1/(1 + k/2) = a`: the calibration of item 3 is kept exactly. It has no free constant; `a = 1` still returns before the weight (bit for bit), `a = 0` still removes every ray. A ray weighted below 1 marks the ratio as blocked; its share of the numerator is `V_ao · c`, the denominator is unchanged. The per-direction product with the BVH (item 4) is unchanged.
- **Why this one.** Integrated numerically (uniform light, GGX, two facets tilted ±11.25°, the same shading point), at an 80° view, roughness 0.3 and `a = 0.95`, the two facets' specular ratios were 0.871 / 0.606 with the hard cone, 0.831 / 0.637 with the widest linear ramp in `μ²` of the same mean, and 0.897 / 0.868 with the power law. A smooth band about the hard threshold keeps the occlusion at the horizon and needs a width constant (Alternatives, "A smooth cone edge"). In the re-rendered views neither defect remains.
- **What it costs, declared (GPT's correction).** A mirror lobe at view angle `θ` keeps `cos^k θ` rather than all or nothing, so the specular occlusion is less view-selective than the hard cone's; normal incidence still keeps 1. The weight is continuous but, for `a > 2/3` (`k < 1`), its derivative is unbounded at the horizon (Kimi); its values there are small. The calibration holds over the full, unclipped hemisphere under uniform light only.
- **Names.** The receipt's model is `cosine_power_visibility` (was `aperture_cone`) and its `cone_axis` field is `axis`. P-OAT is cited for the calibration identity only; the power law is UzPainter's construction from it (GPT, Kimi, Grok on C6).

### A2. The specular ray count stays 64

An earlier build traced 256 specular rays wherever `a < 1`, because with the hard cone 64 left a grain on the Wand's leather (view 02's leather wraps, 680 × 400 pixels: high-pass RMS of the linear colour 0.00358 against 0.00279 at (1024, 1024); 99.9th-percentile error 0.027). Re-measured with the weight of A1 (all three panelists asked for it): 0.00270 at (128, 64) against 0.00259 at (1024, 1024), RMSE 0.00082, 99.9th percentile 0.0117. The 256 rays are withdrawn: every hit traces decision 251's (128, 64), and the receipt has no `specular_rays_in_cone`.

### A3. The Consequences, point by point

- **Time: "the window size stays within the 200 ms cadence".** Untrue as first built (236-244 ms with an AO map), and untrue before this decision for any textured asset: with the Wand's four 2048² maps a render took about 590 ms, because every render packed and uploaded every map and the lighting (decision 251's 200 ms was measured without maps). Now met: see the next point. Measured by `uzp-preview-tests viewport-occlusion-time` on the Wand low mesh, Debug, shared RTX 4090, rays (128, 64), four 2048² maps plus a 2048² AO map of 0.5: 721 ms uploading every input, 621 ms building the resident inputs (the first render of a revision), 135 ms from them; four maps without the AO map, 589 / 540 / 107 ms. The case asserts that a render from resident inputs at 660 × 600 fits 200 ms.
- **"The AO slot's upload is cached with the other material maps and rebuilt only when the revision changes".** Untrue as first built: there was no such cache. Now met: `ResidentInputs` (viewport.h) keeps a scene's materials and maps, lighting, display table and BVH on the GPU; the window keeps one for the revision it shows and invalidates it when it takes a new one. Captures upload once per call. Tested: resident renders give the bytes of plain ones, the second reuses the first's buffers, and after `Invalidate` a changed AO map shows.
- **"A separate case asserts that `a == 1` takes the early return and that the threshold-0 cone passes every kept ray".** The first half is asserted bit for bit (every golden fixture and the concave one, colour and both ratios). The second half no longer applies: there is no threshold after A1, and `μ^0 = 1` is never evaluated because `a = 1` returns before the weight.
- **"Island edges add nothing beyond the bake's own content".** Met by construction and asserted indirectly: the slot reads only the bound image's texels through the same bilinear wrap as the other maps, which the mirrored-and-scaled-UV case checks against the CPU's lookup texel for texel; what lies outside a UV island is the bake's own padding. No case builds a bake with islands; the Wand's bake was measured padded 4 texels everywhere (partly to 8), so no sample inside its islands reads an unbaked texel.
- **"A set with an AO channel and no AO mesh map reads 1, and its receipt says `ao_channel: "not_applied"`".** Untested as first built. Now asserted end to end by `test_preview_capture.py::test_viewport_capture_applies_the_ao_mesh_map`: adding an AO channel to the stack changes no byte of the capture and the receipt says source `none` and `not_applied`; binding an 8-bit grey AO image darkens the capture and never brightens a pixel, with the image's SHA-256 in the receipt; binding an RGB image of another size fails with `unsupported_source`.
- **"An AO map never brightens a pixel"** (not in the decision; added): asserted on the concave fixture with its own bake under the shipped environment, colour and both ratios, dielectric and metal.

### A4. Still open

- **Cavities.** The owner asked for cavities. This decision (C5, item 4) adds no cavity term, and that stands: engraved and inlaid details whose AO bake reads close to 1 (the Wand's ferrule inlays, the 'O' emblem, the pommel band grooves) stay flat in the preview. A cavity term needs its own decision with analytic fixtures, texel-density normalisation and a bound Curvature mesh map, which the Wand does not bind. It needs a decision number from the coordinator and a task item; item 2.5 does not claim it.
- **The phase3.5 item 3.3 recording** still decides whether and how Iray applies AO; nothing here depends on it.
