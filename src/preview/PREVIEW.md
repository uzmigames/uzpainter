# Preview viewport and window (`src/preview/`)

This folder holds `painter_viewport`, the realtime preview of `docs/architecture/07-preview-and-render-parity.md` §1, §5 and §6 (task `phase2.1_preview-viewport-window`; decisions 018, 042 and 134), and the scene its captures render (task `phase2.2_preview-capture`, decision 148). It is a preview and a fast check. It is never the parity target and never acceptance evidence: Iray is the target, through `painter_iray` in Phase 3.

| File | What it does |
|---|---|
| `display_transform.{h,cpp}` | The one display configuration and its transform (item 2.3) |
| `environment.{h,cpp}` | Environment decoding and the image-based-lighting precomputation (item 2.1) |
| `viewport.{h,cpp}`, `shaders/viewport.hlsl` | The forward pass on the render layer (item 2.2) |
| `visibility.{h,cpp}` | The BVH the pass's self-occlusion rays are traced through (decision 251) |
| `latest.h` | The wait-free hand-over between evaluation and the preview thread (item 2.4) |
| `preview.{h,cpp}` | The publisher side, the preview thread and its window (items 2.4 and 2.5) |
| `evaluation.{h,cpp}` | The evaluation of a revision's frame (`EvaluateFrame`) and the attached preview's evaluation thread (`AttachedEvaluation`, decision 248) |
| `cli.{h,cpp}` | `UzPainter.exe --preview <file.uzp>` (item 2.5) |
| `scene.cpp` | The viewport scene of a frame (`SceneOf`, `MaterialsOf`, `ChannelFor`), shared by the window and the captures |

## Display transform (decision 134)

The only supported configuration is `{mode "ocio", config SHA-256 15059d4b…, view "Default - sRGB"}`. That hash identifies Painter's substance config; the constant is the display presets' pin (`src/python/display.h`). The project's colour-management mode decides Legacy or OCIO. The window reads the view, the config pin (when the project's colour management records no hash) and the active preset's clear colour from the display state of the display presets (`python::display::PresetOf`, decision 132). Painter itself does not save the view with the project. Any other configuration fails before any GPU work. The error reads `unsupported_configuration: <what differs> is pinned out of the display transform (decision 038)`. It covers Legacy with tone mapping `Linear` or `ACES`, ACE mode, another mode, OCIO without a hash or with another one, and another view.

The transform is the calibrated model of the view (`parity/semantics/iray.json` `display-encoding`):

```
code = round(65535 · encode(binary16(clamp(L, 0, 1))))
```

`encode` is the IEC 61966-2-1 encoding. `DisplayTable()` holds the code of each of the 65 536 binary16 patterns, computed in double. The shader rounds to binary16 (`RoundToHalf`, ties to even) and looks up the same table, so GPU codes equal CPU codes. NaN and negative values give 0; values above 1 give 65535. OpenColorIO is not linked, and Painter's config file is never read.

## Lighting (item 2.1)

The environment is equirectangular, with row 0 at +Y. It uses the direction mapping of `iray.json` `environment-mapping`: `u = frac(atan2(-d.x, d.z) / 2π + 1/4 + rotation / 360)`, `v = acos(d.y) / π`. OpenEXR (tinyexr) and Radiance HDR files are read. `PrecomputeLighting` builds three things, deterministically on the CPU:

- **SH irradiance** (Ramamoorthi and Hanrahan 2001): nine coefficients, already convolved with the clamped cosine.
- **Prefiltered radiance** (Karis 2013): six GGX levels from 512 × 256 down to 16 × 8, roughness 0 to 1, 256 Hammersley samples per texel. Each level integrates the area-resampled copy at twice its own resolution.
- **Albedo table**, 32 × 32, over (n·v, roughness):
  - `A` and `B` of the split sum, with the height-correlated Smith masking (Heitz 2014) and Schlick's Fresnel;
  - `D`, the albedo of Burley's diffuse lobe (2012).
- **Importance distribution** (decision 251), over the 512 × 256 level-0 radiance: a piecewise-constant 2D distribution (Pharr, Jakob and Humphreys, PBRT 4th ed., `PiecewiseConstant2D`). Each texel weighs the mean of its three channels times `sin θ` at its centre, so no channel's light has zero probability. An environment without light gets the uniform distribution over the sphere. The CDFs are summed in double and stored as float. The self-occlusion rays sample it.

`LightingOf` keeps the result across processes in the `lighting` area of the persistent caches (`src/render/disk_cache.h`, decision 253), keyed by the environment file's SHA-256 (of bytes the caller checked against it), the sampling constants, the build fingerprint and the MXCSR control bits; every float is stored bit for bit, and a hit skips the decode as well. The importance distribution of the visibility rays (decision 251) is not stored: it is a function of level 0 alone, so a hit rebuilds it, bit for bit. Rotation and exposure apply at shading time, so they are not part of the key. It saves 1.0-1.3 s of every capture and preview start (`uzp-preview-tests lighting-cache`).

## Pass (item 2.2)

One compute dispatch per frame on the render layer (`src/render/`):

