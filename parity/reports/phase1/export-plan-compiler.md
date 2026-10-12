# `phase1.15_export-plan-compiler`: local run on the owner's machine and recording requests R-085, R-086

Child of `phase1.18_export-engine` (P1-EXPORT; `docs/architecture/08-export.md` §1, §2, §6; EXP-01, EXP-03, EXP-04, EXP-09, INT-13, QG-03). Under decision 028 the Tier 0 comparisons run locally against the private oracle store, and this report is their evidence. Run on 2026-10-11 on the branch `wt/phase1.15-export-plan` (base main `444406a`, current envelope `painter-12.1.5_js-api.1.1.20`). Decisions 076, 085, 086, 091, 092 and 131; continued on `wt/phase1.15-close` and `wt/close-export`. Implementation: `src/export/` (`src/export/EXPORT.md`).

**Result.**

- The plan compiler is implemented and its tests pass: 18 of 18 in `tests/export`.
- The dry run lists exactly the files Painter wrote on every compared Tier 0 export step: 165 steps, 0 differing.
- Every export probe of recording R-085 compiles as Painter behaved: 90 compilations, of which 6 are refused as not recorded (R-091). The refusals the probes settle are lifted (decision 091).
- Normal_OpenGL and Normal_DirectX, compiled as plan files and evaluated through `EvaluateFileOn`, equal their goldens: 40 maps, 72 comparisons, 0 differing values.
- `AO_Mixed` is not exact: its best model misses r1 at 31 values of recording R-086a (decision 092).
- Nine converted maps are fitted exactly on recording R-086b. They stay release gaps until the evaluator gives channel coverage and recording R-092 covers other templates. View_2D is a render, not an operator (decision 092).

Item 3.5 is closed on UzPainter's own written files, and items 3.6 and 4.1 as a scope split (decision 131). Item 1.1 waits on the prerequisite (§5).

## Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200 (the plan tests and the evaluation run on the CPU store) |
| Build | Zig 0.15.2, Debug; `zig build export-tests` and `zig build painter` exit 0 with `-Wall -Wextra -Werror -ffp-contract=off` |
| Profile | `painter-12.1-isolated-coverage-weights` (current) |
| Oracle | current envelope `painter-12.1.5_js-api.1.1.20`; r1 is the exact target where r1 and r2 differ (decision 032) |
| Commands | `python -m pytest tests/export` (15 passed); `python tests/export/tier0.py <uzp-export-tests.exe> <work>` regenerates `parity/semantics/virtual-maps.json` and `test_virtual_map_goldens_exact` requires the file to equal it |

## 1. Plan tests (hosted CPU lane)

`tests/export/test_export_plan.py`, through `uzp-export-tests plan`, on project skeletons:

- **3.1 Naming (EXP-03).**
  - The Assets3D inline five-map preset (`staff-v10/painter_export.py`) and its hat v8 variant expand to the delivered names. They read the OpenPBR channels through the recorded aliases and take `sizeLog2` 12 as 4096.
  - The recorder's `$textureSet_<map>` names, Adobe's optional groups (`(_$colorSpace)`, `(.$udim)`, dropped when empty) and `/` sub-folders expand over two texture sets.
  - These are refused before any write, the refusal naming the files concerned:
    - collisions, also case-only ones and one preset over two stacks of a set;
    - `..` components, Windows-invalid characters and reserved device names;
    - unknown wildcards, with their alternatives;
    - `$mesh`, an empty wildcard outside a group, a group without a wildcard, and nested and unclosed groups.
- **3.2 Filters.**
  - `{}` and an absent filter select all; `{"dataPaths": []}` selects nothing, and then the parameters are undefined.
  - `outputMaps` matches the unexpanded `fileName`. Members combine with AND.
  - `dataPaths` matches a set (all its stacks) or a `set/stack`.
  - An empty `outputMaps` list writes no file, which is invalid. `uvTiles` on a project without UV tiles is refused.
