# 08 — Requirements for UzPainter derived from the Assets3D pipeline

Conventions as in [01](01-pipeline-overview.md): paths relative to `E:\UzmiGames\Assets3D\`, `SM/` = `Creatures/Undead/Skeletal Mage/Models3D/`.

Every requirement below is a **Recommendation (R)** derived from the **Facts** in files 01–07, which cite the original sources; the "Trace" column points to the primary Assets3D source. Priorities: **MUST** = the current pipeline cannot run without it, or a binding rule demands it; **SHOULD** = used today on some pieces or needed to avoid a recorded failure; **COULD** = useful, not exercised by the pipeline today. This file states needs, not a design.

## 0. Governance prerequisites

| ID | Requirement | Priority | Trace |
|---|---|---|---|
| G-01 | The user must amend the binding rule "Painting is always in Substance Painter" (and the matching skill text) before a UzPainter round can count as a paint round; until then UzPainter output is a private check only | MUST | `AGENTS.override.md` → "Working agreements"; `.claude/skills/pintura-pbr/SKILL.md` ("A pintura é SEMPRE no Substance Painter") |
| G-02 | UzPainter must implement the approved paint standard (3D per-texel masks + reference swatches + uniform fills with one bitmap mask each, grouped by material, editable, Height at three scales) as its primary workflow | MUST | `AGENTS.override.md` → "Paint standard = the approved tunic process" |
| G-03 | Approved deliveries (e.g. tunic v10) must stay reproducible: either keep Painter available for them or rebuild them in UzPainter from their recorded recipes and masks and prove equivalence on exported maps | MUST | `SM/18-Tunica/report.json → painting_v10.source_recovery`; `Docs/Pipeline/Licoes/exportacao-spp-mapas-precisao-nativa.md` |

## 1. Functional requirements

### 1.1 Project

| ID | Requirement | Priority | Trace |
|---|---|---|---|
| PRJ-01 | Create a project from a triangulated low-poly OBJ with per-corner normals and UVs, without re-triangulating, welding, recomputing normals or repacking UVs | MUST | `Docs/Pipeline/Retopologia/cajado-v10/painter_create.py`; `Docs/Pipeline/Licoes/bake-triangulacao-avaliada-salva.md` |
| PRJ-02 | One texture set per mesh material (OBJ `usemtl` name), several texture sets per project, each a separate 0–1 UV tile (no UDIM requirement) | MUST | `SM/22-Bracal-Direito/report.json → painting.mesh`; `SM/00-Corpo/report.json → texture_sets_v3`; `Docs/Pipeline/MCP/substance-painter-mcp-local.patch` |
| PRJ-03 | Per-texture-set resolution, at least 2048 and 4096; 8192 SHOULD be available (Painter baker metadata allows `maxPow2 13`) | MUST (2K/4K) / SHOULD (8K) | `painter_create.py` variants; `SM/10-Chapeu/report.json → painter_recipe.bake_common_properties.OutputSize` |
| PRJ-04 | Normal convention OpenGL (+Y), tangent basis compatible with Blender's Normal Map node and with the Painter "per fragment" setting used today (**H**: MikkTSpace with per-fragment bitangent; to be validated on an exported map) | MUST | `painter_create.py`; `SM/22-Bracal-Direito/report.json → painting.tangent_space`; `Docs/Pipeline/Retopologia/cajado-v10/deliver.py` |
| PRJ-05 | Colour management fixed at creation and recorded: linear working space (sRGB primaries, D65), BaseColor stored/exported sRGB, data channels raw | MUST | `.claude/skills/pintura-pbr/REFERENCE.md` → "OCIO antes de criar o projeto"; `Docs/Pipeline/Render/Render-Comparison-Standard.json → texture_contract` |
| PRJ-06 | Material channels: BaseColor, Roughness, Metallic, Height, Normal; SpecularWeight (OpenPBR specular weight) optional per set; double-sided flag for preview | MUST (first five) / SHOULD (SpecularWeight, double-sided) | `SM/10-Chapeu/report.json → painter_recipe.channels`; `painter_layer_stack.py` docstring; `SM/18-Tunica/report.json` (doubleSided) |
| PRJ-07 | Physical units preserved (metres) so physical-scale procedurals and projections are meaningful | MUST | `Docs/Pipeline/Licoes/pintura-profundidade-tres-escalas.md`; `exportacao-escala-fisica-fonte.md` |
| PRJ-08 | Mesh reload of a changed low that preserves the stack, reports which texture sets/islands changed and marks dependent mesh maps and masks invalid | MUST | `.claude/skills/pintura-pbr/SKILL.md` → "Recarga de malha"; `SM/00-Corpo/report.json → painting_v6.recarga_de_malha` |
| PRJ-09 | Import-time validation: flag non-finite or zero corner normals/tangents, coincident opposite faces, flipped (negative signed area) UV triangles, UVs outside 0–1 | MUST | `Docs/Pipeline/Licoes/bake-normais-tbn-por-canto.md`; `uv-anatomia-cartas-espelhadas.md` |

### 1.2 Mesh maps and bake

| ID | Requirement | Priority | Trace |
|---|---|---|---|
| BAK-01 | Accept externally baked mesh maps as inputs per texture set: geometry Normal (16-bit OpenGL) and AO (16-bit) at minimum; also Curvature, World-Space Normal, Position, Thickness when provided | MUST | `painter_create.py` (`set_mesh_map_resource` Normal/AO); `SM/18-Tunica/report.json → painting.bake` |
| BAK-02 | Provide the mesh-map set that curvature/AO/position-driven generators need (Curvature, WSN, Position, Thickness, AO), either by baking from a high mesh or by computing from the low; normalisation (e.g. curvature range) must be explicit, recordable and not silently auto-rescaled per texture set | MUST | `SM/10-Chapeu/report.json → painter_recipe.node_details` (generators reference these maps); `SM/00-Corpo/report.json → painting_v6.rebake_mesh_maps.curvatura_membros` |
| BAK-03 | If UzPainter bakes from a high mesh: per-texture-set bake, high mesh list per set, ray distances/cage per part, subsampling, dilation width, backface handling; RAW output, ray-hit coverage, used-surface accounting and miss maps; no silent repair of used surface | SHOULD | `SM/10-Chapeu/report.json → painter_recipe.bake_settings`; `Docs/Pipeline/Licoes/bake-raw-cobertura-estagios.md`; `Docs/Pipeline/Pintura/bake_normal_pair.py` |
| BAK-04 | AO bake must report misses (AO = 0 on used surface) and support a second, wider pass applied only to missed texels | SHOULD | `Docs/Pipeline/Licoes/pintura-ao-falhas-de-raio-definicao.md` |
| BAK-05 | Bake jobs are asynchronous with unique job ids, progress, cancellation and unambiguous terminal status bound to that id | MUST (if BAK-03) | `Docs/Pipeline/Licoes/operacao-recarga-job-id.md` |
| BAK-06 | Every mesh map carries provenance (source file hash, object, UV map, triangulation hash, parameters); a mesh/UV change invalidates it | MUST | `Docs/Pipeline/Licoes/bake-invalida-malha-uv-mudou.md` |

### 1.3 Layers and stack

| ID | Requirement | Priority | Trace |
|---|---|---|---|
| LAY-01 | Fill layers with uniform values per channel (BaseColor sRGB; Roughness, Metallic, Height, SpecularWeight raw), per-channel active flags that never reset values when toggled | MUST | `Docs/Pipeline/Pintura/painter_layer_stack.py`; `Docs/Pipeline/Licoes/pintura-fill-ordem-dos-canais.md` |
| LAY-02 | Bitmap BaseColor fill from an imported texture in final-UV space: sRGB, UV projection, scale 1, no repeat, high-quality bilinear filtering, no implicit roughness/height | MUST | `painter_layer_stack.py` (`base_tex`) |
| LAY-03 | Groups (nested) with an optional group mask; per-group Height blend override (replace vs add) | MUST | `painter_layer_stack.py` (`replace_height`); `SM/18-Tunica/report.json → painting_v9.painter` |
| LAY-04 | Layer masks: black/white background, bitmap fill effect (UV projection), Levels (in-min, in-max, gamma, clamp), subtraction of another mask, sharpen; mask opacity and blend | MUST | `painter_layer_stack.py`; `SM/10-Chapeu/report.json → painter_recipe.node_details` (Subtract mask blending, Sharpen, Levels) |
| LAY-05 | Per-channel opacity and blend modes: at least Normal, Multiply, Linear Dodge (add) for Height, Replace, Subtract, Lighten, Passthrough, and a normal-map-detail blend for the Normal channel | MUST | `SM/10-Chapeu/report.json → painter_recipe.node_details` (blend modes counted in 04) |
| LAY-06 | Stable, persistent layer identities (survive save/reopen) and name-based addressing; operations idempotent by name | MUST | `.claude/skills/pintura-pbr/REFERENCE.md` → "Edições por UID"; `Docs/Pipeline/Licoes/operacao-recuperar-spp-recursos.md` |
| LAY-07 | Declarative stack sync from the existing stack JSON (`title`, `groups`, `layers`, fields `base`, `base_tex`, `rough`, `metal`, `spec`, `height`, `op`, `mask`), rebuilding only the named group and hiding (not deleting) other roots; existing stack JSON files must load unchanged | MUST | `Docs/Pipeline/Pintura/painter_layer_stack.py`; `Docs/Pipeline/Retopologia/*/paint/stack-*.json` |
| LAY-08 | Replace a mask/bitmap resource in place on existing layers without rebuilding the stack or losing later per-layer tweaks | MUST | `.claude/skills/pintura-pbr/SKILL.md` → "To refresh 3D masks without rebuilding the stack" |
| LAY-09 | Visibility toggle per layer and per-layer contribution diagnostics (map with a layer hidden, or a direct difference map) | MUST | `Docs/Pipeline/Pintura/painter_layer_isolate.py`; `Docs/Pipeline/Licoes/pintura-isolar-contribuicao-das-camadas.md` |
| LAY-10 | No default-material bleed at the boundary of complementary group masks (or an explicit, documented base) | MUST | `.claude/skills/pintura-pbr/REFERENCE.md` → "Grupos com máscaras complementares" |
| LAY-11 | Portable material folders (export a group as a reusable preset and insert it into another project with identical parameters) | SHOULD | `SM/21-Bracal-Esquerdo/report.json → painting_p1.smart_materials` |
| LAY-12 | Brush/stroke painting | COULD | Only one Paint effect on the hat v5 stack (`SM/10-Chapeu/report.json → layer_tree`); not used by the paint standard |

### 1.4 Materials and procedural sources

| ID | Requirement | Priority | Trace |
|---|---|---|---|
| MAT-01 | Triplanar projection for procedural/bitmap sources with physical-unit scale and normal-weighted blending (to avoid collapse on caps) | MUST | `painter_layer_stack.py` (`smart` grunges triplanar); `Docs/Pipeline/Licoes/pintura-projecao-tampos-lombada.md`, `pintura-profundidade-tres-escalas.md` |
| MAT-02 | Generators driven by mesh maps: edge wear (convex curvature), cavity dirt (AO + concave curvature), ground dirt/dust (WSN/position), with balance/contrast parameters | SHOULD | `SM/10-Chapeu/report.json → painter_recipe` (Metal Edge Wear, Mask Builder, Mask Editor); `SM/00-Corpo/report.json → painting_v3.smart_layers` |
| MAT-03 | A procedural noise/grunge library sufficient for broad/intermediate/fine variation (fbm, Voronoi cracks, spots, scratches, leather grain, felt/weave), seedable and resolution-independent | SHOULD | `SM/00-Corpo/report.json → painting_v3`; `.claude/skills/pintura-pbr/SKILL.md` → "Couro com metal", "Pano grosso" |
| MAT-04 | Equivalents of the Painter starter assets used by locked or delivered recipes (Leather Damaged, Bronze Armor, `cracks_leather`, Fabric Burlap, Leather Pattern, `fabric_felt`, smart masks Dirt Cavities / Edges Uber / Ground Dirt / Dust Dirty / Occlusion Strong / Edge Dirty Cracks), or a documented migration to the 3D-mask method | SHOULD | `SM/22-Bracal-Direito/report.json → leather_family_recipe_r9` (LOCKED); `SM/00-Corpo/report.json → painting_v3` |
| MAT-05 | Height in declared units with a documented Height→Normal conversion, so relief can be calibrated (target band 0.01–0.03 for fibres/grain on current pieces) and measured as normal-angle deviation | SHOULD | `.claude/skills/pintura-pbr/SKILL.md` → "Relevo medido, não suposto" |

### 1.5 Resources

| ID | Requirement | Priority | Trace |
|---|---|---|---|
| RES-01 | Import 16-bit grayscale PNG masks and 8/16-bit sRGB colour textures as project resources, embedded in the project, deduplicated by content hash | MUST | `painter_layer_stack.py` (SHA-1 keyed import); `Docs/Pipeline/Pintura/garment_material_masks.py` docstring |
| RES-02 | Resource identifiers valid across sessions (save/close/reopen) and across machines; no session-scoped URLs | MUST | `Docs/Pipeline/Licoes/operacao-sync-estado-por-sessao.md` |
| RES-03 | Environment (HDRI) resources stored with the project or referenced by hash, so display presets apply in any project | SHOULD | `Docs/Pipeline/Licoes/render-hdri-recurso-do-projeto.md` |
| RES-04 | Procedural resource versions pinned inside the project (re-opening must not re-resolve them differently) | MUST | `Docs/analysis/skeletal-mage-review/05-auditoria-spp-10-13-20261007.md` (resource names changed on re-export) |

### 1.6 Export

| ID | Requirement | Priority | Trace |
|---|---|---|---|
| EXP-01 | Export per texture set: BaseColor (sRGB), Roughness, Metallic, Height (raw, grayscale), combined Normal (OpenGL; geometry normal + painted Height + painted Normal), and the AO map | MUST | `Docs/Pipeline/Retopologia/cajado-v10/painter_export.py`; `AGENTS.override.md` → "Definition independent of the lighting" |
| EXP-02 | PNG 16-bit per channel; 8-bit optional; resolution per export (sizeLog2); padding/dilation to infinity (fill all empty texels); no dithering | MUST (16-bit, padding, no dithering) / SHOULD (8-bit) | `painter_export.py`; `Docs/analysis/skeletal-mage-review/05-auditoria-spp-10-13-20261007.md` (8-bit grimoire export) |
| EXP-03 | Naming template configurable to reproduce the three patterns in use (`<set>_<Map>_sRGB` / `<set>_<Map>_Raw`, `<set>_<Map>`, `<prefix>_<Map>`) and a default deterministic scheme | MUST | `05-export-and-consumers.md` §3 (listing of `SM/*/Textures`) |
| EXP-04 | Export also: geometry-only normal pass-through, any mesh map (diagnostic), per-layer isolated maps (diagnostic), unlit BaseColor | SHOULD | `SM/00-Corpo/report.json → painting_v6` (meshMap export); `painter_layer_isolate.py` |
| EXP-05 | Deterministic, bit-reproducible export: the same saved project exported twice, in different sessions or machines, yields byte-identical files | MUST | `Docs/Pipeline/Licoes/exportacao-spp-mapas-precisao-nativa.md`; `SM/00-Corpo/report.json → painting_v6.validacao.reproducao` |
| EXP-06 | Export is atomic and verified: saves first (or exports from the saved state), writes every listed file, returns paths, sizes and SHA-256, never crashes the host | MUST | `Docs/Pipeline/Licoes/operacao-segundo-plano-caminhos-e-salvamento.md`, `operacao-painter-export-mixed-ao.md` |
| EXP-07 | Opacity/alpha channel export for alpha-tested cloth (lace, fray) | SHOULD | `.claude/skills/pintura-pbr/SKILL.md` step 8; `Docs/Pipeline/README.md` → "Pendências que continuam valendo" |
| EXP-08 | Engine packing presets (glTF metallic-roughness, ORM, engine-specific) | COULD (no consumer defined in Assets3D; GLB packing is done by Blender today) | `.claude/skills/pintura-pbr/SKILL.md` step 8; `SM/23-Cinto/report.json → v5.exports` |

### 1.7 Save, versioning and recipe capture

| ID | Requirement | Priority | Trace |
|---|---|---|---|
| SAV-01 | Single self-contained project file (mesh, mesh maps, resources, stack, display state), `save`, `save_as` to a new version, `open`, `close`; accurate dirty flag; refuse to discard unsaved work | MUST | `painter_create.py`, `painter_open.py`; `Docs/Colaboracao/Colaboracao.md` → "Janela emprestada" |
| SAV-02 | Checkpoint after each step so the user can revert; previous checkpoint kept | MUST | `AGENTS.override.md` → "Keep work visible" ("re-save after each step so the user can File > Revert") |
| SAV-03 | Machine-readable recipe dump of the whole project: per node type, name, visibility, channels, per-channel opacity/blend, sources (uniform values with colour space, resource hash), projections, procedural parameters, masks and effects, plus a deterministic digest (equivalent of `snapshot_layer_tree` + `node_details`) | MUST | `.claude/skills/pintura-pbr/SKILL.md` step 10; `SM/10-Chapeu/report.json → painter_recipe` |
| SAV-04 | Rebuild a project from recipe + resources with identical exports (recovery test) | MUST | `Docs/Pipeline/Licoes/operacao-recuperacao-antes-da-limpeza.md` |
| SAV-05 | Project-adjacent clutter controlled: autosaves and lock files configurable and cleaned on close | SHOULD | `.claude/skills/pintura-pbr/REFERENCE.md` → "Higiene de arquivos"; listing of `SM/10-Chapeu/` |

### 1.8 Preview, capture and diagnostics

| ID | Requirement | Priority | Trace |
|---|---|---|---|
| VIS-01 | Read-only live viewer the user can watch while agents paint (no editing UI required), never requiring mouse/keyboard control | MUST | `AGENTS.override.md` → "Keep work visible" |
| VIS-02 | Headless capture of the current state to PNG with explicit camera, resolution and convergence; capture always reflects the latest state | MUST | `Docs/Pipeline/Licoes/operacao-projeto-captura-reais.md` |
| VIS-03 | Preview modes: lit PBR, unlit BaseColor, single channel (Normal, Roughness, Metallic, Height, AO), mask/ID view | MUST | `Docs/Pipeline/Render/Render-Comparison-Standard.json → comparison_passes` |
| VIS-04 | Display preset that implements the common standard v2 and `ref_match` (HDRI by hash, exposure 0, rotation, sRGB Standard view, no post, fixed background) and is fully serialisable/restorable, separate from the user's presentation snapshot | SHOULD | `Render-Comparison-Standard.json`; `Docs/Pipeline/Licoes/render-snapshot-real-do-preset.md` |
| VIS-05 | Camera import/export in Blender convention (Y-up ↔ Z-up, Euler `Rx@Ry@Rz`, environment `diag(1,1,-1)`), so Painter-style cameras in `Painter-Lighting-*.json` convert exactly | SHOULD | `Render-Comparison-Standard.json → coordinate_contract` |
| VIS-06 | Path-traced preview comparable to Cycles | COULD (Blender Cycles is the gate renderer) | `.claude/skills/pintura-pbr/SKILL.md` → "julgar só no viewport do Painter engana" |
| DIA-01 | Per-texture-set and per-mask-region statistics on exported maps: luminance p10/p50/p90, saturation, coverage % of each mask | SHOULD | `AGENTS.override.md` §4 (tonal range per material); `SM/10-Chapeu/report.json → v6.painting.masks` (coverage per mask) |
| DIA-02 | Relief measurement: angle between exported combined normal and geometry normal per material | COULD | `.claude/skills/pintura-pbr/SKILL.md` → "Relevo medido" (`relief_angle.py`) |

## 2. Integration requirements

### 2.1 MCP and scripting

| ID | Requirement | Priority | Trace |
|---|---|---|---|
| INT-01 | Native MCP server (stdio) plus an in-process Python API; every call returns a structured result with a reliable error flag and non-zero exit on failure | MUST | `Docs/Pipeline/MCP/painter_mcp_client.py`; `.claude/skills/pintura-pbr/REFERENCE.md` → "Batch" |
| INT-02 | MCP tools covering the calls the pipeline makes today: status/project info; create (mesh, settings, mesh maps, colour management); open/close/save/save_as; list texture sets; import resource; set mesh maps; stack sync from JSON; smart-style procedural layers; get/set layer properties; replace mask resource; snapshot/recipe dump; export (preset or inline config); capture; mesh reload; bake + job status (if BAK-03); per-layer isolation | MUST | `02-painter-usage.md` §3–§4 (tools and API counted this session) |
| INT-03 | Filesystem sandbox: allowlisted roots for project, mesh, bake mesh, resource and export paths; absolute Windows paths (`E:/...`) handled correctly | MUST | `painter_mcp_client.py` (`SP_MCP_*_ROOTS`); `.claude/skills/pintura-pbr/SKILL.md` → "pass Windows paths" |
| INT-04 | Single-writer concurrency: one mutating client at a time with an explicit lock owner; concurrent mutating commands must be rejected, not crash the process | MUST | `Docs/Colaboracao/Colaboracao.md` → "Substance Painter"; `Docs/Pipeline/Licoes/operacao-painter-exclusivo-modo.md` |
| INT-05 | Explicit "computation finished" / busy state; mutating and export calls block or fail while busy | MUST | `painter_export.py` (`is_busy` loops); `Docs/Colaboracao/Colaboracao.md` (Edition → sync → wait → save → export) |
| INT-06 | Batch execution (list of calls, stop on first error, per-call results) | SHOULD | `painter_mcp_client.py` (`batch`) |

### 2.2 Blender and Python handoff

| ID | Requirement | Priority | Trace |
|---|---|---|---|
| INT-10 | Inputs accepted as produced today: low OBJ (triangulated, `usemtl`), high OBJ (for bakes), normal/AO PNG 16-bit, masks `M_*.png` 16-bit, colour textures `T_*.png` sRGB, stack JSON | MUST | `01-pipeline-overview.md` §6 |
| INT-11 | Exported maps consumable unchanged by `deliver.py`, `render_pbr_asset.py`, `paintrender.py`, `blender_render_standard.py` and the review panel (via Blender-built GLB) | MUST | `Docs/Pipeline/Retopologia/cajado-v10/deliver.py`, `paintrender.py`; `.claude/skills/pintura-pbr/SKILL.md` step 9 |
| INT-12 | Image orientation convention documented and compatible with the mask tools (rows flipped relative to the raster arrays) | MUST | `Docs/Pipeline/Pintura/iron_material_masks.py` catalogue block; `regularize_garment_trim.py` docstring |
| INT-13 | Export of the curvature (and other mesh maps) back to Python mask tools | SHOULD | `SM/22-Bracal-Direito/report.json → leather_family_recipe_r9.masks` (`--curvature` from Painter) |
| INT-14 | glTF/FBX mesh import | COULD (pipeline uses OBJ) | `painter_create_args.json` |

### 2.3 report.json, manifest and catalogue

| ID | Requirement | Priority | Trace |
|---|---|---|---|
| INT-20 | Emit a JSON block equivalent to `painter_recipe` (project, texture sets, channels, normal format, resolutions, colour management, bake settings, layers, node details, export preset, map list) for `report.json` | MUST | `SM/10-Chapeu/report.json → painter_recipe` |
| INT-21 | Emit, per export, the fields of the manifest `exportacao` block: sources, outputs, timestamp, preset, per-map resolution / bit depth / colour space, comparison result (`bytes-iguais`, `pixels-iguais`, `equivalencia-visual`, `diferente`, `pending`) | MUST | `Docs/Pipeline/Manifesto/manifesto-schema-v1.json → $defs.exportacao, formato_mapa` |
| INT-22 | Project file and maps hashable and registrable with roles `projeto-painter` and `mapa` in `manifestos/vN.json`; tool version/hash recorded per job | MUST | `manifesto-schema-v1.json → $defs.arquivo.papel`; `bake_normal_pair.py` (helper hash recorded) |
| INT-23 | Recipes in `Docs/Biblioteca/Receitas/pintura/*.json` (steps, files with SHA-256, swatches with physical repeat) must be executable against UzPainter without editing their stack/rules files | SHOULD | `Docs/Biblioteca/Receitas/pintura/ferro-martelado-v9.json` |

## 3. Quality-gate requirements

| ID | Requirement | Priority | Trace |
|---|---|---|---|
| QG-01 | UzPainter must make the paint-gate evidence cheap to produce: unlit BaseColor, per-channel maps, exact exported low maps for `ref_match` renders, tone statistics per material mask | MUST | `AGENTS.override.md` → "Stage quality gates" §4; `Docs/Pipeline/Gates/pintura.md` |
| QG-02 | Refuse or loudly warn when creating a project for a version whose manifest does not show `gates.visual.geometria-encaixe = pass` (policy switchable) | SHOULD | `Docs/Pipeline/Licoes/gate-nao-pintar-geometria-reprovada.md` |
| QG-03 | Never report success on partial results: sync, bake and export results list exactly what was imported, changed, written and skipped | MUST | `Docs/Pipeline/Licoes/operacao-sync-estado-por-sessao.md` |
| QG-04 | Approval state is out of scope of the tool: UzPainter records technical facts only; artistic approval stays with the user and the report | MUST | `.claude/skills/pintura-pbr/SKILL.md` step 10; `Docs/Pipeline/Manifesto/README.md` |

## 4. Non-functional requirements

| ID | Requirement | Priority | Trace |
|---|---|---|---|
| NFR-01 | Runs fully headless on Windows 11 (no window, no focus) for CI/batch; the live viewer (VIS-01) is optional | MUST | `AGENTS.override.md` → "Never drive the user's windows"; `Docs/Pipeline/MCP/Ambiente.md` |
| NFR-02 | Determinism: identical inputs + recipe + seed ⇒ identical exports on the same build | MUST | `Docs/Pipeline/Licoes/exportacao-spp-mapas-precisao-nativa.md` |
| NFR-03 | Scale: at least 3 texture sets × 4096² × 5–6 exported maps at 16-bit in one project (body); stacks of 30+ layers (bracer 21: 31 layers) with 20+ imported 4K 16-bit masks (hat v6: 21 masks + 1 colour texture at 4096) | MUST | `SM/00-Corpo/report.json → texture_sets_v3`; `SM/21-Bracal-Esquerdo/report.json → painting_p1`; `SM/10-Chapeu/report.json → v6.painting.masks` |
| NFR-04 | Project file size should not exceed Painter's for the same content (baseline: tunic v10 `.spp` 408,723,056 B; hat v8 556,279,426 B; body v6b 1,190,431,812 B) | SHOULD | Listing this session |
| NFR-05 | Speed: no Painter timing baseline is recorded except a 5-baker, 3-set bake in 54 s; targets must be set during architecture and measured on these pieces | SHOULD | `SM/00-Corpo/report.json → painting_v6.rebake_mesh_maps.job_id_lote` |
| NFR-06 | Robustness: export, bake and capture never terminate the process; a crash leaves the last saved checkpoint intact and recoverable | MUST | `Docs/Pipeline/Licoes/operacao-painter-export-mixed-ao.md`; `operacao-segundo-plano-caminhos-e-salvamento.md` |
| NFR-07 | Offline: no network dependency for painting, export or preview | SHOULD | **H** — not stated in sources; Painter and Blender are used locally (`Docs/Pipeline/MCP/Ambiente.md`) |
| NFR-08 | Version pinning: internal resources and the evaluator version recorded in every project and export | MUST | `Docs/analysis/skeletal-mage-review/05-auditoria-spp-10-13-20261007.md` |

## 5. Boundary: what stays in Blender / Python

| Stays outside UzPainter | Why | Trace |
|---|---|---|
| Meshy generation, assembly/fit, coverage cuts, pivots (`equip_pivot.py`) | Geometry decisions, not painting | `Docs/Pipeline/README.md`; `AGENTS.override.md` → "Equipment pivot" |
| Low/retopo construction, UV unwrap, density normalisation (10.24 px/cm), packing, validation, texture-set split/join | UV is the input contract; "never remediate a bad UV with masks or resolution" | `.claude/skills/uv-profissional/SKILL.md` |
| Authoritative geometry normal bake (`bake_normal_pair.py` with RAW/coverage/stages/parts) and the low+normal vs high fidelity gate | Mature, evidence-producing tool; the gate precedes painting | `Docs/Pipeline/Pintura/bake_normal_pair.py`; `Docs/Pipeline/Render/render_fidelity_pairs.py` |
| 3D per-texel mask computation and swatch projection (`garment_material_masks.py` and siblings) | Masks are computed from 3D construction; UzPainter imports them | `AGENTS.override.md` → "Paint standard" step 2 |
| Swatch generation (`image_gen`) and Library provenance | Image generation by Astra | `Docs/Biblioteca/README.md` |
| Gate renders in Cycles under `ref_match`, boards and tone stats on renders | The measured reference light lives in Blender | `Render-Comparison-Standard.json → presets.ref_match` |
| GLB/FBX export, glTF packing, round-trip checks | Mesh export from copies with tangents | `Docs/Pipeline/Retopologia/cajado-v10/deliver.py` |
| `report.json` writing scripts, `manifesto.py`, catalogue | Pipeline bookkeeping; UzPainter only supplies data (INT-20…22) | `Docs/Pipeline/Manifesto/README.md` |

**R** — What UzPainter takes over from Painter: hosting the editable layer stack; procedural generators/materials that today come from Painter starter assets; auxiliary mesh maps when not supplied; map export; live preview and captures; recipe dump.

## 6. Open questions (need a decision or evidence)

| # | Question | Why it matters | Trace |
|---|---|---|---|
| Q1 | Will the user amend the "Painting is always in Substance Painter" rule, and on which pilot piece? | G-01 blocks adoption | `AGENTS.override.md` |
| Q2 | Must existing `.spp` projects (tunic v10, body v6b, bracers) be imported, or is rebuild-from-recipe enough? `.spp` is a proprietary format | Migration scope | `SM/18-Tunica/report.json → painting_v10.source_recovery` |
| Q3 | Which Painter starter assets need exact equivalents (Leather Damaged, Bronze Armor in the LOCKED leather recipe) vs migration to 3D masks? | MAT-04 scope | `SM/22-Bracal-Direito/report.json → leather_family_recipe_r9` |
| Q4 | Which engine consumes the maps (UzEngine? Unreal?) and with which packing, compression and normal convention? Assets3D does not define it | EXP-08 priority | `.claude/skills/pintura-pbr/SKILL.md` step 8 |
| Q5 | Should UzPainter bake normal/AO itself, or keep Blender authoritative and only import? | BAK-03 priority | `Docs/Pipeline/Retopologia/*/bake.sh` |
| Q6 | Is the preview shader model OpenPBR (as the Painter channel names suggest) or metal-roughness glTF; how far must it match Cycles? | VIS scope | `SM/10-Chapeu/report.json → painter_recipe.channels` (H) |
| Q7 | Is a live viewer acceptable within "no human editing UI"? The user directive asks to watch painting live | VIS-01 | `AGENTS.override.md` → "Keep work visible" |
| Q8 | Is alpha output needed now (lace/fray) or later? | EXP-07 | `Docs/Pipeline/README.md` → "Pendências" |
| Q9 | Performance targets: none recorded | NFR-05 | — |

## 7. MUST list (short form)

G-01, G-02, G-03; PRJ-01…09 (PRJ-03 at 2K/4K; PRJ-06 first five channels); BAK-01, BAK-02, BAK-05 (if baking), BAK-06; LAY-01…10; MAT-01; RES-01, RES-02, RES-04; EXP-01, EXP-02 (16-bit/padding/no dithering), EXP-03, EXP-05, EXP-06; SAV-01…04; VIS-01, VIS-02, VIS-03; INT-01…05, INT-10…12, INT-20…22; QG-01, QG-03, QG-04; NFR-01, NFR-02, NFR-03, NFR-06, NFR-08.
