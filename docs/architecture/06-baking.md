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

All key names, labels, widget types, enum labels and ranges are taken from the documented discovery API (`BakingParameters.common().keys()`, `baker(usage).keys()`, `Property.label()/widget_type()/enum_values()/properties()` — `PAINTER\resources\python-doc\substance_painter\baking.html`, `properties.html`) run on a fresh Painter project in Phase 0, and from Adobe's public mesh-map settings pages; the historical catalogue in `03-baking.md` §3 is historical context, not an implementation input (`docs/licensing-and-clean-room.md`). Baker algorithms are UzPainter's own, written from public ray-casting literature and calibrated black-box. **Defaults** are captured in Phase 0 through the documented API (`Property.value()` for every key of `common()` and `baker(usage)` on a fresh Painter 12.1.0 project, recorded again with each oracle envelope, decision 037); that capture is a private oracle record, kept in the private store with only its hash in the repository (`14-parity-testing.md` §6). The default table UzPainter ships (`assets/defaults/baking.json`) is authored by UzmiGames, never generated from the capture: each entry records its provenance (the public page that states the value, or the hash of the private observation it must equal) and is checked against the capture in a local run on the owner's machine (decision 028). Enum integers are taken from Painter's `enum_values()` labels, never guessed.

The table is `assets/defaults/baking.json` (decision 323).
- **What it holds.** For `common()` and every baker, each key with its name, short name, label, widget type, value type, enum values, range and default. Each entry cites the Painter 12.1.5 record by SHA-256.
- **How the model reads it.** `src/bake/baking_parameters.*` embeds the table and builds `Property` from it.
- **What the model refuses.** `Property.properties()` raises `NotYetSupported`: Painter's meta properties carry its descriptive text, which is not reproduced. A default Painter does not state (`OutputSize`, `TonemappingBounds`) and a value outside a key's range raise `NotYetSupported` too.
- **The local check.** `python -m tools.bake.bake_defaults check [--model <dump>]` compares the table with the record in the private store, read only. With `--model`, it also compares the native model's dump (`uzp-baking-project-tests catalog`) with the table. `tests/bake/test_bake_defaults.py` and `tests/bake/test_baking_project.py` run both.
- **The Python surface.** `substance_painter.baking.BakingParameters` and `properties.Property` bind the model (`src/python/bind_baking.cpp`, `python/uzpainter_facade/baking.py`): `from_texture_set`, `common()`, `baker(usage)`, `set()`, the `Property` getters and the fresh texture set's baking state. The refusals above hold there too, and the bake and the link groups stay release gaps (phase3.5_embree-bakers). `tests/python/test_pyapi_baking.py` replays the Tier 0 golden through the recorder's own Painter-side code and compares every captured field exactly, the refused ones named (item 3.1).

## 3. Semantics

- Cage: custom cage mesh, or distance-based frontal/rear distances (absolute or relative to the bounding box); `Automatic` cage is a release gap until its behaviour is established against Painter (capability manifest `bake_async` @ `cage-mode:automatic`). The box size a relative distance is a fraction of is not recorded, so a relative bake is refused unless the request names it (`relative-to-bounding-box`; decisions 311 and 323).
- Match by name with the three suffixes; `LowAsHigh` bakes the low onto itself.
- Antialiasing: `SubSampling` supersamples per texel and averages — explicit coverage accumulation, not MSAA.
- Dilation: `DilationWidth` texels with optional diffusion, applied to the baked map only (the RAW map is kept); diffusion is refused until a recording settles it (`apply-diffusion`; decision 323).
- Curvature normalisation: `AutoMinMax` computes bounds over the set; the **effective** bounds are recorded in the binding so a re-bake or a linked set can reuse them (lesson `A3D\...\00-Corpo\report.json → painting_v6.rebake_mesh_maps.curvatura_membros`).
- Units: distances follow the project's unit rule (`12-mesh-import.md` §3) and are recorded with the map.
- Normal baker: tangent space from the texturing mesh's MikkTSpace frame with the project's `TangentSpace` mode; output convention per `NormalMapFormat`; the convention fixture of `14-parity-testing.md` §2 is a prerequisite.
- Linked groups: `set_linked_group`, `set_linked_group_common_parameters`, `unlink_all*`, `get_link_group*`, `get_linked_texture_sets*` as Painter; a settings change is one transaction across every linked set.

### 3.1 Project persistence of linked parameters

`src/bake/baking_project.h` connects the supported Common/Detail and AO parameter
model to the project document. `LoadBakingSession(project)` creates an independent
session; `StoreBakingSession(session, project)` stores all sets together.
`EditBakingSession(edit, callback)` operates on a transaction's private project,
and `ExecuteBakingSession(document, request, callback)` uses the document's normal
admission, revision and commit-sink rules. The document remains the source of
truth: a refused request, invalid parameter or failed commit publishes no settings
or link changes. A replay does not invoke the callback again.

