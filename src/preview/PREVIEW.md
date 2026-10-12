# Preview viewport and window (`src/preview/`)

This folder holds `painter_viewport`, the realtime preview of `docs/architecture/07-preview-and-render-parity.md` §1, §5 and §6 (task `phase2.1_preview-viewport-window`; decisions 018, 042 and 134). It is a preview and a fast check. It is never the parity target and never acceptance evidence: Iray is the target, through `painter_iray` in Phase 3.

| File | What it does |
|---|---|
| `display_transform.{h,cpp}` | The one display configuration and its transform (item 2.3) |
| `environment.{h,cpp}` | Environment decoding and the image-based-lighting precomputation (item 2.1) |
| `viewport.{h,cpp}`, `shaders/viewport.hlsl` | The forward pass on the render layer (item 2.2) |
| `latest.h` | The wait-free hand-over between evaluation and the preview thread (item 2.4) |
| `preview.{h,cpp}` | The publisher side, the preview thread and its window (items 2.4 and 2.5) |
| `cli.{h,cpp}` | `UzPainter.exe --preview <file.uzp>` (item 2.5) |

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

## Pass (item 2.2)

One compute dispatch per frame on the render layer (`src/render/`):

1. **Visibility.** The CPU bins the triangles into 16 × 16-pixel tiles. Each pixel casts its centre ray against its tile's triangles in ascending order. The nearest hit wins; on a tie the lowest index wins. Both faces are visible.
2. **Material.** The default open-pbr instance (decision 042) supplies base colour, base metalness, specular roughness and the tangent-space normal. The normal is the project's combined `Normal_OpenGL` map, which carries height as bump. Each map is sampled bilinearly with wrapping. A channel with no map uses open-pbr's default: base colour 0.8, metalness 0, specular roughness 0.3, a flat normal. Emission (luminance 0) and opacity are off, as in the Iray fits.
3. **Normals.** The MikkTSpace frame of the interpolated corner frame. Where the perturbed normal faces away from the viewer, the interpolated normal is kept.
4. **Lighting.** Split-sum GGX specular, with `F0 = mix(0.04, base colour, metalness)` for IOR 1.5. Burley diffuse on the SH irradiance, scaled by one minus the dielectric specular albedo. The environment radiance is multiplied by `2^exposure` and by the fitted intensity scale 1.01919. Pixels with no hit show the clear colour: the standard's linear 0.1, which displays as 89.
5. **Output.** The linear colour as binary16 (`RGBA16Float`) and its display codes (`RGBA16Unorm`), read back through `TextureReadback`.

The same scene, build, adapter and driver give the same bytes. Kernels are IEEE-strict, use no atomics and loop in a fixed order.

## Preview thread and window (items 2.4 and 2.5)

- **Publishing.** `PreviewFeed` is called by the thread that evaluates. It keeps the last evaluated map of each texture set and slot, together with the revision, project, mesh and environment bytes. `Publish()` hands a snapshot to the triple buffer of `latest.h`. Only shared pointers are copied. The publisher never waits for, locks against or calls into the preview thread. A stalled or closed reader only means frames are replaced before they are taken.
- **The preview thread.** `PreviewHost` owns the preview thread. That thread has:
  - its own `render::Engine`, so preview rendering never queues in front of or behind evaluation on the worker's device;
  - the window, through the vendored `platform_window` and `input`. It is read-only, with an orbit camera only: left drag orbits, the wheel zooms.
- **Rendering.** At most one render every 200 ms, and none while the window is minimised. The image is drawn with GDI.
- **Panel.** The right-hand panel states that `painter_iray` is unavailable: no capture can exist before P3-PATHTRACER. It also gives the display configuration and the revision shown.
- **Errors.** An unsupported configuration, a missing environment or a project without a mesh is shown as text in place of the image.
- **Stall hook.** `Stall(true)` blocks the thread while it holds its frame. It is the test hook of item 3.2. In a Debug worker it is reached with `test_fault preview_stall` / `preview_resume` (decision 120).

Two ways to run it:

- **Standalone.** `UzPainter.exe --preview <file.uzp> [--gpu-backend dx12|vulkan]` opens the project as `run` does, holding its lock. It evaluates the preview's channels of every texture set once and shows the window. On close it prints `UZP_JSON:{"status": "closed", "frames_rendered", "revision_shown", "last_error"}`.
- **Attached.** `UzPainter.exe --worker … --preview`, or `--mcp … --preview`, which passes the flag to its workers. The worker publishes after every `evaluate_channel`, and lists the GPU-free `preview_status` tool.

## Regression goldens (item 2.6)

`tests/preview/viewport-goldens.json` holds UzPainter-vs-UzPainter goldens for three UzmiGames-authored fixtures under `sky-patch.exr`, each at 256 × 256:

- `parity/fixtures/render-procedure/sphere.obj`;
- `parity/fixtures/iray-references/plane.obj`, with a checker base colour and a tilted normal map;
- `parity/fixtures/iray-references/bevelled-cube.obj`, as a metal.

Each golden stores the SHA-256 of the display codes and of the linear binary16 values.

A golden is keyed by build, adapter and driver:

- the build is the XXH64 key of the viewport kernel, which covers its HLSL, the compile flags and DXC;
- the adapter is its name;
- the driver is the UMD version from DXGI.

The goldens are exact for a fixed key. They are a repeatability check, never a tier result. A key the file does not hold fails the test. It is recorded with `uzp-preview-tests viewport-golden <dir> tests/preview/viewport-goldens.json --bless` on the owner's machine (decision 028).
