# 05 — Export and downstream consumers

Conventions as in [01](01-pipeline-overview.md): paths relative to `E:\UzmiGames\Assets3D\`, `SM/` = `Creatures/Undead/Skeletal Mage/Models3D/`, **F** Fact / **H** Hypothesis / **R** Recommendation. File sizes come from `ls -la`/`find -printf` run this session (binary files were not opened).

## 1. Export methods in use

| Method | Maps and naming | Parameters | Pieces | Type | Source |
|---|---|---|---|---|---|
| Painter preset "Blender (Principled BSDF)" (`resource://starter_assets/Blender (Principled BSDF)?version=13120355637414252359.spexp`) | Preset defines 7 maps per texture set: `<TextureSet>_BaseColor_sRGB`, `_Normal_Raw`, `_Metallic_Raw`, `_Roughness_Raw`, `_Emission_sRGB`, `_Alpha_Raw`, `_Displacement_Raw`; deliveries keep 5 (no Emission/Alpha). The `_sRGB`/`_Raw` suffixes appear because the project is OCIO-managed | PNG 16-bit, 4096 (hat v5, tunic, body) or 2048 (grimoire) | Hat v5, tunic v8–v10, body v3–v6b, bracers, grimoire | F | `SM/10-Chapeu/report.json → painter_recipe.export`; `SM/18-Tunica/report.json → painting.exports`; `.claude/skills/pintura-pbr/SKILL.md` → "Projeto OCIO" |
| Inline preset written by `painter_export.py` | `<prefix>_BaseColor` (RGB from `basecolor`), `_Roughness`, `_Metallic`, `_Height` (L from document maps), `_Normal` (RGB from virtual map `Normal_OpenGL`) | `fileFormat png`, `bitDepth 16`, `sizeLog2` 12 (4096) or 11 (2048) hard-coded per recipe, `paddingAlgorithm infinite`, `dithering false`, `exportShaderParams false`; saves the project (`Full`) and waits while busy before exporting | Hat v6, staff v9/v10, wand v1, belt/sash v5 | F | `Docs/Pipeline/Retopologia/cajado-v10/painter_export.py`; diffs vs `cintura_v5/` and `varinha11-v1/` (computed this session) |
| Six-map variant with `Mixed_AO` | Added `{"srcMapType": "virtualMap", "srcMapName": "Mixed_AO"}` | Crashed Painter 12.1 (APPCRASH 0xc0000005) on hat v8; the delivered AO is the corrected bake image (16-bit) instead | Hat v8 | F (cause: H) | `Docs/Pipeline/Licoes/operacao-painter-export-mixed-ao.md` |
| Mesh-map export | `srcMapType meshMap`, 16-bit, to compare curvature/AO/thickness/position/WSN between versions | Diagnostic | Body v6 | F | `SM/00-Corpo/report.json → painting_v6.rebake_mesh_maps.curvatura_membros.prova` |
| Layer-isolation export | BaseColor/Normal/Roughness/Metallic/Displacement at 1K 8-bit via MCP `export_textures` with the Blender preset | Diagnostic only | Body v4, bracers | F | `Docs/Pipeline/Pintura/painter_layer_isolate.py` |
| 8-bit delivery | Grimoire r17 export at 2K / 8 bits with the Blender preset | Historic | Grimoire v4 | F | `Docs/analysis/skeletal-mage-review/05-auditoria-spp-10-13-20261007.md` step 2 |

## 2. Map contract

| Map | Colour space | Content | Type | Source |
|---|---|---|---|---|
| BaseColor | sRGB | Painted albedo | F | `Docs/Pipeline/Render/Render-Comparison-Standard.json → texture_contract` |
| Roughness, Metallic, AO | Raw / Non-Color | Grayscale | F | Same |
| Normal | Raw / Non-Color, OpenGL | **Combined**: mesh normal + painted Height/Normal; must not be combined again with the same Height as a bump | F | Same; `.claude/skills/pintura-pbr/SKILL.md` step 8; `Docs/Pipeline/Licoes/pintura-normal-height-uma-vez.md` |
| Height / Displacement | Raw | Exported for reference; not wired in delivery materials | F | `Docs/Pipeline/Retopologia/cajado-v10/deliver.py` (only BaseColor, Roughness, Metallic, Normal wired); `SM/22-Bracal-Direito/report.json → painting_exports.blend` ("Displacement só como referência") |
| Geometry normal | Raw, OpenGL | Blender bake kept beside the combined normal as `<piece>_Normal_OpenGL_bake_v<N>.png` | F | `SM/10-Chapeu/report.json → v6.files_sha256` |
| AO | Raw, 16-bit | Corrected Blender bake; wired as glTF occlusion (directive 2026-10-09) | F | `AGENTS.override.md` → "Definition independent of the lighting" |
| Alpha | — | "Alpha requires its own channel/preset/target material"; fine alpha (lace, fray) remains a pending item on the tunic | F | `.claude/skills/pintura-pbr/SKILL.md` step 8; `Docs/Pipeline/README.md` → "Pendências que continuam valendo" |