Each texture set keeps explicit values in `bake_settings.common`, `detail` and
`per_baker.AO`. The UzPainter-owned `bake_settings.linked_groups` extension stores
`{common: [texture_set_id, ...], per_baker: {AO: [texture_set_id, ...]}}`.
Membership uses persistent texture-set IDs, never display names. Every set stores
the same group declaration; empty arrays explicitly mean unlinked. Unknown fields
outside this owned extension remain intact.

Loading first validates every set independently, then checks the complete group
declarations and equality of the values being shared, and only then links the
session. Missing members, repeated IDs, inconsistent declarations or values, and
unsupported groups are refused without changing the project. This prevents the
last loaded member from silently overwriting another member's settings. If every
set lacks the extension, the legacy common-group default applies, provided the
common/detail values agree. Partial presence is invalid. Explicitly unlinked
projects stay unlinked after save and reopen.

This persistence contract does not establish Painter's unrecorded property types,
defaults, enum integers or regrouping rules. Those refusals and each remaining
baker's ownership continue to apply.

### 3.2 Native Normal calculation

The CPU request accepts `Normal`, `AO`, or both, with the geometry maps of §3.3. For `Normal`, it interpolates the
high mesh's authored corner normals at the primary hit, normalizes that vector,
and expresses it through the inverse of the low mesh's interpolated MikkTSpace
frame. The frame is not orthonormalized. `normal.tangent_space` selects
`PerVertex` (the default from decision 031) or `PerFragment`. `LowParts` computes
MikkTSpace over the complete source object before selecting its material; the
result keeps one tangent and sign per triangle corner. A direct native `BakeMesh`
without tangents is treated as one complete object and computes them before the
job starts. Singular or non-finite frames fail the job without a result.

`normal_raw` and `normal` contain interleaved RGB16 codes. Each OpenGL component
uses the Phase 0 prototype's float32 operation order:
`e = clamp(n * 0.5f + 0.5f, 0, 1); code = floor(e * 65535.0f + 0.5f)`.
`normal.format = DirectX` complements the encoded green code, `65535 - G`,
including the neutral value `32768 -> 32767`. Negative Z remains negative;
misses, hidden texels and back-face hits keep zero codes and their separate
classification. No neutral fill or repair is implicit.

This native domain requires `SubSampling = 1`, `DilationWidth = 0` and identity
transforms on imported low objects. Normal supersample reduction, padding and
transformed frames require further evidence; requests outside this domain are
refused before a job starts. Existing cage, diffusion and relative-distance
refusals remain. A Normal-only request ignores AO settings, casts no secondary
rays and leaves AO maps empty. A combined request shares primary hits and retains
the AO calculation.

AO-only canonical results retain `UZPBAKE3`; results containing Normal use
`UZPBAKE4` with usage and normal configuration metadata. Thread counts remain
outside the canonical bytes. Both usages remain `pending-evidence`, owned by
`phase3.4_baker-ao` and `phase3.2_baker-normal` respectively. This native calculation
does not expose baking through Python/MCP, establish unrecorded defaults or
certify Painter equality. Phase 0's calibrated residual of up to one RGB16 code
does not satisfy the Tier 2b equality gate.

### 3.3 Native geometry maps

Decisions 337 and 341 add geometry maps to the CPU request, on the same primary hits as AO and Normal.
Each map has its own file in `src/bake/` and its own owner task. The rules they share:
- A parameter value whose label names one computation on the bake mesh's data is implemented.
  Any other value is refused before a job starts, with `NotYetSupported` naming the owner task.
- `SubSampling` above 1 and `DilationWidth` above 0 are refused: the resolve and padding rules of
  these maps are not recorded.
- Non-hit texels hold zero and keep their class. Nothing is filled.
- Combined with AO or Normal, a map shares the primary hits and leaves the other maps' bytes
  unchanged.
- In the canonical bytes, each map present follows the distance record as a tagged block. A result
  without these maps keeps its `UZPBAKE3`/`UZPBAKE4` bytes.

**WorldSpaceNormal** (`world_normal_baker.*`, phase3.4_baker-world-space-normal). The map holds the
high mesh's interpolated corner normal at the hit, normalised in double. The frame is the meshes'
scene frame (object transforms applied, normals through the inverse transpose). With `LowAsHigh`,
the normal is the low mesh's own. `world_normal` stores float32 xyz, signed and unencoded: Painter's
channel format and value mapping wait on the Tier 2b goldens. Block tag: `WSN1`.

**Position** (`position_baker.*`, phase3.4_baker-position). The map holds the high surface point at
the hit, in the same frame. All axis writes xyz; One axis writes the coordinate on `Axis`.
`Normalization` None writes centimetres (mesh units times `scale_to_internal`); with no bounds,
`NormalizationScale` has no effect. BBox and BSphere, Painter's default, are refused: their bounds
and mapping are not recorded. `position` is float32 and unclamped. `PositionNormalizationRecord`
holds the applied normalisation, and `PositionNormalizationJson` gives it as the binding's
`baked.effective_normalization`. Block tag: `POS1`. Position's parameter values are stored per
texture set (`StoresBakerValues`) in `bake_settings.per_baker.Position`, with no link group.

