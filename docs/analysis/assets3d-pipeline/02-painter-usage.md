# 02 — How Substance 3D Painter is driven today

Conventions as in [01](01-pipeline-overview.md): paths relative to `E:\UzmiGames\Assets3D\`, `SM/` = `Creatures/Undead/Skeletal Mage/Models3D/`, **F** Fact / **H** Hypothesis / **R** Recommendation.

## 1. Connection and control surface

| Item | Value | Type | Source |
|---|---|---|---|
| Painter version | 12.1.0 (installed under `C:\Program Files\Adobe\Adobe Substance 3D Painter\`) | F | `Docs/Pipeline-Guide.md` → "Operação por MCP e ferramentas locais"; OCIO path in `Pipeline/retopology/staff-v10/painter_create.py` |
| Launch | `--enable-remote-scripting`; endpoint listens on IPv6 `::1:60041`, so clients must use host `localhost`, not `127.0.0.1` | F | `.claude/skills/pbr-painting/REFERENCE.md` → "Armadilhas" |
| MCP server | `Tools/SubstancePainterMCP` (community, elliezu), venv `Tools/SubstancePainterMCP/.venv`, 79 tools listed in `tool-schema.json` (counted this session) | F | `Docs/README.md` → "Ferramentas (submodules)"; `Tools/SubstancePainterMCP/tool-schema.json` |
| Local server patch | (1) bake without UDIM: empty UV-tile list no longer an error when the texture set has no tiles; (2) `insert_mask_effect` fill actually assigns the resource (`set_source` + `ProjectionMode.UV`); (3) uniform colours created in the OCIO colour space (BaseColor sRGB, others Raw) with a Legacy fallback | F | `Pipeline/mcp/substance-painter-mcp-local.patch` |
| Client | `Pipeline/mcp/painter_mcp_client.py`: stdio MCP client; one call (`tool args.json`) or a `batch` list; sets `SP_MCP_HOST=localhost`, `SP_MCP_TIMEOUT=120`, allowlists `SP_MCP_{EXPORT,PROJECT,MESH,BAKE_MESH,RESOURCE}_ROOTS` = Assets3D root, `SP_MCP_ALLOW_EXECUTE_PYTHON=1` only for `execute_python`; read timeout 180 s; writes `painter-last-response.json` / `painter-batch-result.json` into `SP_MCP_CLIENT_OUTPUT_DIR` | F | `Pipeline/mcp/painter_mcp_client.py` |
| Python return contract | Code sent through `execute_python` must assign the variable `result`; `print()` is not returned | F | `.claude/skills/pbr-painting/REFERENCE.md` → "Painter MCP" |
| Batch caveat | The batch stops at the first `isError` but the client may still exit 0; every result and job must be read | F | `.claude/skills/pbr-painting/REFERENCE.md` → "Painter MCP" |
| UI policy | No mouse, keyboard or focus control; the user watches the visible Painter window; work is re-saved after each step so the user can File > Revert | F | `AGENTS.override.md` → "Working agreements" |
| Concurrency | One agent at a time under `collab.py lock acquire --app Painter`; simultaneous paint/display commands crashed Painter (Qt6Core, grimoire, 2026-10-06) | F | `Docs/Colaboracao/Colaboracao.md` → "Substance Painter"; `Docs/Lessons/operation-painter-exclusive-mode.md` |

## 2. Two driving modes

| Mode | What it looks like | When | Type | Source |
|---|---|---|---|---|
| Typed MCP tools | `create_project`, `set_baking_mesh_inputs`, `configure_baking`, `start_bake`, `import_project_resource`, `create_layer_recipe`, `insert_mask_effect`, `insert_smart_material`, `set_fill_resource`, `snapshot_layer_tree`, `start_mesh_reload`, `export_textures` | Hat pilot (2026-10-04/05) and audits/diagnostics afterwards | F | `.claude/skills/pbr-painting/REFERENCE.md` → "Chamadas usadas no chapéu" |
| Painter Python files sent through `execute_python` | `painter_layer_stack.py sync/smart/capture/run`; per-piece `painter_create.py`, `painter_open.py`, `painter_export.py`, `painter_info.py`; render adapters `painter_render_standard.py`, `painter_lighting.py` | Used since the tunic v9 (2026-10-05, `painter_layer_stack.py sync`) and dominant afterwards; the 2026-10-09 recipes use only this mode | F | `.claude/skills/pbr-painting/REFERENCE.md` → "Comandos da construção do material (base v9)"; `Pipeline/painting/painter_layer_stack.py`; `Pipeline/retopology/waist-v5/round.sh` |

**H** — The shift to Python files happened because the typed tools did not cover everything (channel order, bitmap BaseColor, levels, smart masks, export presets) and because one Python call per round is cheaper; the sources describe the scripts but do not state this reason explicitly.

## 3. MCP tools actually referenced by the pipeline

Computed this session with `grep -w` over `Docs/`, `.claude/skills/` and `SM/` (excluding `catalog.json`). A reference can be documentation of a past call, not a script call.

| Tool | Where referenced (examples) | Use |
|---|---|---|
| `execute_python` | `Pipeline/mcp/painter_mcp_client.py`, `Pipeline/painting/painter_layer_stack.py`, `Pipeline/render/painter_lighting.py`, `SM/22-Bracal-Direito/report.json` | Main control path |
| `import_project_resource` (as MCP tool and as Python `resource.import_project_resource`) | `painter_layer_stack.py`, all `Pipeline/retopology/*/painter_create.py`, `SM/00-Corpo/report.json` | Import masks, colour bitmaps, normal/AO mesh maps, HDRI |
| `snapshot_layer_tree` | `.claude/skills/pbr-painting/SKILL.md` step 10, `SM/18-Tunica/report.json`, `SM/00-Corpo/report.json`, `SM/23-Cinto/report.json` | Record stack state + SHA-256 digest |
| `open_project` | `Docs/Colaboracao/Colaboracao.md`, `Docs/analysis/skeletal-mage-review/05-spp-audit-10-13-20261007.md` | Reopen projects / audit copies |
| `export_textures` | `Pipeline/painting/painter_layer_isolate.py`, `05-spp-audit-10-13-20261007.md` | Diagnostic exports (preset "Blender (Principled BSDF)") |
| `create_project` (+ `get_project_creation_job`) | `.claude/skills/pbr-painting/SKILL.md` step 3, `SM/21-Bracal-Esquerdo/report.json → painting_p1.project.creation_job` | Project creation (async job) |
| `start_mesh_reload` | `.claude/skills/pbr-painting/SKILL.md` ("Recarga de malha"), `SM/22-Bracal-Direito/report.json` | Reload a changed low, preserving layers |
| `insert_mask_effect`, `insert_smart_material`, `set_fill_resource`, `create_layer_recipe`, `search_resources` | `.claude/skills/pbr-painting/REFERENCE.md` | Hat pilot stack |
| `set_baking_mesh_inputs`, `configure_baking`, `start_bake`, `capture_baking_preset`, `inspect_baking` | REFERENCE.md; `SM/18-Tunica/report.json`; `SM/10-Chapeu/report.json → painter_recipe.bake_settings` (schema `substance-painter-mcp/baking-preset@1`) | Painter mesh-map bakes |
| `get_fill_parameters`, `get_fill_projection`, `get_fill_sources` | REFERENCE.md; `SM/18-Tunica/report.json` | Recipe capture |
| `export_smart_material` | `SM/21-Bracal-Esquerdo/report.json → painting_p1.smart_materials` | Copy "SM Couro"/"SM Bronze" folders between projects as `.spsm` |
| `import_session_resource` | `Pipeline/render/Render-Comparison-Standard.json → presets.ref_match.painter.environment` | Load the `ref_match` HDRI as a session resource |
| `get_project_info` | `Docs/Colaboracao/Topicos/creatures-undead-skeletal-mage-assembly.md` | Status check |

Not referenced anywhere (not used as far as the sources show): the shelf tools, `replace_outdated_resources`, anchor-point tools, geometry-mask setters, `export_with_profile`, `start_batch_bake` by name. **H** — `SM/00-Corpo/report.json → painting_v6.rebake_mesh_maps.job_id_lote` ("lote" = batch) suggests a multi-texture-set bake job, possibly `start_batch_bake`; not confirmed.

## 4. Painter Python API actually called by pipeline scripts

Counted this session over `painter_layer_stack.py`, `painter_layer_isolate.py`, `retopology/*/painter_*.py`, `painter_render_standard.py`, `painter_lighting.py`.

| Module | Calls | Type |
|---|---|---|
| `substance_painter.project` | `Settings(normal_map_format, default_texture_resolution, import_cameras)`, `create`, `open`, `close`, `is_open`, `is_busy`, `needs_saving`, `file_path`, `save(ProjectSaveMode.Full)`, `save_as(path, Full)` | F |
| `substance_painter.textureset` | `all_texture_sets`, `TextureSet.from_name`, `set_active_stack`, `get_active_stack`, `set_mesh_map_resource(MeshMapUsage.Normal/AO, id)`, `get_mesh_map_resource`, `get_resolution`, `ChannelType` | F |
| `substance_painter.layerstack` | `insert_group`, `insert_fill`, `insert_smart_mask`, `insert_levels_effect`, `delete_node`, `get_root_layer_nodes`, `InsertPosition.*`, node `set_name`, `add_mask(MaskBackground.Black)`, `set_source`, `set_projection_mode(UV/Triplanar)`, `set_projection_parameters(UVProjectionParams(BilinearHQ, RepeatNone, scale 1))`, `active_channels`, `set_opacity(ch)`, `set_blending_mode(mode, ch)`, `set_visible` | F |
| `substance_painter.resource` | `import_project_resource(path, Usage.TEXTURE, name, group)`, `ResourceID.from_url`, `search`, `import_session_resource(..., Usage.ENVIRONMENT)` | F |
| `substance_painter.colormanagement` | `Color(r,g,b, color_space=GenericColorSpace.sRGB/Raw)` with `LegacyColorSpace`/`DataColorSpace` fallback | F |
| `substance_painter.export` | `export_project_textures(config)` with inline preset | F |
| `substance_painter.display` / `_substance_painter.display` | `get/set_environment_resource`, `save_viewport` (unreliable: stale camera) | F |
| `substance_painter.ui` | `get_main_window` (Qt widgets for exposure/rotation/Iray), `get_current_mode`, `switch_to_mode` | F |

Sources: the files listed above; `Pipeline/render/Render-Comparison.md` → "Captura e aplicação".

## 5. Project creation settings

| Setting | Value used | Type | Source |
|---|---|---|---|
| Mesh format | OBJ of the triangulated low, exported from Blender (`export_low.py` / `export_lows.py` per recipe) | F | `Pipeline/retopology/staff-v10/painter_create_args.json`; `SM/21-Bracal-Esquerdo/report.json → painting_p1.project.created_from` |
| Texture-set naming | One texture set per OBJ material; agents edit the OBJ `usemtl` line to name it (e.g. `usemtl 22-Bracal-Direito`); without it the set is `DefaultMaterial` (tunic) or the Blender material name (`Hat_Surface.001`) | F | `SM/22-Bracal-Direito/report.json → painting.mesh`; `SM/18-Tunica/Textures/` file names; `SM/10-Chapeu/report.json → painter_recipe.texture_set` |
| Normal map format | OpenGL | F | `painter_create.py` (`NormalMapFormat.OpenGL`); `SM/10-Chapeu/report.json → painter_recipe.normal_format` |
| Tangent space | Per fragment (setting name; the exact tangent/bitangent algorithm behind it is not confirmed) | F | `SM/22-Bracal-Direito/report.json → painting.tangent_space`; `SM/21-Bracal-Esquerdo/report.json → painting_p1.project.tangent_space` |
| Default resolution | 2048 (belt/sash v5, wand v1, bracers, pauldrons) or 4096 (hat, staff, tunic, body sets); chosen by density and use distance, not maximum | F | `painter_create.py` diffs across `Pipeline/retopology/*`; `.claude/skills/pbr-painting/SKILL.md` ("Defina resolução pela densidade e distância de uso") |
| Cameras | `import_cameras=False` | F | `painter_create.py` |
| Colour management | OCIO with Painter's own config: `os.environ["OCIO"] = …\resources\ocio\substance\config.ocio` set inside Painter **before** `create`; a project created without it became Legacy and could not be converted | F | `painter_create.py`; `.claude/skills/pbr-painting/REFERENCE.md` → "OCIO antes de criar o projeto" |
| Channels / shader | Channels seen: `BaseColor`, `BaseMetalness`, `SpecularRoughness`, `Height`, `Normal`; optional `SpecularWeight` must be added to the texture set first — the hat v8 adds it with `painter_add_channel.py` as an `L8` channel and sets it on 3 of its 43 layers (felt 0.5, leather/iron 1.0; counted this session); shader parameter "Double sided" = true on the tunic | F | `SM/10-Chapeu/report.json → painter_recipe.channels`, `v8.painter.channels_added`, `v8.specular`; `painter_layer_stack.py` docstring; `Pipeline/retopology/hat-v6/painter_add_channel.py`, `paint/stack-hat-v8.json`; `SM/18-Tunica/report.json` (shader parameter `doubleSided`, `"openpbr": "_double_sided"`) |
| Shader model | The channel names and the shader-parameter metadata point to Painter's OpenPBR-based default shader | H | Same sources; shader name not recorded |
| UV workflow / UDIM | One 0–1 tile per texture set; no UDIM; the MCP was patched so bakes accept texture sets without UV tiles. Painter's UV-tile workflow option itself is not recorded | F / not confirmed | `Pipeline/mcp/substance-painter-mcp-local.patch`; `Docs/README.md` ("bake sem UDIM") |
| Template | `create_project` accepts `template_file_path`; no template is recorded in any script or report | F / not confirmed | `Tools/SubstancePainterMCP/tool-schema.json`; `painter_create.py` |
| Mesh maps at creation | Normal (Blender bake) and, since 2026-10-09, AO (Blender bake) imported as project resources (`Usage.TEXTURE`, group `mesh_maps_v<N>`) and assigned with `set_mesh_map_resource` | F | `painter_create.py` |
| Save | `save_as(dst, ProjectSaveMode.Full)` right after creation; refuses to close an open project that still needs saving | F | `painter_create.py` |

## 6. Texture-set conventions per piece

| Piece / version | Texture sets | Resolution | Normal source | Other mesh maps | Stack method | Source |
|---|---|---|---|---|---|---|
| 10-Chapeu v5 (pilot) | `Hat_Surface.001` | 4096 | Painter bake | Painter: WSN, AO, Curvature, Position, Thickness (ID configured, then removed) | Manual + MCP; smart material, generators, Mask Builder/Editor, user-authored black Metal Edge Wear layer | F — `SM/10-Chapeu/report.json → painter_recipe` |
| 18-Tunica v9/v10 (approved) | `DefaultMaterial` | 4096 | Blender bake (cage 0.006 m, ray 0.014 m, 16-bit) | Painter: WSN, AO, Curvature, Position, Thickness | `painter_layer_stack.py sync`, 22 uniform fills, groups "Tecido externo" (no mask) and "Forro" (`M_lining`, Height replace) | F — `SM/18-Tunica/report.json → painting.bake`, `painting_v9.painter`, `painting_v10` |
| 00-Corpo v3–v6b | `00-Corpo-Cranio`, `00-Corpo-Tronco`, `00-Corpo-Membros` | 4096 each | Blender bake per set | Painter per set: WSN, AO, Curvature, Position, Thickness | `painter_layer_stack.py smart` (smart masks + grunges) + `sync --texture-set` | F — `SM/00-Corpo/report.json → texture_sets_v3`, `painting_v3`, `painting_v6` |
| 22/21 Bracers | one set each (`usemtl` named) | 2048 | Blender bake | Painter: WSN, AO, Curvature (FromMesh, fixed bounds), Position, Thickness | Smart materials "Leather Damaged" + "Bronze Armor" + `sync` detail group (31 layers on 21 p1) | F — `SM/22-Bracal-Direito/report.json → painting`; `SM/21-Bracal-Esquerdo/report.json → painting_p1` |
| 19/20 Pauldrons v9 | one set | 2048 | Blender bake | not recorded | `sync` with `stack_v9.json` (14 layers, group "Ferro") | F — `SM/19-Ombreira-Esquerda/report.json → v9.painting` |
| 10-Chapeu v8 | one set (project copied from v6; v6 group hidden) | 4096 | Blender bake of v6 (same low, UV and bake) | AO = merged Blender AO bake set as the AO mesh map (`painter_set_ao.py`) | `sync` with `stack-hat-v8.json`: 43 layers in 5 groups (felt, leather, iron, dirt, accent/AO); `SpecularWeight` channel added | F — `SM/10-Chapeu/report.json → v8.painter`; `Pipeline/retopology/hat-v6/README.md` → "v8"; texture size from the PNG headers this session |
| 10-Chapeu v6, 09-Cajado v9/v10, 11-Varinha v1, 23-Cinto v5, 25-Faixa v5 | one set each | 4096 (hat, staff) / 2048 (wand, belt, sash) | Blender `bake_normal_pair.py --parts` | AO from Blender (`garment_blender_io.py extract`); no Painter bake recorded | `sync` only (uniform fills + bitmap masks + `base_tex` swatches) | F — `Pipeline/retopology/*/painter_create.py`, `*/bake.sh`; reports `v6`/`v10`/`v5`/`claude_v1`; H for "no Painter bake ran" (absence in reports) |

## 7. Typical session sequence (current practice)

1. **Gate check** — the manifest of the version shows `gates.visual.geometria-encaixe = pass`; UV validated; `low_high_fidelity = pass` (F — `Docs/Gates/painting.md`; `.claude/skills/pbr-painting/SKILL.md` → "Pré-requisitos obrigatórios").
2. **Lock** — `collab.py lock acquire --app Painter`; confirm PID, visible window, project path and round through the API (F — `Docs/Colaboracao/Colaboracao.md` → "Substance Painter").
3. **Inputs** — export the low OBJ (and high OBJ if Painter bakes), Blender normal and AO PNGs, masks `M_*.png` and swatch textures `T_*.png` into `_tmp/<agent>/<job>/` (F — `Pipeline/retopology/waist-v5/sashchain.sh`).
4. **Create or open** — `painter_create.py` (new project, mesh maps, `save_as`) or `painter_open.py` (close a saved project, open the target `.spp`, wait while busy) (F — scripts in `Pipeline/retopology/waist-v5/`).
5. **Optional Painter bake** — `set_baking_mesh_inputs` → `configure_baking` → `start_bake` → poll `get_bake_job` with the current `job_id` (F — `.claude/skills/pbr-painting/REFERENCE.md`; `Docs/Lessons/operation-reload-job-id.md`).
6. **Stack** — `painter_layer_stack.py sync --stack S.json --masks DIR --state state-<piece>-<round>.json --resource-prefix … --resource-group … [--texture-set NAME]`; for Painter-procedural layers `smart --config C.json` (F — `Pipeline/retopology/waist-v5/round.sh`; `painter_layer_stack.py` docstring).
7. **Wait** — stay in Edition mode until computation finishes; Visualisation/Iray pauses the layer engine (F — `Docs/Lessons/operation-painter-exclusive-mode.md`).
8. **Save** — `project.save(Full)`, confirm `needs_saving == False` and not busy (F — `painter_export.py`; `Docs/Colaboracao/Colaboracao.md`).
9. **Export** — inline preset, 16-bit PNG, padding infinite, no dithering (F — `painter_export.py`); the hat v8 adds `SpecularWeight` to the preset and takes AO from the Blender bake, not from Painter (F — `Pipeline/retopology/hat-v6/painter_export_v8.py`); then check files exist, size > 0 and hashes changed when the stack changed (F — `Docs/Lessons/operation-background-paths-and-saving.md`, `operation-sync-state-per-session.md`).
10. **Review** — Blender Cycles `paintrender.py` under `ref_match` at reference framing + board; optionally Painter Iray + `capture_live_view` (F — `Pipeline/retopology/waist-v5/round.sh`; `Pipeline/render/Render-Comparison.md`).
11. **Record and release** — `snapshot_layer_tree` plus parameters/resources/channels/blend/opacity/projection into `report.json`; save; `lock release`; publish a message with the saved round (F — `.claude/skills/pbr-painting/SKILL.md` step 10; `Docs/Colaboracao/Colaboracao.md`).

## 8. `painter_layer_stack.py` — the de facto paint API

| Behaviour | Detail | Type | Source |
|---|---|---|---|
| Scope | Rebuilds only the root group named by the stack `title`; other root layers are hidden, not deleted (`--keep-visible` prefixes excepted); on failure the new group is deleted; after success the previous root group with the same title is deleted | F | `Pipeline/painting/painter_layer_stack.py` (`SYNC_CODE`, lines 81–127) |
| Resources | Each mask/bitmap is imported once as a project resource named `<prefix><name>_<sha1[:6]>` in `--resource-group`; the `--state` JSON maps SHA-1 → resource URL so unchanged masks are reused. This cache is a session convenience, not a persistent cross-session resource identity (next row) | F | Same |
| Session scope of URLs | Stored URLs are valid only in the Painter session that imported them; after closing/reopening the project, `sync` fails with "resource not found" unless a fresh state file is used | F | `Docs/Lessons/operation-sync-state-per-session.md` |
| Layer model | Each layer = fill; channels activated first, then uniform sources (`BaseColor` sRGB, `SpecularRoughness`, `BaseMetalness`, `SpecularWeight`, `Height` raw); optional bitmap mask (black background + fill effect with UV projection); `op` = BaseColor opacity (in `sync`; in `smart`, `op` is applied to every active channel, line 163) | F | Same |
| `base_tex` | Loads `<masks>/T_name.png` as BaseColor bitmap, sRGB colour space, UV projection, scale 1, rotation 0, offset 0, `RepeatNone`, `BilinearHQ` | F | Same |
| Height blending | Docstring: Height adds (Linear Dodge); a group with `replace_height` blends Height as Normal (replaces below). The `sync` code sets only that group blend (line 88); fills keep Painter's default Height blend, which the tool neither sets nor reads back, so the effective fill mode is not confirmed by this source. `smart` sets Linear Dodge explicitly (line 164) | F | Same |
| `smart` | Recreates root fills prefixed `SM ` from `{layers:[{name,color,rough,height,op,blend,mask:{type: smart_mask or grunge, name, tiling, params, levels}}]}`; smart masks use the set's baked mesh maps; grunges are triplanar | F | Same |
| `capture` | `display.save_viewport` private capture; can be stale — use `painter_render_standard.capture_live_view` for evidence | F | Same; `Pipeline/render/Render-Comparison.md` |
| Diagnostics | `painter_layer_isolate.py` hides one layer at a time, exports BaseColor (or Normal/Roughness/Metallic/Displacement) at 1K 8-bit with preset "Blender (Principled BSDF)", measures mean/p99/area>15 per layer, restores visibility | F | `Pipeline/painting/painter_layer_isolate.py` |

## 9. Recipe capture and project persistence

| Practice | Type | Source |
|---|---|---|
| A layer tree alone is not a recipe: record parameters, resources, procedural inputs, projections, blend modes, per-channel opacity and masks (`painter_recipe.node_details` on the hat is 70,834 characters of JSON) | F | `.claude/skills/pbr-painting/SKILL.md` step 10; `SM/10-Chapeu/report.json → painter_recipe` (size measured this session) |
| Recreate by name/resource, not by UIDs; UIDs are stable only inside one project | F | `.claude/skills/pbr-painting/REFERENCE.md` → "Edições por UID" |
| Resources are embedded in the `.spp`, but OBJ paths stored inside it can point to deleted folders; a rebake must re-export high/low from the current `.blend` | F | `.claude/skills/pbr-painting/REFERENCE.md` → "Caminhos dentro do `.spp`" |
| Painter leaves `*_autosave_*.spp` copies and `.spp.painter_lock` files next to projects (e.g. `SM/10-Chapeu/10-Chapeu-v8.spp.painter_lock`, 78 bytes) | F | Directory listing this session; REFERENCE.md → "Higiene de arquivos" |
| Reopening a project can report `needs_saving == true` without edits; do not force-save someone else's project | F | `Docs/Colaboracao/Colaboracao.md` → "Janela emprestada" |
| Smart-material folders are portable between projects via `export_smart_material` (`.spsm`); a dump diff showed 0 differences except resource URLs | F | `SM/21-Bracal-Esquerdo/report.json → painting_p1.smart_materials` |

## 10. Display and capture usage (details in 06)

| Practice | Type | Source |
|---|---|---|
| Display state (HDRI, exposure, rotation, environment opacity/blur, shadows, Iray samples/resolution) is read and written through Qt widgets found by objectName/class (`Alg::Slider` `pbrExposure`, `envRotation`, `cubemapOpacity`, `envBlur`), because the public API exposes only the environment resource | F | `.claude/skills/pbr-painting/REFERENCE.md` → "Ajuste de iluminação do Painter por API" |
| Live evidence comes from `capture_live_view` (Qt/QScreen crop of the real window) after convergence, in a separate call; `save_viewport` returned stale cameras and `QMainWindow.grab()` was black under Vulkan | F | Same; `Pipeline/render/Render-Comparison.md` |
| The user's presentation snapshot is captured before technical comparisons and restored afterwards | F | `Pipeline/render/Render-Comparison.md` → "Aplicar" |
