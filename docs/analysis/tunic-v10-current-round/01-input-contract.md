# Tunic v10 current round: input contract

The input contract for the pinned current round `phase2/tier1/tunic-v10-current` (decision 300 items 7 and 8; phase2.10 items 2.1 and 2.8). It is derived from the admitted Tunic v10 migration golden (decision 215) and the piece's committed report. This is technical preparation: it is not a baseline policy and approves nothing. Revised on 2026-11-02 after two 9router reviews (`cx/gpt-6-astra`, `cx/gpt-6.1-sol`). The revision added the OBJ position and normal checks, the effective Cycles device check, the pinned decoding of the Normal, array checks on the intermediates, the exact mesh-map state, and explicit project settings. It also relabelled the normal-map format as authored. This page holds only counts, public names, statuses and hashes. The detail, with the readback values it was derived from, is private (`%LOCALAPPDATA%\UzPainter\tunic-v10-current-contract.json`, SHA-256 `3b61cf98a15c…`, 18,575 bytes).

**Result.** The round cannot be requested yet, and no current Painter round may run until this contract and every input are complete.
- **Preserved and verified.** The 8 recovered masks, the Normal, the stack working copy, the export configuration and the scripts.
- **Missing.** The 9 substitute masks, every generator intermediate, and the low OBJ, which has no exporter yet.
- **Recorder gaps.** The recorder cannot load the chosen route yet (see Readiness).
- **The candidate meshes.** They are not inspected yet.

## Binding