- **3.3 Resolution order.**
  - Preset parameters come first, then the matching rules in list order; later rules override earlier ones.
  - A parameter left undefined is invalid, naming the map and the parameter. `dilationDistance` is required only by `transparent`, `color` and `diffusion`.
  - The bit depth must suit the format. `sizeLog2` accepts a scalar or `[w, h]`.
  - An integer `bitDepth` and a `sizeLog2` outside 7..13 are refused.
- **3.4 Identifiers and formats.**
  - `Mixed_AO` is a `ValueError` whose alternatives start with `AO_Mixed`.
  - `tiff`, `tif`, `psd`, `webp` and `sbsar` raise `NotYetSupported` ("not in v1"); `tga`, `jpeg` and `dds` name `phase3.2_unreal-ue56-packed-preset`. Nothing exists under `exportPath` afterwards.
  - Also checked with their alternatives: `srcMapType`, channel letters and destination sets, `documentMap` spellings, mesh-map and default-map names, presets, undocumented keys, `srcPath`, JSON syntax and root paths.
- **Presence and sources (decision 085).**
  - Absent `documentMap`s and white-only maps are skipped and listed.
  - Unrecorded combinations, release-gap virtual maps and unbound or native-precision mesh maps are refused.
  - `normal_base` resolves as `geometry_only` and the combined normals as `combined`. Channel mixes follow the documented rules.
- **2.6 Diagnostic sources (decision 076).** Sources resolve in the stacks that hold their node and are skipped elsewhere. These are invalid:
  - a node in no exported stack;
  - a malformed name;
  - a statistics source in an image slot;
  - a missing channel or ID map.

  `regionStats` is a JSON statistics file.
- **2.3 Plan hash.** The same project and configuration give the same plan and hash, and a parameter change changes the hash.

## 2. Dry run against Painter (item 3.5, Painter's side)

`test_dry_run_equals_painter_export` takes each export step of every golden of the current envelope: 104 goldens and 167 steps, the phase-0 and phase-1 goldens included. For each step it plans the recorder's documented `json_config` (`tools/parity/recorder/job.py`) over the recording's captured texture sets, stacks and channel formats, plus the mesh maps the sequence bound. It then compares the planned `(rootPath, file)` set with the files Painter returned in that step, on r1 and on r2 wherever r2 lists the same files.

| Outcome | Steps |
|---|---|
| Planned files = Painter's files | 165 |
| Differing | 0 |
| Refused: release gap | 2: `phase1/mesh-import/polygon-triangulation` (`meshMap position` at native precision, phase1.16); `tier0/semantics/ao-mixed` (`AO_Mixed`, R-086) |
| Refused unexpectedly | 0 |

Before decision 086 made `AO_Mixed` a gap, the `ao-mixed` step also planned exactly Painter's files, giving 166 equal steps. The equality covers the 26 template channel sets of the `base-values-*` goldens. Each of them requests every documented `documentMap`, so the presence and alias rules of decision 085 are measured on every template.

### The export probes (recording R-085, decisions 087 and 091)

`test_dry_run_equals_painter_probes` compiles every probe of the six `export-probes-*` goldens. It uses the recording's texture sets, the mesh file name, and the project path: none for r1, and r2's `golden.spp`. Each result is compared with what Painter did:

- a configuration Painter's `list_project_textures` refused must be a `ValueError`;
- an export Painter refused must make the dry run raise `ValueError` (`CheckExportable`);
- otherwise the planned files must be exactly the files on disk after Painter's export, meaning its result less the inventory's missing names, with Painter's bit depth and channel count;
- each legacy name must read the channel whose direct export Painter wrote with the same bytes.

| Outcome | Compilations (45 probes × r1, r2) |
|---|---|
| As Painter (files, depths, channels, refusals) | 84 |
| Legacy-name pairings checked against Painter's bytes | 24 |
| Refused as not recorded (R-091) | 6: the case-only collision P9 and srcChannel A (P6, two probes) |
| Differing, or refused unexpectedly | 0 |