**ID** (`id_baker.*`, phase3.4_baker-id). With `ColorSource` Mesh ID / Polygroup, a hit texel's
label is the index of the high mesh it hit plus one, in request order (`LowAsHigh`: the low part).
`id_labels` is uint16, 0 off hits, and `id_label_meshes` names the meshes in label order. Block tag:
`IDM1`. Vertex color, Material color (Painter's default), File ID and Submesh are refused: the bake
mesh carries no such input, or nothing recorded describes it. Every `ColorGenerator` is refused too,
because the colour Painter gives a label is not recorded. So no colour map exists yet: a request
without a generator bakes the labels only, and a request made from parameters always names one. ID's
values are stored per texture set in `bake_settings.per_baker.ID`, with no link group.

**Opacity** (`opacity_baker.*`, phase3.4_baker-opacity, decision 341). The map holds the opacity of
the high surface at the hit. A bake mesh carries no transparency input, so a hit is 1 and every
other texel 0 with its class. `opacity` is float32 in [0, 1], unencoded: Painter's channel format
waits on the Tier 2b goldens. Opacity has no parameters. Block tag: `OPA1`.

**Height** (`height_baker.*`, phase3.4_baker-height, decision 341). The map holds the signed distance
from the low surface to the high surface along the primary ray, positive where the high surface lies
in front of the low one (towards the ray's origin), in centimetres (mesh units times
`scale_to_internal`). Every `MaximizeRange` value is refused, Painter's default "Relative to low
mesh (per UV tile)" included: how each maps a signed distance to a value, and how `Divisor` composes
with it, are not recorded. So only a request without a normalisation bakes, an evidence request no
parameter makes; `Divisor` is recorded and not applied. `height_map` is float32 and unclamped.
`HeightNormalizationRecord` holds what was applied, and `HeightNormalizationJson` gives it as the
binding's `baked.effective_normalization`. Block tag: `HGT1`. Height's values are stored per texture
set in `bake_settings.per_baker.Height`, with no link group. Painter's Height has no secondary-ray
keys (decision 323's record), so none is read.

Parity is `pending-evidence` for every map. Python and MCP expose no bake.

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

The used surface is the conservative coverage. Its seven classes are disjoint and sum to `coverage.conservative_texels` — the conservation rule of the pipeline's `used_surface_summary` (`A3D\Pipeline\painting\bake_normal_pair.py`): straight and cage hits, centre misses, hidden texels (only with a hidden mask), ring texels filled from neighbouring hits, ring texels without a hit neighbour, and repaired texels. `fallback_texels` counts used texels set to a neutral value, which happens only when the request enables a fallback; the compatible map otherwise keeps Painter's behaviour. `padding_texels` lie outside the used surface; `changed_used_texels` counts used texels that differ from RAW. UzPainter never repairs on its own; a low normal Z is reported as an inspection signal, never used to replace values. Tests: analytic fixtures (plane, sphere, bevelled cube with highs, a part with a buried face) with known expected counts per class; the test asserts the exact counts and the conservation identity, not only JSON validity.

Publication is atomic per `(texture set, input revision)`: either all enabled usages are bound with provenance (`03-project-model.md` §4) and the receipt is stored with them, or the job fails/cancels with no partial authoritative bake; evidence maps are stored under `cache/` and are regenerable.

## 5. External mesh maps

`project.create(mesh, mesh_map_file_paths=[…])` and `TextureSet.set_mesh_map_resource(usage, resource)` accept 16-bit PNG/EXR maps (geometry-only OpenGL normal, AO, curvature, WSN, position, thickness as produced by `A3D\Pipeline\painting\bake_normal_pair.py` and `garment_blender_io.py`); original bytes and declared role/convention/units are kept (BAK-01). Generators bind by usage regardless of origin. External maps are the migration reference for the Assets3D corpus; they never certify native bake parity.

## 6. Job model

`bake_async(texture_set) → StopSource` and `bake_selected_textures_async()` in the facade over a native `Job` with id, progress, `cancel()`, terminal status `Success | Cancel | Fail` and per-baker error detail. Events `BakingProcessAboutToStart(stop_source)`, `BakingProcessProgress(progress)`, `BakingProcessEnded(status)` are dispatched on the Python dispatcher thread; `project.is_busy()` is true while the job runs. Cancellation is acknowledged immediately and the receipt states whether the bake stopped before or after publication.

## 7. Parity (Tier 2b)

Reference: Painter's CPU bakers (Adobe records CPU/GPU AO differences, Painter 12.0 release notes cited in `docs/analysis/reviews/technology-options-astra-review.md` finding 1); the backend used is recorded in every golden. Fixtures: analytic (plane, sphere, bevelled cube with highs), the wand and hat low/high/cage pairs; compare `hit`/coverage first, then maps; repeat across thread counts and ISAs. Equality is the gate; an unreachable channel is a release gap or an owner exception.
