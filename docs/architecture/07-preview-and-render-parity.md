# 07 — Preview and render parity

Implements D6 as decided by the owner on 2026-10-10 (decision 018, superseding 008, from Q2: **Painter's Iray output is the render-parity target**; equality rule Q1, decision 017; clean-room implementation per decision 002). Requirements: VIS-01…06, RES-03, G-04, ARC-06, CLR-01…03 (`docs/prd.md`). Supersedes the round-3 text that made the realtime viewport the target (`docs/analysis/architecture-discussion/06-round4-changes.md`).

## 1. Render modes

| Mode | Purpose | Implementation | Parity status |
|---|---|---|---|
| `painter_iray` | **The render-parity target**: reproduce what Painter's Iray renderer produces for the same project state and render settings | UzPainter-owned clean-room path tracer on the vendored render core (§3): DX12 DXR (primary) and Vulkan ray tracing (second Windows backend) | Tier 3 against converged Iray references in the private oracle store; passes only through the Q1 exception register (§4) |
| `painter_viewport` | Human preview (read-only window) and a **fast check** during authoring and CI (§6) | Forward rasterised pass on the same render core, same material parameters and display transform | Not a parity target; never acceptance evidence |
| Diagnostic captures | Unlit BaseColor, single channel, mask/ID views for the paint gates (VIS-03, QG-01) and the region masks of §4 | Direct channel visualisation | Exact (they are channel exports) |

No UzEngine renderer runs inside UzPainter (decision 021, Q8: zero dependency on UzEngine). The UzEngine export preset is validated by an **external** consumer fixture — UzEngine's own executable running a test scene in CI, like the Unreal and Blender fixtures (P3-UZE). Whatever window or session that executable needs belongs to the fixture; it is never part of UzPainter's no-window acceptance (NFR-01).

## 2. The Iray reference (captured, private)

Painter's Iray renderer is Adobe/NVIDIA software; nothing from it is read, linked or copied, and Painter's shipped material and shader files (`PAINTER\resources\mdl\`, `PAINTER\resources\starter_assets\shaders\`, `PAINTER\resources\shader-doc\`) are not opened. Painter is used only as a black-box oracle on the owner's machine (Q9b), driven by the UzmiGames recorder (`14-parity-testing.md` §2) through its documented Python API, plus the settings panels that Adobe's public help pages describe.

### 2.1 What Painter exposes publicly

Sources: the public Python API documentation (`PAINTER\resources\python-doc\substance_painter\display.html`, `ui.html`, `project.html`, `resource.html`) and Adobe's public help pages *Iray Renderer*, *Iray Settings* and *Viewer and MDL Settings* (Substance 3D Painter user guide). Anything not found there is **not confirmed — Phase 0 probe**.

| Setting | Public source | How a reference fixes it | Status |
|---|---|---|---|
| Iray mode on/off | `ui.switch_to_mode(UIMode.Visualisation)`, `ui.get_current_mode()`; `Visualisation` is documented as the "(Iray) mode" | Recorder, by API | Documented |
| Camera | `display.Camera.get_default_camera()`: `position`, `rotation` (Euler degrees), `projection_type`, `field_of_view` (3–179°), `focal_length` (1–500 mm), `orthographic_height`, `focus_distance`, `aperture` (lens radius, depth of field); event `CameraPropertiesChanged` | Recorder sets and reads back; fixtures use `aperture = 0` | Documented |
| Environment map | `display.get/set_environment_resource`; import of an environment file with `resource.import_project_resource(path, Usage.ENVIRONMENT)` | Recorder, by API; identity = resource URL plus SHA-256 of the file | Documented |
| Colour LUT | `display.get/set_color_lut_resource` | Recorder | Documented; where Iray applies it in the display chain — not confirmed, Phase 0 probe |
| Tone mapping | `display.get/set_tone_mapping` (`Linear`, `ACES`); raises `RuntimeError` when the project is colour managed | Recorder (projects without colour management) | Documented |
| Colour-management mode | `project.create`: OCIO mode when the OCIO environment variable names a config, ACE mode when `PAINTER_ACE_CONFIG` names a preset, otherwise Legacy | Recorder sets the variable before project creation; config file hashed | Documented; the selected display/view transform is not in the Python API — not confirmed, Phase 0 probe |
| Min Sample, Max Sample, Max Time (+ unit), Caustic Sampler, Firefly Filter, Override viewport resolution (Width, Height) | Help page *Iray Settings* | Operator, in the Iray settings panel | Not in the Python API; whether they persist in the project or can be read back — not confirmed, Phase 0 probe |
| Convergence state: Status (Rendering / Paused / Done), Iterations against the maximum, Rendering time against the maximum | Help page *Iray Settings* (information section) | Operator reads before capture | A programmatic readiness check — not confirmed, Phase 0 probe |
| Environment Exposure, Environment Rotation, dome (Infinite Sphere / Sphere / Sphere with ground), Radius, Texture Scale, Clear Color, ground position, Reflectivity, Glossiness, Shadow Intensity, Visible from below | Help page *Viewer and MDL Settings* | Operator | Not in the Python API — not confirmed, Phase 0 probe |
| Post effects and the other display settings Iray shares with the viewport | Help page *Iray Renderer* (display settings are identical to the regular viewport) | Operator; fixtures turn post effects off | Which display settings change the Iray image — not confirmed, Phase 0 probe |
| Material parameters of the default MDL per material instance: Emissive Intensity, Refraction, IOR, Scattering, Absorption, Absorption Color | Help page *Viewer and MDL Settings* (default MDL compatible with PBR Metallic/Roughness) | Operator records; fixtures keep refraction and scattering off | Not in the Python API — not confirmed, Phase 0 probe |
| Denoiser | No control on the public *Iray Settings* page | — | Whether a denoiser affects the saved render and whether it can be disabled — not confirmed, Phase 0 probe |
| Random seed | Not documented | — | Whether repeated renders are bit-identical — not confirmed, Phase 0 probe (§4 measures it either way) |
| Save Render | Help page *Iray Settings*: exports the current render, even if unfinished, to a file | Operator, after convergence | Output format, bit depth and whether the display transform is baked in — not confirmed, Phase 0 probe |

Decision 038 (owner, 2026-10-11) limits the reference procedure to the fixed Assets3D render pipeline (`Render-Comparison-Standard.json`: the v2 block, the `ref_match` preset and the `base_color` diagnostic). Every other setting in this table is pinned to the standard's value or Painter's default and is not a supported variable. The answers per row, including those marked `not_required`, are in `parity/reports/phase0/iray-capture-procedure.md`. A setting the probe finds cannot be fixed or read is recorded as `uncontrolled` in the reference manifest and must be named in the evidence of any exception that relies on that reference (§4). Painter's separately documented JavaScript API (reachable through the documented `js.evaluate`) is consulted only if the approved-source index admits its documentation (P0-SOURCES). The Assets3D render adapter (`A3D\Pipeline\render\painter_render_standard.py`) automates these panels and grabs the displayed window through Painter's undocumented live UI objects; it is a pipeline tool, not a documented interface, and the recorder does not depend on it unless the owner approves it as an external observation procedure in a recorded decision.

### 2.2 Capture procedure

One settings sheet per reference, executed by the recorder (`tools/parity/recorder/*.py`, P0-RECORDER) and the operator. P0-FEAS-RENDER qualifies the procedure, including readiness and current-frame verification, before any render golden is admitted:

1. The recorder opens the fixture or project, applies and reads back every documented setting of §2.1, switches to Iray mode and writes the readback into the private reference manifest.
2. The operator applies the panel settings from the sheet; the recorder stores the entered values and an image of each settings panel as private evidence.
3. Convergence: Min Sample = Max Sample = S, and Max Time well above the time S samples take, so the sample count — not the time cap — ends the render. Capture only when Status reads Done, Iterations equals S and Rendering time is below Max Time.
4. Pixels: Save Render at the overridden resolution. If Phase 0 shows Save Render unusable (stale frame, unknown encoding), the fallback is an external observation of the displayed frame at 1:1 pixels with overlays excluded, recorded as display-referred 8-bit. The qualified procedure names which one is used.
5. Current-frame verification: the saved image must postdate the last settings change and the convergence, and its silhouette must match the fixture geometry projected from the recorded camera.
6. Repeats: each reference is recorded at least twice in separate Painter sessions (after a restart), plus once at k·S samples (k fixed in Phase 0) to estimate Iray's own Monte-Carlo error at S (§4).
7. Storage: images, readbacks, panel evidence and operator entries go to the private oracle store (`14-parity-testing.md` §6). The public manifest holds only their SHA-256, the independently authored fixture description and the settings sheet.

### 2.3 Reference profiles

Two profiles, kept distinct:

- **Analytic fixture profile — superseded by decision 038:** references use the fixed pipeline's values (OCIO, Default - sRGB, Studio White Soft; `parity/reports/phase0/iray-capture-procedure.md` §2). The fixtures captured under it, with `ref_match` at both views, and their noise terms are in `parity/reports/phase0/iray-references.md` (decision 046). The original proposal follows: UzmiGames-authored meshes (sphere, plane, bevelled cube) with constant-parameter materials; UzmiGames-authored or CC0 environments (constant colour, a single bright patch, a Poly Haven HDRI) imported through the documented resource import; 1200×1200 override resolution; Min = Max Sample 256 and Max Time 3600 s (the pipeline standard's values, `A3D\Pipeline\render\Render-Comparison-Standard.json → painter.iray_settings`); Caustic Sampler and Firefly Filter off; denoiser off if the probe finds a control; Infinite Sphere dome, exposure 0, rotation 0, no ground, shadows off, Clear Color background, post effects off; Legacy colour management with `Linear` tone mapping; `aperture = 0`.
- **Production-project profile — captured, not chosen:** for pilot assets, the project's actual state recorded per §2.1–§2.2: the pipeline standard's environment (an Adobe starter-asset environment, identified by hash, used only on the owner's machine and never shipped), its colour-managed display configuration and its cameras (VIS-05 conversions per `Render-Comparison-Standard.json → coordinate_contract`).

## 3. The clean-room path tracer (`painter_iray`)

### 3.1 Sources

Implementation sources are public literature and specifications only, each entered in the approved-source index (P0-SOURCES; `docs/licensing-and-clean-room.md` §2):

- **Light transport:** Kajiya 1986 (the rendering equation); Veach 1997 (multiple importance sampling, path-space formulation); Pharr, Jakob and Humphreys, *Physically Based Rendering*, 4th ed. (path tracing, environment-map importance sampling, Russian roulette); Burley 2020, *Practical Hash-based Owen Scrambling* (scrambled Sobol sampling).
- **Materials:** NVIDIA's *Material Definition Language* specification and the open-source MDL SDK (BSD-3-Clause; allowed by the owner under Q2) for distribution-function and layering semantics; the OpenPBR Surface specification and the glTF 2.0 PBR appendix for lobe definitions; the BRDF papers already listed in `licensing-and-clean-room.md` §2 (Walter 2007, Heitz 2014 and 2018, Schlick 1994, Burley 2012). Code taken from the MDL SDK keeps its BSD-3 notice and is listed in the dependency inventory (`licensing-and-clean-room.md` §3).
- **Never:** Iray, the Iray SDK or Painter internals; Painter's shipped MDL and shader files. Painter's outputs are private oracles used only for fitting.

### 3.2 Light transport

Unidirectional path tracing with next-event estimation and multiple importance sampling between BSDF and environment sampling; environment importance sampling from a piecewise-constant 2D distribution; Russian roulette after a fixed minimum depth and a maximum path depth fitted in Phase 0; Owen-scrambled Sobol sequences indexed by (pixel, sample, dimension) under a fixed seed. Transport is RGB in fp32; whether matching Iray needs more (spectral transport, caustic paths) is decided by the Phase 0 residuals, not assumed. Each pixel accumulates its own samples in a fixed order without floating-point atomics, so a given build, adapter, driver, seed and sample count can produce repeatable bytes; that repeatability is measured (`14-parity-testing.md` §1), not assumed.

### 3.3 Material model

- Painter's default Iray material is described publicly only as an MDL compatible with PBR Metallic/Roughness, with the parameters listed in §2.1. UzPainter maps the texture-set channels of the project's template and those parameters onto a layered BSDF written from the MDL specification's distribution functions and OpenPBR's lobes: GGX/Trowbridge-Reitz microfacets with height-correlated Smith masking and visible-normal sampling, Schlick or conductor Fresnel, Lambert or Burley diffuse, coat, sheen, transmission with absorption for Refraction/Scattering/Absorption, emission scaled by Emissive Intensity, opacity.
- Normal mapping in the MikkTSpace frame; height→normal per `04-layer-stack-and-compositing.md` §6. Whether Iray applies height as bump or as displacement — not confirmed, Phase 0 probe.
- Which variants correspond to Painter's material is decided by black-box calibration on the analytic fixtures — constant-parameter spheres sweeping base colour, metallic and roughness; a white-furnace fixture for energy conservation; single-channel perturbations (normal, height, emissive, opacity) — never by inspecting Adobe or Iray code.
- Every formula choice and fitted constant is recorded in `parity/semantics/iray.json` with its public source and residual. These fits are independently derived behaviour and public; the references they were fitted to stay private (`14-parity-testing.md` §6). The first fits (task phase0.8_render-reference-fits, decision 050) were made with a CPU feasibility prototype on the fixed pipeline's references: variants chosen on one chessboard half of the pixels, residuals reported on the other half and on held-out goldens; the noise floor they are judged against is in `parity/reports/phase0/iray-noise-floor.md`.

### 3.4 Camera, scene and display

- Painter's documented camera model (§2.1) in its Y-up scene space; conversions to the Blender convention per `A3D\Pipeline\render\Render-Comparison-Standard.json → coordinate_contract` (VIS-05).
- The project's colour-management mode, working space and display/view transform are preserved, never rewritten: Legacy projects use the documented `ToneMappingFunction` (`Linear`: linear → sRGB per IEC 61966-2-1 with values above 1 clamped, as documented; `ACES`: the Academy's public ACES transforms, variant fitted black-box); OCIO projects use OpenColorIO (BSD-3) with the project's pinned config and recorded view. Each supported configuration is pinned and tested; an unsupported one (including ACE mode until qualified) fails with an explicit error before rendering.

### 3.5 Backends and GPU requirements

| | DX12 (primary) | Vulkan (second backend on Windows) |
|---|---|---|
| Ray tracing | DXR **Tier 1.1** (`D3D12_FEATURE_D3D12_OPTIONS5`: `RaytracingTier ≥ D3D12_RAYTRACING_TIER_1_1`) | `VK_KHR_acceleration_structure` (with its required `VK_KHR_deferred_host_operations`) and `VK_KHR_ray_query`; features `accelerationStructure` and `rayQuery` enabled |
| Shader model / IR | Shader Model 6.6, the application baseline (`13-engine-integration.md` §5); inline `RayQuery` itself needs 6.5 | Vulkan 1.2 or later (buffer device address, descriptor indexing and SPIR-V 1.4 are core); SPIR-V generated by DXC from the same HLSL |
| Kernel form | Compute shaders with inline ray queries; no shader tables | The same kernels |
| Not required | DXR pipeline state objects | `VK_KHR_ray_tracing_pipeline` |

- Acceleration structures: one bottom-level structure per texture-set mesh, rebuilt only when geometry changes; one top-level structure for the scene; built through the vendored core's DXR primitives and UzPainter's Vulkan ray-tracing addition (`13-engine-integration.md` §2).
- Feature detection runs at startup and in `selftest` (`13-engine-integration.md` §4). A missing feature yields `PathTracerUnavailable{backend, missing}` before any work. There is no silent fallback to `painter_viewport` and no software path tracer; the WARP probe reports what it supports and never produces Tier 3 evidence.
- Both backends run the same kernels. DXR and Vulkan outputs of the same fixture are compared and every difference is reported; a cross-backend bound, like any non-zero difference, exists only as an owner exception (§4).

## 4. Comparison and acceptance (how stochasticity is handled, plainly)

Iray is a stochastic renderer, and so is UzPainter's path tracer. A converged Iray image is still one Monte-Carlo estimate; UzPainter cannot reproduce Iray's internal random sequence, and Iray's seed is not exposed (§2.1). **Pixel-exact equality between `painter_iray` and an Iray reference is therefore not achievable, and this document does not claim it.** Under Q1 (exact equality; a divergence is accepted only through an owner-approved exception with evidence; no preset tolerances), every Tier 3 pass is an exception by construction:

1. **Noise measurement** (Phase 0, per fixture): (a) Iray run-to-run difference between the two session-separated references — zero if Iray proves repeatable; (b) Iray's own Monte-Carlo error at S, from the S reference against the k·S reference; (c) UzPainter's error at S, from renders with several seeds against its own k·S render. (b) and (c) form the **noise floor**; (a) is the oracle-stability result (`14-parity-testing.md` §1).
2. **Comparison on converged images** in the reference's own encoding: if Save Render yields linear float, linear buffers are compared; if it yields display-referred 8-bit, UzPainter's linear buffer goes through the same display transform and quantisation first. Reported per fixture and per material region (from the diagnostic ID captures): max |Δ|, mean |Δ|, p99 |Δ|, differing-pixel count, mean signed Δ with its standard error from (b) and (c) — a bias test: noise averages out, a wrong lobe does not — the same statistics after 2×, 4× and 8× box downsampling, and FLIP. FLIP is computed with NVIDIA's reference implementation (`NVlabs/flip`, BSD-3-Clause), pinned by version and hash in the comparison tool and listed with its notice in the dependency inventory; it is diagnostic only.
3. **Routing through the exception register:** a Tier 3 comparison passes only through an explicit, versioned entry in the register (`14-parity-testing.md` §5: `parity/exceptions.json` plus a decision under `.rulebook/decisions/`) that names the fixture class, the metrics, bounds derived from the measured noise floor of step 1, every `uncontrolled` setting of §2.1 it relies on, and a defect-detection test showing the bounds still fail a missing channel, a wrong lobe, a roughness offset and a wrong environment rotation. Illustration only, not a default: "per region, |mean signed Δ| within three standard errors and p99 |Δ| within the p99 of the combined noise floor". The owner approves the entry; without it Tier 3 is **blocked**, never passed, and every report lists the entries it relied on.
4. The exception never relaxes texture parity (Tiers 0–2 stay exact) and never covers a structural difference: a wrong material binding, a missing map, or a wrong geometry, camera or environment fails regardless of any metric.
5. **Scope:** Tier 3 covers the fixtures and project configurations its report lists. Any other configuration is a gap in the capability manifest, and VIS-06 is not claimed beyond the approved scope; G5 requires every in-scope capability to be supported or covered by an owner scope decision (`docs/dag.md`, gate rule).

## 5. Capture

`display.capture(path, mode=painter_iray|painter_viewport|base_color|channel:<name>|mask:<uid>, camera, size, samples, seed, preset)`:
1. waits for evaluation of the current revision and all resource uploads;
2. renders to an offscreen target without a swapchain or window: RGBA32F accumulation for `painter_iray` (exactly `samples` samples per pixel; no time cap, no adaptive stop), RGBA16F for `painter_viewport`;
3. applies the display transform of §3.4; reads back through UzPainter's `TextureReadback`;
4. writes PNG (and EXR for the linear buffer) and a receipt `{revision, evaluator_profile, render_state_digest, mode, backend, adapter, driver, samples, seed, camera, size, display_configuration, hashes}`.

All UzPainter captures are window-independent (VIS-02, NFR-01); there is no hidden-window path, because no UzEngine renderer runs in-process (§1). The preview window (`--preview`) is a separate consumer of `painter_viewport` frames and cannot pause evaluation or captures.

## 6. Realtime viewport (`painter_viewport`): preview and fast check

- **Role:** the human's window into the work (VIS-01) and a fast check during authoring and CI. It is never the parity target and never acceptance evidence, and it is not calibrated against Painter's own realtime viewport.
- **Implementation:** the material parameters and display transform of `painter_iray`, evaluated with realtime approximations from public literature (split-sum image-based lighting, Karis 2013; SH irradiance, Ramamoorthi and Hanrahan 2001; the same GGX/Smith/Schlick/Burley lobes).
- **Fast check:** UzPainter-vs-UzPainter regression goldens of the viewport (exact for a fixed build, adapter and driver), and an informational difference against the latest `painter_iray` capture of the same state. Neither is a Tier 3 result.
- **Preview window:** `UzPainter.exe --preview <file.uzp>` or attached to a worker: read-only, orbit camera only, renders `painter_viewport` at a low rate on its own thread; optionally shows the latest `painter_iray` capture. Delivered by P2-PREVIEW; G2 does not include render parity.

## 7. Display presets and environments (VIS-04, RES-03)

- A display preset is serialisable data: `{environment {sha256, exposure, rotation, dome}, background, ground, display configuration (tone mapping or OCIO view), cameras, samples, seed}`. UzPainter implements the pipeline's common comparison standard and its `ref_match` preset (`A3D\Pipeline\render\Render-Comparison-Standard.json`); presets are separate from presentation snapshots.
- Implementation (decision 132): presets are `uzpainter/display-preset/1` JSON (`src/python/display.h`): `uzpainter.render.display.preset()`, `presets()` and `apply_preset()`, and the MCP `display_*` tools. Camera conversion follows the standard's `coordinate_contract`. Shipped environments are in `assets/environments/`, each with a record valid under `src/python/environment-provenance.schema.json`.
- Environments are stored in the project as bytes plus SHA-256; a missing environment is an explicit error, never a substitute (RES-03). UzPainter ships CC0 environments (Poly Haven) under UzPainter names; Adobe environments are never shipped or committed and are used only on the owner's machine, by hash, as private test inputs (`docs/licensing-and-clean-room.md` §1).

## 8. Settling evidence

- **Phase 0 (P0-FEAS-RENDER):** an answer, with evidence, for every "not confirmed" row of §2.1; the qualified capture procedure; two session-separated references plus one k·S reference per analytic fixture; the noise-floor report; first clean-room lobe fits with residuals; DXR Tier 1.1 and Vulkan ray-query probes on the owner's GPU; the analytic fixture values proposed to the owner. The noise-floor report's term (c) is the feasibility prototype's; P3 measures the shipped tracer's with the same statistics (decision 050).
- **Phase 2 (P2-PREVIEW):** `painter_viewport`, display presets, preview window. Phase 2 provides capture for preview and diagnostic modes; `painter_iray` remains an explicit unavailable capability until P3-PATHTRACER passes.
- **Phase 3 (P3-PATHTRACER):** `painter_iray` on both backends; the cross-backend report; Vulkan ray tracing qualified against DXR on the analytic fixtures (`13-engine-integration.md` §7); the Tier 3 report with the exception proposals the owner must approve.
