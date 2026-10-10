# 06 — Review render standard (Painter × Blender)

Conventions as in [01](01-pipeline-overview.md): paths relative to `E:\UzmiGames\Assets3D\`, `SM/` = `Creatures/Undead/Skeletal Mage/Models3D/`, **F** Fact / **H** Hypothesis / **R** Recommendation.

## 1. Purpose and rules

| Rule | Type | Source |
|---|---|---|
| One shared standard (`Docs/Pipeline/Render/Render-Comparison-Standard.json`) applies to all pieces and all review stages, including previews the user watches in Painter, so that paint changes are separated from lighting changes | F | `Docs/Pipeline/Render/Render-Comparison.md` (first paragraph) |
| The user's presentation look is stored as a separate snapshot and never silently replaces the comparison standard | F | Same; `Docs/Pipeline/Render/Painter-Lighting-Tunica.json → scope` |
| One `ref_match` preset per character, calibrated once from its references, for every piece, in Blender and Painter; never tune light per piece; if an asset differs under it, the paint or geometry is wrong, not the light | F | `AGENTS.override.md` → "Working mode", "Document as you go"; `Render-Comparison-Standard.json → presets.ref_match.purpose` |
| Colour-transform validation does not prove photometric parity between Iray and Cycles | F | `Docs/Pipeline/README.md` ("A validação de cor não comprova paridade completa entre Iray e Cycles") |

## 2. Common standard v2 (top-level block)

| Control | Painter | Blender | Source |
|---|---|---|---|
| Working space | Linear, sRGB primaries / D65 | Linear Rec.709 | F — `Render-Comparison.md` → "Condições fixas" |
| Output | Display transform "Default – sRGB", colour management on | sRGB / Standard / look None, exposure 0, gamma 1 | F — `Render-Comparison-Standard.json → painter.display_transform`, `blender.color_management` |
| HDRI | `resource://starter_assets/Studio White Soft?...`, interpreted Linear | Same EXR from Painter's install (`…/environments/Studio/Studio White Soft.exr`), SHA-256 `c2bb3294…`, strength 1 | F — JSON `painter.lighting.environment_url`, `blender.environment` |
| Environment | Infinite sphere, no ground, shadows off, rotation 0, exposure 0, environment opacity 0, blur 0, clear colour on (expected background RGB 89) | World only, scene lights hidden, World Normal → `diag(1,1,-1)` → Environment Texture; background linear 0.0999 to camera rays only | F — JSON `painter.lighting`, `blender.environment.vector_matrix_3x3`, `blender.background` |
| Post | No post effects, LUT, colour profile or display SSS; firefly filter off | No AgX/Filmic, curves, white balance or compositor | F — JSON `painter.render_contract`; `Render-Comparison.md` |
| Image | 1200×1200, Iray 256 samples (min = max = 256, max time 3600 s), override resolution on | 1200×1200, Cycles CPU, 256 samples, seed 0, no denoise | F — JSON `painter.iray_settings`, `blender.render` |

## 3. Coordinate, camera and texture contracts

| Contract | Value | Type | Source |
|---|---|---|---|
| Object axes | Painter `(x,y,z)` → Blender `(x,−z,y)` (Y-up → Z-up) | F | JSON `coordinate_contract.painter_to_blender` |
| Environment direction | Painter 0° ↔ Blender World Normal × `diag(1,1,−1)`; the earlier 180° hypothesis failed the live test (2026-10-06) | F | JSON `coordinate_contract.environment_direction`; `Docs/Pipeline/Licoes/render-orientacao-entre-motores.md` |
| Camera | Painter Euler degrees → `Rx @ Ry @ Rz`, then basis `(x,y,z) → (x,−z,y)`; use `apply_painter_camera`, never copy Euler numbers | F | JSON `coordinate_contract.camera_rotation`; `Render-Comparison.md` |
| Textures in review | BaseColor sRGB; roughness/metallic/AO Raw; normal OpenGL Raw; Height Raw and never applied twice when already in the combined normal | F | JSON `texture_contract` |
| Normal provenance | Study: current geometry normal + this round's Height once; delivery: current Painter combined normal; trace `Principled.Normal` to the map's round and UV | F | `Render-Comparison.md` → "Aplicar" (last paragraphs); `Docs/Pipeline/Licoes/pintura-normal-height-uma-vez.md` |