`test_luma_probe_exact` evaluates P5 through the plan: srcChannel L of BaseColor, field A in Raw, as the Rec. 601 luma of the linear channel. Written with Painter 12.1.5's 16-bit sRGB encode (`srgb16`), it equals r1 and r2 on every texel of s0, and so does the channel's RGB export. On s1 the BaseColor holds its base value, and the luma of a base value is refused (decision 091 §5).

## 3. Virtual maps through the plan (item 3.6)

`test_virtual_map_goldens_exact` uses `uzp-export-tests files`. Each golden's texture set is built from its instruction sequence (`spec_from_steps`, with the bound mesh maps), and the recorder's configuration for the map is compiled. Every planned file is evaluated through `EvaluateFileOn` on the CPU store and written with the 16-bit UNORM write rule.

| Golden | Sets | Maps | Comparisons (r1 + r2 where r2 = r1) | Differing values |
|---|---|---|---|---|
| `tier0/semantics/height-normal-plane-amplitudes` | s0-s3 | Normal_OpenGL, Normal_DirectX | 16 | 0 |
| `tier0/semantics-ui/height-normal-sharp-plane-strength` | s0-s7 | both | 28 | 0 |
| `tier0/semantics-ui/height-normal-sobel-plane-strength` | s0-s7 | both | 28 | 0 |

`AO_Mixed` (decision 086). The calibrated operator of `parity/semantics/ao-mixed.json` behaves as follows on `ao-mixed`:

- It is exact on s0, s2 and s3 against both recordings.
- On s1 (an AO fill at opacity 0.5) it misses 30 values against r1 and 17 against r2. Each miss is one 8-bit code (257), within 0.03 of a 2^-12 step.
- Painter's r1 and r2 differ at 27 AO_Mixed values there while their AO channel exports are identical. 10 values miss both.

Operand models tried and rejected on s1:

| Model | Misses r1 / r2 |
|---|---|
| unquantised read-out `a (1 + (b - 1)/2)` | 30 / 49 |
| `a + (a b - a)/2`, plain and with fma | 30 / 49 |
| half-float channel | 1153 / 1148 |
| half-float product | 1561 / 1544 |
| 8-bit channel | 8166 / 8139 |
| decoding by multiplying with float32(1/65535), either operand | 30 / 17 |

### R-086: AO_Mixed and the converted maps (decision 092)

Recording R-086 (decision 087) was fitted in the scratchpad against the private store; only counts are published.

**AO_Mixed** (`ao-mixed-opacity`, its OpenEXR 32f twin, and `ao-mixed`):

- The values lie on the 8-bit lattice before encoding, and step A equals step B. r1 and r2 differ by one 8-bit step at 9 to 41 values per set.
- **Best model:**
  - the AO channel before its L16 write, `c = fma(C - 1, alpha, 1)`, with the layer's opacity and colour taken at their L16 codes;
  - times the mesh map, `a = k/255`, in float32;
  - written at 8 bits (12 fractional bits, nearest, ties down).

| Model | r1 misses: `ao-mixed-opacity` s0-s7 (its twin the same) | `ao-mixed` s0-s3 |
|---|---|---|
| product with the exported L16 channel (decision 086) | 28/30/37/33/0/30/37/0 | 0/30/0/0 |
| best model | 0/9/2/0/0/9/2/0 | 0/9/0/0 |

Every remaining miss lies within 3 ulps of the product from a 2^-12 boundary, and no correctly rounded float32 evaluation of the tested inputs reproduces it. The rejected candidates are listed in `virtual-maps.json`. AO_Mixed stays a gap, and recording R-092 isolates the unknown.

**The converted maps** (`virtual-maps-converted` and its OpenEXR 32f twin; r1 = r2 on all 160 maps):

