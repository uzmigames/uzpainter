# `phase1.17_export-presets`: local run on the owner's machine and recording request R-095

This task is a child of `phase1.18_export-engine` (P1-EXPORT; `docs/architecture/08-export.md` §4; EXP-01, EXP-08 subset, CLR-01, CLR-06, LIC-03). Under decision 028 its Tier 0 comparison runs locally against the private oracle store, and this report is its evidence.

Run on 2026-10-12, branch `wt/phase1.17-presets`, on main after the phase1.16 close (decisions 089 and 090; current envelope `painter-12.1.5_js-api.1.1.20`). Decisions 095 and 096. Implementation: `src/export/preset_aliases.{h,cpp}`, `assets/export-presets/` (`src/export/EXPORT.md` §5).

**Result.**

- **Three presets ship**, each with a provenance record valid under `src/export/preset-provenance.schema.json`:

  | Id | Answers to | Layout | Parity |
  |---|---|---|---|
  | `assets3d-inline-five-map` | its id (the Assets3D `painter_export.py` preset) | `pipeline` | pending: R-090 (BaseColor), R-095 (a golden with all five maps) |
  | `pbr-metallic-roughness` | `PBR Metallic Roughness` | `unconfirmed` | pending: R-095, R-090 |
  | `blender-principled-bsdf` | `Blender (Principled BSDF)` | `unconfirmed` | pending: R-095, R-090 |

- **Alias table.**
  - The Painter names and their `resource://starter_assets/` URLs resolve to the shipped ids. A URL resolves with no query, or with the version recorded in Assets3D for the Blender preset.
  - An unrecorded version is refused naming R-095.
  - An inline preset of the referenced name wins.
- **Unconfirmed layouts.** The two Painter-named presets are written from public sources and UzmiGames' own observations. They are refused before anything is planned, naming R-095.
- **The five-map preset**
  - plans, file for file, what the pipeline's inline configuration plans;
  - is refused before writing when it writes BaseColor (R-090, `phase1.18_export-engine` item 6.1);
  - writes the other maps;
  - writes a Normal map that is byte-identical to Painter's `Normal_OpenGL` PNG 16 files on the recorded plane goldens: 4 of 4 texture sets, against r1 and against r2 where r2 equals r1.
- **Guard.** No preset file or record holds a private record. None matches the owner's private store index.

Items 3.1 and 4.1, full output parity per preset, are deferred, not passed. They are a scope split to `phase1.18_export-engine` item 6.2 (decision 096, §4).

## Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200; the export tests evaluate on the CPU store |
| Build | Zig 0.15.2, Debug; `zig build export-tests` and `zig build painter` exit 0 with `-Wall -Wextra -Werror -ffp-contract=off` on UzPainter's sources |
| Oracle | current envelope `painter-12.1.5_js-api.1.1.20`, golden `tier0/semantics/height-normal-plane-amplitudes`; r1 is the exact target where r1 and r2 differ (decision 032) |
| Commands | `python -m pytest tests/export/test_export_presets.py tests/export/test_export_plan.py tests/export/test_export_encoders.py` |

## 1. Sources of each preset

Every map's decision and its source are in the preset's `.provenance.json` (`packing`, `sources`). No Adobe preset file, readback or descriptive text is used. Adobe's help page gives the two Painter names only.

- **Five-map preset: the pipeline script.** Its maps, channels and parameters are `painter_export.py`'s; its SHA-256 is in the record. File names use `$textureSet` where the script passes one caller prefix. The size is left to the texture set, where the script sets it per recipe.
- **Blender: file names.** They come from the files Painter wrote on UzmiGames' OCIO projects: the hat report and the delivered `Textures` folders, with their SHA-256. Hence `(_$colorSpace)` and the map order.
- **Blender: channels.** They come from Blender's Principled BSDF inputs. The OpenGL normal comes from the Assets3D render standard's `texture_contract`.
- **PBR: maps.** The maps are the five an Assets3D MCP export through the preset produced.
- **PBR: channels.** They come from glTF 2.0's metallic-roughness model. The OpenGL normal follows glTF's +Y-up convention.
- **Unknown, for both Painter-named presets.** The naming prefix and the preset's own parameters are unknown. The shipped presets carry no parameters, and R-095 records them.

## 2. Tests

`tests/export/test_export_presets.py` (CPU lane unless marked):