## 3. Naming and placement observed in `SM/*/Textures` and `Export`

| Pattern | Example (size) | Type | Source |
|---|---|---|---|
| `<TextureSet>_<Map>_sRGB.png` / `<TextureSet>_<Map>_Raw.png` (Blender preset, OCIO) | `18-Tunica/Textures/DefaultMaterial_Normal_Raw.png` (37,008,276 B); `13-Grimorio/Textures/Grimorio_BaseColor_sRGB.png` (3,267,295 B) | F | Directory listing this session |
| `<TextureSet>_<Map>[_vN].png` (preset without colour-space suffix) | `00-Corpo/Textures/00-Corpo-Cranio_BaseColor_v6b.png` (45,680,642 B) | F | Same |
| `<Piece>_<Map>_v<N>.png` (inline preset, renamed on delivery) | `10-Chapeu/Textures/10-Chapeu_BaseColor_v6.png` (47,363,519 B); `09-Cajado_Normal_v10.png` (27,168,332 B); `11-Varinha-Madeira_BaseColor_v1.png` (2,602,122 B) | F | Same |
| Bake evidence beside maps | `_Normal_OpenGL_v6b_raw.png`, `_coverage.png`, `_stages.png`, `_invalid_mask.png`, `_bake.json` | F | `00-Corpo/Textures/` listing |
| Swatches | `09-Cajado/Textures/Swatches/staff-wood-BaseColor-v1.png` (9,178,814 B) | F | Same |
| Export | `Export/<piece>-v<N>.glb` and `.fbx`, sometimes `Export/vN/` subfolders; OBJ copies for bakes | F | Same |

**F** — Naming is not uniform across pieces (three patterns above), and some Textures folders keep older rounds (`_v2`, `_v6p`) next to current ones (listing this session). **R** — UzPainter should emit one deterministic naming scheme and let the manifest identify the round (see 08).

## 4. Consumers

| Consumer | How it uses the maps | Type | Source |
|---|---|---|---|
| Blender delivery (`deliver.py`) | Builds a game low copy (corner normals preserved), Principled BSDF with BaseColor (sRGB), Roughness, Metallic, Normal (Non-Color) through a Normal Map node on `UVMap`; exports GLB (`export_tangents=True`) and FBX (`path_mode="RELATIVE"`, `mesh_smooth_type="OFF"`); saves `<piece>-vN.blend` with game low + hidden high | F | `Docs/Pipeline/Retopologia/cajado-v10/deliver.py` |
| GLB content | Blender's glTF exporter packs Metallic+Roughness into one 8-bit PNG; 16-bit PNGs in `Textures/` remain the authoring source; belt v5 GLB reimport showed 2048 images (BaseColor, Metallic+Roughness, Normal) | F | `.claude/skills/pintura-pbr/SKILL.md` → "Reprodução do `.spp`"; `SM/23-Cinto/report.json → v5.exports.glb_reimport` |
| FBX content | Textures external, relative paths `..\Textures\*_v2.png` | F | `SM/22-Bracal-Direito/report.json → painting_exports.fbx` |
| Blender review renders | `render_pbr_asset.py` reloads maps preserving colour spaces, exports copies, checks geometry/UV hashes; per-piece `paintrender.py` under `ref_match` | F | `.claude/skills/pintura-pbr/SKILL.md` step 9; `Docs/Pipeline/Retopologia/cajado-v10/paintrender.py` |
| Review panel (browser) | Loads the newest GLB in `Export/`; three.js 0.170, `NoToneMapping`, `SRGBColorSpace` output, hemisphere ambient + one directional key with shadows, contact shadow; without an AO map the ambient term is uniform | F | `Docs/Pipeline/Painel/README.md`; `Docs/Pipeline/Painel/index.html`; `AGENTS.override.md` → "Definition independent of the lighting" |
| Character assembly | Textured lows replace highs in `Assembly/Skeletal-Mage-Assembly-v7.blend`; placements in `Assembly/equip-placements.json` | F | `Docs/Pipeline/README.md` → "Montagem v7"; `Docs/Pipeline/Painel/README.md` |
| Players' equipment | Hand items: origin at the grip centre, axis +Z Blender / +Y glTF, front −Y Blender / +Z glTF, identity transform, metres; head items at equipped size, origin at the headband centre | F | `AGENTS.override.md` → "Equipment pivot"; `Docs/Pipeline/Licoes/exportacao-pivo-empunhadura.md` |
| Unreal | "Conversion to Unreal and compression/packing are a later stage: check the target's normal convention and channels"; "material Unreal" listed as pending in the collaboration history; not executed | F | `.claude/skills/pintura-pbr/SKILL.md` step 8; `Docs/Colaboracao/Historico/Colaboracao-Log-2026-10-04_a_2026-10-07.md` |
| UzEngine | Not mentioned anywhere in Assets3D | not confirmed | Search this session over `Docs/`, `.claude/skills/`, `AGENTS*.md` |
| ORM / engine packing | No ORM or occlusion-roughness-metallic packing is defined; the only packing is the glTF metallic-roughness texture produced by Blender's exporter | F (absence) | Search this session (0 catalogue hits for "ORM") |