1. **Visibility.** The CPU bins the triangles into 16 × 16-pixel tiles. Each pixel casts its centre ray against its tile's triangles in ascending order. Coverage is watertight (decision 178): the edge functions of Woop, Benthin and Wald (2013) on the ray-sheared corners decide it, so a ray on an edge shared by two triangles never misses both. The depth and barycentrics of a covering triangle are Möller-Trumbore's. The nearest hit wins; on a tie the lowest index wins. Both faces are visible.
2. **Material.** The default open-pbr instance (decision 042) supplies base colour, base metalness, specular roughness and the tangent-space normal. The normal is the project's combined `Normal_OpenGL` map, which carries height as bump. A fifth input, `occlusion`, is the texture set's AO mesh map (decision 257, under 5). Each map is sampled bilinearly with wrapping. A channel with no map uses open-pbr's default: base colour 0.8, metalness 0, specular roughness 0.3, a flat normal; a set without an AO mesh map reads 1. Emission (luminance 0) and opacity are off, as in the Iray fits.
3. **Normals.** The MikkTSpace frame of the interpolated corner frame. The shading normal then fades toward the interpolated normal as the view's mirror reflection about it sinks toward the geometric tangent plane (decision 256). The shading and geometric normals define different hemispheres, a mismatch that must be handled with care (*Physically Based Rendering*, 4th ed., §9.1.5). Here the mirror reflection about the shading normal can fall below the geometric surface, and the pass then reflects the dark lower environment. Let `e` be the reflection's height above that plane (`dot(r, ng)`, `ng` facing the viewer). At `e >= 0.2` the shading normal is kept. At `e <= 0`, or where it faces away from the viewer, the interpolated normal is used. In between the two blend by `smoothstep(0, 0.2, e)`. The band 0.2 is UzPainter's own preview constant. The rule it replaced switched to the interpolated normal only where the perturbed one faced away. That jumped at the viewer's horizon, and drew thin dark lines along strongly baked edges such as the Wand gem's.
4. **Lighting.** Split-sum GGX specular, with `F0 = mix(0.04, base colour, metalness)` for IOR 1.5. Burley diffuse on the SH irradiance, scaled by one minus the dielectric specular albedo. The environment radiance is multiplied by `2^exposure` and by the fitted intensity scale 1.01919. Pixels with no hit show the clear colour: the standard's linear 0.1, which displays as 89.
5. **Self-occlusion (decision 251).** The mesh's own geometric occlusion of the environment light, which Iray path-traces and the split sum alone leaves out. Each hit traces visibility rays against every triangle of every texture set, and the specular and diffuse terms are each multiplied, per RGB channel, by a visibility ratio `R = Σ V·w·L / Σ w·L`. `V` is 1 for a ray nothing blocks, else 0, and `L` is the level-0 radiance in the ray's direction.
   - **Diffuse.** `diffuseRays` directions: half are cosine-weighted about the shading normal and half are drawn from the environment's importance distribution. Each is weighed by the balance heuristic of the two (Veach 1997): `w = cos / p_mix`, with `p_mix` the mixture's density. The environment samples are what resolve the shadows of the bright regions.
   - **Specular.** `specularRays` directions: half are reflections of the view about GGX visible normals of the shading normal (Heitz 2018) and half are drawn from the environment's importance distribution. Each is weighed by the balance heuristic of the two: `w = f·cos / p_mix = F·D·G2 / (4·n·v·p_mix)`, with Schlick's Fresnel, the GGX distribution and the height-correlated Smith masking of the albedo table, and the visible-normal density `G1·D / (4·n·v)` in `p_mix`. Lobe samples alone carry a bright light that the lobe only grazes on one heavy ray, and blocking that ray zeroes a highlight; the environment samples resolve it.
   - **Exclusions and guards.** Directions below the geometric facet are left out of both sums. This keeps light the geometry would block near the shadow terminator; it is an approximation, not a terminator fix. A ratio is exactly 1 where no ray is blocked, so an unoccluded pixel keeps the colour of the pass without rays bit for bit. Where its denominator is zero or not finite it is also 1; otherwise it is clamped to [0, 1].
   - **Rays.** A ray leaves the hit point moved off its triangle along the geometric normal by Wächter and Binder's integer-ulp offset (Ray Tracing Gems, 2019, ch. 6: each coordinate moves by `256·n` units in the last place of its integer representation, or by `n·2^-16` within 1/32 of zero), and skips the hit triangle. A surface closer than that offset leaks light (tested). The hit test is the camera rays' watertight edge-function test (decision 178), with both faces counting; the ray stops at its first hit.
   - **BVH** (`visibility.{h,cpp}`). The CPU builds a bounding volume hierarchy of the world-space triangles with the binned surface-area heuristic (16 bins per axis, leaves of at most 4 triangles), in a deterministic order. A node at depth 32 is a leaf whatever it holds, and the kernel's traversal stack has 32 entries, so it cannot overflow. Boxes are the exact float bounds of their triangles; the slab test grows the far distance by `1 + 2γ(3)` (Ize 2013). `VisibilityBvhOf` keeps the last two structures, keyed by the triangles' world-space corners bit for bit: the worker's new mesh object of every evaluation reuses its structure, and only a change of geometry builds another.
   - **Samples.** A Hammersley set per pixel and term, shifted (Cranley-Patterson) and digit-scrambled by a hash of the pixel coordinates only. The same pixel gets the same rays in every frame; there is no accumulation across frames.
   - **Counts.** 128 diffuse and 64 specular rays per hit (`kDiffuseVisibilityRays`, `kSpecularVisibilityRays`). Two measurements choose them:
     - **Noise.** On the concave fixture (`viewport-visibility` section 8), each ratio's RMSE against a 1024-ray render must be within `0.5 / sqrt(N)`. With the mixtures above, the diffuse ratio meets it from 32 rays (0.073, bound 0.088). The specular one misses it at 16 rays (0.130, bound 0.125) and meets it at 64 (0.051, bound 0.0625). (32, 16) is therefore too few, and (128, 64) is the smallest pair of the ladder that meets the bound for both terms.
     - **Time.** The ladder below, measured with `uzp-preview-tests viewport-ladder` on the Wand v1 low mesh (1248 triangles) under `studio-small-09.exr`, fitted camera, Debug build, RTX 4090 driver 32.0.16.1714. Times are a whole `RenderViewport` call, median of 3; RMSE is of the linear colour against a (1024, 1024) render of the same estimator. Another agent's GPU test ran on the machine at the same time, so the times are noisy and not monotonic. Every row fits the window's 200 ms period, but (256, 128) does so by 6 ms only; (128, 64) leaves 30 ms.

     | Rays (diffuse, specular) | 660 × 600 (window) | RMSE | 1700 × 1250 | RMSE |
     |---|---|---|---|---|
     | (0, 0), no occlusion | 166.6 ms | 0.0354 | 590.1 ms | 0.0355 |
     | (8, 4) | 160.7 ms | 0.0223 | 711.8 ms | 0.0234 |
     | (16, 8) | 135.4 ms | 0.0153 | 655.2 ms | 0.0162 |
     | (32, 16) | 146.2 ms | 0.0106 | 715.6 ms | 0.0107 |
     | (64, 32) | 173.8 ms | 0.0063 | 600.0 ms | 0.0067 |
     | **(128, 64)** | 170.0 ms | 0.0042 | 688.9 ms | 0.0048 |
     | (256, 128) | 193.6 ms | 0.0032 | 701.8 ms | 0.0033 |

     The BVH build of that mesh took 21.1 ms under the same load (14.6 ms on a quiet machine), once per geometry. On a quiet machine the (0, 0) render took 116.2 ms and (32, 16) 118.7 ms: the rays cost little, and most of the call is fixed cost. `samples` stays 1, one camera sample per pixel; the counts are internal and the capture receipt states them.
   - **What it is.** Visibility only: one bounce, no interreflection, no light transport. The ratio of two Monte-Carlo sums is a consistent but biased estimator. It gives the preview its depth cues; closeness to Iray is not claimed (07 §6). The display state's `shadows` flag changes nothing (Captures).
   - **Ambient occlusion (decision 257).** The low-poly rays alone darken only what the low-poly encloses; the leather wraps, ring grooves and engravings live in the baked AO map. The AO mesh map enters the same rays:
     - **Input.** `exporter::PassThroughMeshMap` reads the set's bound AO mesh map: one linear channel, the UNORM code over the code maximum (the standard's Non-Color / Raw), at the set's resolution, sampled like the other maps. A set without one reads 1; another image layout or size fails as the pass-through does, never silently 1. The painted `AO` channel and its Multiply/Replace mix with the mesh map are not applied (decision 131's rule is unrecorded), the Height and Curvature mesh maps are not read, and height enters only as the bump already in the combined normal.
     - **Strength.** `a = 1 + s·(ao − 1)` (glTF 2.0 `occlusionTexture.strength`) with `s = 1.0` (`kOcclusionStrength`), UzPainter's provisional preview default: read-only, reported by `render.display.state()` and the receipt, changed only by a decision.
     - **Visibility weight.** An assumed directional AO. Each ray of either ratio that no triangle blocks counts with the weight `V_ao(d) = μ^k`, where `μ = dot(s, d)` about the shading normal `s` after the fade of step 3 and `k = 2(1 − a)/a`. Under the cosine-weighted measure `t = μ²` is uniform on [0, 1], so the mean of `V_ao` is `∫₀¹ t^(k/2) dt = 1/(1 + k/2) = a`: under uniform light the cosine-weighted visible fraction of the hemisphere is exactly `a`, the calibration of a visibility cone with `sin²α = a` (Oat and Sander 2007, *Ambient Aperture Lighting*). The power law is UzPainter's own construction from that identity. A ray weighted below 1 marks the ratio as blocked, so it is the sums' quotient; weights, mixtures, exclusions, clamps and the zero-denominator rule are decision 251's. `a = 1` returns before the weight, so such a pixel is the pass's without it bit for bit; `a = 0` removes every ray, so the ratio is exactly 0 wherever its denominator is valid. An AO map never brightens a pixel: with the same rays and denominators, every ray's share can only fall.
     - **What it gives.** Diffuse AO; a specular occlusion that is the weight averaged over the sampled lobe, so it depends on view and roughness (the principle of Jimenez et al. 2016; the per-ray form is UzPainter's); and directional micro-shadows: light along the normal keeps its weight, grazing light loses most of it, more in a lower-`a` groove. No cavity term (from the normal's divergence, the Height or a Curvature map), no horizon term, no separate specular-occlusion formula.
     - **Why not a hard cone.** Decision 257 first specified a hard cone, `V = [dot(s, d) ≥ sqrt(1 − a)]`, with the same calibration. On the Wand it produced two deterministic defects, present in (1024, 1024) renders too: a torn, near-black smear with ragged tendrils on the tip-side ferrule, where a smooth metal's narrow lobe sits just outside the cone and the normal map moves it in and out; and AO darkening on the last leather wrap that ended in a straight line along a triangle edge, because the cone puts all of its occlusion near the horizon of `s`, exactly the band that the per-triangle facet clip removes differently on each side of an edge. Integrated numerically (uniform light, GGX, two facets tilted ±11.25°, the same shading point), at an 80° view, roughness 0.3 and `a = 0.95` the specular ratio of the two facets was 0.871 / 0.606 with the hard cone, 0.831 / 0.637 with the widest linear ramp in `μ²` of the same mean, and 0.897 / 0.868 with the power law. The power law spreads the occlusion over the whole hemisphere and is continuous in `s`, so neither defect remains in the renders. Its cost is less view selectivity: a mirror lobe at view angle `θ` keeps `cos^k θ` rather than all or nothing. The AO bake was not the cause: it is smooth there, and it is padded 4 texels beyond every UV island and partly to 8.
     - **Specular rays.** The shipped 64. With the hard cone, 64 rays left a visible grain on the leather close-up and an earlier version of this item traced 256 in the cone; with the fractional weight the grain is gone at 64. On view 02's leather wraps (680 × 400 pixels) the high-pass RMS of the linear colour is 0.00270 at (128, 64) against 0.00259 at (1024, 1024), with an RMSE of 0.00082 and a 99.9th-percentile error of 0.0117 against that render (the hard cone at 64: 0.00358 and 0.027).
     - **Declared biases.** The weight is symmetric about the shading normal and assumes where the occluders are. Its calibration holds for the cosine measure under uniform light only, before facet clipping; under a real environment the difference is the directional cue. The bake's cage and ray distance differ from the low-poly rays. The bake's low-poly-scale occlusion is not divided out: where the low-poly blocks directions the weight also lowers, the darkening counts twice (measured below, not bounded). On assets whose albedo carries painted occlusion, as the Wand's does, the preview darkens those regions again (BAK-08 intends it; the receipt says `painted_occlusion: "may_compound"`).
     - **Not parity.** A `painter_viewport` approximation only: whether and how Iray applies AO is owed to the phase3.5 item 3.3 recording, and `painter_iray` is unchanged.
     - **Resident inputs.** A render's camera-independent inputs (the materials and their maps, the lighting, the display table and the BVH) can stay on the GPU between renders of one scene (`ResidentInputs`). The window keeps them for the revision it shows and invalidates them when it takes a new one, so orbiting uploads only the frame words, the triangles and their tiles. Captures upload everything once per call.
     - **Time.** `uzp-preview-tests viewport-occlusion-time` on the Wand v1 low mesh under `studio-small-09.exr`, fitted camera, Debug build, RTX 4090 driver 32.0.16.1714, rays (128, 64), a whole `RenderViewport` call, median of 3. The maps are 2048 × 2048 constants: base colour, metalness, roughness and normal, as on the Wand, and an AO map of 0.5, so every hit is AO-mapped (the worst case). The machine was shared, so the times are noisy.

       | Inputs | 660 × 600 (window): every input uploaded / building the resident inputs / from them | 1700 × 1250: the same |
       |---|---|---|
       | no maps | 168.0 / 172.9 / 138.5 ms | 580.2 / 572.9 / 557.9 ms |
       | four 2048² maps | 588.7 / 539.7 / 106.9 ms | 886.2 / 964.1 / 541.7 ms |
       | four maps and the AO map | 721.0 / 620.9 / 135.0 ms | 1192.9 / 1031.8 / 484.9 ms |

       Uploading the maps dominates: with the Wand's four maps the window took about 590 ms a render before the AO map, so decision 251's 200 ms measurement, made without maps, did not hold for a textured asset. From resident inputs the window's default size renders in 107-135 ms and fits the 200 ms period; the case asserts it. The first render of each revision pays the upload once.
