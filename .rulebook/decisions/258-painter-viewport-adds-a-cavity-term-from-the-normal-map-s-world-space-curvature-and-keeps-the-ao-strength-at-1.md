# 258. `painter_viewport` adds a cavity term from the normal map's world-space curvature, and keeps the AO strength at 1

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase2.3_realtime-preview, phase1.25_pilot-wand

## Context

After decisions 251 and 257 the owner asked again: "cadê as cavidades? microshadow? AO bem definido?" ("where are the cavities? micro-shadows? well-defined AO?"). On the Wand the change from decision 257 is small. Over the wand pixels of the four views the mean change is −1.33, −1.44, −0.58 and −1.02 8-bit display codes, and no pixel gets brighter. In the leather-wrap crop of view 02 (680 × 400 px), the linear-luminance ratio after/before is p1 0.725, p5 0.923, p25 0.994 and p50 1.000. Only 3.9 % of its pixels darken by more than 10 %. Decision 257 (C5, A4) left the cavity term out. The owner now asks for it explicitly.

This decision amends decision 257 items 4 and 5 for `painter_viewport` only. `painter_iray` is unchanged. The preview stays never-parity evidence (decisions 018, 148, 212).

### Why the AO reads weak (measured, scratch `cavity/`)

| # | Question | Measurement | Finding |
|---|---|---|---|
| W1 | What does the Wand's AO bake actually hold? | `11-Varinha-Madeira_AO_v1.png` (`1dd1ed01…`, 16-bit grey, 2048²), sampled inside the UV islands rasterised from the low OBJ and eroded by 2 texels (12.2 % of the map). Percentiles p0.1/p1/p5/p25/p50: 0.531/0.656/0.812/0.953/0.984. By the asset's own material masks: leather p5 0.844, p50 1.0 (96.8 % of leather texels ≥ 0.8); leather crease (`M_leather_recess`) p5 0.625, p50 0.828; wood groove p5 0.719, p50 0.922; iron p5 0.656, p50 0.984. The values sit on steps of 1/64. | **The bake is mild.** This is the main cause. |
| W2 | Does decision 257's cosine-power weight lose darkening under `studio-small-09` (decision 212)? | The weight `μ^k`, integrated against the shipped HDRI (1024 × 512 luminance, cosine-weighted, unblocked) for 400 random normals. Irradiance-weighted mean ratios: 0.952/0.903/0.806/0.708/0.609/0.510 for `a` = 0.95/0.9/0.8/0.7/0.6/0.5. That is 97–98 % of the uniform-light darkening `1 − a`. Only the normal that faces the brightest light keeps much more (`a` = 0.6 → 0.80, `a` = 0.8 → 0.91). | Minor: 2–3 % on average. It is larger on surfaces that face the key light. |
| W3 | Is the ratio applied to the right term? | Kernel review (`viewport.hlsl` `main`): `colour = (specular · R_s + diffuse · R_d) · intensity`, where `diffuse` is the irradiance term and `specular` the prefiltered one. Leather is dielectric, so diffuse dominates there. | Wired correctly. |
| W4 | Do exposure or tone mapping compress it? | Exposure 0. The view is OCIO "Default - sRGB", an sRGB encode with no tone curve (PREVIEW.md). At the leather's median linear luminance 0.064 (code 71.6), a linear factor of 0.95/0.9/0.83/0.75/0.6 moves the code by −1.8/−3.7/−6.4/−9.7/−16.4. | The encode roughly halves a relative linear change once it is counted in codes. |
| W5 | Does Painter document a viewport AO intensity default? | The public help page *Shader settings* (https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/shader-settings/shader-settings, A-HELP-GUIDE, retrieved 2026-10-13) documents only undo, shader file, instance name, restore defaults, displacement (source channel, scale unit, scale amount) and tessellation. It says "Shader parameters are dependent of the shader file currently loaded." *Texture Set settings* (`…/using/interface/texture-set/texture-set-settings`, retrieved 2026-10-13) documents only the AO mixing mode between the baked AO and the AO channel: Multiply (the default) or Replace. Neither page documents an AO intensity or strength, nor a default for one. HelpX's copy of the shader page returned 403. The shader-API pages (Q-SHADERDOC) were not opened. | **No documented default** to compare with `s = 1.0`. |
| W6 | Painted occlusion. | The Wand's albedo already carries occlusion painted from the same AO (`M_ao_albedo`, decision 257 §Context; BAK-08). | Part of the crease contrast was already in the "before" image. |

