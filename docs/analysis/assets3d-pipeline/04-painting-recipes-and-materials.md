# 04 — Painting recipes, layer stacks and materials

Conventions as in [01](01-pipeline-overview.md): paths relative to `E:\UzmiGames\Assets3D\`, `SM/` = `Creatures/Undead/Skeletal Mage/Models3D/`, **F** Fact / **H** Hypothesis / **R** Recommendation. All colours below are sRGB 0–255 unless written as 0–1. Every numeric value is a case value of one piece; the sources say explicitly that they are not universal presets (`SM/18-Tunica/report.json → quality_reference.values_policy`; `.claude/skills/pintura-pbr/SKILL.md` → "Material e escala são decisões por peça").

## 1. The binding paint standard (tunic process)

**F** — `AGENTS.override.md` → "Paint standard = the approved tunic process (user decision 2026-10-08)":

1. Read the reference enlarged 4×; list each visual feature with its scale in mm and its colour.
2. Build one mask per feature, computed in 3D per texel on the low from real geometry: high normal/ridge, geodesic distance to edges, AO, convexity, labelled parts, seeded 3D noise. Export 4K 16-bit masks.
3. Base colour comes from reference-derived samples: Astra generates flat BaseColor swatches, projected in 3D.
4. In Painter each layer is a uniform-colour fill with one bitmap mask, grouped by material, kept editable. Height is layered at broad, intermediate and fine scales.
5. Review Base Color and the lit material next to the enlarged reference, in the visible Painter.

**F** — "Generic grunge or smart-mask stacks are not the material's character; they were rejected on pads v4c–v7" (same section). The body v3 and bracer stacks (smart masks, smart materials) predate or sit beside this rule (`Docs/Pipeline/Licoes/pintura-texture-sets-anatomia.md`: "a pilha smart/grunge é história do corpo, não substitui o padrão atual"). The standard does not retire existing recipes: the bracer leather family is LOCKED on Painter's `starter_assets/Leather Damaged` (`SM/22-Bracal-Direito/report.json → leather_family_recipe_r9`), so migration and parity tests still have to reproduce it (08, MAT-04).

**F** — Visual depth rules (`AGENTS.override.md` → "Paint must have visual depth…"; "Definition independent of the lighting"): build broad / intermediate / fine scales; cavities must read as recessed relief (Normal/Height + darkened recess + roughness), not coloured dots; AO and fine cavity darken BaseColor in their own editable layers; deliver a 16-bit AO map wired as glTF occlusion.

## 2. Data model of a synced stack

**F** — Schema read by `Docs/Pipeline/Pintura/painter_layer_stack.py` (docstring and `SYNC_CODE`):

| Field | Meaning |
|---|---|
| `title` | Name of the root group that `sync` rebuilds |
| `groups[]` | `{key, name, mask: null or "M_name", replace_height: bool}`, listed bottom to top. The docstring advises leaving the first group unmasked (two complementary group masks let Painter's default material show at the seam); the code does not enforce it (line 87), and the staff v10 (`M_wood`) and hat v8 (`M_felt`) stacks start with a masked group |
| `layers[]` | `{id, group, name, mask: null or "M_name", base: [r,g,b] (0–1 or 0–255, sRGB) or base_tex: "T_name", rough, metal, height, spec, op}`, listed bottom to top inside each group |
| `base` | Uniform BaseColor (sRGB) |
| `base_tex` | `<masks>/T_name.png` used as BaseColor bitmap (sRGB, already projected into the final UV; scale 1, RepeatNone, BilinearHQ) |
| `rough` / `metal` / `spec` / `height` | Uniform `SpecularRoughness`, `BaseMetalness`, `SpecularWeight` (OpenPBR specular weight; channel must exist; used on 3 hat v8 layers), `Height` (Linear Dodge per the docstring; `sync` does not set the fills' Height blend, so the effective mode is Painter's default, not read back by the tool) |
| `op` | BaseColor opacity only (in `smart`, `op` applies to every active channel) |
| Mask | Black-background layer mask + fill effect with the bitmap resource, UV projection |

**F** — The `smart` config: `{layers:[{name, color, rough, height, op, blend, mask:{type:"smart_mask"|"grunge", name, tiling, params, levels:[in_min,in_max,gamma]}}]}`; smart masks read the set's baked mesh maps; grunges are triplanar with a `Levels` effect (same source).

## 3. Where masks come from (computed outside Painter)

| Input field | How it is computed | Source |
|---|---|---|
| `raster.npz` | Low triangulated in the final UV: triangle id, barycentrics, 3D position, corner normal and island per texel | F — `.claude/skills/pintura-pbr/REFERENCE.md` → "Campos e máscaras da base v9" |
| `ridge` | Divergence of the high→low tangent normal (OpenGL), Gaussian band-pass 0.8 px − 6 px inside each island | Same |
| `rim_sd` | Signed geodesic distance to the cloth/lining boundary (Dijkstra on vertices) | Same |
| `sd_hem` | True hem: border vertices with cloth above and free space below (≥ 4 of 5 rays) | Same |
| `conv` | Displacement of the low vs 8 Laplacian smoothing iterations along the normal | Same |
| AO | Cycles AO high→low (see 03) | Same |
| `highrelief.npz` | High positions/normals/relief vs Laplacian-smoothed copy (default 120 iterations; pauldron v9 needs 40) | F — `Docs/Pipeline/Pintura/garment_blender_io.py`; `Docs/Biblioteca/Receitas/pintura/ferro-martelado-v9.json` |
| Construction tables | For generated pieces the masks come from the generator itself (stitch phase, holes, edges, tab outlines) | F — `Docs/Pipeline/Retopologia/cintura_v5/README.md` → "Máscaras" |
| Painter curvature | The Painter-baked Curvature mesh map is exported (temporary layer) and fed back into `leather_distress_masks.py --curvature` | F — `SM/22-Bracal-Direito/report.json → leather_family_recipe_r9.masks` |

| Mask script | Main masks | Archetype | Source |
|---|---|---|---|
| `garment_material_masks.py` | honeycomb pores (13 projection directions), fibres, dye fade, stains/drips, embroidered band, piping, lace band, eyelets, fray, hem dirt, cavity, worn crests | Cloth (tunic, sash) | F — script docstring; REFERENCE.md |
| `bone_material_masks.py` | `M_cav`, `M_groove`, `M_deep`, `M_halo`, `M_edge`, `M_pores`, `M_speck`, `M_cracks`, `M_stain`, `M_yellow`, `M_dust`, `M_sutures`, `M_gap/M_bump`, named soft boxes (`M_teeth`) | Bone | F — script docstring |
| `book_material_masks.py` | labels (cover, spine cloth, bands, pages, straps, iron, gem) + masks | Book | F — script docstring |
| `leather_metal_masks.py` | `M_leather/M_metal`, mottle, scuff, distress, edge, stitch, crease, cav, crack, dirt, metal edge/cav/patina/pits, `M_deep` | Leather with hardware | F — script docstring |
| `normal_detail_masks.py` | stitch beads/grooves from the normal, inner face, rolled edges, holes, worn stitch/edge, fine crack/scratch | Leather family | F — script docstring |
| `leather_distress_masks.py` | open cracks + rims, mottle light/dark, abrasion (fbm or scratch), convexity | Leather family, hammered iron | F — script docstring; `ferro-martelado-v9.json` |
| `iron_material_masks.py` | `T_iron`, `T_rust` (8-bit sRGB, swatches projected triplanar) + `M_edge`, `M_rim_rust`, `M_seam_rust`, `M_rust_stain`, `M_cav`, `M_sheen` (16-bit) | Plate armour | F — script docstring |
| `strap_band_masks.py`, `part_masks.py`, `high_part_labels.py` | strap band masks/textures; part-ID masks and cabochon (gem) masks; hardware labels on fused highs | Straps, gems, hardware | F — script docstrings |
| Per-piece scripts | `hat_masks.py`, `staff_masks.py`, `wand_masks.py`, `waist_masks.py` | Hat, staff, wand, belt/sash | F — `Docs/Pipeline/Retopologia/*/README.md` |

**F** — All masks are 16-bit PNG with padding; colour textures `T_*` are sRGB 8-bit; image rows are flipped relative to the raster convention (`iron_material_masks.py` catalogue block; `regularize_garment_trim.py` docstring).

## 4. Painter-native features actually used

| Feature | Where | Type | Source |
|---|---|---|---|
| Fill layers, groups, layer masks, fill effects with bitmaps, Levels, Sharpen filter, Paint effect, a paint layer | Hat v5 (22 fill layers, 20 fill effects, 8 generators, 4 groups, 4 filters, 1 paint effect, 1 levels, 1 paint layer — counted this session) | F | `SM/10-Chapeu/report.json → painter_recipe.node_details` |
| Blend modes | Normal, Linear Dodge (Height), Normal Map Detail (Normal channel), Replace, Subtract (mask), Multiply, Passthrough, Lighten | F | Same (counted this session) |
| Generators | Metal Edge Wear (user-authored black-accent layer), Mask Builder – Legacy (AO + concave curvature), Mask Editor, Dirt | F | Same; `.claude/skills/pintura-pbr/REFERENCE.md` table; `.claude/skills/pintura-pbr/SKILL.md` sources list |
| Generators depend on Painter mesh maps (WSN, position, curvature, AO, thickness) | Hat v5 node resources reference `world space normal / position / curvature / ambient occlusion / thickness Hat_Surface.001` | F | Same |
| Substance materials | `fabric_felt`, `leather_grain`, Fabric Burlap (scale 5 vs factory 32), Leather Pattern (triplanar 0.55–0.9) | F | `.claude/skills/pintura-pbr/REFERENCE.md`; SKILL.md → "Pano grosso", "Couro com metal sem ID" |
| Smart materials | Leather Damaged, Bronze Armor (starter assets), a forged-iron smart material (hat v5) | F | `SM/22-Bracal-Direito/report.json → painting.stack_top_to_bottom`; REFERENCE.md |
| Smart masks | Dirt Cavities, Edge Dirty Cracks, Edges Uber, Ground Dirt, Dust Dirty, Occlusion Strong | F | `SM/00-Corpo/report.json → painting_v3.smart_layers`; SKILL.md → "00-Corpo v4" |
| Grunges / procedurals | grunge_rock, grunge_stone_details, grunge_dirt_large, dirt_spots_dense_small, bnw_spots_2/3, grunge_scratches(_fine/_dirty), grunge_rust_fine, grunge_humidity, Grunge Map 009/012, gaussian_spots_2, dirt_1, cracks_leather, fabric_linen | F | `SM/00-Corpo/report.json → painting_v3`; `SM/10-Chapeu/report.json → painter_recipe.node_details` (resource names counted this session) |
| Custom bitmaps as BaseColor-only fills | `Custom_Wool_v1`, `Custom_Leather_v1` (hat v5), `T_*` swatch projections (`base_tex`) | F | REFERENCE.md; `painter_layer_stack.py` |
| Projections | UV (bitmaps), triplanar (grunges and materials) | F | `painter_layer_stack.py` |
| Smart material export/import | `.spsm` export of folders and reinsertion in another project | F | `SM/21-Bracal-Esquerdo/report.json → painting_p1.smart_materials` |
| Anchor points, geometry masks (non-empty), hand painting by strokes | Not used as far as the sources show (layer trees show empty Mesh geometry masks; one Paint effect on the hat) | F / not confirmed | `SM/10-Chapeu/report.json → layer_tree` |

## 5. Library recipes (Docs/Biblioteca)

| Recipe | Status / proved in | Steps (short) | Swatches | Limits | Source |
|---|---|---|---|---|---|
| `pintura/tecido-tunica-v9` | candidate; tunic 18 v10 approved baseline (visual) | read ref 4×; extract raster/AO/relief; fields + masks; `sync` uniform fills (stack in `/painting_v9/stack`); v10 hem/trim regularisation | none (fill colours read from the reference) | UV technical gate pending | F — `Docs/Biblioteca/Receitas/pintura/tecido-tunica-v9.json` |
| `pintura/ferro-martelado-v9` | candidate; pauldrons 19/20 v9 (user comment "ombreiras ficaram boas agora", no formal approval) | extract (AO 2048, 64 samples, cage 0.004, ray 0.01); highrelief 40 iterations; fields 2048; `iron_material_masks.py`; `leather_distress_masks.py`; `sync stack_v9.json`; gate boards | `ferro-martelado-v2` (0.10 m repeat), `ferrugem-v2` (0.05 m) | more silver glints, more concentrated rust than ref; thresholds for 2–4 mm rims | F — `ferro-martelado-v9.json` |
| `pintura/couro-tira-v4` | candidate; strap 24 v4 (delivery, no approval) | strap rebuild; extract + fields 2048; `strap_band_masks.py`; `sync stack24v4.json` | `couro-escuro-v1` | leather lighter/warmer than ref; detail only in painted Height | F — `couro-tira-v4.json` |

**F** — Recovery was tested by regeneration from durable files only: 15/15 (19 v9), 15/15 (20 v9), 14/14 (24 v4) masks byte-identical, after recording a non-default parameter (`highrelief --iterations 40`) that had first caused 4 of 15 masks to diverge (`Docs/Pipeline/Licoes/operacao-recuperacao-antes-da-limpeza.md`). This proves mask regeneration only, not recovery of the full stack, maps or render.

**F** — The approved tunic's recovery record binds masks per layer: the historical `painter_stack_recipe` names `M_piping` for both C07 and F03, but v10 changed C07 only. C07 must use `Source_v10_M_piping` (`M_piping.png`, SHA-256 `822f926d…`) and F03 `Source_v9_M_piping` (`M_piping_lining_v9.png`); the override F03 → `M_piping_lining_v9` is applied to a working copy of the recipe before any sync, because a global mask-name sync would also change the lining (`SM/18-Tunica/report.json → painting_v10.source_recovery.layer_specific_masks`).

## 6. Material targets per archetype (case values)

| Piece / archetype | Recorded values | Source |
|---|---|---|
| Tunic cloth (approved v10) | Base C01 sRGB (0.37, 0.105, 0.1) rough 0.86; pores (0.05, 0.02, 0.018) op 0.9 rough 0.95 height −0.035; piping (0.62, 0.54, 0.39) op 0.85 rough 0.7 height 0.04; lace holes height −0.05; lining F01 (0.16, 0.1, 0.075) rough 0.9; 22 fills total; Height Linear Dodge, lining group Height replace | F — `.claude/skills/pintura-pbr/REFERENCE.md` → "Pilha-base v9 preservada na v10" |
| Hat v5 (felt/leather/linen/iron) | Felt sRGB (0.255, 0.066, 0.087) rough 0.94, triplanar 4.5; relief fill `fabric_felt` scale 3, density 0.58, tension 0.18, Height 0.024, Normal 0.36; leather (0.16, 0.108, 0.078) rough 0.69; linen (0.535, 0.455, 0.345) rough 0.88 | F — REFERENCE.md → "Receita vigente e entrega reproduzível" |
| Hat v8 | 43 layers in 5 groups; OpenPBR SpecularWeight felt 0.5 (≈ F0 2 %), leather/iron 1.0; painted relief p50/p90 in degrees vs the baked mesh normal: felt 17.16/37.88, leather 5.11/13.56, binding 5.74/17.9, iron 4.49/8.27 (v6 r3 felt 0.45/1.89); artistic approval pending | F — `SM/10-Chapeu/report.json → v8.painter`, `v8.specular`, `v8.relief_painted_deg_p50_p90`, `v8.artistic_approval` |
| Hat v6 | Swatch medians by material: felt (68.3, 16.4, 16.4), leather (58.0, 38.3, 27.5), binding (71.3, 49.8, 37.6), iron (122.8, 112.2, 102.7); r3 felt crown 88/49/49 vs ref 77/41/40 | F — `SM/10-Chapeu/report.json → v6.painting` |
| Bone (body) | v3 base (212, 194, 164) rough 0.7 → v4 base (194, 180, 162); pelvis/femur p50 ≈ 160–167 vs ref 152–161 under Cycles White Soft; relief −0.12 to −0.25 rejected ("sponge/stone"); `M_gap` and cavity dirt ≤ 0.55 on the 80 px/cm skull | F — `.claude/skills/pintura-pbr/SKILL.md` → "Peça orgânica: 00-Corpo" |
| Leather + brass (belt v1, bracers) | Leather Damaged base (50, 33, 22) → bracer r9 base (32, 19, 10) rough 0.7, Leather Pattern height op 0.01, triplanar 0.9; Bronze Armor base (150, 118, 72), edges (200, 168, 110) in Normal blend; `cracks_leather` triplanar 8 with Levels 0.42–0.6; `M_l_distress` ≤ 10 % | F — SKILL.md → "23-Cinto", "22-Bracal-Direito"; `SM/22-Bracal-Direito/report.json → leather_family_recipe_r9` |
| Belt v5 | Leather `base_tex` rough 0.62 → tabs 0.68 → 0.85 to stop studio specular greying dark leather | F — SKILL.md → "Cintura v5" |
| Sash v1 | Fabric Burlap base (44, 30, 22), weave scale 5; light threads `fabric_linen` + Levels 0.6–0.8 at op 0.45; fibres ≤ 15 % | F — SKILL.md → "Pano grosso" |
| Staff v9/v10 | Wood/leather/iron/gem groups, each with `base_tex` swatch + 1–5 detail fills; gem rough 0.06; iron metal 1.0 rough 0.5; polished iron edges (200, 196, 186) rough 0.3 | F — `Docs/Pipeline/Retopologia/cajado-v10/paint/stack-staff.json` |
| Pauldrons v9 | Tone L p10/p50/p90 23/51/105 vs ref 21/53/104 (lateral); frontal p90 145 vs 113 (specular) | F — `ferro-martelado-v9.json → medidas` |

## 7. Rules and limits for painting

| Rule | Why | Source |
|---|---|---|
| Isolate every material in all channels (BaseColor, Height, Normal, Roughness, Metallic); an unmasked base leaks Height/Normal under other materials | Cloth relief invaded leather and metal on the hat | F — `.claude/skills/pintura-pbr/SKILL.md` step 5; `Docs/Pipeline/Licoes/pintura-isolamento-materiais-todos-canais.md` |
| Activate channels before setting uniform sources | Setting channels afterwards resets fills to white | F — `Docs/Pipeline/Licoes/pintura-fill-ordem-dos-canais.md` |
| Keep the bottom group unmasked, or otherwise guarantee a defined base under complementary masks | Complementary group masks expose Painter's default grey at seams. The staff v10 and hat v8 start with masked groups, so this is advice, not a schema rule | F — REFERENCE.md → "Armadilhas desta rodada"; `painter_layer_stack.py` lines 34, 87; `Docs/Pipeline/Retopologia/cajado-v10/paint/stack-staff.json`; `Docs/Pipeline/Retopologia/chapeu-v6/paint/stack-hat-v8.json` |
| Separate colour from relief; check the actually active channels and exported maps | Hat v4 lost relief: Normal was not an active channel although the substance parameter was on | F — REFERENCE.md → "Correção do tecido liso na v5" |
| Measure relief: angle between exported Normal and mesh-only normal per material; fibres/grain/cracks need Height 0.01–0.03 (0.002–0.006 is "practically nothing"); ~5° read as leather, 20° as tree bark (case guidance from the hat and bracer, not a universal depth) | Flat "plastic" look | F — SKILL.md → "Realismo" |
| 20/80 rule: ~80 % of the read from medium/large forms, 20 % fine detail | Fine noise over flat colour fails | F — SKILL.md → "Realismo" |
| Dirt hierarchy (dust, soil in recesses by AO, old oily grime, particles), each with own colour/roughness/mask; convex curvature subtracted from dirt; dirt is brown/grey, not a darker material tone; Metallic 0 on dirt over metal | Hat "too clean / washed" | F — SKILL.md → "Realismo" |
| Value check: p10/p50/p90 luminance per region vs reference under `ref_match` | High darks are the signature of "washed" | F — SKILL.md → "Realismo"; `AGENTS.override.md` §4 |
| AO in three uses: exported 16-bit AO map (glTF occlusion), fine cavity multiplied into albedo, moderate AO layer in albedo; the same corrected AO is the Painter AO mesh map (hat v8) | Definition independent of lighting | F — SKILL.md → "Realismo"; `Docs/Pipeline/Licoes/pintura-ao-falhas-de-raio-definicao.md` |
| Felt and other fibrous cloth: lower OpenPBR SpecularWeight (felt 0.5, leather/iron 1.0) instead of darkening the albedo or changing the light | Default dielectric specular put a grey veil of +20–30 in G/B on the felt under `ref_match` | F — `Docs/Pipeline/Licoes/pintura-especular-feltro-veu.md`; `SM/10-Chapeu/report.json → v8.specular` |
| Swatches are not measured albedo; only BaseColor; relief/roughness stay procedural | Photo RGB includes light and camera | F — `Docs/Biblioteca/README.md`; `Docs/Pipeline/Licoes/pintura-cor-de-amostra-nao-procedural.md` |
| Calibrate procedural projection scale on the exported mask; `projection_3d.scale` is not metres (0.16 subpixel vs 16 broad spots) | Wrong frequency | F — SKILL.md → "Mandatory visual depth"; `Docs/Pipeline/Licoes/pintura-profundidade-tres-escalas.md` |
| Trim/hem follow a smoothed guide per panel at physical width, not every tear | Zig-zag lace | F — `Docs/Pipeline/Licoes/pintura-barras-guia-por-painel.md` |
| Find a defective layer by measuring (export with each layer hidden), not by guessing | Leopard spots on skull came from a different layer than suspected | F — `Docs/Pipeline/Licoes/pintura-isolar-contribuicao-das-camadas.md` |
| Never paint over construction failures (bad high/low/fit/UV/bake) and never paint before UV and fidelity gates pass | Lost work on belt, pads, tunic | F — `AGENTS.override.md` → "No painting over construction failures"; `Docs/Pipeline/Licoes/gate-nao-pintar-geometria-reprovada.md` |
| Art direction: dark-fantasy weight; localized subtle contrast; dark accents at edges/seams/joins; clean material boundaries; colour checked under neutral light | User feedback on hat/tunic | F — SKILL.md → "Direção de arte, pelo feedback do usuário" |
| Only what the reference shows: invented wear (sweat marks, water rings) was removed | Hat v8 r2 | F — SKILL.md → "Realismo" |

## 8. Swatch library

| Swatch | Used in | Notes | Source |
|---|---|---|---|
| `ferro-martelado-v2`, `ferrugem-v2` | Pauldrons 19/20 v9 | Codex `image_gen`; 1254² native although 2048² requested; physical area 10 × 10 cm (iron) | F — `Docs/Biblioteca/Amostras/ferro-martelado-v2/proveniencia.json` |
| `couro-escuro-v1` | Strap 24 v4; hat v6 | Astra | F — `Docs/Biblioteca/README.md`; `SM/10-Chapeu/report.json → v6.painting.method` |
| `feltro-vinho-v1/v2`, `ferro-forjado-v1`, `ferrugem-v1`, `latao-v1` | hat v6 (`feltro-vinho-v1`), otherwise candidates | | F — same |
| Prompt template | "seamless PBR base color texture … flat top-down orthographic … even neutral diffuse illumination; no highlights, shadows …" | | F — `.claude/skills/pintura-pbr/REFERENCE.md` → "Texturas próprias: modelo de prompt" |
| Projection | `book_material_masks.py project`, `iron_material_masks.py` (triplanar), per-piece scripts with per-channel gain to the reference median → `T_base` | | F — SKILL.md → "Peça rígida: 13-Grimorio"; `cintura_v5/README.md` → "Cor base" |
