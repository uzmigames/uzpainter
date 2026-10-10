# 06 — Baking

Implements D5 (`05-resolution.md`) and owner answer Q9 (decision 022: CPU baking needs no GPU; the GPU path runs on DX12 and Vulkan). Requirements: BAK-01…08, INT-13, PRJ-04 (`docs/prd.md`). Painter facts: the public `baking` API documentation and Adobe's public mesh-map settings pages (`docs/analysis/substance-parity/03-baking.md` is quarantined, historical context only); pipeline practice: `docs/analysis/assets3d-pipeline/03-bake-settings.md`.

## 1. Backends

```cpp
struct IBaker { virtual Capabilities caps() = 0;              // which usages, max resolution, determinism class
                virtual JobHandle bake(const BakeRequest&) = 0; };   // one texture set, enabled usages, settings, input revision
```

- **`EmbreeBaker` (v1 reference).** Embree 4.x from upstream (Apache-2.0), pinned version and build configuration (ISA set, internal tasking or TBB, no fast-math), vendored with its notices. Needs no GPU: CPU baking runs on the Windows/CPU/ISA configurations qualified for the pinned Embree build; unsupported configurations receive an explicit capability error; cross-machine repeatability is measured separately (below). No Adobe binary is used or consulted.
- **`GpuBaker` (later, optional; DAG node P4-DXR).** Same `BakeRequest`, same sample sequences, two backends on the vendored render core (`13-engine-integration.md` §2): **DX12** with DXR Tier 1.1 and SM6.5 `RayQuery` kernels (the vendored capability check tests only Tier 1.0 — `docs/analysis/uzengine-renderer/10-review-response.md` F04 — and is extended in UzPainter's copy, `13-…` §3.4) and **Vulkan** with `VK_KHR_ray_query` and `VK_KHR_acceleration_structure` (added by UzPainter; the vendored code has no Vulkan ray tracing). UzPainter builds the acceleration structures from the high-poly streams with explicit vertex strides (`12-mesh-import.md` §2). Each backend is qualified separately against the Embree outputs and the Painter goldens; the GPU path is never a requirement for importing maps or stack operations.

Determinism: fixed per-texel sample addressing (Hammersley by texel index and sample id), fixed reduction order, tile-based work partitioning independent of thread count → repeatable on one build and configuration. Cross-machine bit identity is measured on the qualified CPU/ISA matrix, not promised.

## 2. Bakers and parameters

Ten `MeshMapUsage` bakers: `Normal`, `WorldSpaceNormal`, `ID`, `AO`, `Curvature`, `Position`, `Thickness`, `Height`, `BentNormals`, `Opacity`. Parameters mirror Painter's dynamic `Property` model: `BakingParameters.common()` (common + detail), `baker(usage)`, `set({Property: value})`, `Property.{value,name,short_name,label,widget_type,enum_values,enum_value,properties}`.

| Group | Keys (Painter short names) |
|---|---|
| Common | `OutputSize` (log2 pair), `DilationWidth`, `ApplyDiffusion` |
| Detail (high-poly) | `HipolyMesh` (pipe-joined `file:///` URLs), `LowAsHigh`, `CageMode` (Distance-based / Automatic / Custom file), `CageMesh`, `MaxHeight`, `MaxDepth`, `RelativeScale`, `SmoothNormals`, `IgnoreBackface`, `FilterMethod` (Always / By mesh name), `LowpolySuffix` `_low`, `HipolySuffix` `_high`, `BackfaceCullingSuffix` `_ignorebf`, `SubSampling` (None / 2×2 / 4×4 / 8×8), `SkewFaceBehavior`, `OffsetMap` |
| AO / BentNormals | `NbSecondary`, `MinDistance`, `MaxDistance`, `MaxDistanceRelativeScale`, `Spread`, `Distribution`, `IgnoreBackfaceSecondary`, `FilterMethodSecondary`; AO also `Attenuation`, `GroundPlane`, `GroundOffset` |
| Curvature | `NbSecondary`, `SamplingRadius`, `MaxDistanceRelativeScale`, `AutoMinMax`, `TonemappingBounds`; `CurvatureMethod` FromMesh / FromNormalMap |
| Position | `Mode`, `Axis`, `Normalization`, `NormalizationScale` |
| Thickness / Height | `NbSecondary`, distances, `Spread`, `Distribution`, `MaximizeRange`; Height also `Divisor` |
| ID | `ColorSource` (Vertex Color, Material Color, File ID, Mesh ID/Polygroup), `ColorGenerator` (Random, Hue shift, Grayscale) |

All key names, labels, widget types, enum labels and ranges are taken from the documented discovery API (`BakingParameters.common().keys()`, `baker(usage).keys()`, `Property.label()/widget_type()/enum_values()/properties()` — `PAINTER\resources\python-doc\substance_painter\baking.html`, `properties.html`) run on a fresh Painter project in Phase 0, and from Adobe's public mesh-map settings pages; the historical catalogue in `03-baking.md` §3 is historical context, not an implementation input (`docs/licensing-and-clean-room.md`). Baker algorithms are UzPainter's own, written from public ray-casting literature and calibrated black-box. **Defaults** are captured in Phase 0 through the documented API (`Property.value()` for every key of `common()` and `baker(usage)` on a fresh Painter 12.1.0 project); that capture is a private oracle record, kept in the private store with only its hash in the repository (`14-parity-testing.md` §6). The default table UzPainter ships (`assets/defaults/baking.json`) is authored by UzmiGames, never generated from the capture: each entry records its provenance (the public page that states the value, or the hash of the private observation it must equal) and is checked against the capture on the self-hosted runner. Enum integers are taken from Painter's `enum_values()` labels, never guessed.

## 3. Semantics

- Cage: custom cage mesh, or distance-based frontal/rear distances (absolute or relative to the bounding box); `Automatic` cage is a release gap until its behaviour is established against Painter.
- Match by name with the three suffixes; `LowAsHigh` bakes the low onto itself.
- Antialiasing: `SubSampling` supersamples per texel and averages — explicit coverage accumulation, not MSAA.
- Dilation: `DilationWidth` texels with optional diffusion, applied to the baked map only (the RAW map is kept).
- Curvature normalisation: `AutoMinMax` computes bounds over the set; the **effective** bounds are recorded in the binding so a re-bake or a linked set can reuse them (lesson `A3D\...\00-Corpo\report.json → painting_v6.rebake_mesh_maps.curvatura_membros`).
- Units: distances follow the project's unit rule (`12-mesh-import.md` §3) and are recorded with the map.
- Normal baker: tangent space from the texturing mesh's MikkTSpace frame with the project's `TangentSpace` mode; output convention per `NormalMapFormat`; the convention fixture of `14-parity-testing.md` §2 is a prerequisite.
- Linked groups: `set_linked_group`, `set_linked_group_common_parameters`, `unlink_all*`, `get_link_group*`, `get_linked_texture_sets*` as Painter; a settings change is one transaction across every linked set.

## 4. Outputs and evidence

Per bake and usage: the **compatible map** (what Painter would produce) plus evidence maps that never alter it: `raw` (before dilation), `hit` (straight / cage hit), `coverage` (texel centre, conservative used surface), `miss` (used-surface texels without a hit), `extension` (dilated texels), per-class counts and the per-part Z<0 statistics the pipeline asks for (`docs/analysis/assets3d-pipeline/07-lessons-and-pitfalls.md` §3). AO reports misses from hit evidence, distinct from real holes, hidden surfaces and low AO (BAK-04); a second pass with wider distances applied only to missed texels is a documented option.

**Bake receipt (BAK-07).** Every bake writes a `BakeReceipt`; its accounting is a tested contract, not only a schema:

```
BakeReceipt { job_id, texture_set, input_revision, status, settings_hash,
  tools  {baker_version, backend: embree|dx12_rt|vulkan_rt, backend_version, isa_or_gpu, build_hash},
  inputs {low_mesh_hashes, parts[] {name, high_meshes[] sha256, cage: sha256 | {frontal, rear, relative}}, hidden_mask sha256?},
  usages[] { usage, map sha256, raw sha256,
    coverage     {centre_texels, conservative_texels},
    used_surface {hit_straight, hit_cage, miss, hidden, ring_extended, ring_no_hit_neighbour, repaired},
    fallback_texels, padding_texels, changed_used_texels, surface_modified,
    fidelity_evidence: used_surface_as_baked | contains_fallback | diagnostic_only,
    parts[] {name, hits, misses, z_negative_texels}, effective_normalization } }
```

The used surface is the conservative coverage. Its seven classes are disjoint and sum to `coverage.conservative_texels` — the conservation rule of the pipeline's `used_surface_summary` (`A3D\Docs\Pipeline\Pintura\bake_normal_pair.py`): straight and cage hits, centre misses, hidden texels (only with a hidden mask), ring texels filled from neighbouring hits, ring texels without a hit neighbour, and repaired texels. `fallback_texels` counts used texels set to a neutral value, which happens only when the request enables a fallback; the compatible map otherwise keeps Painter's behaviour. `padding_texels` lie outside the used surface; `changed_used_texels` counts used texels that differ from RAW. UzPainter never repairs on its own; a low normal Z is reported as an inspection signal, never used to replace values. Tests: analytic fixtures (plane, sphere, bevelled cube with highs, a part with a buried face) with known expected counts per class; the test asserts the exact counts and the conservation identity, not only JSON validity.

Publication is atomic per `(texture set, input revision)`: either all enabled usages are bound with provenance (`03-project-model.md` §4) and the receipt is stored with them, or the job fails/cancels with no partial authoritative bake; evidence maps are stored under `cache/` and are regenerable.

## 5. External mesh maps

`project.create(mesh, mesh_map_file_paths=[…])` and `TextureSet.set_mesh_map_resource(usage, resource)` accept 16-bit PNG/EXR maps (geometry-only OpenGL normal, AO, curvature, WSN, position, thickness as produced by `A3D\Docs\Pipeline\Pintura\bake_normal_pair.py` and `garment_blender_io.py`); original bytes and declared role/convention/units are kept (BAK-01). Generators bind by usage regardless of origin. External maps are the migration reference for the Assets3D corpus; they never certify native bake parity.

## 6. Job model

`bake_async(texture_set) → StopSource` and `bake_selected_textures_async()` in the facade over a native `Job` with id, progress, `cancel()`, terminal status `Success | Cancel | Fail` and per-baker error detail. Events `BakingProcessAboutToStart(stop_source)`, `BakingProcessProgress(progress)`, `BakingProcessEnded(status)` are dispatched on the Python dispatcher thread; `project.is_busy()` is true while the job runs. Cancellation is acknowledged immediately and the receipt states whether the bake stopped before or after publication.

## 7. Parity (Tier 2b)

Reference: Painter's CPU bakers (Adobe records CPU/GPU AO differences, Painter 12.0 release notes cited in `docs/analysis/reviews/technology-options-astra-review.md` finding 1); the backend used is recorded in every golden. Fixtures: analytic (plane, sphere, bevelled cube with highs), the wand and hat low/high/cage pairs; compare `hit`/coverage first, then maps; repeat across thread counts and ISAs. Equality is the gate; an unreachable channel is a release gap or an owner exception.