- 9 of 10 maps equal r1 with 0 differing values on every texel of s0-s7, at PNG 16 and EXR 32f: Diffuse, Specular, Glossiness, Glossiness2, Unity4Diff, Unity4Gloss, reflection, 1/ior and f0. Their operators are in `virtual-maps.json`.
- They read each channel's coverage: Unity4Diff and Unity4Gloss through their alpha, and all nine through fixed inputs where a channel has no layer. Those inputs (BaseColor 1.3, roughness 0.5980393, metalness 0) were seen on one template only.
- View_2D varies texel to texel like a render and is not fitted.
- All ten stay gaps (decision 092 §2 lists what lifts them).

## 4. Recording requests (for the agent that owns Painter)

R-085 and R-086 below were recorded and admitted (decision 087). The follow-ups are specified in their decisions:

- **R-091** (decision 091 §7): the export cases the probes left open.
- **R-092** (decision 092 §5): AO_Mixed's operands, the converted maps on other templates and at fractional coverage, and the View_2D view state.

Both requests use the documented API through the recorder, Legacy colour management and the current envelope's build. Each golden is recorded as r1 (same session) and r2 (after save and reopen), and goldens are added to `tools/parity/tier0_semantics/current.py` (`api_goldens`) as decision 077 did.

### R-085: export semantics left open by the documentation (decision 085)

One project per probe group, on `grid2x2` (texture sets s0-s3), OpenGL, 256 px. Each probe calls `substance_painter.export.list_project_textures(config)` and records the returned dict, or the `ValueError` text. When it succeeds, `export_project_textures(config)` follows and records the file list, and the blobs where pixel values are named below. Unless stated, the configuration is the recorder's preset `uzp_recorder` with parameters `{"fileFormat": "png", "bitDepth": "16", "dithering": false, "paddingAlgorithm": "infinite"}` on rootPaths s0 and s1.

| Probe | Configuration change | Records |
|---|---|---|
| P1 wildcards | maps `$mesh_$textureSet_a`, `$project_$textureSet_b`, `$textureSet_$sceneMaterial_c` (documentMap basecolor RGB) | file names |
| P2 empty wildcard outside a group | `$textureSet_$udim_d`, `$textureSet_$colorSpace_e` | file names or error |
| P3 groups | `$textureSet(_v2)` (no wildcard), `$textureSet((_$udim))` (nested), `$textureSet(_$udim` (unclosed) | file names or error |
| P4 uvTiles without UV tiles | `exportList[0].filter = {"uvTiles": [[0, 0]]}`, then `[[1, 0]]`; a rule `{"filter": {"uvTiles": [[0, 0]]}, "parameters": {"bitDepth": "8"}}` | files and their bit depths |
| P5 srcChannel L of a colour source | BaseColor filled with `field-a` (16-bit RGB fixture, Raw); map `$textureSet_lum` destChannel L, srcChannel L, documentMap basecolor | blob (the R+G+B mix) |
| P6 srcChannel A | map RGB from basecolor plus destChannel A, srcChannel A from documentMap `specularroughness` (L8 ramp fill), and from `basecolor` | blob |
| P7 present + absent source | RGB from basecolor plus A from documentMap `opacity` on a stack without Opacity | files, blob |
| P8 black only | a map of `defaultMap black` L only, and one of `black` RGB | files, blob |
| P9 collisions | two maps both named `collide`; maps `$textureSet_A` and `$textureSet_a`; one preset over two stacks of a layered set (`$textureSet_x`) | files or error |
| P10 undocumented key | top-level `"exportPathh": "x"`, a map key `"comment": "x"` | accepted or error |
| P11 integer bit depth | `"bitDepth": 16` (an integer) | accepted or error |
| P12 unbound mesh map | meshMap `curvature` on a set without a baked curvature | files, blob |
| P13 unobserved legacy aliases | on the OpenPBR coat, fuzz and subsurface templates: documentMap `sheencolor`, `sheenroughness`, `sheenopacity`, `coatopacity`, `translucency`, `absorptioncolor`, `scatteringcolor`, `specularedgecolor` (RGB) | files (presence) and blobs (pairing) |