Nothing is mis-wired, so decision 257 owes no bug fix. The weak look comes from a mild bake (W1), the sRGB encode (W4) and the painted occlusion already in the albedo (W6). The directional weight accounts for only a small part of it (W2).

### Cavity sources without new bakes

- **Curvature mesh map.** The Wand binds none (decision 257 §Context). A curvature bake is not available without new bakes.
- **Height.** The Wand's painted Height is flat except the iron dimples (−0.003). It already enters the combined `Normal_OpenGL` as bump (decision 257 item 2), so it is not a separate source of crease detail.
- **The normal map.** The combined normal is the only input that carries the sharp detail.
  - **The measure.** Its slope field `s = (−n.x/n.z, −n.y/n.z)` has a divergence: the Laplacian of the height the normal map implies, positive where the surface is concave. Measured per texel inside the islands, on the baked input normal (8-bit, `071a7123…`): p1 −0.398, p5 −0.172, p50 −0.004, p95 0.227, p99 0.630, p99.9 1.55.
  - **By mask (p50/p90/p99).** Leather crease 0.194/0.734/1.50; wood groove 0.137/0.283/0.515.
  - **What it shows.** It draws crisp lines along the wrap edges, the rivet rings, the band grooves and the wood grain, where the AO is broad and soft. That includes engraved details whose AO reads close to 1. Inside the leather its correlation with `1 − ao` is only 0.29, so it is mostly information the AO does not hold.
  - **Steep slopes.** Only 0.08 % of island texels have `n.z < 0.3`.
- **Texel density on the Wand.** The world length per texel, area-weighted, is p5/p50/p95 = 0.165/0.171/0.182 mm: nearly uniform. The mesh spans 0.34 units along its length, metres at the asset's real size.

### Model panel (one round; cx/gpt-6-astra, kimi/k3, xai/grok-4.5)

The dossier is in scratch (`cavity/panel/dossier.md`). `kimi/kimi-k3` returned 503, so the same dossier went to `kimi/k3` on the same router, streamed.

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 The diagnosis W1–W4; nothing mis-wired, no bug fix owed for decision 257 | PARTLY | AGREE | AGREE |
| C2 `s` stays 1.0; no exponent or contrast curve on the AO map (alternative: `ao^2`) | AGREE | PARTLY | AGREE |
| C3 Cavity from the combined normal's slope divergence, four extra bilinear samples, mirror-invariant | PARTLY | PARTLY | AGREE |
| C4 Texel-density normalisation by the hit triangle's UV Jacobian, radius `R · t_set` (alternative: a fixed world radius, 0.25 mm) | DISAGREE | PARTLY | AGREE |
| C5 `a_cav = 1/(1 + x)`, `R = 1`, difference spacing from the pixel footprint | PARTLY | PARTLY | PARTLY |
| C6 `a = a_ao · a_cav` into decision 257's weight (alternative: `min`) | PARTLY | PARTLY | AGREE |
| C7 Receipt record and tests | PARTLY | PARTLY | AGREE |

**Adopted:**