## 4. Comparison passes

| Pass | Painter | Blender | What it diagnoses | Source |
|---|---|---|---|---|
| `base_color` | Base color single-channel view, display transform on | Emission of decoded BaseColor, strength 1 (`base_color_diagnostic()` context manager; calling it without `with` silently does nothing) | Texture content and colour transfer, no lighting/BRDF | F — JSON `comparison_passes`; `.claude/skills/pintura-pbr/SKILL.md` → "Base Color sem luz" |
| `neutral_control` | Linear 18 % grey card + reflective sphere | Same (`render_control_scene.py`) | Illumination gain and direction before judging paint | F — JSON; `Docs/Pipeline/Render/render_control_scene.py` |
| `material` | Iray | Cycles | Combined material response; BRDF/GI residuals remain | F — JSON |

## 5. `ref_match` preset (v3, character boards)

| Item | Value | Type | Source |
|---|---|---|---|
| Light | Camera-relative soft key from camera-left 6° and 45° above the view axis (Gaussian σ 20°), peak 13.06; dim ambient gradient sky 0.0504 / horizon 0.0432 / floor 0.0288 (0.1 × key flux); no rim; Standard sRGB, 0 EV | F | `Render-Comparison-Standard.json → presets.ref_match.blender.environment.lights` |
| HDRI | `Docs/Pipeline/Render/HDRI/TOS-RefMatch-Skeletal-Mage.exr` (976,777 B), SHA-256 `77eeed8d…`, generated by `make_studio_hdri.py` with the recorded command | F | Same; listing this session |
| Camera-relative | `Vector Transform World→Camera`, so front/back/side views get the same light as the reference photos | F | Same |
| Backdrop | Camera-only vertical gradient sRGB8 bottom (163,164,169) / middle (141,142,148) / top (144,145,150); does not light the asset | F | Same |
| Framing | Same aspect and view as the reference; orthographic camera fitted on landmarks (skull top, sole, skull centre) | F | Same; `Render-Comparison.md` → "Ref-match preset (v3)" |
| Render | Cycles CPU, 256 samples, seed 0, 1200×1200 (piece scripts override resolution, e.g. staff 1024×1536; samples 64 in round previews) | F | Same; `Docs/Pipeline/Retopologia/cajado-v10/paintrender.py`; `Docs/Pipeline/Retopologia/cintura_v5/round.sh` |
| Calibration | 2026-10-08 on the Skeletal Mage: key direction from albedo-independent shading profiles; softness/fill from skull and long-bone profiles; one global key level minimising mean \|dp10\|+\|dp50\|+\|dp90\| over 19 regions | F | `presets.ref_match.calibration` |
| Painter equivalent | Documented, **not live-verified** (remote scripting was disabled on 2026-10-08): HDRI as session resource (`import_session_resource`, `Usage.ENVIRONMENT`), envRotation 0 for the front view and rotated by camera yaw for other views, Default – sRGB, shadows on, flat clear colour (141,142,148). Limits: no camera-relative environment and no gradient backdrop in Painter; realtime viewport uses prefiltered IBL; Iray is closer to Cycles | F | `presets.ref_match.painter` |

## 6. Validation evidence

| Check | Result | Type | Source |
|---|---|---|---|
| OCIO transforms (21,312 samples) | Painter Default/sRGB vs Blender Standard/sRGB differ at most 0.003586 of an 8-bit level; linear 18 % grey → RGB 118 in both | F | `Render-Comparison.md` → "Validação e limites" |
| Reflective sphere | Mean error 1.08/255 | F | Same; JSON `validation.lighting_parity` |
| Rough 18 % grey card | Iray ≈ 7.80/255 brighter than Cycles (documented residual, not compensated) | F | Same |
| Grimoire v3 BaseColor pair | MAE 0.539/255, p99 3/255 over 309,425 interior pixels | F | JSON `validation.asset_pair` |
| Clear colour | With infinite sphere and no ground, toggling clear colour changed the background, not the material pixels (0–0.001/255) | F | `Render-Comparison.md` → "Condições fixas" |
| Evidence files | `Docs/Pipeline/Render/Render-Standard-Validation.json`, `Review/Render-Control-Comparison.png`, `ref-match/ref-match-study.json` + boards | F | Listing; `Render-Comparison.md` |

