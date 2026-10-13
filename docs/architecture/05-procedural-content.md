# 05 — Procedural content

Implements D4 (`05-resolution.md`; the legal route was decided by the owner on 2026-10-10: clean room, Apache-2.0, no Adobe content — `docs/licensing-and-clean-room.md`). Requirements: MAT-02, MAT-03, MAT-04, LAY-11, RES-04, ARC-05, CLR-01…06 (`docs/prd.md`). Owner answers applied: Q1 (decision 017: exact equality, divergence only through an owner-approved exception) and Q5 (decision 019: milestones named by proven scope, gaps visible); publication rule per Astra F01 (§3).

## 1. The problem

Painter's generators, filters, grunges, materials, smart masks and smart materials are Substance (`.sbsar`) graphs executed by Adobe's proprietary engine shipped with Painter. UzPainter cannot execute `.sbsar` files and will not link, bundle or depend on any Adobe binary. The locked bracer recipe and the body and hat stacks depend on these assets (`A3D\...\22-Bracal-Direito\report.json → leather_family_recipe_r9`, `00-Corpo\report.json → painting_v3`, `10-Chapeu\report.json → painter_recipe`). A licensed Substance runtime adapter and shipping Painter-derived captures were considered and rejected by the owner (decision 002).

## 2. Backend seam

```cpp
struct ProceduralRequest { AssetId asset; Version version; Params params; Preset preset; ImageInputs inputs /* mesh maps, anchors, bitmaps by hash */;
                           uint32 resolution; ChannelFormat format; ColorSpace space; TileRect tile; uint64 seed; };
struct IProceduralBackend { virtual ParityStatus status(AssetId, Version) = 0;   // exact | calibrated{metric} | unavailable
                            virtual bool canEvaluate(const ProceduralRequest&) = 0;
                            virtual Future<Raster> evaluate(const ProceduralRequest&) = 0; };
```

Backends, tried in this order per asset: `SnapshotBackend` (frozen per-project snapshots), `HlslBackend` (certified UzPainter resource families). `HlslBackend.canEvaluate` is true only inside the asset's certified editable domain (§6). An asset with no backend able to serve the request raises `UnsupportedProcedural{asset, reason}` before any mutation; it never substitutes a visually similar asset. There is no Adobe runtime adapter behind this seam, and none is reserved (decision 002).

## 3. Certified resource families (`HlslBackend`)

UzPainter's own implementations, written from public literature (procedural noise: Perlin 1985/2002, simplex and Worley noise, fBm; edge/cavity detection from curvature and ambient-occlusion maps; standard morphological and blur operators) and the parameter semantics Adobe documents publicly for its generators (names, ranges, labels discovered through the `Property` API), then calibrated black-box against Painter outputs recorded as private oracles. Each family ships with a provenance record (public sources, author, calibration corpus id, held-out corpus id, certified editable domain, residuals; §6). Initial corpus, from the recipes in `docs/analysis/assets3d-pipeline/04-painting-recipes-and-materials.md`:

| Family | Painter assets to reproduce (names used as compatibility aliases) | Inputs |
|---|---|---|
| Mesh-map generators | Mask Builder (Legacy), Mask Editor, Metal Edge Wear, Dirt, Curvature, Position, World Space Normals, Ambient Occlusion generators | AO, curvature, position, WSN, thickness mesh maps; parameters |
| Filters | Sharpen (hat v8), grayscale conversion, Levels (native effect), Blur (the Tier 0 `effect-order` golden; decision 069) | layer content |
| Grunges and noises | the grunge, dirt, spots, scratches, rust, humidity and cracks procedurals the body and hat recipes reference; `fabric_linen` | tiling, seed, parameters |
| Materials | felt, leather grain, burlap, leather pattern | parameters, physical size |
| Smart masks | Dirt Cavities, Edge Dirty Cracks, Edges Uber, Ground Dirt, Dust Dirty, Occlusion Strong | expand to generator/levels/fill effect lists; the observed structures stay private (publication rule below) |
| Smart materials | Leather Damaged, Bronze Armor, the recorded forged-iron recipe | expand to groups referencing the families above; the observed structures stay private (publication rule below) |

Smart masks and smart materials are *structures* of layers and effects. **Publication rule:** public smart presets are independently designed UzmiGames recipes expressed in the documented layer/effect model. Adobe preset trees, parameter collections and serialized readbacks obtained during observation (inserting a preset in a scratch project and reading it back with `get_root_layer_nodes`, `content_effects`, `mask_effects`, `get_source`, `get_parameters`) remain private oracle or per-project migration data (`14-parity-testing.md` §6); changing their format or names does not qualify them for publication. Each shipped recipe records independently authored provenance, including a provenance record for every family and resource it uses, and passes output-parity tests: the same recipe rebuilt in Painter through the documented API produces equal outputs (Tier 2a). Painter's asset names are kept only in an internal compatibility alias table so existing scripts resolve them (`resource.search`). On the owner's machine an alias resolves to the private observed structure for migration and testing; where none is available it raises `UnsupportedProcedural{asset, reason: "private preset unavailable"}`. It never substitutes a UzmiGames recipe, which would be an art change (§5).