| Test | Item | Checks |
|---|---|---|
| `test_provenance_records_are_complete` | 3.2 | Every preset has a schema-valid record naming it, with one packing entry per map in order, `answersTo` equal to the alias table, existing tests, R-095 pending for unconfirmed layouts, and private records for an exact status |
| `test_a_preset_without_provenance_fails_naming_it` | spec scenario | A missing record, or a record of another preset, fails loading with the preset's name |
| `test_painter_names_resolve_to_shipped_presets` | 3.3 | Names, URLs and the recorded version resolve; unrecorded versions are refused naming R-095; `defaultExportPreset: "Blender (Principled BSDF)"` reaches `blender-principled-bsdf` |
| `test_unconfirmed_presets_are_refused_naming_r095` | 2.1 | Both Painter-named presets, by name, URL or id, as `defaultExportPreset` or `exportList[].exportPreset`, are refused naming R-095 |
| `test_preset_references_resolve_inline_first` | 2.3 | Inline first; a shadowing inline preset is a `ValueError`; unknown names list the shipped ids and Painter names; other shelf and generator URLs are `NotYetSupported` |
| `test_five_map_preset_plans_the_pipeline_maps` | 2.1 | The plan equals the pipeline's inline configuration, file for file |
| `test_five_map_preset_refuses_basecolor_naming_r090` | 2.1 | BaseColor is refused before writing, naming R-090 and item 6.1; without it, the files are written |
| `test_five_map_preset_normal_equals_painter_files` (Tier 0) | 3.1, part | The Normal map is byte-identical to Painter's on s0-s3 of the plane goldens |
| `test_shipped_presets_pass_the_guard` | 3.4 | The repository guard over `assets/export-presets/` finds nothing with the owner's store index, and catches a planted hash |

Results of this run: `test_export_presets.py` 9 of 9 passed, with the Tier 0 case and the store index on the owner's machine. With `test_export_plan.py` and `test_export_encoders.py`, whose refusal texts and identifier case this task changes, 45 of 45 passed in 14 minutes.

## 3. Recording request R-095 (for the agent that owns Painter)

The probes are export probes (decision 087): a literal `json_config` is an authored input of the golden. The recorder lists it with `list_project_textures` and, when that succeeds, exports it, recording the refusal too. No recorder change is needed. Each golden is recorded as r1 (same session) and r2 (after save and reopen).

**Project.**

- `grid2x2`, s0 to s3, every UV tile covered; OpenGL; 256 px; Legacy colour management unless stated.
- Channels: BaseColor sRGB8, SpecularRoughness L16, BaseMetalness L16, Height L16F, Normal RGB16F, EmissionColor sRGB8 and Opacity L8.
- Fills:
  - s0: every channel from `field-a`, or from `grey-a` for the grey channels;
  - s1: distinct uniform values per channel;
  - s2: only BaseColor, SpecularRoughness and BaseMetalness, to show which maps are absent;
  - s3: Height from `field-a` at opacity 0.5.

| Probe | Configuration | Decides |
|---|---|---|
| P1 PBR, parameters given | `defaultExportPreset` `resource://starter_assets/PBR Metallic Roughness`, plus one `exportParameters` rule: PNG 16, `infinite`, no dithering | The preset's maps, their file names, channels and sources, and its normal convention: the layout of `pbr-metallic-roughness` |
| P2 PBR, its own parameters | P1 without `exportParameters` | The preset's own per-map parameters, or Painter's error when it has none |
| P3 Blender, parameters given | P1 with `resource://starter_assets/Blender (Principled BSDF)` | The layout of `blender-principled-bsdf` |
| P4 Blender, its own parameters | P3 without `exportParameters` | Its own parameters |
| P5 Blender under OCIO | P3 on the same project created with OCIO colour management (the Painter default config) | `$colorSpace` per map (`_sRGB` and `_Raw` observed in Assets3D) |
| P6 Five-map | The `assets3d-inline-five-map` configuration (`painter_export.py` with `$textureSet_` names, no `sizeLog2`) | Every file of the five-map preset, BaseColor included |
| P7 Versions | Read back each preset's resource URL (`resource.search` on `starter_assets` export presets) | The `?version=` values the alias table accepts |
| P8 Layout readback | `ResourceExportPreset.list_output_maps()` of both presets | A private oracle record confirming P1 and P3. It is never shipped or used to generate a preset (licensing §6) |

P1 to P6's BaseColor files also serve R-090's sRGB8 fit (R-090 P10).

## 4. Scope split to `phase1.18_export-engine` item 6.2 (decision 096)

Items 3.1 and 4.1 of phase1.17 are checked as recorded scope splits: deferred, not passed. Item 6.2 records R-095 and does the following:

- confirms or corrects the two Painter-named presets, setting their layout to `confirmed`;
- adds the output-parity test per shipped preset against the R-095 goldens (every file's name and decoded pixels);
- sets each record's `privateRecords` and `parity.status` to `exact` once BaseColor (item 6.1) is fitted.

Until then, the two Painter-named presets are refused, and every BaseColor export is refused.

## 5. Owner actions

- **Review the provenance records.** Their `reviewer` field stays null until the owner reviews them (licensing §6).
- **Run R-095.** It is run by the agent that owns Painter.