- **C1 (all three; GPT's narrowing).**
  - W2's 2–3 % is an average over normals, not a bound for every hit.
  - W4 concerns relative code changes.
  - Kimi added the third attenuator, W6.
- **C2 (GPT, Grok; Kimi's correction).**
  - `s` stays 1.0, and no exponent is applied.
  - The glTF range [0, 1] constrains the strength multiplier only. It is not an argument against an exponent (Kimi, GPT).
  - An exponent is rejected because it is an unsourced stylisation that re-crushes the soft low-frequency bake. The definition the owner asks for comes from the high-frequency cavity term (all three).
- **C3: adopted with GPT's and Kimi's corrections.**
  - **Full Jacobian.** MikkTSpace's tangent and bitangent are orthonormalised shading axes, not `dP/du` and `dP/dv` in general (GPT). So the derivatives are mapped into the shading frame through the hit triangle's full 2 × 2 UV Jacobian, not by dividing by two axis lengths (item 3). This also handles shear, rotated frames and mirroring.
  - **Slope clamp.** `n.z` is clamped at 0.3 before the slopes are formed (Kimi), so the slopes stay bounded where the creases are steep.
  - **Not physical.** The public sources motivate curvature-driven darkening. They do not make it physical visibility. The estimator and the mapping are UzPainter's constructions (GPT).
- **C4: a fixed world radius (GPT and Kimi; Grok preferred `R · t_set`).**
  - A radius in texels of the set (`R · t_set`) halves the world radius when the map's resolution doubles. That would contradict C7's own two-resolution test (Kimi, GPT).
  - The radius is `r = 0.25 mm`, in mesh units read as metres (the glTF unit, and the Wand's real size). An asset authored in other units gets a scaled look, which is declared in the receipt.
  - On the Wand, `r` is 1.46 median texels.
- **C5: the mapping, with changes.**
  - **The mapping.** `a_cav = 1/(1 + x)` is kept (all three).
  - **The strength.** `R = 1` is replaced by C4's `r = 0.25 mm`. Kimi asked for less (0.5 texels), Grok for more (2 texels); GPT called any value an artistic calibration. 1.46 texels on the Wand lies between the two.
  - **The spacing.** The difference spacing is separated from the radius (GPT). It comes from per-axis ray differentials (Igehy 1999), not from a single isotropic spread (Kimi, GPT).
  - **Aliasing.** Wider spacing reduces aliasing but does not prefilter, because the maps have no mips (GPT). The residual is declared and measured.
  - **Neutral path.** It is explicit (GPT): no normal map, or `κ ≤ 0`, gives exactly 1.
- **C6: the product (Kimi and Grok against `min`; GPT accepts it declared).**
  - `min` would drop the cavity wherever the bake is darker, the very detail asked for.
  - The overlap is declared as an artistic overlap, not as scale separation (GPT). The stack is three layers: the painted albedo occlusion, the AO map and the cavity (Kimi).
- **C7 (all three, with GPT's and Kimi's additions).**
  - The receipt states the estimator, the frame convention, the clamp, the spacing rule, the radius and its unit basis, and a version.
  - The tests add sheared and rotated UVs, seams, steep slopes (`n.z < 0.5`), the neutral bypass, stated tolerances, and a time percentile on a named GPU and window size.

**Not adopted:**

- **The `ao^2` exponent (C2).** Rejected as the solution. It is not illegal, but the cavity term supplies the missing definition.
- **Prefiltered slope or curvature data (GPT, C5).** The preview's maps have no mip chain. Building one belongs to a later decision. The residual aliasing is measured instead (Consequences).
- **Band separation before the product (GPT, C6).** It needs a frequency split of the bake that has no source. The overlap is declared instead.
- **A seam and stability regression gate on the Wand (GPT, C7).** The Wand renders stay for the owner's eye and are not a gate (decisions 251, 257). The analytic fixtures carry the gates.

### Review of the first implementation (second panel round)

A 3D-artist and a clean-room review of the first implementation's Wand renders raised four points. Each was measured in the worktree (scratch `cavity/r2/`) and put to one panel round (dossier `cavity/r2/panel/dossier.md`; the same three models).

| # | Point | Measured | Panel (GPT / Kimi / Grok) | Outcome |
|---|---|---|---|---|
| R1 | Metal grooves barely change | The specular lobe is centred on the view reflected about the shading normal, so `μ` there is about `n·v`: seen head-on `μ^k` stays near 1 for any `a`, and metal has no diffuse term. On view 02, where `a_cav < 0.8`, the iron pommel's median luminance ratio against the pass without the cavity was 0.677 with `a_cav` 0.642; the leather's was 0.570, darker than `a_cav` (0.656), because the weight removes its grazing light. | Fix the specular term with a plain multiplier, and leave how the AO map reaches it to decision 257: PARTLY / AGREE / AGREE. GPT: the multiplier is accessibility, not derived visibility, and a mean equal to `a` on diffuse is not guaranteed under a real HDRI. | Implemented first as a plain multiplier on the whole colour. That lightened the leather creases from 0.570 to 0.667, which bore out GPT's caveat. The shipped form keeps `a = a_ao · a_cav` in the weight and takes the specular ratio as the lesser of the weighted one and `a_cav` times the ratio without the cavity (item 5). |
| R2 | No contact AO at the part joins | The diffuse ratio alone (a diagnostic render) falls to 0.50-0.75 on the pommel's bevel and to 0.91-0.96 on the leather within about 2 mm of it. The low mesh (626 vertices) steps from radius 13.0 to 11.6 mm over 1 mm along the axis: a 1.4 mm bevel at about 55°. The other joins are similar, and the AO bake there is at least 0.9. | The contact term is computed and is mild because the geometry is; a stronger band would be an unsourced exaggeration and a new decision: PARTLY / AGREE / AGREE. GPT asked for the specular side as well, which R1 covers. | No change. Decision 251's rays and decision 257's bake produce the joins' shading; this decision adds only the normal map's cavity. |
| R3 | Hard to see at normal viewing distance | The 1920 × 1080 views have a footprint of about one texel (0.16 mm per pixel, 0.17 mm per texel), so the first version's minification loss did not act there. The reviewer judged 2 × downscaled images. At the window's default 660 × 600 a pixel spans several texels, and there the first version computed `f(E[κ])`: on the analytic far groove `a_cav` kept 60 % of a supersampled reference's high-pass energy (0.064 against 0.107), because a crease cancelled against its convex shoulders. | Box-filter `a_cav` over up to 3 × 3 points of the footprint: PARTLY / AGREE / AGREE. Keep `r` a decision constant and render the window's size for the owner: AGREE ×3. Kimi: state the test bounds before measuring. | Implemented (item 4): 94 % of the energy and 85 % of the mean darkening, against a lower bound of three quarters stated before the measurement. Owner renders at 660 × 600 added. |
| R4 | This record did not state the radius's unit rule | The code converts the radius to 0.025 scene units where the mesh states its unit, and the receipt then says `radius_unit: "metre"`. | AGREE ×3 (GPT: say that `metre` names the physical radius, not the scene-unit number). | Items 4, 6 and 7 amended. |

## Decision

1. **Diagnosis recorded, AO strength unchanged.**
   - Decision 257 is correctly wired (W3).
   - The Wand's AO reads weak because its bake is mild (W1), the sRGB encode halves relative changes in codes (W4), and the albedo already carries painted occlusion (W6). The directional weight costs 2–3 % on average (W2).
   - `s` stays 1.0. No exponent or contrast curve is applied to the AO map.
   - Painter's public help documents no AO intensity default (W5), so nothing documented contradicts 1.0.

2. **Source.** The cavity comes from the normal slot, the evaluated combined `Normal_OpenGL`, which holds the baked detail and the painted Height as bump.
   - No Curvature or Height mesh map is read, and no new bake or new slot is added.
   - Height is not applied as geometry, because displacement stays pinned at 0 (decision 042).

3. **Estimator: world-space curvature of the implied height field, per hit.**
   - **Slopes.** From the tangent-space normal `tn`: `s = (−tn.x, −tn.y) / max(tn.z, 0.3)`, along the shading tangent `T` and bitangent `B` the pass decodes with.
   - **Samples.** Four bilinear samples of the normal slot per point, at `± (g_u/W, 0)` and `± (0, g_v/H)` about it, where `W × H` is the map size and `g` the tap spacing of item 4. They give, by central differences in texel units, `D = [[∂s_T/∂u, ∂s_T/∂v], [∂s_B/∂u, ∂s_B/∂v]]`.
   - **Jacobian.** `J = [[T·P_u/W, T·P_v/H], [B·P_u/W, B·P_v/H]]` is the world length per texel step, projected on `T` and `B`. `P_u` and `P_v` are the hit triangle's `dP/du` and `dP/dv`, solved from its corner positions and uvs.
   - **Curvature.** `κ = trace(J⁻¹ · D)`, the divergence of the slope field per world length, positive where concave. It is invariant to mirroring, scaling, shear and rotation of the UV layout. Where `|det J|` is degenerate (a zero-area UV triangle), the cavity is 1.
   - **Declared biases.**
     - The frame is taken as constant across the taps.
     - A normal map need not be the gradient of a height field (it may not be integrable).
     - `κ` is the Laplacian, twice the mean curvature only for small slopes.
     - The clamp at `n.z = 0.3` limits slopes to about 73°.

4. **Mapping, radius and spacing.**
   - **Mapping.** `x = r · max(0, κ)` and `1/(1 + x)` per point; `a_cav` is the mean over the footprint's points (spacing, below).
   - **Radius.** `r = 0.25 mm`, a physical length. Where the mesh states no unit (an OBJ without a mesh unit scale, as the Wand is), the mesh unit is read as the metre and `r` is `2.5e-4` scene units. Where the file states its unit or a mesh unit scale is given, the scene is in centimetres (`units.scale_to_internal`) and `r` is `0.025` scene units. It is UzPainter's provisional preview default: a fixed constant that changes only by a decision, and is reported read-only like `s`.
   - **Neutral path.** Exact, with no sampling where there is nothing to do:
     - with no normal map, `a_cav = 1`;
     - with `κ ≤ 0` at every point, `a_cav = 1`;
     - with `a_cav = 1` the weight is unchanged, the specular multiplier of item 5 is exactly 1 and its two ratios are equal, so the pixel is the pass's without the cavity bit for bit.
   - **Spacing.** The footprint `h_u = max(1, W · max(|∂u/∂x|, |∂u/∂y|))`, and `h_v` likewise, from the primary ray's differentials transferred to the hit (Igehy 1999). Under orthographic projection the pixel's world size is used. It is covered by `n = min(⌈h⌉, 3)` points per axis, centred on the hit and spread over `h − g`, with tap spacing `g = max(1, h/n)`; `h ≤ 1` is one point with `g = 1`. At most 9 points and 36 taps. `a_cav` is thus a box filter of the cavity, not the cavity of a box-filtered `κ`, so a crease and its convex shoulders in one footprint do not cancel (R3). Beyond 3 texels per axis the spacing grows; aliasing is reduced, not removed, because the maps have no mips.
   - **On the Wand.** Measured on the baked input normal: `r` is 1.46 median texels. `a_cav` inside the islands is p1 0.52 and p5 0.75, with 14.1 % of texels below 0.9. Leather crease p5/p50: `a_cav` 0.414/0.777, `ao · a_cav` 0.316/0.673. Whole leather p5: 0.801 and 0.699.

5. **Combination.** `a = a_ao · a_cav`, with `a_ao = 1 + s (ao − 1)`, feeds decision 257's cosine-power weight unchanged.
   - The cavity therefore darkens diffuse and specular through the same directional model, with no new rays. In a crease, grazing light is lost first and light along the normal stays: these are the micro-shadows.
   - **Specular (R1).** The specular ratio is `min(a_cav · R_s(a_ao), R_s(a_ao · a_cav))`, both sums over the same rays and occlusion tests. Seen head-on, the lobe sits on the weight's axis and keeps a weight near 1, so a metal groove facing the viewer would keep its full reflection; the plain multiplier (accessibility shading, Miller 1994) darkens it by `a_cav`, and at grazing views the weighted ratio, which is darker, stays. The lesser of the two is UzPainter's construction. It never brightens a pixel. On view 02, where `a_cav < 0.8`, the median luminance ratio is 0.627 on the iron pommel (0.677 with the weight alone), 0.595 on the ferrule (0.642) and 0.566 on the leather (0.570).
   - **Declared overlap.** Where the bake already darkens a crease, the product darkens it again. On assets like the Wand, the albedo's painted occlusion adds a third layer. This is an artistic overlap, not scale separation, and the receipt names it.

6. **Declared, not silent.**
   - **The receipt.** `occlusion.cavity` (null since decision 257) becomes:
     - `model: "normal_divergence"`;
     - `version: 1`;
     - `source: "normal_slot"`;
     - `estimator: "central_difference_4tap_uv_jacobian"` (per point);
     - `slope_nz_min: 0.3`;
     - `radius: 0.00025`;
     - `radius_unit`: `"mesh_unit_as_metre"` where the mesh states no unit, `"metre"` where the scene unit is known; `radius` is the physical radius in metres in both;
     - `mapping: "1/(1+r*max(0,kappa))"`;
     - `combine: "weight_product_and_specular_min"`;
     - `spacing: "footprint_grid_up_to_3x3_min_1_texel"`;
     - `stacks_with: ["ao_mesh_map", "painted_albedo_occlusion"]`.

     It stays null for the diagnostic output modes. `ao_strength` stays 1.0, and `painted_occlusion: "may_compound"` stays.
   - **Schema, state and docs.**
     - `src/python/capture-receipt.schema.json` follows.
     - `render.display.state()` reports `cavity_radius` read-only.
     - The capability notes of `uzpainter.render.capture` and `uzpainter.render.display.state` follow, and so do `src/preview/PREVIEW.md` and 07 §6 (the approximations list, with the biases of item 3).
   - **Kernel key.** The kernel key changes.

7. **What would pin each parameter later.**

   | Parameter | Value now | What could settle it |
   |---|---|---|
   | AO strength `s` | 1.0 | Unchanged from decision 257: phase3.5 item 3.3's recording informs a new decision |
   | AO exponent | none | Nothing; only a new decision |
   | Cavity radius `r` | 0.25 mm: 0.00025 scene units where the mesh states no unit (read as metres), 0.025 where the scene is in centimetres | The owner's eye on the Wand renders (1920 × 1080 and the window's 660 × 600), then a new decision; no Painter or Iray counterpart is a target |
   | Mapping, clamp, spacing, specular combination | `1/(1 + x)`, 0.3, up to 3 × 3 footprint points, the lesser specular ratio | None: these are UzPainter's preview choices |
   | Prefiltered normal or curvature | none | A later decision that adds mips to the preview's maps |

8. **Sources and clean room.**
   - **New rows first.** Before any code, the implementing item adds rows to `docs/approved-sources.md`, each separating the published method from UzPainter's adaptation:
     - Miller 1994, *Efficient Algorithms for Local and Global Accessibility Shading*, Proc. SIGGRAPH 94: accessibility falls as concavity grows, relative to a probe radius.
     - Vergne, Pacanowski, Barla, Granier and Schlick 2010, *Radiance Scaling for Versatile Surface Enhancement*, Proc. I3D 2010: curvature-driven shading of surface detail.
     - Igehy 1999, *Tracing Ray Differentials*, Proc. SIGGRAPH 99: the footprint of a pixel's ray at the hit.
     - The divergence of a height field's gradient as its Laplacian is textbook calculus and needs no row.
   - **The help pages.** The two help pages of W5 are used under A-HELP-GUIDE only for the absence of a documented AO default.
   - **Nothing from Painter or Iray.** Nothing comes from Painter's shader library or shader documentation (Q-SHADERS, Q-SHADERDOC), its MDL files, or any description of Iray (Q-IRAY).

9. **Owner.**
   - **The task.** The work is a new item 2.6 of `phase2.3_realtime-preview`, on branch `wt/viewport-cavity` (worktree `E:\UzmiGames\UzPainter-wt\cavity`). This commit records the decision only; the implementing agent adds item 2.6 to `tasks.md`.
   - **The gate.** Like items 2.4 and 2.5, it is preview quality. It leaves the DAG gate and G2 unchanged.
   - **Owner actions.** None are required. The owner judges `r` on the Wand renders; a change needs a new decision.

## Alternatives Considered

- **Raise the AO strength above 1, or apply `ao^γ`.**
  - `s > 1` leaves glTF's range and clips every `ao < 1 − 1/s` to 0.
  - `γ = 2` is an unsourced stylisation that crushes the soft bake without adding its missing sharp detail.
  - Rejected (C2).
- **A radius in texels of the set (`R · t_set`).** Rejected (C4). It ties the look to the map's resolution.
- **`min(a_ao, a_cav)`.** Rejected (C6). It drops the cavity where the bake is darker.
- **A screen-space cavity from the depth or normal buffer.** It is view-dependent and changes with zoom, and the pass shades one ray per pixel with no neighbour buffer. Not raised by the panel; not adopted.
- **A CPU-derived cavity map per revision, sampled like the AO slot.** It would need texel density per texel, which is ambiguous where mirrored islands overlap, and a sixth slot. The per-hit form uses the hit triangle's own Jacobian. Not adopted.
- **Horizon mapping from a height field integrated from the normal (Max 1988).** It needs a Poisson integration per island and a horizon table. That is a bake, out of scope for a cavity term. Not adopted.

## Consequences

The evidence for item 2.6. These are UzPainter-against-UzPainter checks, never parity:

- **Neutral path.** The three convex goldens keep their display and linear bytes. Where a fixture binds no normal map, the cavity code is not entered (asserted). A flat normal map and a purely convex analytic normal map change no byte where every tap lies on the flat or convex region.
- **Analytic curvature.**
  - On a plane with a normal map generated from a cylindrical and from a sinusoidal groove (UzmiGames-authored, generated by the test), `κ` matches the closed-form Laplacian within a stated bound.
  - Steep-slope cases (`n.z < 0.5`) are covered, and the clamp at 0.3 is checked.
- **Invariance.** The same world geometry at two map resolutions and at two texel densities gives the same `a_cav` within the stated bound, and so do mirrored, sheared and rotated UVs. Across a UV seam, the two sides agree within the bound.
- **Monotone.** The cavity never brightens a pixel. With `a_cav < 1`, the colour and both ratios are at most their values without it, on dielectric and metal, and a metal's colour is at most its value without the cavity times `a_cav` (within the binary16 rounding).
- **Mapping.** `a_cav` equals the footprint's mean of `1/(1 + r·max(0, h''))`, formed by the test from the closed form, within `r` times the `κ` bound plus 0.002.
- **Minification.** A far camera on the analytic groove keeps the high-pass energy of the cavity factor within twice (plus 0.005) that of a supersampled reference, and at least three quarters of its energy and of its mean darkening.
- **Receipt.** The `cavity` record, the schema, the read-only `cavity_radius` in `state()` and the kernel key are as in item 6.
- **Time.** At 660 × 600 and at 1700 × 1250 on the RTX 4090 (Debug, rays (128, 64), the Wand's five 2048² maps, resident inputs), the frame time is reported as median and p95. The window size stays within the 200 ms cadence.
- **The Wand, for the owner's eye.** Before and after captures under the owner's state and the four views, and three views at the window's 660 × 600, as preview evidence only and not a gate. The crops include the leather wraps, the ferrule inlays, the 'O' emblem and the pommel grooves.