## 7. How renders and screenshots are produced

| Producer | What it does | Type | Source |
|---|---|---|---|
| `blender_render_standard.py` | `apply(config, scene)` or `apply(config, scene, preset='ref_match')` replaces the world, hides scene lights, disables post; `apply_painter_camera`; `base_color_diagnostic()`; CLI `--config --preset --render` | F | Script docstring |
| `render_fidelity_pairs.py` / `render_fidelity_sets.py` | Same orthographic camera: high, low+baked normal, low alone, all in neutral grey (linear 0.18, roughness 0.5); MAE, silhouette IoU, p95 per view; views front/back/left/right/quarter/top/bottom/game + closes JSON | F | Script docstrings |
| `render_ref_view_crops.py` + `board_ref_vs_render.py` | Render the saved scene through the calibrated reference cameras (`Assembly/ref-views/*.json`), crop the piece region; board = reference above / render below; tone L p10/p50/p90 and saturation on pixels present in both | F | Script catalogue blocks |
| Per-piece `paintrender.py` + `board_paint.py` | Painted low under `ref_match` at the reference framing plus closes; board reference \| render with per-material tone stats in regions measured on the reference | F | `Docs/Pipeline/Retopologia/cajado-v10/paintrender.py`; `cintura_v5/board_paint.py` |
| `render_reference_board.py` | Region pairs from normalized boxes (`tos.reference-regions/1`), no colour or perspective change | F | `Render-Comparison.md` → "Ler as diferenças" |
| `painter_render_standard.py` (inside Painter via `execute_python`) | `capture()` / `restore()` full display state, `apply(config)` and `apply(config, mode='base_color')` for the unlit diagnostic, `capture_camera` / `apply_camera`, `capture_live_view(path)` (Qt/QScreen crop of the real window after convergence, separate call) | F | Script docstring; `Render-Comparison.md` → "Aplicar" |
| `painter_lighting.py` | `save(path,label,feedback)`, `capture()`, `apply(path, dry_run)` for environment/ground only; validates HDRI resource and controls before applying | F | Script docstring; `.claude/skills/pintura-pbr/REFERENCE.md` |
| Qt adapters | Display controls are `Alg::Slider` widgets (`pbrExposure`, `envRotation`, `cubemapOpacity`, `envBlur`); Iray samples are `Alg::Slider`, width/height `QSpinBox`; override resolution via `on_overrideViewportRes_clicked(bool)`; combo changes must emit `activated`; names are internal and change between versions | F | REFERENCE.md → "Ajuste de iluminação do Painter por API" |
| Review panel | three.js viewer, ortho camera calibrated on reference px/m and skull landmarks, hemisphere + directional key replicating `ref_match` intensities, contact shadow; compare modes side-by-side, curtain, overlay | F | `Docs/Pipeline/Painel/README.md`; `Docs/Pipeline/Painel/index.html` |

## 8. Acceptance criteria