Parity status per asset is `exact` (zero residual on every calibration and held-out case of §6) or `calibrated{max |Δ|, mean |Δ|, p99 |Δ|, corpus id}`, published by `uzpainter assets list --parity`. Under Q1 there is no preset tolerance: a calibrated asset passes only through an owner-approved, versioned exception in the register (`14-parity-testing.md` §5); without one it is a failure.

## 4. Frozen snapshots (`SnapshotBackend`)

A snapshot is a raster the user's own Painter produced for the user's own project, recorded through the documented export API with a full **signature**: `{asset id, asset version, effective parameters incl. defaults, preset, seed, output id, resolution, channel format, colour space, image inputs by hash, project settings that affect evaluation}`. It is served only for a request whose signature matches exactly — no resampling, no parameter extrapolation; otherwise `unavailable`. Snapshots preserve an existing approved state during migration (Tunic v10, locked bracers); they never make an asset editable, never count as calibration or held-out evidence and never widen a certified editable domain (§6), and they are **project-private data**: embedded in that project's `.uzp`, never shipped with UzPainter, never copied into another project. A `uzpainter assets snapshot` command records them locally on a machine with the owner's Painter licence.

## 5. What remains unsupported

- Executing arbitrary `.sbsar` files; importing one raises `UnsupportedProcedural{reason: "no runtime"}`.
- Any Painter asset outside the certified families until it is reimplemented and calibrated; the capability manifest lists them as release gaps.
- A changed art corpus (replacing a Painter asset by a different UzPainter material) is a separately accepted art change, not parity.

These gaps stay visible in the capability manifest; milestones are named by the procedural scope they prove, and no "full replacement" of Painter's procedural content is claimed while a required gap is open (owner Q5).

## 6. Certification procedure (Tier 2a)

For each asset: three meshes (unit sphere, bevelled cube, hat v6 low with its mesh maps) × resolutions {1024, 2048, 4096} × parameter sets {defaults, each recipe's recorded set, two boundary sets} × seeds {recorded, one other}. Oracles are recorded with the owner's Painter through the documented API and stored privately (`14-…` §6). Compare native outputs; record max/mean/p99 and affected-texel counts; a non-zero residual is a candidate exception for the owner, never a pass.

That matrix is the **calibration set**: the cases a family is fitted against. Fitting them proves the fit, not that edits reproduce Painter, so certification adds three rules (decision 222):

- **Certified editable domain.** Before calibration each asset declares the domain it will certify, recorded in its provenance record, in `uzpainter assets list --parity` and in the capability manifest:
  - parameters: per parameter a closed range or an enumerated set, inside the documented range found through the `Property` API, plus any joint constraint between parameters;
  - seeds: the seed policy (any 32-bit seed, or a listed set);
  - geometry: the image inputs by checkable properties (mesh-map usages present, their resolution, format and colour space, a single UV tile) and the mesh classes the held-out meshes stand for;
  - output: resolutions, channel formats and colour spaces.
- **Held-out set, reserved before calibration.** In the same recording batch as the calibration set, record an independent held-out set that is never used for fitting: at least one mesh that is not in the calibration set, interior parameter points drawn inside each declared range, seeds that are not in the calibration set, and at least one resolution per family. Its hash list is committed to the batch manifest before calibration starts. An asset is `exact` only if both sets are exact. A held-out case that has been looked at to change a fit is spent: it moves to the calibration set as a regression case, and a new held-out set is recorded before the asset can be certified. A held-out failure is a failure (or a candidate exception for the owner), never a reason to refit on the same cases.
- **Loud refusal outside the domain.** A request whose parameters, seed, image inputs or output settings fall outside the certified domain makes `HlslBackend.canEvaluate` false; unless a snapshot of the project matches its exact signature (§4), it raises `UnsupportedProcedural{asset, reason: "outside certified domain", field, value, certified range}` before any mutation. There is no clamping, no nearest-point substitution and no fallback to a similar asset. The uncovered part of the documented range is listed as a release gap in the capability manifest (`NotYetSupported` in `10-python-api.md` terms).

The certified domain states what the calibration and held-out cases sample; exact results on those cases are evidence for the domain, not a proof over every continuous value in it, and the Tier 2a report says so. Snapshots (§4) stay exact-signature-only migration data and certify no editing.

## 7. Painter API semantics to keep (from `python-doc`)

`SourceSubstance`: `get/set_parameters` (booleans passed as int, as documented; a value that no backend can serve — outside the asset's certified editable domain and matching no snapshot signature of the project — raises `UnsupportedProcedural` before mutation, §6), `get_properties`, `get_preset_list`/`apply_preset`, `image_inputs` with `get/set/reset/remove_source` (bitmap, colour, anchor), `image_outputs`, `output_mapping`, `active_output`, `mask_output`, `resolution: ResolutionOverride{mode, value, log2_offset}` with the documented constraints (power of two in [128, 4096]; `Auto` follows the texture-set resolution; raises for sources used by a Filter effect). Generators bind mesh maps by usage automatically (Adobe's public "Mesh Map" documentation); a missing or invalid mesh map fails evaluation loudly.