6. **Output.** The linear colour as binary16 (`RGBA16Float`) and its display codes (`RGBA16Unorm`), read back through `TextureReadback`.

The same scene, build, adapter and driver give the same bytes. Kernels are IEEE-strict, use no atomics and loop in a fixed order.

## Preview thread and window (items 2.4 and 2.5)

- **Evaluating a frame.** `EvaluateFrame` evaluates what the window shows of one revision on a GPU evaluator: the base colour, metalness and roughness of every texture set's first stack, and its combined Normal_OpenGL map. It passes the set's AO mesh map through (`OcclusionOf`, decision 257) when the set binds one; the window lists it as `<texture set>/Occlusion`.
  - A project whose display configuration the viewport refuses (Legacy, decision 038) is published without evaluating anything, so the window shows the refusal.
  - A failed evaluation is recorded in the frame. The window shows it in place of the image, never a material with that map missing.
  - The texturing mesh is derived again only when the project's mesh reference changes.
- **Publishing.** `PreviewFeed` is called by the one thread that evaluates the frames. `Update` starts a revision's frame and drops the previous one's maps. The frame holds the evaluated map of each texture set and slot, with the revision, project, mesh and environment bytes, or the failed evaluations. `Publish()` hands the frame to the triple buffer of `latest.h`.
  - Only shared pointers are copied. The publisher never waits for, locks against or calls into the preview thread.
  - A stalled or closed reader only means frames are replaced before they are taken.
