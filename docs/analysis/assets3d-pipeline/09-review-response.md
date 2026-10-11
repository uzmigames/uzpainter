# 09 — Response to the technical review (Astra, 2026-10-10)

Response to `../reviews/assets3d-pipeline-astra-review.md` (Astra owns UV, bake and technical QA in Assets3D). Every finding was checked against the primary sources before acting: Assets3D (read-only), UzEngine code and `../uzengine-renderer/04-material-and-texture-standard.md`. Path prefixes follow the review: **A/** = `E:\UzmiGames\Assets3D\`, **A/SM/** = `A/Creatures/Undead/Skeletal Mage/Models3D/`, **U/** = `E:\UzmiGames\UzEngine\`, **P/** = `E:\UzmiGames\UzPainter\`. **Owner** = product-owner requirements stated 2026-10-09 and 2026-10-10 (see 08, header).

Verdicts: **accepted** = the source confirms it and the analysis was corrected (or already said it); **partially accepted** = part confirmed, part not; **rejected** = the source contradicts it; **forwarded** = confirmed facts were recorded here, but the decision belongs to the architecture (or to a document outside this write scope).

**Totals.** 115 findings (8 file verdicts, 15 numbered findings, 67 sample claims, 15 inconsistencies, 10 missing requirements): 110 accepted, 2 partially accepted, 0 rejected, 3 forwarded to architecture. The 82 per-requirement comments: 81 accepted, 1 partially accepted (G-01). Open-question answers: 8 accepted, 1 partially accepted (Q1). The 20 architect questions are forwarded (§3.2).

## 1. Findings

### 1.1 File verdicts

| ID / short title | Severity | Verdict | Evidence path | What changed and where |
|---|---|---|---|---|
| V-01 — 01 overview: accept as historical with qualifications | File verdict | accepted | A/AGENTS.override.md; A/Pipeline/retopology/hat-v6/deliver_v8.py | 01 conventions (snapshot date, Owner), §1 (observed route ≠ product boundary), §6, §8 (hat v8 row), §9 |
| V-02 — 02 Painter usage: revise | File verdict | accepted | A/Pipeline/painting/painter_layer_stack.py; A/SM/10-Chapeu/report.json → v8 | 02 §5 (tangent, SpecularWeight), §6 (hat v8 row), §7 step 9, §8 (scope, cache, `op`, Height blend) |
| V-03 — 03 bake: revise scope and QA | File verdict | accepted | A/Pipeline/painting/bake_normal_pair.py; A/SM/10-Chapeu/report.json → v8.ao | 03 §1, §2, §3, §4, §5, §7, §8 |
| V-04 — 04 painting: revise migration/parity claims | File verdict | accepted | A/SM/18-Tunica/report.json → painting_v10.source_recovery; A/SM/22-Bracal-Direito/report.json → leather_family_recipe_r9 | 04 §1, §2, §5, §6, §7 |
| V-05 — 05 export: revise current contract and adoption | File verdict | accepted | A/Pipeline/retopology/hat-v6/deliver_v8.py; A/SM/10-Chapeu/report.json → v8 | 05 §1, §2, §4, new §4.1, §5, §6 |
| V-06 — 06 render: accept measured standard, reject identity inference | File verdict | accepted | A/Pipeline/render/Render-Comparison-Standard.json → validation, presets.ref_match.painter | 06 §1, §3, §5, §6 |
| V-07 — 07 lessons: tighten cause/status | File verdict | accepted | A/Docs/Lessons/bake-per-corner-normals-tbn.md; A/Docs/analysis/skeletal-mage-review/05-spp-audit-10-13-20261007.md | 07 §2 (new specular card), §3, §4, §5, §8 |
| V-08 — 08 requirements: substantial revision | File verdict | accepted | P/README.md; A/Docs/Gates/painting.md | 08 rewritten in place: priority rule, 25 re-classifications, 10 new requirements (§2 below) |

### 1.2 Numbered findings

| ID / short title | Severity | Verdict | Evidence path | What changed and where |
|---|---|---|---|---|
| F1 — Define and prove literal texture/render parity | Blocker | accepted | P/README.md; P/.rulebook/decisions/001-…md (status "proposed"; its `.metadata.json` says "accepted"); A/Pipeline/render/Render-Comparison-Standard.json → validation.lighting_parity ("Approximate"), presets.ref_match.painter.status ("NOT live-verified") | 08 new G-04, VIS-06; 06 §1 new row, §6 note |
| F2 — Native bake and requested export targets cannot be optional | Blocker | accepted | P/README.md → "Baking", "Output"; Owner | 08 BAK-03, BAK-05, EXP-08 → MUST; INT-02 condition removed; §5 boundary rows; §6 Q5; 01 §1; 03 §1 |
| F3 — Starter-material substitutes do not satisfy equal output | Blocker | accepted | A/SM/22-Bracal-Direito/report.json → leather_family_recipe_r9 (`LOCKED`, `starter_assets/Leather Damaged`); A/SM/21-Bracal-Esquerdo/report.json → painting_p1.smart_materials; A/SM/10-Chapeu/report.json → painter_recipe.node_details | 08 MAT-02, MAT-03, MAT-04 → MUST; LAY-11 → MUST; 04 §1 sentence |
| F4 — Tunic migration needs per-layer resource identity | Blocker | accepted | A/SM/18-Tunica/report.json → painting_v10.source_recovery.layer_specific_masks (C07 → `Source_v10_M_piping`; F03 → `Source_v9_M_piping`; override F03 → `M_piping_lining_v9`) | 04 §5 new paragraph; 08 LAY-07 reworded, new LAY-13, G-03, INT-23 |
| F5 — Current SpecularWeight channel and consumer evidence | Major | accepted | A/SM/10-Chapeu/report.json → v8 (date 2026-10-10, seven files, `channels_added`, `specular`, `export_notes`, `artistic_approval: pending`); A/Pipeline/retopology/hat-v6/paint/stack-hat-v8.json (43 layers, 5 groups, counted); `deliver_v8.py` line 26 (Specular IOR link inside a comment). Added: `glb_add_specular.py` writes `KHR_materials_specular` into the GLB; `paintrender_v8.py` wires it for review; `painter_add_channel.py` adds an `L8` channel; delivered PNG is 8-bit RGBA (header read) | 01 §6, §8; 02 §5, §6, §7; 04 §2, §6, §7; 05 §1, §2 (new SpecularWeight row), §5; 07 §2; 08 PRJ-06, EXP-01, INT-11, NFR-03 |
| F6 — Mandatory AO contract vs uneven adoption; reconcile counts | Major | accepted | A/AGENTS.override.md → "Definition independent of the lighting"; only `hat-v6/deliver_v8.py` wires AO among six deliver scripts (search); A/SM/10-Chapeu/report.json → v8.ao; A/_tmp/claude/chapeu-v6/paint/masks-v8*.log; arithmetic 171,408 − 94,890 = 76,518 ≠ 77,588 | 03 §1, §5 (note + **H**); 05 §2; 01 §6; 08 BAK-04 → MUST (miss evidence), new BAK-08 |
| F7 — UV / corner-basis certification | Major | accepted | A/.claude/skills/professional-uv/SKILL.md; A/Docs/Lessons/bake-per-corner-normals-tbn.md, bake-evaluated-triangulation-saved.md; A/Pipeline/uv/validate_uv_mesh.py | 08 PRJ-09 expanded, new PRJ-10, QG-02 |
| F8 — Preserve RAW and expose all bake stages | Major | accepted | A/Pipeline/painting/bake_normal_pair.py docstring, lines 688–742; A/Docs/Lessons/bake-raw-and-coverage-stages.md | 03 §4 (RAW, coverage, stages rows); 08 new BAK-07 |
| F9 — Mesh-map normalisation is part of the recipe | Major | accepted | A/SM/00-Corpo/report.json → painting_v6.rebake_mesh_maps.curvatura_membros (bounds, linked settings restored to auto) | 03 §7, §8; 08 BAK-02, INT-13 → MUST |
| F10 — Determinism without an unproved universal guarantee | Major | accepted | A/SM/00-Corpo/report.json → painting_v6.validacao.reproducao; A/Docs/Lessons/export-spp-maps-native-precision.md | 05 §6; 07 §5; 08 EXP-05 split, NFR-02 |
| F11 — Keep uncertainty about the historical hat cause | Major | accepted | A/Docs/analysis/skeletal-mage-review/05-spp-audit-10-13-20261007.md ("Hipótese (não comprovada)"; Astra addendum: resource-version change not established) | 07 §5 QA05 row, §8; 08 RES-04, NFR-08 |
| F12 — Enforce prerequisite chain and baseline protection | Major | accepted | A/.claude/skills/pbr-painting/SKILL.md → "Pré-requisitos obrigatórios"; A/Docs/Gates/painting.md; A/Pipeline/manifest/manifest-schema-v1.json → $defs.invalidacao | 08 QG-02 → MUST, new QG-05 |
| F13 — Freeze the exact UzEngine import/cook route | Major | forwarded to architecture | U/runtime/shaders/runtime/gbuffer/gbuffer_ps.hlsl lines 217–242; U/runtime/engine/asset/importers/mesh_importer.cpp lines 523–558; fbx_importer.cpp lines 30–32, 1521–1539, 1575–1585 (default `r.Mesh.NormalImportMode = 1` recomputes normals — not named in the review) | Facts in 05 §4.1; +Y kept "not confirmed"; 08 PRJ-04, EXP-10. Route choice and calibration fixture: architect question 11 |
| F14 — Override problematic cooked-map selection | Major | forwarded to architecture | U/runtime/tools/uzcook.cpp lines 162–287 (no height/thickness rule → BC7 sRGB), 276–282 (opacity → BC4); gbuffer_ps.hlsl lines 283–297 (`.a`); U/runtime/engine/asset/importers/texture_importer.h lines 55–75 (explicit format option) | Facts in 05 §4.1; 08 EXP-07, EXP-10. The preset table in `../uzengine-renderer/04-material-and-texture-standard.md` §8 is outside this write scope |
| F15 — Trace completeness and normative wording | Minor | accepted | A/Pipeline/manifest/manifest-schema-v1.json → $defs.exportacao.required (8 fields incl. `evidencias`, `pendencias`), comparacao; painter_layer_stack.py line 87; stack-staff.json | 08 INT-21 completed; EXP-03, INT-02, INT-10 traces now primary; G-01 |

### 1.3 Sample claims (67)

All 67 sample claims were accepted: the sources confirm the review's reading. "No change" means the analysis already scoped the claim as the review asks.

| ID / short title | Severity (review) | Verdict | Evidence path | What changed and where |
|---|---|---|---|---|
| P01 — low OBJ triangulated | Confirmed | accepted | A/Pipeline/retopology/staff-v10/export_low.py | No change (02 §5 cites per-recipe exporters) |
| P02 — `usemtl` names the set | Confirmed | accepted | A/SM/22-Bracal-Direito/report.json → painting.mesh | No change |
| P03 — OpenGL normal format | Confirmed | accepted | staff-v10/painter_create.py line 14 | 08 PRJ-04 (engine conversion per preset) |
| P04 — PerFragment tangent | Confirmed + H | accepted | A/SM/22-Bracal-Direito/report.json → painting.tangent_space | 02 §5; 08 PRJ-04 |
| P05 — 2048/4096 | Confirmed | accepted | painter_create.py variants | No change |
| P06 — `import_cameras=False` | Confirmed | accepted | staff-v10/painter_create.py | No change |
| P07 — OCIO before create | Confirmed | accepted | A/.claude/skills/pbr-painting/REFERENCE.md → "OCIO antes de criar o projeto" | No change |
| P08 — Normal/AO as mesh maps | Confirmed | accepted | staff-v10/painter_create.py lines 22–25 | 08 BAK-01 (provenance) |
| P09 — Full save, refuse unsaved close | Confirmed | accepted | staff-v10/painter_create.py | 08 INT-05 (explicit timeout failure) |
| P10 — bracer map sources | Confirmed | accepted | A/SM/22-Bracal-Direito/report.json → painting.mesh_maps | No change |
| P11 — sync scope and rollback | Confirmed | accepted | painter_layer_stack.py lines 81–127 | 02 §8 scope row |
| P12 — SHA-1 resource cache | Confirmed | accepted | painter_layer_stack.py lines 68–75 | 02 §8 resources row |
| P13 — channels before sources | Confirmed | accepted | painter_layer_stack.py line 96; painting-fill-channel-order.md | 08 LAY-01 (readback) |
| P14 — sRGB/Raw inputs | Confirmed | accepted | painter_layer_stack.py lines 61–66 | 08 PRJ-05 |
| P15 — `base_tex` sampler | Confirmed | accepted | painter_layer_stack.py lines 98–112 | No change (LAY-02) |
| P16 — `op` = BaseColor opacity | Confirmed | accepted | painter_layer_stack.py lines 116, 163 | 02 §8; 04 §2 |
| P17 — `replace_height`, Height adds | Confirmed with qualification | accepted | painter_layer_stack.py lines 33, 88 (group only), 164 (`smart`) | 02 §8; 04 §2; 08 LAY-03 |
| P18 — first group must be unmasked | Imprecise | accepted | painter_layer_stack.py lines 34 (advice), 87; stack-staff.json (`M_wood`); stack-hat-v8.json (`M_felt`) | 04 §2, §7; 08 LAY-10 |
| P19 — tunic process binding | Confirmed | accepted | A/AGENTS.override.md → "Paint standard" | 04 §1 sentence |
| P20 — starter dependencies | Confirmed | accepted | leather_family_recipe_r9.base | 08 MAT-04 |
| P21 — smart folders reused | Confirmed as recorded | accepted | A/SM/21-Bracal-Esquerdo/report.json → painting_p1.smart_materials | 08 LAY-11 |
| P22 — 15/15/14 masks recovered | Confirmed as recorded | accepted | A/Docs/Lessons/operation-recovery-before-cleanup.md | 04 §5 sentence |
| P23 — tunic 22 fills | Confirmed | accepted | REFERENCE.md → "Pilha-base v9 preservada na v10" | No change |
| P24 — staff iron values | Confirmed | accepted | stack-staff.json | No change |
| P25 — Blender preset 7 maps, 5 delivered | Confirmed historically | accepted | A/SM/10-Chapeu/report.json → painter_recipe.export (padding "Export preset/tool default") | 05 §1 padding note and v8 row |
| P26 — inline export parameters | Confirmed | accepted | staff-v10/painter_export.py lines 15–21; hat-v6/painter_export_v8.py | 05 §1; 08 EXP-01 |
| P27 — combined Normal, no Height again | Confirmed | accepted | Render-Comparison-Standard.json → texture_contract.height; painting-height-in-normal-only-once.md | 08 new EXP-09 |
| P28 — AO delivered pipeline-wide | Imprecise | accepted | deliver_v8.py lines 20–21, 29–34; staff-v10/deliver.py lines 19–21; six deliver scripts searched | 01 §6; 03 §1; 05 §2 |
| P29 — Blender delivery details | Confirmed for staff | accepted | staff-v10/deliver.py | 05 §4 |
| P30 — GLB metallic-roughness 8-bit | Confirmed as recorded | accepted | pbr-painting/SKILL.md line 199 (bracer section) | 05 §4 "(as recorded …)" |
| P31 — panel loads latest GLB | Confirmed | accepted | A/Pipeline/panel/panel.py lines 75–76 (mtime) | 05 §4; 08 QG-05 |
| P32 — Unreal only future | Imprecise | accepted | A/SM/10-Chapeu/report.json → v8.export_notes | 01 §9; 05 §4 |
| P33 — saved SPP ≠ delivered maps | Confirmed | accepted | export-spp-maps-native-precision.md | 05 §6; 08 EXP-05 |
| B01 — Blender normal for every piece | Imprecise | accepted | bake_normal_pair.py; painter_create.py lines 22–25; tunic painting.bake | 01 §1; 03 §1 |
| B02 — frozen, UV-validated low | Confirmed with qualification | accepted | bake_normal_pair.py lines 460–463, 841–842 | 03 §2 |
| B03 — per-part highs | Confirmed | accepted | bake_normal_pair.py lines 8–18 | 08 BAK-07 (cage fill distinct) |
| B04 — staff v10 parameters | Confirmed | accepted | staff-v10/bake.sh, staff-parts.json | No change |
| B05 — hat v6 parts | Confirmed | accepted | hat-v6/hat-parts.json | No change |
| B06 — wand bake | Confirmed as recorded | accepted | wand11-v1/bake/report.json | No change |
| B07 — body v3 bake | Confirmed as recorded | accepted | A/SM/00-Corpo/report.json → normal_bake_v3 | No change |
| B08 — tunic bake | Confirmed as recorded | accepted | A/SM/18-Tunica/report.json → painting.bake.normal | No change (03 §1C separates the Painter auxiliary job) |
| B09 — geometry-only RGB16 contract | Confirmed | accepted | bake_normal_pair.py | 03 §3 sentence |
| B10 — RAW kept | Confirmed with qualification | accepted | bake_normal_pair.py lines 688–693 | 03 §4 RAW row |
| B11 — coverage channels | Confirmed | accepted | bake_normal_pair.py lines 698–703 | 03 §4 coverage row |
| B12 — stage channels | Confirmed with qualification | accepted | bake_normal_pair.py lines 734–742 | 03 §4 stages row |
| B13 — invalid mask layered | Confirmed | accepted | bake_normal_pair.py docstring | No change |
| B14 — hidden evidence = identity | Confirmed | accepted | bake_normal_pair.py docstring | 08 BAK-07 |
| B15 — hat used-surface counts | Confirmed as recorded | accepted | A/Pipeline/retopology/hat-v6/bake/report-hat.json (fields read this session) | 03 §4 example |
| B16 — AO counts | Imprecise / unreconciled | accepted | painting-ao-ray-misses-and-definition.md; v8.ao; masks-v8*.log; hat_masks_v8.py lines 106–113 | 03 §5 note; corrected count "not confirmed" |
| B17 — AO zero = miss | Confirmed with qualification | accepted | hat_masks_v8.py (`< 0.02`); A/Docs/Gates/painting.md | 03 §5; 08 BAK-04 |
| B18 — 2,641 black texels / TBN | Confirmed with qualification | accepted | bake-per-corner-normals-tbn.md; QA05 audit | 03 §8; 07 §3 |
| B19 — evaluated triangulation | Confirmed | accepted | bake-evaluated-triangulation-saved.md | No change |
| B20 — changes invalidate maps | Confirmed | accepted | bake-invalid-when-mesh-or-uv-changes.md; Manifesto README → "Invalidação" | 08 BAK-06 |
| B21 — validate each set before join | Confirmed | accepted | professional-uv/SKILL.md lines 219–227 | 08 new PRJ-10 |
| B22 — xatlas mirrored charts | Confirmed as recorded | accepted | professional-uv/SKILL.md lines 183–188 | 07 §4 |
| B23 — pack margin vs measured texels | Confirmed as recorded | accepted | uv-measured-margins-resolution.md (17,137 / 9,177) | No change |
| B24 — 144,983 belt texels | Confirmed as recorded | accepted | bake-raw-and-coverage-stages.md | 07 §3 |
| R01 — one common standard | Confirmed | accepted | Render-Comparison.md | No change |
| R02 — `diag(1,1,−1)` mapping | Confirmed | accepted | Render-Comparison-Standard.json → coordinate_contract | 06 §3 |
| R03 — texture contract | Confirmed | accepted | texture_contract | No change (06 §3 provenance row) |
| R04 — `ref_match` calibrated once | Confirmed | accepted | presets.ref_match | No change |
| R05 — Painter not live-verified | Confirmed | accepted | presets.ref_match.painter.status, per_view_rotation | 06 §5 (side-view sign) |
| R06 — OCIO transform test | Confirmed as recorded | accepted | Render-Comparison.md; Render-Standard-Validation.json | 06 §6 note |
| R07 — sphere / grey-card residuals | Confirmed as recorded | accepted | validation.lighting_parity | 06 §1, §6 |
| R08 — visible differences block | Confirmed | accepted | A/AGENTS.override.md → "At each gate" | No change |
| R09 — preset labels do not restore state | Confirmed | accepted | render-actual-preset-snapshot.md | 08 VIS-04 |
| R10 — stale captures, Iray pause | Confirmed | accepted | Render-Comparison.md; pbr-painting/SKILL.md line 354; Colaboracao.md | 08 new INT-07 |

### 1.4 Inconsistencies

| ID / short title | Severity | Verdict | Evidence path | What changed and where |
|---|---|---|---|---|
| C01 — snapshot misses hat v8 | Inconsistency | accepted | A/SM/10-Chapeu/report.json → v8 | 01, 02, 04, 05, 08 NFR-03 (see F5) |
| C02 — 08 scope vs owner brief | Inconsistency | accepted | P/README.md; 08 (before) | 08 §0, BAK-03, EXP-08, VIS-06, §5 |
| C03 — smart-material priorities vs INT-02 | Inconsistency | accepted | 08 MAT-01…04 vs INT-02; leather_family_recipe_r9 | 08 MAT-02…04 MUST |
| C04 — native identity vs session cache | Inconsistency | accepted | operation-sync-state-per-session.md; operation-recover-spp-resources.md | 02 §8; 08 LAY-06 labelled corrective |
| C05 — repeat export vs historical delivery | Inconsistency | accepted | A/SM/00-Corpo/report.json → painting_v6.validacao.reproducao | 05 §6; 07 §5; 08 EXP-05, NFR-02 |
| C06 — sRGB I/O vs storage | Inconsistency | accepted | A/SM/10-Chapeu/report.json → painter_recipe.color_management ("uniform colors stored in GenericColorSpace.Working"); U/runtime/engine/renderer/material/material_interface.h lines 200–209 | 08 PRJ-05 |
| C07 — ORM order vs glTF handoff | Inconsistency | accepted | U/…/gbuffer_ps.hlsl lines 177–182, 204–206; staff-v10/deliver.py | 05 §4 ORM row, §4.1; 08 EXP-08, EXP-10 |
| C08 — OpenGL +Y universally compatible (H) | Inconsistency | accepted | gbuffer_ps.hlsl lines 217–242; mesh_importer.cpp; fbx_importer.cpp | 05 §4.1 (kept "not confirmed"); 08 PRJ-04, EXP-10 |
| C09 — signed normals vs Z ≥ 0 | Inconsistency | accepted | bake_normal_pair.py (repair is "inspection heuristic"); gbuffer_ps.hlsl `sqrt(max(…,0))` | 05 §4.1; 08 EXP-10, BAK-07 |
| C10 — Height/Thickness preset needs explicit options | Inconsistency | partially accepted | Confirmed: uzcook.cpp lines 162–287 (BC7 sRGB fallback); texture_importer.h lines 55–75 (explicit format/sRGB). Not found: a `uzcook` metadata (sidecar) override | 05 §4.1; 08 EXP-10; correction of `../uzengine-renderer/04…` §8 forwarded (outside write scope) |
| C11 — separate-opacity contract | Inconsistency | forwarded to architecture | uzcook.cpp lines 276–282; gbuffer_ps.hlsl lines 283–297; uzengine-renderer/04 §2.1 | 05 §4.1; 08 EXP-07, EXP-10; route choice = architecture |
| C12 — authoring vs cooked precision | Inconsistency | accepted | U/…/texture_importer.cpp lines 254–271 (RGBA8 decode); staff-v10/painter_export.py | 05 §4.1; 08 EXP-10 |
| C13 — packing agreement ≠ render identity | Inconsistency | accepted | Render-Comparison-Standard.json → validation | 06 §1, §6; 08 G-04, VIS-06 |
| C14 — viewer capability vs optional opening | Inconsistency | accepted | P/README.md | 08 VIS-01, NFR-01 wording |
| C15 — manifest trace completeness | Inconsistency | accepted | manifest-schema-v1.json → $defs.exportacao, comparacao; A/SM/10-Chapeu/report.json → v8.artistic_approval | 08 INT-21, QG-04 |

### 1.5 Missing requirements

| ID / short title | Severity | Verdict | Evidence path | What changed and where |
|---|---|---|---|---|
| ADD-01 — instruction replay / output-parity contract | Missing (MUST) | accepted | P/README.md; P/.rulebook/decisions/001-…md | 08 new G-04 |
| ADD-02 — immutable approved state, scoped invalidation | Missing (MUST) | accepted | A/AGENTS.override.md → "Protect approved work"; manifest-schema-v1.json → $defs.invalidacao | 08 new QG-05 |
| ADD-03 — per-node resource bindings, recovery closure | Missing (MUST) | accepted | tunic painting_v10.source_recovery; operation-recovery-before-cleanup.md | 08 new LAY-13; SAV-04 |
| ADD-04 — relief applied exactly once | Missing (MUST) | accepted | painting-height-in-normal-only-once.md | 08 new EXP-09 |
| ADD-05 — material isolation in every channel | Missing (MUST) | accepted | painting-material-isolation-all-channels.md | 08 new LAY-14 |
| ADD-06 — per-set UV certification | Missing (MUST) | accepted | professional-uv/SKILL.md; uv-measured-margins-resolution.md | 08 new PRJ-10, PRJ-09 expanded |
| ADD-07 — bake surface accounting and lineage | Missing (MUST) | accepted | bake_normal_pair.py; bake-raw-and-coverage-stages.md | 08 new BAK-07 |
| ADD-08 — target identity, coherent async snapshots | Missing (MUST) | accepted | operation-reload-job-id.md; operation-sync-state-per-session.md; operation-background-paths-and-saving.md | 08 new INT-07 |
| ADD-09 — explicit engine format/binding metadata | Missing (MUST) | accepted | uzcook.cpp; gbuffer_ps.hlsl; material_interface.h | 08 new EXP-10 |
| ADD-10 — SpecularWeight handoff validation | Missing (MUST) | partially accepted | deliver_v8.py line 26 confirms the `.blend` gap; but `glb_add_specular.py` already writes the GLB extension (report: "checked inside the GLB") and the FBX gap is recorded by the report itself | Folded into 08 PRJ-06, EXP-01, INT-11 (no separate ID); fixing the Blender consumer is Assets3D work |

## 2. Requirement re-classifications (08)

| ID | Before | After | Reason | Source |
|---|---|---|---|---|
| G-01 | MUST (user must amend the rule first) | SHOULD (align governance text) | The owner already requires full replacement; no new permission. The review proposed COULD; SHOULD kept because `AGENTS.override.md` is still the binding text Assets3D agents read | Owner; A/AGENTS.override.md → "Working agreements" |
| PRJ-06 | MUST (five channels) / SHOULD (SpecularWeight, double-sided) | MUST (all) | SpecularWeight is in the current hat v8 delivery; double-sided is a Painter shader parameter on the approved tunic | Owner (rendering parity); A/SM/10-Chapeu/report.json → v8.specular; A/SM/18-Tunica/report.json |
| BAK-03 | SHOULD (if UzPainter bakes) | MUST | Native high-poly bake is an owner requirement; the Blender route stays accepted | Owner; P/README.md → "Baking" |
| BAK-04 | SHOULD | MUST (miss evidence) / SHOULD (second pass) | Binding directive requires checking AO misses; native AO bake is owner scope | A/AGENTS.override.md → "Definition independent of the lighting"; Owner |
| BAK-05 | MUST (if BAK-03) | MUST | Condition removed with BAK-03 | Owner; operation-reload-job-id.md |
| LAY-11 | SHOULD | MUST | Smart materials are owner scope and exercised on the bracers | Owner; A/SM/21-Bracal-Esquerdo/report.json → painting_p1.smart_materials |
| LAY-12 | COULD | MUST | Painter functionality includes paint layers; hat v5 has a Paint effect and a paint layer (parity corpus) | Owner; A/SM/10-Chapeu/report.json → layer_tree |
| MAT-02 | SHOULD | MUST | Used generators must evaluate identically for output parity | Owner; A/SM/10-Chapeu/report.json → painter_recipe |
| MAT-03 | SHOULD | MUST (used procedurals) / SHOULD (generic library) | Generic noise does not reproduce recorded instructions | Owner; A/SM/00-Corpo/report.json → painting_v3 |
| MAT-04 | SHOULD | MUST | Locked and delivered recipes depend on Painter starter assets; art migration is not parity | Owner; leather_family_recipe_r9 (LOCKED) |
| MAT-05 | SHOULD | MUST | Height units and Height → Normal conversion determine exported normals | Owner; pbr-painting/SKILL.md → "Relevo medido" |
| RES-03 | SHOULD | MUST | A missing HDRI broke a preset; equal render needs the same environment bytes | Owner; render-hdri-as-project-resource.md |
| EXP-04 | SHOULD | MUST | Gate QA uses mesh-map, isolated-layer and unlit outputs | A/Docs/Gates/painting.md; painter_layer_isolate.py |
| EXP-05 | MUST (byte-identical across sessions/machines) | MUST (same build) / SHOULD (cross-session, cross-machine) | Sources show consecutive equality and cross-session drift; cross-machine identity is not demonstrated | A/SM/00-Corpo/report.json → painting_v6.validacao.reproducao |
| EXP-07 | SHOULD | MUST (capability) / SHOULD (asset adoption) | Painter export functionality includes alpha; cloth adoption is a production gate | Owner; painter_recipe.export.preset_details (`_Alpha_Raw`) |
| EXP-08 | COULD | MUST (Unreal ORM, UzEngine, Painter-equivalent PBR) / SHOULD (glTF metallic-roughness) | Owner names these targets; Blender GLB packing is a handoff, not grounds for COULD | Owner; P/README.md → "Output" |
| VIS-04 | SHOULD | MUST | One `ref_match` preset in Blender and Painter is a binding rule; equal render needs the same display state | A/AGENTS.override.md → "Document as you go"; Owner |
| VIS-05 | SHOULD | MUST | Recorded cameras must convert exactly for comparisons | Owner; Render-Comparison-Standard.json → coordinate_contract |
| VIS-06 | COULD (path-traced preview comparable to Cycles) | MUST (render equal to Painter's) | Acceptance is equal render; the method is architecture | Owner; P/.rulebook/decisions/001-…md |
| DIA-01 | SHOULD | MUST (evidence access) / SHOULD (native statistics) | Region tone/saturation evidence is a paint-gate requirement | A/AGENTS.override.md → "Stage quality gates" §4 |
| DIA-02 | COULD | MUST | Measured relief is binding practice; access to geometry-only/combined normals is enough | pbr-painting/SKILL.md line 41; v8.relief_painted_deg_p50_p90 |
| INT-13 | SHOULD | MUST | The LOCKED leather recipe consumes exported Painter Curvature with fixed bounds | leather_family_recipe_r9.masks |
| INT-23 | SHOULD | MUST | Durable recipes are migration inputs; replay via adapters, tested | hammered-iron-v9.json; tunic source_recovery |
| QG-02 | SHOULD (warn, switchable) | MUST | Failed/pending upstream gates block painting | pbr-painting/SKILL.md → "Pré-requisitos obrigatórios"; Gates/painting.md |
| NFR-04 | SHOULD (no larger than Painter) | MUST (compact; target not confirmed) | Compact saving is an owner requirement; the numeric criterion is still open | Owner; P/README.md → "Compact project file" |
| G-04 | — | MUST (new) | Output-parity protocol (ADD-01) | Owner; decision 001 |
| PRJ-10 | — | MUST (new) | Per-set UV certificate (ADD-06) | professional-uv/SKILL.md |
| BAK-07 | — | MUST (new) | Bake accounting and lineage (ADD-07) | bake_normal_pair.py |
| BAK-08 | — | MUST (new) | AO integration rule: one corrected AO for mesh map, delivery and albedo layers | AGENTS.override.md; v8.ao.uses; painter_set_ao.py |
| LAY-13 | — | MUST (new) | Per-layer mask bindings for the tunic rebuild (ADD-03) | tunic source_recovery.layer_specific_masks |
| LAY-14 | — | MUST (new) | Material isolation in all channels (ADD-05) | painting-material-isolation-all-channels.md |
| EXP-09 | — | MUST (new) | Relief applied once (ADD-04) | painting-height-in-normal-only-once.md |
| EXP-10 | — | MUST (new) | Engine format/binding metadata (ADD-09) | uzcook.cpp; gbuffer_ps.hlsl |
| INT-07 | — | MUST (new) | Target identity and coherent async snapshots (ADD-08) | operacao-* lessons |
| QG-05 | — | MUST (new) | Approved-state protection (ADD-02) | AGENTS.override.md; $defs.invalidacao |

Wording corrected, priority unchanged: G-02, G-03, PRJ-01…05, PRJ-07…09, BAK-01, BAK-02, BAK-06, LAY-01, LAY-03…10, MAT-01, RES-01, RES-04, EXP-01…03, EXP-06, SAV-01…04, VIS-01…03, INT-01…05, INT-10…12, INT-20…22, QG-01, QG-03, QG-04, NFR-01…03, NFR-05, NFR-06, NFR-08. Unchanged: LAY-02, RES-02, SAV-05, INT-06, INT-14, NFR-07.

## 3. The review's answers and questions for the architect

### 3.1 Answers to the analysis's open questions (08 §6)

| Q | Review answer (short) | Response |
|---|---|---|
| Q1 | The Painter-only rule is historical; replacement is authorized; remove G-01 as a blocker; pilot is architecture | Partially accepted: the rule is still current text in A/AGENTS.override.md (moved there 2026-10-09), not historical; but the owner's requirement supersedes it for UzPainter, so G-01 is now alignment (SHOULD) |
| Q2 | Rebuild acceptable only with full approved state, exact per-layer bytes and proven equal maps/render; Painter may be a temporary oracle | Accepted → 08 G-03, LAY-13; mechanism (SPP reader, pinned extraction or rebuild) stays open |
| Q3 | Every parity-corpus dependency must evaluate identically; names/settings do not reconstruct algorithms | Accepted → 08 MAT-04; availability not confirmed |
| Q4 | Proven consumers are Blender and the GLB panel; Unreal ORM and UzEngine are mandatory targets; define full adapters | Accepted → 08 EXP-08, EXP-10; 05 §4, §4.1 |
| Q5 | Support both routes; native bake is product scope; low-derived ≠ high-derived | Accepted → 08 BAK-01…03, §5 |
| Q6 | Target Painter's actual versioned shader/render; Cycles stays pipeline QA | Accepted → 08 G-04, VIS-06 |
| Q7 | Yes: optional read-only preview; capture/camera via API | Accepted → 08 VIS-01, VIS-02 |
| Q8 | Alpha belongs to full parity; using it on cloth is a separate gate | Accepted → 08 EXP-07 |
| Q9 | Only the 54 s batch is recorded; measure after equal outputs | Accepted → 08 NFR-05 |

### 3.2 Questions forwarded to the architect

| # | Question (short) | Related requirement |
|---|---|---|
| 1 | Which pinned Painter build, shader, resource versions and recorded instruction sequences form the first parity corpus (tunic v10, locked leather/bronze, hat v8)? | G-04, MAT-04 |
| 2 | What exactly is "the same render": viewport or Iray, resolution, convergence, samples, seed, camera, lights/HDRI basis, post, display, encoding? | G-04, VIS-06 |
| 3 | How are decoded textures, rendered pixels and encoded bytes compared separately, with no tolerance unless the owner accepts one? | G-04, EXP-05 |
| 4 | How is exact Painter procedural/material evaluation obtained, and which dependencies are not confirmed? | MAT-02…04 |
| 5 | Native SPP reader, pinned extraction/oracle or recipe rebuild; how is completeness proven (hidden nodes, aliases, effects, embedded masks, display state)? | G-03, SAV-04 |
| 6 | How are the tunic C07/F03 bindings represented, and how does a resource refresh avoid changing an approved consumer? | LAY-13, QG-05 |
| 7 | Which native bake algorithms/settings must match Painter vs the Blender reference route, with both traceable? | BAK-03 |
| 8 | How are per-set highs, parts/cages, physical vs relative distances, backface rules, subsampling/dilation and normalisation captured? | BAK-02, BAK-03 |
| 9 | How are misses, cage hits, SAT/ring extensions, hidden-flat exceptions and fallbacks surfaced without hiding used-surface changes? | BAK-07 |
| 10 | Which per-set UV/corner-basis certificate and gate chain does the production adapter require, while allowing flagged diagnostics? | PRJ-09, PRJ-10, QG-02 |
| 11 | Which UzEngine import route/settings preserve corner normals, UV orientation and handedness; which fixture fixes the normal convention? | PRJ-04, EXP-10 |
| 12 | What are the complete Unreal and UzEngine material contracts (ORM, normal, AO, SpecularWeight, Height, opacity, flags, precision, mips), and which consumers validate them? | EXP-08, EXP-10 |
| 13 | Explicit metadata or direct cooking for Height/Thickness/SpecularWeight; how does alpha opacity survive the fixed-PBR route? | EXP-07, EXP-10 |
| 14 | Which consumer fixes the commented Blender Specular IOR link and proves Blender/GLB/FBX/engine correspondence? | INT-11 |
| 15 | What is the compact-project criterion and dependency storage model (embedded bytes, dedup, references, checkpoints)? | NFR-04, SAV-01 |
| 16 | What transaction/job model binds every mutation, reload, save, export and capture to project/revision/set/round, with a non-pausing preview? | INT-07, BAK-05 |
| 17 | Which workflows stay external Python/Blender, and which interfaces make them reproducible without becoming hidden prerequisites? | §5 boundary |
| 18 | Who reconciles the AO remaining-count discrepancy and checks per-asset AO adoption before using those values as benchmarks? | BAK-04, BAK-08 |
| 19 | How does an approval registry keep historical acceptance, hat v8 artistic pending, tunic alpha/rig limits and independent review distinct? | QG-04, QG-05 |
| 20 | After equal outputs, which corpus, hardware and build set memory, latency and storage budgets? | NFR-05 |

### 3.3 Not verified in this response

- How the recorded AO remainder 77,588 was counted (03 §5 keeps a **Hypothesis** only).
- Painter's default Height blend for fills created by `sync` (needs a live Painter read-back; not run).
- Whether Assets3D OpenGL (+Y) normal maps shade correctly in UzEngine, and the alpha value a BC4 opacity texture yields in the fixed-PBR shader (no fixture or render run).
- The tangent algorithm behind Painter's "PerFragment" setting; 8K project evaluation (PRJ-03 **H**).
- Unreal's ORM channel order against an Unreal source (only UzEngine's shader order was read).
- Historical numbers re-quoted by the review and not recomputed here (B04–B08 bake parameters, R06/R07 render residuals, P30 GLB bit depth); they stay "as recorded".
- Decision 001's status: the `.md` says "proposed", its `.metadata.json` says "accepted"; the owner's statements are taken as the binding premise.