### R-086a: AO_Mixed operator and Painter's run-to-run noise (decision 086)

- **Golden** `ao-mixed-opacity`: `grid4x2` (s0-s7), OpenGL, 256 px; channel AO L16 added; `grey-a` imported and bound as the AO mesh map of every set; `grey-b` imported.
- **Layers:**
  - s0-s3: one fill with active channel AO, source `grey-b`, blending Normal at opacity 0.25, 0.5, 0.75 and 0.9;
  - s4: a uniform 0.3 (Working) at opacity 0.5;
  - s5: `grey-b` at 0.5 inside a group at opacity 1;
  - s6: two `grey-b` fills at 0.5 each;
  - s7: empty.
- **Exports:**
  - step A: `virtualMap/AO_Mixed:L` and `documentMap/ambientOcclusion:L` (PNG 16);
  - step B: the same maps again, so a second export in the same session measures run-to-run noise. The recorder must key outputs by step for this, a recorder change.
- **Twin golden** `ao-mixed-opacity-float`: the same sequence with `AO_Mixed` exported as OpenEXR 32f. It shows whether Painter's AO_Mixed holds the 8-bit lattice before encoding.

### R-086b: the converted maps

- **Golden** `virtual-maps-converted`: `grid4x2`, OpenGL, 256 px, the project created with no template (`assets/templates/default.json`).
- **Layers:**
  - s0: BaseColor `field-a`, SpecularRoughness `grey-a`, BaseMetalness 0;
  - s1: the same with BaseMetalness 1;
  - s2: BaseMetalness `grey-b`, SpecularRoughness `grey-a`;
  - s3: BaseColor uniform (0.8, 0.3, 0.1), SpecularRoughness 0 and BaseMetalness 0.5;
  - s4: uniform roughness 1;
  - s5-s7: empty.
- **Exports**, each map once per golden and each export step repeated once in the same session:
  - PNG 16: `virtualMap/Diffuse:RGB`, `Specular:RGB`, `Glossiness:L`, `Glossiness2:L`, `Unity4Diff:RGBA`, `Unity4Gloss:RGBA`, `reflection:RGB`, `1/ior:L`, `f0:RGB`, `View_2D:RGBA`.
  - Twin golden `virtual-maps-converted-float`: the same maps as OpenEXR 32f.
- **Recorder change needed:** `OutputMap.file_name` must replace the `/` of `1/ior`, for example with `$textureSet_1_over_ior`. Otherwise Painter writes a sub-folder.

## 5. Items left open and closed

- **1.1** Prerequisite `phase1.14_compositor-core` is merged. Its child `phase1.12_compositor-height-normal` is archived (2026-10-11); phase1.14 and its child phase1.13 are closing on `wt/close-compositor`. phase1.12 changed the virtual normal maps' set-size and Normal-mesh-map limits. The plan defers those limits to the evaluator, so nothing in `src/export/` needs to change for them (decision 085).
- **3.5** Closed. Painter's side is proven (§2). UzPainter's side (decision 085) is proven by the phase1.16 writers and the phase1.17 receipts:
  - `WriteExport` writes exactly the dry run's files, with the sizes and SHA-256 it reports, in two processes (`test_written_files_equal_the_dry_run_in_two_processes`, CPU, 1 passed on 2026-10-12);
  - it does so on all 40 export steps (80 files) of phase1.16's Tier 0 goldens (`parity/reports/phase1/export-processing-encoders.md`);
  - the receipt lists the published files with their sizes and SHA-256 (`test_receipt_schema_and_fields`).
- **3.6, 4.1** Closed as a scope split (decision 131). The maps marked supported are exact (§3). AO_Mixed, which item 3.6 names, stays a release gap refused before writing: its best model misses r1 at 31 values of R-086a (decision 092), and the R-092 isolation goldens (decision 093) have not identified the operator. Its exact fit is `phase3.2_unreal-ue56-packed-preset` item 2.10. The converted maps are not marked supported, so they do not block 3.6.