## 5. Recorded sizes

| Artifact | Size (bytes) | Type | Source |
|---|---|---|---|
| Tunic v10 maps 4K/16-bit | BaseColor 16,427,270; Normal 37,008,276; Displacement 15,563,151; Roughness 3,892,377; Metallic 98,066 | F | `SM/18-Tunica/report.json → painting_v10.textures`; listing |
| Hat v6 maps 4K/16-bit | BaseColor 47,363,519; Normal 47,412,567; geometry normal 41,919,575; Height 8,009,155; Roughness 3,378,330; Metallic 145,024 | F | Listing |
| Staff v10 maps 4K/16-bit | BaseColor 29,901,306; Normal 27,168,332; Height 2,493,002 | F | Listing |
| Belt v5 maps 2K/16-bit | BaseColor 8,316,099; Normal 9,922,102; Height 2,075,708 | F | `SM/23-Cinto/manifestos/v5.json → arquivos` |
| GLB | Body v6b 345,256,168; hat v6 100,045,988; staff v10 61,688,468; tunic v10 57,910,868; belt v5 20,049,236; wand v1 5,816,620 | F | Listing |
| `.spp` | Body v6b 1,190,431,812; hat v8 556,279,426; tunic v10 408,723,056; grimoire v4 314,799,733; staff v10 132,520,497; pauldron 19 v9 119,959,895; belt v5 86,634,087; sash v5 74,544,892; wand v1 26,610,023 | F | Listing |

## 6. Export verification rules

| Rule | Type | Source |
|---|---|---|
| Save the `.spp` before exporting; exporting during a save failed with "project locked"; Painter closed twice during export | F | `.claude/skills/pintura-pbr/REFERENCE.md` → "Operação verificada na túnica v6"; `Docs/Pipeline/Licoes/operacao-segundo-plano-caminhos-e-salvamento.md` |
| After each export: file exists, size > 0, right object, map hashes changed when the stack changed (an equivalent re-export may legitimately keep the hash) | F | `Docs/Pipeline/Gates/exportacao.md`; `operacao-segundo-plano-caminhos-e-salvamento.md` |
| A saved `.spp` does not prove the delivered maps: re-open a byte-identical copy, export twice with the recorded preset/resolution/bit depth, compare bytes and native 16-bit pixels (Pillow truncates RGB16 to 8 bits; use `image.pixels.foreach_get` in Blender) | F | `Docs/Pipeline/Licoes/exportacao-spp-mapas-precisao-nativa.md` |
| Same-session exports are byte-identical; across sessions BaseColor/Roughness/Metallic reproduced exactly while Height/Normal differed by up to 1 and 12 / 65,535 (pauldrons) or 135 and 12 LSB (body); the hat re-export produced 2,641 black normal texels absent from the delivery | F | `.claude/skills/pintura-pbr/SKILL.md` → "Verified shoulder material lesson"; `SM/00-Corpo/report.json → painting_v6.validacao.reproducao`; `Docs/analysis/skeletal-mage-review/05-auditoria-spp-10-13-20261007.md` |
| `.spp`, `.blend`, maps, GLB/FBX and `Review/` must identify the same round before announcing a delivery | F | `Docs/Pipeline/Licoes/exportacao-rodada-coerente.md`; SKILL.md step 10 |
| Export meshes from copies and re-import to compare geometry, UV per corner, triangulation, normals and micro-faces (the GLB exporter removed a microscopic triangle from a shared mesh) | F | `Docs/Pipeline/Licoes/exportacao-round-trip-normais-microfaces.md`; REFERENCE.md → "Exportador GLB" |
| Manifest `exportacoes[]`: `fontes`, `saidas`, `momento`, `preset`, per-map `{resolucao, bit_depth (8/16/32), color_space}`, `comparacao.resultado` ∈ {bytes-iguais, pixels-iguais, equivalencia-visual, diferente, pending}, evidence and pending items; parameters not proven for the round stay null | F | `Docs/Pipeline/Manifesto/manifesto-schema-v1.json → $defs.exportacao, formato_mapa`; `SM/18-Tunica/manifestos/v10.json → exportacoes` |