- **The preview thread.** `PreviewHost` owns the preview thread. That thread has:
  - its own `render::Engine`, so preview rendering never queues in front of or behind evaluation on the worker's device;
  - the window, through the vendored `platform_window` and `input`. It is read-only, with an orbit camera only: left drag orbits, the wheel zooms.
  - The camera is fitted to the mesh on the first frame and again only when the project's mesh reference changes, so an edit keeps the user's orbit. `preview_status` counts the fits (`camera_fits`).
- **Rendering.** At most one render every 200 ms, and none while the window is minimised.
- **Presenting (decision 227).** The window is double buffered with GDI. Nothing is ever drawn straight onto the window.
  - **Composing.** Each frame is composed whole in a memory bitmap the size of the client area: the image stretched to the view (HALFTONE), or the message, then the panel and its text. A frame is composed only when something it shows has changed: a new image or message, a newly taken frame's revision, or another client size.
  - **Presenting.** WM_PAINT copies the whole frame to the window with one BitBlt. An unchanged window is drawn again only when Windows asks for a repaint.
  - **No erase.** The vendored window class's black background brush is removed, and WM_ERASEBKGND is answered without erasing. The vendored window procedure is subclassed, not edited.
  - **Resizing.** WM_SIZE presents a frame of the new size inside the size change, so the compositor never shows the new size holding the old frame. The loop waits for messages instead of sleeping, so a resize sent from another thread is answered at once.
  - **Rendering a new frame.** While a new frame renders, and during a live resize (the loop then waits inside Windows' modal size loop), the window keeps showing the last complete frame, stretched to the new size.
  - **No swap chain.** The image is read back for the CPU anyway, so the capture path and its goldens are unchanged.
  - **Counter.** `preview_status` counts the presents (`presents`).
- **Panel.** The right-hand panel states that `painter_iray` is unavailable: no capture can exist before P3-PATHTRACER.
  - It gives the project's display configuration (`DisplayLabel`). That is "OCIO, Painter's substance config, Default - sRGB (decision 042)" for the pinned one. Otherwise it names what differs and says the viewport does not display it, e.g. "Legacy colour management with tone mapping Linear: not displayed, … (decision 038)".
  - It also gives the revision shown, or that no project is open.
  - `preview_status` and the standalone report return the display line as `display`.
- **Environment.** A project that names no environment is lit by the installation's default, `bin/assets/environments/studio-small-09.exr` checked against its SHA-256 (`DefaultEnvironment`, decision 212); the capture receipt's `environment.default` is then true. A named environment whose bytes are missing fails with no substitute (RES-03).
- **Errors.** An unsupported configuration, a failed evaluation, a missing environment or a project without a mesh is shown as text in place of the image. A frame without a project shows that no project is open. While a message is shown, `revision_shown` is -1 and `maps_shown` is empty; with an image they name its revision and its maps (`<texture set>/<slot>`).
- **Stall hook.** `Stall(true)` blocks the thread while it holds its frame. It is the test hook of item 3.2. In a Debug worker it is reached with `test_fault preview_stall` / `preview_resume` (decision 120).

Two ways to run it:

- **Standalone.** `UzPainter.exe --preview <file.uzp> [--gpu-backend dx12|vulkan]` opens the project as `run` does, holding its lock. It evaluates the preview's channels of every texture set once (`EvaluateFrame`) and shows the window. On close it prints `UZP_JSON:{"status": "closed", "frames_rendered", "revision_shown", "display", "last_error"}`. A Legacy project exits 0 with `frames_rendered` 0 and the decision-038 refusal in `last_error`.
- **Attached** (decision 248). `UzPainter.exe --worker … --preview`, or `--mcp … --preview`, which passes the flag to its workers. The worker lists the GPU-free `preview_status` tool.
  - The window shows the open project's committed revision after `project_open`, `project_create`, a rebuild from a recipe and every committed call. It shows that no project is open once the project closes.
  - **Hand-over.** The worker hands every change of what its session holds (`python::Session::on_durable_change`) to `AttachedEvaluation`. That class has its own thread and its own device and evaluator. It evaluates the newest committed revision with `EvaluateFrame`, and it is the feed's only publisher. `evaluate_channel` publishes nothing.
  - **Newest wins.** A revision superseded before its evaluation ends is abandoned and never published; the window keeps the last complete frame.
  - **Nothing waits.** The worker's request thread and device never wait for the preview. The window's thread never queues a render behind an evaluation.
  - **Stall hook.** `AttachedEvaluation::Stall(true)` blocks the evaluation thread inside its evaluation, between its steps (after it started a revision's frame, before each map and before publishing). In a Debug worker it is reached with `test_fault preview_evaluation_stall` / `preview_evaluation_resume`, and `preview_status` reports it as `evaluation_stalled`. `test_the_previews_evaluation_never_delays_or_changes_the_workers_results` holds it on the OCIO fixture while the worker evaluates, commits and exports.
  - **After the window closes.** Nothing more is evaluated.
  - **Store access.** The evaluation thread reads the project's resources through a `StoreAccess`, one locked read at a time. When the project closes or another one opens, the worker's thread revokes the access within that change. It waits at most for one read in flight. So the store, its lock and an untitled project's folder are released before the call that closed the project returns.
  - **Cost.** The preview's evaluation still shares the GPU and the CPU with the worker. Export times with and without the preview are settling metrics with no threshold (decision 162).

**Headless (decision 252).** The window is the only one UzPainter can open, and only an explicit `--preview` opens it. `UZP_HEADLESS=1` refuses it. A leading `--headless` (`UzPainter.exe --headless <command> …`), or `--headless` among the options of `--preview` or `--mcp`, sets that variable for the process and its children. While headless, all three entry points refuse the preview as a usage error (exit 2), and the message names the switch:

- `--preview <file>` refuses before it opens the project or creates a device (`cli.cpp`, `Headless()`);
- `--mcp --preview` refuses before any worker starts (`python/uzpainter_supervisor/main.py`);
- `--worker --preview` refuses before the worker creates its pipe (`src/supervisor/worker.cpp`).

The preview tests open their windows on a private desktop that nobody sees (`tests/desktop.py`). The anti-flicker test reads the screen, so it runs only when the owner asks for it with `UZP_SCREEN_TESTS=1`.

## Captures (phase2.2_preview-capture, decision 148)

`uzpainter.render.capture(path, mode, camera, size, samples, seed, preset, stack)` and the worker's `capture` tool live in `src/python/capture.{h,cpp}`. Every capture reads the committed revision once and evaluates it synchronously; inside an open Transaction it refuses. Its receipt names the revision it shows. The modes:

- **`painter_iray`** raises `PathTracerUnavailable`, a `NotYetSupported`, before anything else: no argument is checked, no project read, no device created and no file written (P3-PATHTRACER).
- **`painter_viewport`**:
  - **Inputs.** The base colour, metalness, roughness and combined Normal_OpenGL of every texture set's first stack, evaluated on a CPU evaluator with the export's inputs, and each set's AO mesh map passed through (decision 257).
  - **Scene.** `SceneOf`, the window's own builder, with the project's display state, or with `preset` (a standard preset's name or a whole preset) applied to an in-memory copy that is never committed.
  - **Checks.** The display configuration, the mesh and the environment are checked before any evaluation or device. An unsupported configuration raises `UnsupportedInUzPainter` with decision 134's `unsupported_configuration` text.
  - **Device.** The pass runs on the worker's engine, or on a device of `run`'s `--gpu-backend` created for the call (`gpu_backend_unavailable` without one). It uploads its buffers and dispatches in one submission, waits for it, and reads both targets back through `TextureReadback`.
  - **Files.** `path`, a 16-bit RGB PNG of the display codes, and `<stem>.exr`, RGB binary16 of the linear colour. Alpha is always 1 and is not written.
  - **Camera.** A Painter camera record, with right, up and forward `R·x`, `R·y`, `-R·z` for `R = Rx @ Ry @ Rz`. `field_of_view` is taken as the vertical angle; this is UzPainter's convention, not a measured Painter fact. Without one, the display state's default camera, else `FitCamera`. An `Orthographic` record casts parallel rays along the forward axis from the plane through its position; `orthographic_height` is the view's full vertical extent in scene units and the width is that times the aspect, again UzPainter's convention (decision 163). Only hits in front of that plane count, and `field_of_view` does not apply.
  - **Arguments.** `size` is required, `samples` is 1, and `seed` is only recorded.
  - **Today.** It renders OCIO projects with Painter's substance config whose sources the evaluator takes under OCIO: uniform colours, an 8-bit colour bitmap in sRGB or Raw on an sRGB8 channel at 1:1 and a 16-bit grey mask source at 1:1 (decision 190). Every other source fails before any device work, as in the export.
- **`base_color`, `channel:<name>`, `mask:<uid>`** are texture-space captures of one stack, at its set's resolution.
  - The stack is `stack` (Python) or `texture_set`/`stack` (worker), else the active stack; `mask:<uid>` takes its node's.
  - The export engine compiles and encodes a one-file plan of `documentMap baseColor`, `documentMap <name>` or `diagnosticMap materialMask/<uid>` with padding `passthrough`. In `channel:<name>`, `<name>` is a channel type as `evaluate_channel` and `source_set` take it (`SpecularRoughness`) or the export's documentMap name of one (`specularroughness`); the source is the documentMap the export records for that channel (decision 242). Any other name raises `ValueError` ("names no channel"), and a channel the stack lacks raises "has no channel". It writes a 16-bit PNG at `path` and an OpenEXR 32f at `<stem>.exr`, so each equals the export of its source with the same parameters.
  - A given `camera`, `preset`, `samples` or `seed`, or another size, raises `ValueError`.
- **Receipt.** Every capture writes `<stem>.receipt.json` (`src/python/capture-receipt.schema.json`): `{schema, revision, project_uuid, evaluator_profile, render_state_digest, mode, source, encoding, backend, adapter, driver, samples, seed, camera, size, display_configuration, environment, visibility, occlusion, shadows, hashes}`.
  - `render_state_digest` is the SHA-256 of the canonical JSON of the resolved render state. For `painter_viewport` that is the environment, background, camera and pose, size, samples, seed, shader, display configuration, `visibility` and `occlusion`; for the other modes, the source, size and encoding.
  - `visibility` is `{model: "ray_traced_self_occlusion", diffuse_rays, specular_rays}` (decision 251). It is in the digest because the model and its counts change the image, so captures from before and after the self-occlusion are told apart. `samples` keeps its meaning: one camera sample per pixel.
  - `shadows` is `{requested, effect: "none in painter_viewport"}`, outside the digest. The display state's `shadows` flag (off under `common`, on under `ref_match`) acts in Painter only on its realtime viewport, which is not a target, and Painter disables it in Iray mode; `painter_viewport` always traces its self-occlusion, under both presets (decision 251). `render.display.state()` reports the same as `shadows_effect`, so the flag is declared inert rather than silently ignored (decision 042, ARC-03).
  - `occlusion` (decision 257) is `{model: "cosine_power_visibility", ao_source, ao_strength: 1.0, ao_channel: "not_applied", axis: "shading_normal_after_fade", cavity: null, painted_occlusion: "may_compound"}`. `ao_source` lists every texture set in order as `{texture_set, source: "mesh_map" | "none", sha256}`, with the bound AO image's SHA-256, so captures with another AO bake are told apart. It is in the digest. `render.display.state()` reports `ao_strength` and `ao_channel` the same way.
  - `visibility`, `occlusion` and `shadows` are null for the diagnostic modes.
  - `adapter` and `driver` (the DXGI user-mode version) are null on the CPU.

## Regression goldens (item 2.6)

`tests/preview/viewport-goldens.json` holds UzPainter-vs-UzPainter goldens for four UzmiGames-authored fixtures under `sky-patch.exr`, each at 256 × 256:

- `parity/fixtures/render-procedure/sphere.obj`;
- `parity/fixtures/iray-references/plane.obj`, with a checker base colour and a tilted normal map;
- `parity/fixtures/iray-references/bevelled-cube.obj`, as a metal;
- `cube-on-plane`, authored in the test: a 1.5-unit cube (texture set 1) resting on a 6 × 6 plane (texture set 0), the concave fixture of the self-occlusion (decision 251).

Each golden stores the SHA-256 of the display codes and of the linear binary16 values.

A golden is keyed by build, adapter and driver:

- the build is the XXH64 key of the viewport kernel, which covers its HLSL, the compile flags and DXC;
- the adapter is its name;
- the driver is the UMD version from DXGI.

The goldens are exact for a fixed key. They are a repeatability check, never a tier result. A key the file does not hold fails the test. It is recorded with `uzp-preview-tests viewport-golden <dir> tests/preview/viewport-goldens.json --bless` on the owner's machine (decision 028).

When a change to the kernel is meant to leave existing images alone, the new key's hashes are compared with the previous key's before the old entries are removed: the orthographic camera (decision 163) re-keyed the file to `3f173b7573f95bba` (CRLF checkout) and `91bc3285269b6519` (LF) with every image hash unchanged. The watertight coverage (decision 178) re-keyed it again, to `51810c8132b4cdc5` (CRLF) and `115b8b6f3f2579a9` (LF), and again no golden pixel changed: no golden camera puts a pixel centre on a shared edge. The five former crack pixels are in the perspective capture of `test_orthographic_capture_casts_parallel_rays`, which now requires that view to be solid. The self-occlusion (decision 251) re-keyed it to `e570812a72826a6c` (CRLF) and `6f233e84d741c0ac` (LF). The three convex fixtures are its negative control: no visibility ray of a convex surface can be blocked, so their images must not move, and a pixel-by-pixel comparison against the renders of `51810c8132b4cdc5` found 0 changed pixels in each (display and linear). `cube-on-plane` is new; its image is the expected change. The review's specular mixture and counts (128, 64) re-keyed it to `87e4fbc2537c02f2` (CRLF) and `4e1b7a7f23a5ebfb` (LF, blessed from a checkout with `core.autocrlf=false`). The convex fixtures again showed 0 changed pixels against the `e570812a72826a6c` renders, and only `cube-on-plane` changed. Rebased onto the normal fade (decision 256), whose own re-key `f8c9aa42d1df9cb3` (CRLF) and `ff36ce4703f095c0` (LF) left every convex image as it was, the file is re-keyed to `a3bfa13b0a445df0` (CRLF) and `7a9a6eb3a7a24186` (LF): the three convex fixtures equal the hashes of both former keys, and `cube-on-plane` equals its `87e4fbc2537c02f2` render. The AO mesh map (decision 257) re-keyed it to `12ad333c66b267b6` (CRLF) and `bb1a1bc7ea0a64bd` (LF; blessed from a build whose two kernel sources, `viewport.hlsl` and `image_common.hlsli`, had LF endings, a method that reproduces the former LF key `5202d8b4769df118` from the former sources): no golden fixture binds an AO map, so all four, `cube-on-plane` included, equal the hashes of the former keys.

`uzp-preview-tests viewport-visibility` checks the self-occlusion itself (`test_preview_viewport.py::test_viewport_self_occlusion`), UzPainter against UzPainter and never parity:

- a camera inside a closed box under a constant environment renders exactly 0, which only valid, blocked rays give (the ratio-1 fallback would light it);
- on the concave fixture, the sphere and the box, the BVH's visibility of 20 000 rays per mesh equals a CPU cast of the same float operations against every triangle, and a depth cap of 2 still holds every triangle once;
- an occluder twice the origin offset above a surface blocks, one at half of it leaks (at y = 1 and within 1/32 of zero);
- rays through every shared diagonal, box edge and corner of a closed box are blocked;
- under a sun, the cube shadows the plane where the geometry predicts: the diffuse ratio is below 0.3 where the cube hides the whole sun texel and above 0.7 where it hides none, and the shadow is darker;
- a red-and-blue environment beside a wall that hides the red half gives a red ratio below 0.5 and a blue one above 0.98;
- on the plane (with and without its tilted normal map) and the sphere, every ratio is exactly 1 at grazing and steep views: no self-shadowing acne;
- against a 1024-ray render of the same estimator on the occluded pixels, four times the rays at least nearly halve the RMSE, and the RMSE at the shipped count `N` is within `0.5 / sqrt(N)` for both terms (both mix their lobe's directions with environment-importance ones);
- a new mesh object of the same geometry reuses its BVH.

`uzp-preview-tests viewport-occlusion` checks the AO weight (`test_preview_viewport.py::test_viewport_ao_visibility`), UzPainter against UzPainter and never parity:

- an AO map of exactly 1 leaves every pixel of the four golden fixtures bit for bit, colour and both ratios, under the sun and the shipped environment (the early return);
- with an AO map of 1, a flat and a tilted normal map keep every ratio exactly 1: no micro-shadow or cavity comes from the normal map;
- an AO map of 0 gives exactly 0, both ratios and the colour, dielectric and metal;
- on an open plane under a uniform environment the 1024-ray diffuse ratio is `a` (0.25, 0.5, 0.75: means 0.2500, 0.5000, 0.7500, largest pixel error 0.0012), also at an 82-degree view, and the 128-ray render is within `0.5 / sqrt(128)` of it (RMSE 0.0015-0.0039);
- with `a = 0.3`, light within 25 degrees of the normal keeps a 1024-ray diffuse ratio of 0.8401 and a 65-85-degree band 0.0036, against 0.8442 and 0.0033 for `μ^k` summed over the environment's lit texels;
- on a metal plane with `a = 0.5`, the 1024-ray specular ratio falls with roughness (0.881, 0.814, 0.666, 0.541, 0.474 for 0.1 to 0.9) and with the view angle (0.911, 0.814, 0.570, 0.294, 0.152 for 0 to 75 degrees), and the shipped 64 rays are within `0.5 / sqrt(64)` (RMSE 0.0098);
- a 2 × 2-block checker AO map on mirrored, doubly scaled UVs gives exactly 1 and 0 where the CPU's bilinear lookup has four equal texels, so the slot reads nothing but the bound image's texels;
- with the BVH and the AO weight together, every ratio is at most each alone, pixel by pixel (the per-ray product). The double darkening is reported, not bounded: on the concave fixture with its own 64 × 64 AO bake, the plane near the cube has a mean diffuse ratio of 0.850 with the BVH only, 0.848 with the weight only and 0.736 with both (0.107 below the darker of the two); the cube with a constant `a = 0.5`, 0.850, 0.500 and 0.442 (0.059); a square floating above with `a = 0.5`, 0.966, 0.500 and 0.475 (0.025);
- an AO map never brightens a pixel: on the concave fixture with its bake under the shipped environment, colour and both ratios are at most those without it, dielectric and metal;
- resident inputs give the bytes of renders without them, a second render reuses them, and after `Invalidate` a changed AO map shows.

`test_preview_capture.py::test_viewport_capture_applies_the_ao_mesh_map` checks the real input path, `OcclusionOf` through `exporter::PassThroughMeshMap` to the slot: an AO channel without an AO mesh map changes no byte and the receipt says `none` and `not_applied`; a bound 8-bit grey map darkens the render, never brightens a pixel, and the receipt names it with its image's SHA-256; an RGB image of another size fails the capture with `unsupported_source`.
