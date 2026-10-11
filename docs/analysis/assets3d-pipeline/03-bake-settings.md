# 03 — Bake workflow actually used

Conventions as in [01](01-pipeline-overview.md): paths relative to `E:\UzmiGames\Assets3D\`, `SM/` = `Creatures/Undead/Skeletal Mage/Models3D/`, **F** Fact / **H** Hypothesis / **R** Recommendation.

## 1. Three bake families

| Family | Engine | Maps | Status in the pipeline | Type | Source |
|---|---|---|---|---|---|
| A. Geometry normal | Blender Cycles, selected-to-active, via `Pipeline/painting/bake_normal_pair.py` | Tangent-space normal, OpenGL, 16-bit RGB PNG | Normal source in every recipe checked after the hat pilot (tunic, body, bracers, pauldrons, grimoire, hat v6/v8, staff, wand, belt/sash); imported into Painter as the Normal mesh map. This is the observed route, not a product exclusion: the owner requires native high-poly bake in UzPainter (08, BAK-03) | F | `bake_normal_pair.py` docstring; `Pipeline/retopology/*/bake.sh`; `painter_create.py` |
| B. AO, mask and label bakes | Blender Cycles (`garment_blender_io.py extract` AO; `EMIT` selected-to-active for material labels; `high_part_labels.py bake`; `part_masks.py faceattr` emission bake of the low onto its own UV) | AO (`ao.npy` → 16-bit PNG), per-material masks, per-part masks | Inputs of the 3D mask computation; since 2026-10-09 the AO is also the Painter AO mesh map; its delivery as glTF occlusion is required by directive but implemented only in the hat v8 deliver script among the checked ones | F | `Pipeline/painting/garment_blender_io.py`, `high_part_labels.py`, `part_masks.py` docstrings; `Docs/Lessons/painting-ao-ray-misses-and-definition.md`; `Pipeline/retopology/*/deliver*.py` (search this session) |
| C. Painter mesh-map bakers | Painter 12.1 baker | Normal (hat pilot only), World Space Normal, AO, Curvature (from mesh), Position, Thickness; ID configured once and removed | Hat v5 (all maps); tunic, body, bracers (auxiliary maps only); not recorded for the 2026-10-09 construction pieces | F (H for "not run" on the 10-09 pieces: absence in reports) | `SM/10-Chapeu/report.json → painter_recipe.bake_settings`; `SM/18-Tunica/report.json → painting.bake`; `SM/00-Corpo/report.json → painting_v3.mesh_maps`; `SM/22-Bracal-Direito/report.json → painting.mesh_maps` |

## 2. High-poly sources

| Fact | Type | Source |
|---|---|---|
| Highs are Meshy outputs (dense, fused single surfaces, metal without material ID), preserved read-only; work happens on copies inside the piece `.blend` | F | `Docs/Pipeline-Guide.md` → "Geração", "Conferência"; `.claude/skills/pbr-painting/SKILL.md` → "Couro com metal sem ID na high" |
| Example sizes: hat high 667,248 tris; staff high 162,964 tris; wand 172,908 tris; grimoire v2 606,526 tris; body high 1,307,100 polygons (up to 18 sides) / 1,341,366 loop triangles | F | `SM/10-Chapeu/report.json → source_data`; `Pipeline/retopology/staff-v9/README.md`; `wand11-v1/README.md`; `Docs/Pipeline-Guide.md` (grimório v2); `Docs/Lessons/bake-evaluated-triangulation-saved.md` |
| Fused highs are split per part (`bakeprep.py`) so each low part bakes only from its own high part (`--parts`), e.g. staff split at z 1.759 / 1.724 m with a small overlap | F | `Pipeline/retopology/staff-v10/bakeprep.py`, `README.md` |
| For Painter bakers the high is exported from the current `.blend` as a triangulated OBJ with normals; the hat pilot used a high OBJ with material colours (R cloth, G leather, B metal) | F | `SM/00-Corpo/report.json → painting_v6.rebake_mesh_maps.high`; `.claude/skills/pbr-painting/REFERENCE.md` → "Bake dos mapas no Painter" |
| Material labels are stored as point attributes on the working high (`Mask_Leather`, `Mask_Metal`, `Mask_Cloth`) to rebake masks | F | `SM/10-Chapeu/report.json → source_data.high_point_attributes` |
| Bake requires a UV-validated, topology-frozen low (no modifiers or shape keys). The helper itself refuses modifiers/shape keys and shared mesh data and checks only the active UV's bounds, sign and area; full UV validation and the fidelity gate are separate prerequisites | F | `bake_normal_pair.py` docstring and lines 460–463, 841–842; `.claude/skills/pbr-painting/SKILL.md` → "Pré-requisitos obrigatórios" |

## 3. Blender normal bake parameters per piece

Values from the recipes' `bake.sh`, parts JSON (which overrides the command-line ray/cage per part) and reports. Every recipe with a `bake.sh` (hat v6, staff v9/v10, belt/sash v5) uses `--repair-min-z 0.15` and `--margin 16`; margins of the other rows are noted when recorded.

| Piece / version | Resolution | Ray distance / cage extrusion (m) | Parts / cage fill | Source |
|---|---|---|---|---|
| 10-Chapeu v6 | 4096 | crown 0.018/0.008; band 0.022/0.008; brim 0.020/0.008; strap-keeper 0.010/0.004; buckle 0.012/0.004 | 5 parts; cage fill 0.008/0.003 on strap-keeper and buckle | F — `Pipeline/retopology/hat-v6/bake.sh`, `hat-parts.json`, `bake/report-hat.json` |
| 09-Cajado v10 | 4096 | shaft 0.012/0.004; head 0.008/0.003 | 2 parts; cage fill 0.006/0.002 on head | F — `Pipeline/retopology/staff-v10/bake.sh`, `staff-parts.json` |
| 11-Varinha-Madeira v1 | 2048 | 0.006/0.003 | none recorded | F — `Pipeline/retopology/wand11-v1/bake/report.json` |
| 23-Cinto v5 | 2048 | 0.010/0.004 | `belt-parts.json` (generated by `bakeprep.py`) | F — `Pipeline/retopology/waist-v5/bake.sh` |
| 25-Faixa-Cintura v5 | 2048 | 0.012/0.005 | `sash-parts.json` | F — same |
| 00-Corpo v3 | 4096 per texture set | 0.005/0.002 | per set (Crânio/Tronco/Membros) | F — `SM/00-Corpo/report.json → normal_bake_v3` |
| 19-Ombreira v9 | 2048 | 0.006/0.003 | none | F — `SM/19-Ombreira-Esquerda/report.json → v9.normal_bake` |
| 18-Tunica (v6–v10) | 4096, 16-bit | 0.014/0.006, margin 8 | none | F — `SM/18-Tunica/report.json → painting.bake` |
| 13-Grimorio v3 | 2048 | 0.0025/0.0012 | none | F — `SM/13-Grimorio/report.json → normal_bake_v3` |
| 13-Grimorio v4 | 2048 (16-bit), margin 32 | 0.003/0.0015 | none; then 2×2 supersampling (mean of signed normals, renormalised, Raw 16-bit RGB) | F — `SM/13-Grimorio/report.json → normal_bake`, `normal_supersampling` |

**F** — Output contract (`bake_normal_pair.py`, `Pipeline/retopology/wand11-v1/bake/report.json`): 16-bit RGB PNG, colour space Non-Color, convention "OpenGL +X +Y +Z tangent", margin type EXTEND, PNG round-trip error recorded (hat v6: 1.0e-5), source = geometry only (high shader detail disabled during bake), low Normal input replaced (never compounded with an older normal or bump), PNG packed into the `.blend` when `--save-blend` is given. The round-trip figure certifies PNG serialization only, not visual fidelity or renderer parity.

## 4. Bake evidence produced by `bake_normal_pair.py`

| Output | Meaning | Type | Source |
|---|---|---|---|
| `<out>_raw.png` | Combined bake as returned by Blender (all parts; straight-ray hits plus accepted cage-fill hits), before hit/hidden/margin/repair processing; texels without a hit are 0. Not straight-ray-only data | F | `bake_normal_pair.py` docstring and lines 688–693 |
| `<out>_coverage.png` | R = ray hit (straight OR cage hit, before `--hidden-mask`), G = pixel centre (texels Blender bakes), B = used surface (conservative triangle × pixel-square SAT test) | F | Same, lines 698–703; `.claude/skills/pbr-painting/SKILL.md` → "Verified 2026-10-07" |
| `<out>_stages.png` | R = used surface set flat (centre miss, edge ring without a hit neighbour, hidden), G = extended from neighbours (edge ring inside the used surface, margin fill outside), B = changed by `--repair-min-z`; padding with none of R/G/B and no hit was set flat (not reached by the margin) | F | Same, lines 734–742 |
| `<out>_invalid_mask.png` | Layered annotations (red used surface flagged, blue fill); not exclusive classes | F | Same |
| `<out>_cage_fill.png` | Texels filled by the per-part cage bake | F | Same |
| `used_surface_summary` | `used_surface_texels`, `baked_intact`, `centre_miss_flat`, `hidden_flat`, `ring_extended`, `ring_no_hit_neighbour_flat`, `repair_modified`, `neutral_fallback_texels`, `flagged_left_as_baked`, `fidelity_evidence` verdict (`used_surface_as_baked` only when no fallback; suffixes `_with_cage_fill`, `contains_neutral_fallback`) | F | `Pipeline/retopology/staff-v10/bake/report-staff.json` |
| Binding | Helper SHA-256 at start and end; parts JSON and face→part assignment hashed; `--hidden-mask` + `--hidden-evidence` (hash only) | F | `bake_normal_pair.py` docstring |

Example (F, `Pipeline/retopology/hat-v6/bake/report-hat.json`): hat v6 at 4096 — 10,006,401 used-surface texels, 9,471,331 baked intact, 503,741 centre-miss flat, 512,149 neutral-fallback texels, 22,921 ring-extended, 0 hidden-flat, 0 repair-modified, verdict `contains_neutral_fallback_with_cage_fill`. The fidelity gate then decided `pass (agent)` with a pending close-up of the buckle window (`SM/10-Chapeu/report.json → v6.normal_bake.decision`). The counts neither grant nor reject artistic approval; the buckle close-up stays pending.

## 5. AO bakes

| Piece | Parameters | Use | Type | Source |
|---|---|---|---|---|
| 18-Tunica v9 | Cycles AO high→low, 2K, 96 samples, cage 0.006 m, max ray 0.014 m | Cavity masks | F | `SM/18-Tunica/report.json → painting_v9.mask_sources.ao` |
| 10-Chapeu v6 → v8 | First bake cage 8 mm / ray 30 mm: 171,408 used-surface texels at AO < 0.02 (1.7 %); a second bake cage 20 mm / ray 60 mm used only on those texels recovered 94,890; recorded remainder 77,588 (hidden faces + a real brim tear of 6,149 texels) — see the note below | AO map (16-bit, glTF occlusion), moderate AO layer in albedo (`M_ao_albedo`), fine cavity (`M_cavity`), Painter AO mesh map (`painter_set_ao.py`) — one corrected AO for all uses | F | `Docs/Lessons/painting-ao-ray-misses-and-definition.md`; `SM/10-Chapeu/report.json → v8.ao`; `Pipeline/retopology/hat-v6/hat_masks_v8.py` lines 106–113 |
| 19/20 Pauldrons v9 | 2048, 64 samples, cage 0.004, max ray 0.01 | Mask inputs | F | `Docs/Library/Recipes/painting/hammered-iron-v9.json → passos` |
| 21 Bracer p1 | 32 samples, cage 0.003, ray 0.008 | Mask inputs | F | `SM/21-Bracal-Esquerdo/report.json → painting_p1.masks.work` |
| 25 Sash v5 | 2048, 96 samples | Mask inputs + Painter AO mesh map | F | `Pipeline/retopology/waist-v5/sashchain.sh` |

**F** (arithmetic this session) — 171,408 − 94,890 = 76,518, which is 1,070 fewer than the recorded remainder 77,588. `hat_masks_v8.py` prints only first-bake misses, recovered texels and the tear (`_tmp/claude/chapeu-v6/paint/masks-v8*.log`: "first-bake misses 171408 recovered by the second 94890 brim tear 6149"); no checked source states how 77,588 was counted. **H** — 77,588 may count every second-bake miss (`ao2 < 0.02`), including texels the first bake hit; not confirmed. The corrected remaining count is not confirmed.

**F** — Rule since 2026-10-09: AO = 0 on used surface is a ray miss, not occlusion; rebake those texels with a larger cage/ray; paint a real hole in the high as a hole (`AGENTS.override.md` → "Definition independent of the lighting"). The hat implementation counts a miss as AO < 0.02 (`hat_masks_v8.py`), and the paint-gate check asks to separate hidden faces, ray misses and real holes in the high (`Docs/Gates/painting.md`): a zero or low AO value alone does not prove a miss.

## 6. Mask/label bakes in Blender

| Bake | Parameters | Type | Source |
|---|---|---|---|
| Material masks (hat pilot) | Cycles, 1 sample, OptiX; `bake(type='EMIT', use_selected_to_active=True)`; max ray 0.004 m, cage 0.002 m; margin 16 px; 4096² Non-Color; label material emits white, others black (vertex weights via Attribute node) | F | `.claude/skills/pbr-painting/REFERENCE.md` → "Bake das máscaras no Blender" |
| Stitch dots (tunic) | `bake_garment_edge_masks.py` uses margin 0 (margin 16 merged dots into bands); dilation happens in Painter | F | REFERENCE.md → "Máscaras de pontos de costura" |
| Hardware labels on fused highs | `high_part_labels.py bake` (defaults 2048, ray 0.006, cage 0.003, margin 16) then `inject` into `raster.npz` | F | `Pipeline/painting/high_part_labels.py` docstring |
| Part IDs of the low | `part_masks.py faceattr` emission bake onto the low's own UV, 16-bit PNG + `.npy` | F | `Pipeline/painting/part_masks.py` docstring |

## 7. Painter baker settings that were used

| Parameter | Hat v5 (full Painter bake) | Body v3/v5/v6 | Bracers 21/22 | Source |
|---|---|---|---|---|
| Bakers | Normal, WorldSpaceNormal, AO, Curvature (FromMesh), Position, Thickness | WSN, AO, Curvature, Position, Thickness (Normal from Blender) | WSN, AO, Curvature (FromMesh), Position, Thickness | F — `SM/10-Chapeu/report.json → painter_recipe.bake_settings`; `SM/00-Corpo/report.json → painting_v6.rebake_mesh_maps`; `SM/21-Bracal-Esquerdo/report.json → painting_p1.project.bake` |
| Output size | `[12,12]` (4096) | 4096 | 2048 | same |
| SubSampling | 2 | 2 | 2 | same |
| MaxHeight / MaxDepth | 0.006, relative scale, no cage (`CageMode 0`) | 0.01 relative, no cage | 0.02 | same |
| Dilation | 32 px, no diffusion | 16 px (v6) | 32 px | same |
| Other common | `IgnoreBackface`, `SmoothNormals`, `LowAsHigh=false`, suffixes `_low/_high/_ignorebf` | `IgnoreBackface`, `SmoothNormals` | — | same |
| AO | 64 secondary rays, min 1e-5, max 1.0 relative, spread 180°, distribution 1, attenuation 2, no ground plane | 64 rays | — | F — `SM/10-Chapeu/report.json → painter_recipe.bake_settings.baker_values.AO`; body report |
| Curvature | 32 rays, sampling radius 0.001 (`MaxDistanceRelativeScale=true`), `AutoMinMax=true`, bounds [-1, 1] | Membros v6: `AutoMinMax=false`, bounds (-1297.67, 769.75), then reset to auto (settings are linked across the 3 sets, so a re-bake returns to the automatic range unless the bounds are reapplied; Crânio thickness differed 40.41/255 on unchanged texels and was not re-baked at that stage) | `AutoMinMax=false`, bounds ±3250 (1/m), same as 22 r4 | same; `SM/00-Corpo/report.json → painting_v6.rebake_mesh_maps.curvatura_membros` |
| Position / Thickness | Position mode 0, axis 0, normalization 1; Thickness 64 rays, max 0.1 relative, maximize range | 64 rays | — | `SM/10-Chapeu/report.json → painter_recipe.bake_settings` |
| Timing | — | Batch bake of 5 bakers on 3 sets: 54 s | — | F — `SM/00-Corpo/report.json → painting_v6.rebake_mesh_maps.job_id_lote` |

## 8. Known failures and fixes

| Failure | Cause | Fix / rule | Status | Source |
|---|---|---|---|---|
| Painter bake refused texture sets without UV tiles ("no enabled UV tiles") | MCP preflight/`start_bake` required a non-empty tile list even for non-UDIM sets | Local patch: only require enabled tiles when `all_uv_tiles()` is non-empty | Fixed (patch) | F — `Pipeline/mcp/substance-painter-mcp-local.patch`; `Docs/README.md` |
| Bake ran on the old mesh after a reload | Status read from the previous job; existing backup blocked reload | Pass `overwrite_backup: true`; poll the current `job_id`; reload → rebake mesh maps → resync masks | Procedure | F — `Docs/Lessons/operation-reload-job-id.md`; `.claude/skills/pbr-painting/SKILL.md` → "Recarga de malha" |
| New islands changed curvature everywhere in a set | Painter's automatic curvature range (the body report says auto tonemapping per UV tile; the skill says per texture set) | Re-bake curvature with fixed bounds found by iteration against the old map; record the effective bounds per set, because the shared settings were restored to automatic and a re-bake reverts | Validated on body v6 | F — `.claude/skills/pbr-painting/SKILL.md` → "Carrying paint onto a changed mesh"; `SM/00-Corpo/report.json → painting_v6` |
| AO = 0 read as occlusion; dark spot on hat crown | Ray misses (cage/ray too short) | Second, wider AO bake only on missed texels; real tears become their own mask | Validated | F — `Docs/Lessons/painting-ao-ray-misses-and-definition.md` |
| AO bake could not see the high | Collections excluded from the view layer | `garment_blender_io.py extract` re-enables collections/layers before baking | Fixed in tool | F — `.claude/skills/pbr-painting/REFERENCE.md` → "Armadilhas desta rodada" |
| `--repair-min-z` altered used surface, wrapped with `np.roll`, kept no RAW (144,983 texels on belt) | Low Z treated as invalid; centre-only masks | Keep RAW + masks; repair padding only; conservative SAT coverage; count every fallback | Tool fixed; per-asset revalidation pending | F — `Docs/Lessons/bake-raw-and-coverage-stages.md` |
| Black (Z < 0) normal texels on hidden faces / tab interiors | Rays starting inside another part of a fused high; twisted low rows | `--parts`, `--hidden-mask`, `cage_fill`; common row heights across a panel | Validated | F — `.claude/skills/pbr-painting/SKILL.md` → "Couro com metal: 23-Cinto"; `Docs/Lessons/low-shared-lines-per-panel.md` |
| 2,641 black RGB16 texels in a Painter re-export of the hat normal | Coincident opposite faces with zero corner normals/bitangents in the saved low; the re-export stored ≈ 0 in all channels. The internal zero → NaN stage is not confirmed | Fix geometry/normal basis in a derivative; assert finite non-degenerate TBN before bake/export. Control candidate A (six corner normals repaired; same 16,000 faces and per-corner UV) exported 0 black texels but still differs from the delivery by up to 1,472/65,535 (1.5 % of texels above 2 LSB) | Diagnosed; production fix pending | F — `Docs/Lessons/bake-per-corner-normals-tbn.md`; `Docs/analysis/skeletal-mage-review/05-spp-audit-10-13-20261007.md` |
| Masks/lookups wrong after vertices moved | Blender re-triangulates ngons when vertices move | Bind masks and lookups to the evaluated triangulation of the exact saved file | Rule | F — `Docs/Lessons/bake-evaluated-triangulation-saved.md` |
| Persistent halo around a gem rim | Voxel smoothing rounded the low's support step | Local geometry patch + local cage; supersampling does not fix it | Validated | F — `Docs/Lessons/bake-halo-from-low-support-geometry.md` |
| Old bakes used with new mesh/UV | Derivatives not bound to their source round | Hash file/object/UVMap/transforms/triangulation; any change invalidates bakes, masks, fidelity, exports | Rule | F — `Docs/Lessons/bake-invalid-when-mesh-or-uv-changes.md` |
| Rebake from `.spp` impossible | OBJ paths stored inside the `.spp` point to deleted folders | Re-export high/low from the current `.blend` before any rebake; Painter writes `.assbin` caches next to the high | Procedure | F — `.claude/skills/pbr-painting/REFERENCE.md`; `SM/22-Bracal-Direito/report.json → painting.mesh_maps.note` |
| Texture-set validation after join is meaningless | Joined sets overlap in 0–1 | Validate (and bake) each set before `uv_join_texture_sets.py` | Rule | F — `.claude/skills/professional-uv/SKILL.md` → "Variante: vários texture sets por região" |

## 9. Gate after the bake

**F** — Render the low with the baked normal and the high in a neutral material (no paint, no procedural weave), in the views required by `AGENTS.md`; check silhouette, layers, openings, folds, details and projection artefacts; record `low_high_fidelity = pass` only if visually identical or very close; revalidate after any geometry/UV/triangulation/bake change (`.claude/skills/pbr-painting/SKILL.md` step 4 "Portão após o bake"; tool `Pipeline/render/render_fidelity_pairs.py`, neutral grey linear 0.18, roughness 0.5, MAE and silhouette IoU per view). Numbers support but never replace the visual check (`AGENTS.override.md` → "At each gate").