| Item | Value |
|---|---|
| Migration golden | `phase2/tier1/tunic-v10`, admitted (decision 215) |
| Public manifest (current envelope) | `parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/manifests/phase2/tier1/tunic-v10.json`, SHA-256 `ce702ddfcfe7…` |
| Private golden record | `59ef801eaf67c74879e3f5ec51dc526da110ce80fc364c4e366f2ba2582701bf` (138,731 bytes), loaded from the store |
| Environment record | `bcd2741110b9…` |
| Painter | `12.2.0+js-api.1.1.20`, OCIO (Painter's substance configuration) |
| Piece report | `report.json`, SHA-256 `7829b2add3961e6916bfba32fdea470c3736c2f060636fd8a03b0272a982af5f` (git blob `6cbd8011…`, the same at Assets3D `1c9a312a` and HEAD `a8a06a1c`; the checkout holds the blob's bytes) |
| Stack working copy | `tunic.working_copy` / `stack_bytes` of that report: 5,332 bytes, SHA-256 `a5bc5613f9507c184e1b6df29c0d5e59b9c87dd812bd04db5695847f963a3650`. The override applies to F03 only: F03 binds `M_piping_lining_v9`, and C07 keeps `M_piping` |
| Export configuration | `parity/fixtures/tier1/tunic-v10/export-config.json`, SHA-256 `7167a93ec10baf82f6d394efff7ea91d3f525b747ed1a71b47dc5bc75b846de8` |
| Preserved `.blend` | `18-Tunica-v10.blend`, SHA-256 `f6243a577f67…`, in the private store |
| Input inventory | `parity/reports/phase2/tunic-v10-input-inventory.md`, SHA-256 `ab4232e45319…` |

## What the saved state shows

- **Stability.** The r1 and r2 texture-set readbacks are equal, apart from the resource context (`projectN`).
- **Texture set.** One set, `DefaultMaterial`, at 4096 × 4096, with five channels.
- **The last-imported mesh.** `_tmp/astra-tunica/normalized_low.obj`. It is lost, and its hash is unknown.
- **Root.** One visible group, the v10 stack, holding 2 sub-groups and 22 fills. Beside it are 16 hidden fill layers from earlier versions; two of them carry generator mask effects.
- **Bindings in the visible group.** There are 21 mask fill effects (20 layer masks and the `Forro` group mask) on 17 resources, all with colour space Data.
  - 8 bindings are preserved, one per preserved file.
  - 13 bindings use the 9 missing masks. `M_pores`, `M_fray`, `M_hem` and `M_cav` are each bound twice.
- **The stack matches the working copy.** The `Forro` group's Height is Normal (`replace_height`), and the outer group's Height is LinearDodge.
- **Mesh maps.** Six of the ten slots are bound:
  - Normal, to `Tunic_v6_HighNormal`, the recovered Normal;
  - AO, Curvature, Position, Thickness and WorldSpaceNormal, to Painter-baked resources.

## Route (decided): decision 300 item 7 as written

Decision 300 item 7 fixes the Tunic's route: "the unchanged sync with the stack working copy and the F03 override (decision 194), on a project the recorder creates, with decision 194's export configuration". The round therefore has three steps:

1. **Create.** The recorder creates the project itself, not through a piece script.
2. **Sync.** The unchanged `painter_layer_stack.py sync` runs from the pinned snapshot.
3. **Export.** The recorder runs `substance_painter.export.export_project_textures` with `export-config.json` (`7167a93e…`), the migration golden's own configuration. So the current round writes the same five map names, `DefaultMaterial_{BaseColor_sRGB, Normal_Raw, Metallic_Raw, Roughness_Raw, Displacement_Raw}`, and `current_reference` pairs them one to one.

**Option B is rejected:** reusing the waist-v5 `painter_create.py` and `painter_export.py` that the Sash round runs.
- The create script hard-codes `default_texture_resolution=2048`, while the record holds 4096.
- It imports and binds an AO mesh map, which this round has no input for. The generator's `ao.npy` is not a Painter mesh map.
- It names its resources `_v5`, in the group `mesh_maps_v5`.
- The export script writes other names at `sizeLog2` 11.

## Arguments

A *derived* value is read from the record or the report. An *authored* value is chosen for the round and named as such. *Unknown* means the record does not state it.

| Step | Argument | Value | Status |
|---|---|---|---|
| 1 create (recorder) | `mesh` | the current round's low OBJ (see Meshes) | **missing**; it needs a committed exporter |
| | `default_texture_resolution` | 4096 | derived |
| | `normal_map_format` | OpenGL | authored. It matches the preserved Normal's encoding (the report's OpenGL tangent bake); the historical project setting is not read back and stays unknown |
| | `import_cameras` | False | authored |
| | every other `project.Settings` field | each one passed explicitly. The request lists each value, so no setting is left to preferences or host state | authored; unknown in the record |
| | Normal mesh map | the preserved Normal, imported with usage TEXTURE under the name `Tunic_v6_HighNormal` (derived), in the group `tunica18_v10c_mesh_maps` (authored), and bound as Normal | derived and authored |
| | other mesh maps | none bound, and no Painter bake | authored (see the risks) |
| | texture set | `DefaultMaterial` | derived; the OBJ's material must produce it |
| 2 `painter_layer_stack.py sync` | `--stack` | the working copy (`a5bc5613…`) | derived |
| | `--masks` | one folder with exactly 17 files, `<mask>.png`: 8 preserved and 9 substitutes | 9 **missing** |
| | `--state` | a fresh file, so every bitmap is imported | authored |
| | `--resource-prefix` | `v10c_` | authored. The historical names mix the `v9_` and `v10_` forms from several rounds, so one sync cannot reproduce them |
| | `--resource-group` | `tunica18_v10c` | authored; groups are not read back |
| | `--texture-set` | `DefaultMaterial` | derived |
| | `--stack-key`, `--keep-visible` | none | authored. The 16 hidden historical layers are not rebuilt |
| | import closure | `run.py`, `decision_evidence.py` and `stage_review_evidence.py` | pinned (see Scripts) |
| 3 config export | `config` | `export-config.json` (`7167a93e…`): shipped Blender (Principled BSDF) preset, `DefaultMaterial`, 16-bit PNG, `sizeLog2` 12, `infinite` padding, no dithering, no shader parameters | derived (the migration's own file) |

## Scripts

These are a named input choice for the current round, not a historical recovery. Every pin is the raw LF git blob, read from the Assets3D object database (`git cat-file`) into the private input store, with no checkout and no normalising after hashing. All six blobs were verified on 2026-11-02.

| Script | Commit | Git blob | SHA-256 of the blob (bytes) |
|---|---|---|---|
| `Pipeline/painting/painter_layer_stack.py` (sync) | `1c9a312a` | `c83a2db598e5…` | `834c4bca3d32ebdeb9cd705e699782ee86fb86eb6dcff277345fae7bd63827aa` (22,407) |
| `Pipeline/production/run.py` | `1c9a312a` | `dc93f607f7ae…` | `7d8017d256a2359d5062fcc6e9e06881fee5d2bbb113e8000f8fba819a85b0a2` (119,859) |
| `Pipeline/production/decision_evidence.py` | `1c9a312a` | `3967c1c1113d…` | `a1f11c9a6938a8c77284e63c3e515b78a892424df480d8931a90f825a1967d60` (12,533) |
| `Pipeline/production/stage_review_evidence.py` | `1c9a312a` | `868ee2714914…` | `598c774ade15d7893bec154aead7065ddb515fd5799ab42fcf8f6e97735f502a` (7,780) |
| `Pipeline/painting/garment_material_masks.py` (mask donor) | `f49fe67c` | `1539a06b0b3f…` | `dfed970b93a387fe9321a66538c483ef48216efd7bdbdd0489901eb91e2976ca` (28,507, no CR) |
| `Pipeline/painting/garment_blender_io.py` (extract donor) | `f49fe67c` | `27773e1b2979…` | `805f9ccc5430e47ac49c4b50651e271b2e6da68f8455fa231306f3462b0c8a4d` (13,617, no CR) |

- **The sync and its closure.** These are the same four pins as the Sash contract (`docs/analysis/sash-v5-current-round/01-input-contract.md`). The recorder's sync step now takes the typed options and the `import_closure` (`parity/RECORDER.md` §9a).
- **The donors' history.**
  - At `f49fe67c` (2026-10-11) the two donors moved unchanged from `Docs/Pipeline/Pintura/`, and the same blobs are still at HEAD `a8a06a1c`.
  - Both blobs first appear at `6c7a1a9b` (2026-10-06). The first commit, `76e92f06` (2026-10-05), holds other blobs at both paths.
  - The report names these scripts for v9 (2026-10-05) and records a later regression run against v9.
  - So which bytes made the recorded masks stays unestablished. The substitutes are current inputs, not recoveries.

## Inputs

### Preserved: the 8 masks and the Normal (never regenerated)

Each one was checked in the private store on 2026-11-02:
- its SHA-256 equals its `tunic.py` pin;
- each file is a PNG: the masks are 16-bit grey and the Normal is 16-bit RGB;
- its SHA-1 followed by `.image` equals one recorded version string, as written.

No version normalisation rule is adopted (decision 300).

| Binding | Source (packed image in the `.blend`) | SHA-1 |
|---|---|---|
| `M_band` (C05) | `Source_v10_M_band` | `45203ad9bd2f…` |
| `M_embro` (C06) | `Source_v10_M_embro` | `ee39f50a2363…` |
| `M_piping` (C07) | `Source_v10_M_piping` | `68ac4eba0a92…` |
| `M_hemband` (C08) | `Source_v10_M_hemband` | `53e97a5427f3…` |
| `M_lacerings` (C08b) | `Source_v10_M_lacerings` | `8f29b7fe1b4e…` |
| `M_laceholes` (C08c) | `Source_v10_M_laceholes` | `d3be1b18a871…` |
| `M_hemline` (C08d) | `Source_v10_M_hemline` | `00326e6cdcc1…` |
| `M_piping_lining_v9` (F03 only) | `Source_v9_M_piping` | `ccf4857c52a8…` |
| Normal mesh map | `Source_v6_HighNormal` | `a5de3314c3cd…` |

### Substitutes: only the 9 missing masks

The donor's `masks` command writes 16 masks. The round keeps only these 9. Its outputs for the 7 preserved names (`M_band`, `M_embro`, `M_piping`, `M_hemband`, `M_lacerings`, `M_laceholes`, `M_hemline`) are discarded, never bound.

| Mask | Bindings | What the pinned donor computes it from |
|---|---|---|
| `M_pores` | C02, F02 | raster position and normal |
| `M_fiber` | C02b | raster position, `M_pores` |
| `M_dyeinv` | C03 | raster position |
| `M_stains` | C04 | raster position |
| `M_fray` | C10, F04 | `rim_sd` (lining), position |
| `M_hem` | C11, F05 | height, position, the rim-tip term (`rim_sd`) |
| `M_cav` | C12, F06 | `ao.npy`, `geo` convexity |
| `M_ridgewear` | C13 | `rim_sd`, `geo` convexity, position |
| `M_lining` | the `Forro` group | `rim_sd` (1 minus the outer cloth) |

Their recorded SHA-1 versions (inventory) stay what the historical files would have to match. A substitute is not expected to match them, and is never accepted as an original.

### Generator intermediates (all required, all missing)

| Input | Producer and pinned arguments |
|---|---|
| `low.npz`: `co`, `lt`, `lv`, `uv`, `cn`, `lining` | `garment_blender_io.py extract --low-object 18-Tunica-Low --lining-attribute LiningMask`. The arrays are the evaluated low in world space: positions, loop triangles, loop vertices, active UV, corner normals and the POINT lining attribute |
| `highnormal.npy` | same run, `--normal-image Source_v6_HighNormal` (the preserved Normal's packed image) |
| `ao.npy` | same run, `--high-object 18-Tunica-High-OriginalFit --ao-resolution 2048 --ao-samples 96 --cage 0.006 --max-ray 0.014`. These are the values the report states for v9, and they equal the donor's defaults |
| `raster.npz`, `ridge.npy`, `rim_sd.npy`, `geo.npz` | `garment_material_masks.py fields --resolution 4096`, with no `--recipe` (the donor's built-in 18-Tunica defaults; the report keeps no separate v9 mask recipe) |
| the 9 masks | `garment_material_masks.py masks`, with no `--recipe` |

- **The Normal's role.** In the pinned donor, `highnormal.npy` feeds only `ridge.npy`, and through it the discarded `M_piping`. It is still required: the `fields` set is complete only with it.
- **The run.** It happens on a hash-checked private copy of the `.blend`, in a fresh `%LOCALAPPDATA%\UzPainter\oracle-work\<run>`.
- **Pins.** The run pins the Blender executable by SHA-256, and the Python, NumPy, SciPy and Pillow builds, with Pillow's zlib.
- **The Cycles device.** The donor's `use_gpu` enables OptiX when any OptiX device exists; otherwise Cycles keeps its default device. The donor runs unchanged, so the device is enforced by the machine:
  - the pinned value is OptiX on the pinned GPU;
  - after the bake, the wrapper reads the effective `scene.cycles.device` and the enabled devices from Blender;
  - it refuses a fallback, a mismatch, or a device it cannot read.
- **Array checks before `masks`.**
  - Every intermediate has its required keys, dtype and shape, and only finite values.
  - The arrays agree with each other: `lt` indexes `lv`, `lv` indexes `co` and `lining`, and `uv` and `cn` have one row per loop.
  - The rasters are 4096², and `ao.npy` is 2048².
  - A violation refuses the run.
- **Repeat.** A second, independent run must give byte-identical intermediates and masks.

### Meshes: to inspect on a private copy after a prepared review

The candidates are in the preserved `.blend` (`f6243a57…`):
- **The low.** `18-Tunica-Low`: 5,392 vertices, 11,000 triangles and `UVMap`, by the report.
- **The high.** `18-Tunica-High-OriginalFit`.

**Not known yet.** These are to be read from a hash-checked private copy, after a prepared review, and not now:
- each object's world matrix, modifier stack and shape keys;
- the low's material slots, and whether they give the texture set `DefaultMaterial`;
- whether a POINT attribute `LiningMask` exists. The report's mask recipe names `LiningMask`, while its source-recovery note lists `Source_Lining`;
- the colour-space setting of the packed `Source_v6_HighNormal`, which the extract reads through Blender's pixels;
- the evaluated counts.

**What the round requires of the meshes.**
- **The OBJ exporter.** The round's OBJ comes from a committed, deterministic exporter of `18-Tunica-Low` on the model of `tools/parity/tier1/sash_low_export.py`.
- **One source for both.** The OBJ and `low.npz` come from the same private copy and the same evaluated object.
  - **What the host checks.** It compares the OBJ against `low.npz`, corner by corner through `lt` and `lv`: triangles, positions (`co`), UVs (`uv`) and corner normals (`cn`).
  - **Conventions.** Both are fixed in the exporter's pins: one axis conversion, and the serialisation tolerance for positions and normals.
  - **Refusals.** Any other transform, rescale or normal recomputation, and any material other than the one that gives `DefaultMaterial`.
- **The Normal's decoding.** The inspection records the packed `Source_v6_HighNormal`: its identity (SHA-256 of its packed bytes), its colour-space setting, and how Blender decodes it into `highnormal.npy`. These are pinned before any generation. The extract checks them first and refuses a mismatch. The image and its settings are never changed to improve agreement.
- **No fitting.** Nothing is fitted, rescaled or normalised toward the golden, and no choice is made to make maps match. The earlier FBX and BaseMesh comparison is settled and is not repeated.

## Refusal rules

The donors downgrade silently or fill with zeros where the current round must refuse:

| Missing | What the pinned donor does | What the current round does |
|---|---|---|
| `LiningMask` (absent, or not a POINT attribute) | `extract` zero-fills `lining`, prints a warning and treats the whole mesh as outer cloth. `rim_sd` then has no boundary, `M_lining` comes out empty, and `M_fray`, `M_hem` and `M_ridgewear` change | refuses: `extract_report.lining_attribute` must name it, and the lining must cross 0.5 on at least one edge |
| Normal | without `--normal-image`, no `highnormal.npy` is written. `fields` then skips `ridge.npy` ("piping mask will be empty"), and `masks` uses zeros | refuses: the preserved Normal must pass its pins, and `highnormal.npy` and `ridge.npy` must exist |
| AO | without `--high-object`, no `ao.npy` is written. `masks` builds `M_cav` from pleat valleys only ("cavity uses pleat valleys only") | refuses: `ao.npy` must exist at the pinned resolution |

**The round also refuses on any of these.**
- **Inputs.**
  - Any preserved input whose SHA-256 or SHA-1 differs.
  - Any of the 9 masks absent, or not a 4096 px 16-bit grey PNG.
  - Any of the 17 files missing from the mask folder, or another file in it.
  - Any input not in the private store by hash before Painter starts: the request lists every absent role, as `sash_current` does.
- **Repeatability.** A repeat run that differs in any byte.
- **Behaviour.** Any change to the donors' bytes or behaviour beyond running them as committed with the pinned arguments.

## Readiness: what must exist before a request

1. **A recorder-native create step.** It calls `project.create` with the pinned settings, then imports and binds the Normal. Today `script_job_from_manifest` requires the create, sync and export steps all to be pipeline scripts.
2. **An export that is only the configuration export.** Today a job without an export script is refused. `current_reference` must still accept the current side's interface (`uzmigames_pipeline_scripts`), or be amended with it.
3. **The Tunic low exporter**, as described under Meshes.
4. **`tools/parity/tier1/tunic_intermediates*.py`.** It runs the two donors with the refusal rules above, on the coordinator's say-so.
5. **A Tunic current-request writer**, on the model of `tools/parity/recorder/sash_current.py`.
6. **The prepared mesh review and its private inspection.**

These are code tasks. None needs a stub or a guard bypass.

## Checks the recorded round must pass

- **Texture set.** `DefaultMaterial` at 4096 px, with the record's five channel formats.
- **Root.** The synced group is visible, plus Painter's hidden default layer.
- **Resources.** 21 bindings on 17 layer-stack resources, all colour space Data, with C07 and F03 resolving to different resources.
- **Mesh maps.** The exact slot state: Normal is bound to the preserved Normal, and every other slot is unbound. The round refuses any bake or other binding.
- **Maps.** The configuration's five maps, as 16-bit PNG at 4096 px.
- **Recordings.** The five exported maps are byte-identical across r1, r1-repeat and r2. The r1 and r2 readbacks are equal except for the resource context (`projectN`) and the project path. Version strings are compared literally.

## Double-sided state (settled)

Decision 196's amendment (SUP-030, under the owner's delegation) settles this. The phase2.10 task notes supersede item 2.8's older wording, and this contract raises no question about it and makes no policy choice.

- **In Painter.** The API cannot set this display state or read it back (§9b), so the Painter round neither sets it nor checks it.
- **In UzPainter.**
  - `double_sided=true` must survive save and reopen;
  - render parity is reported as false while it is true;
  - the exported maps stay unchanged.

## Pending owner approval

- **The changed baseline.** Using this round as phase2.10's changed baseline is the one pending item (decision 300 item 8). It is one yes or no, asked once a concrete comparison exists, and never decided by a panel.

## Open risks

- **Historical generator bytes.** They are unestablished (see Scripts). The substitutes' maps can differ from the approved v10.
- **The Painter-baked mesh maps.** In the migration project, AO, Curvature, Position, Thickness and WorldSpaceNormal were baked in Painter, and the 16 hidden layers exist only there. The visible stack binds no generator, but whether their absence changes any export is not established until the maps are compared.
- **The AO bake.** It depends on the Cycles device. The donor picks OptiX when it is available and records no device itself, so the wrapper's device check is the only guard.
- **Literal versions.** Identity rests on a SHA-1 plus `.image` text match. No rule is adopted.
- **Library builds.** The NumPy, SciPy, Pillow and zlib builds change the mask bytes, so they must be pinned.
- **`infinite` padding.** Its equality on the UzPainter side is still open (phase1.25 item 2.7). That does not affect this Painter round.