| Gate | Criteria | Type | Source |
|---|---|---|---|
| Geometry | Clay under `ref_match` at every reference framing next to the reference: same shape, proportion, scale, count/placement of details; no deformation; no penetration or floating gap | F | `AGENTS.override.md` → "Stage quality gates" §1 |
| Low/UV | Silhouette of approved high within budget; checker render with no stretch, even density, hidden seams | F | Same §2 |
| Bake | Lit render of the low with the bake: no cage misses, waviness or seam artefacts | F | Same §3 |
| Paint | vs-reference board under `ref_match`; per-material tonal range p10/p50/p90 and saturation within targets; reference details present | F | Same §4 |
| At every gate | List every visible difference; any difference visible at the reference framing blocks; in doubt it fails; metrics (IoU, MAE) support but never replace the visual check | F | Same, "At each gate" |
| Extra paint checks | Unlit BaseColor; relief channels; the piece in the panel viewer (flat ambient + one directional) in addition to `ref_match`; close-ups and game-distance views | F | `AGENTS.override.md` → "Definition independent of the lighting"; `Docs/Pipeline/Gates/pintura.md` |
| Approval scopes | Technical review, provisional acceptance and final user approval are separate; `artistic_approval` changes only with user evidence | F | `.claude/skills/pintura-pbr/SKILL.md` step 10; `Docs/Pipeline/Manifesto/README.md` |
| Minimum record in `report.json` | Stage/round/date/owner/state; open file and checkpoint per app; standard path/version/SHA-256, HDRI hash, engine versions, controls re-read; mesh/UV/triangulation and map hashes with colour space and normal role (`geometry_only` / `combined_painter`); camera/aspect/resolution/samples/passes; live capture or saved render; differences, cause, next step | F | `Render-Comparison.md` → "Registro mínimo no relatório da peça" |

## 9. Presets and snapshots on disk

| File | Content | Type | Source |
|---|---|---|---|
| `Render-Comparison-Standard.json` (14,250 B) | v2 block + `presets.ref_match` v3 | F | Listing; file |
| `Painter-Lighting-Tunica.json` | User-adjusted presentation of the tunic; lighting + `full_display_state`; excludes camera, shader, ground reflectivity and clear colour; on disk it records 0°/infinite sphere/no ground, not the historical 330°/dome described in the log | F | File `scope`, `not_included`; `Render-Comparison.md` → "Auditoria documental" |
| `Painter-Lighting-Grimorio.json` | "Grimorio – comparacao neutra v2": White Soft + fixed camera (position, rotation degrees [27, −25, −12], perspective FOV 35) | F | File `label`, `camera` |
| `Grimorio-Presentation.json`, `Studio-Presentation.json` | White Umbrella study and a generated studio HDRI candidate (pending approval) | F | Files `status`; `Render-Comparison.md` |
| HDRIs | `HDRI/Studio-Presentation-Character.exr` (8,311,119 B), `HDRI/Studio-Presentation.exr` (8,268,962 B), `HDRI/TOS-RefMatch-Skeletal-Mage.exr` (976,777 B) | F | Listing |

## 10. Known pitfalls in review rendering

| Pitfall | Type | Source |
|---|---|---|
| A preset's name does not restore its real state; save the full state, re-read controls, compare with a live capture | F | `Docs/Pipeline/Licoes/render-snapshot-real-do-preset.md` |
| A preset HDRI must exist in the current project's resources ("Preset environment is not available") | F | `Docs/Pipeline/Licoes/render-hdri-recurso-do-projeto.md` |
| `display.save_viewport` returned a stale camera; after a mesh reload it always returned the same image | F | `Docs/Pipeline/Licoes/operacao-projeto-captura-reais.md`; `.claude/skills/pintura-pbr/SKILL.md` → "Recarga de malha" |
| Iray/Visualisation pauses the layer engine; finish computation in Edition before Iray | F | `Render-Comparison.md` → "Captura e aplicação" |
| The viewport OCIO selection is not saved with the project and must be reapplied; the custom clear colour is not serialized by the adapter | F | `Render-Comparison.md` → "Condições fixas" |
| Painter's viewport light hid albedo variation that Cycles showed; judge by exporting and rendering under the common standard | F | `.claude/skills/pintura-pbr/SKILL.md` → "Peça orgânica: 00-Corpo" |
| Framing/occupancy must match; a smaller subject looks less detailed | F | `Docs/Pipeline/Licoes/render-enquadramento-comparavel.md` |
| A recessed layer under an overhang renders dark under `ref_match` with correct albedo; fix geometry, not colour | F | `Docs/Pipeline/Licoes/geometria-camada-sob-saliencia-sombra.md` |
