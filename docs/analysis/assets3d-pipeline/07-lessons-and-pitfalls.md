# 07 — Lessons and pitfalls involving Painter, bake, UV, texture sets and export

Conventions as in [01](01-pipeline-overview.md): paths relative to `E:\UzmiGames\Assets3D\`, `SM/` = `Creatures/Undead/Skeletal Mage/Models3D/`, **F** Fact / **H** Hypothesis / **R** Recommendation.

Lesson cards live in `Docs/Lessons/<id>.md` (index: `Docs/Lessons/README.md`). Each card carries a status: cause `confirmada|hipotese`, fix `validada|pendente` (`Docs/Lessons/README.md` → "Como registrar o próximo aprendizado"). The "Status" column copies those two fields. The last column is our reading of why the lesson constrains a Painter replacement (**R**).

## 1. Painter operation and persistence

| Card / source | Symptom → cause → fix (F) | Status | Why it matters for UzPainter (R) |
|---|---|---|---|
| `operacao-painter-exclusivo-modo` | Concurrent display/layer commands crashed Painter (Qt6Core); Visualisation/Iray pauses computation → one owner under LOCK, sync and wait in Edition before save/export/render | confirmed / pending | Concurrency safety and an explicit "computation finished" signal are needed; never let a preview mode pause the evaluator |
| `operacao-painter-export-mixed-ao` | Export with virtual map `Mixed_AO` closed Painter 12.1 (APPCRASH); deliver the AO from the bake instead | hypothesis / validated | Export must not crash; AO output must be a first-class map, not a fragile virtual one |
| `operacao-projeto-captura-reais` | `save_viewport` returned an old camera; `QMainWindow.grab` black under Vulkan → live capture after convergence | confirmed / pending | Captures must be deterministic and reflect the current state |
| `operacao-recarga-job-id` | Bake ran on the old mesh because a previous job's "success" was read; existing backup blocked reload → `overwrite_backup`, track the current `job_id` | confirmed / pending | Job API with unique ids and unambiguous status |
| `operacao-recuperacao-antes-da-limpeza` | Recipe/seeds could stay only in temp/cache; regeneration from durable files diverged on 4/15 masks until a non-default parameter was recorded | confirmed / validated | Projects must be reproducible from declared inputs; every non-default parameter must live in the recipe |
| `operacao-recuperar-spp-recursos` | After a crash, cached UIDs did not match saved bitmaps → verify resources in the reopened file; resync with a fresh state | confirmed / pending | Saved files must be self-describing; no hidden session caches |
| `operacao-segundo-plano-caminhos-e-salvamento` | Relative paths wrote renders to `C:\`; masks synced into the wrong open project; Painter closed twice during export; empty GLB from a hidden same-name object → absolute paths, check the open project, save before export, check files | confirmed / validated | Absolute paths, explicit target project in every call, save-before-export atomicity |
| `operacao-sync-estado-por-sessao` | Exported maps byte-identical to the previous round although stack/masks changed; resource URLs in the sync state died when the project was reopened; the filtered log hid "resource not found" → fresh state per session, unfiltered output, hash check | confirmed / validated | Resource identity must survive save/reopen; errors must fail loudly |
| Skill: "Visualisation pausa a computação"; 2 agents crashed Painter | Use `collab.py lock` and save after each good sync | F — `.claude/skills/pbr-painting/SKILL.md` → "Erros que já custaram tempo" | Same as above |
| Skill: Windows paths in Painter Python | A Git-Bash POSIX path `/e/...` resolved against the current drive and created stray folders | F — SKILL.md → "Carrying paint onto a changed mesh" | Path handling must be platform-correct |
| Skill / REFERENCE: OCIO before create | Creating without `OCIO` produced a Legacy project; Colour API rejected both colour-space classes; not convertible afterwards | F — `.claude/skills/pbr-painting/REFERENCE.md` → "Armadilhas" | Colour management must be fixed at project creation and recorded |
| REFERENCE: batch exit code | MCP batch stops at first error but may exit 0 | F — REFERENCE.md → "Painter MCP" | Tool results must carry a reliable success flag |
| Collaboration: `needs_saving` after reopen | Reopening an unchanged `.spp` reported `needs_saving == true` | F — `Docs/Colaboracao/Colaboracao.md` → "Janela emprestada" | Dirty state must be exact |
| `painter_layer_stack.py` history | 0–255 colours reached Painter unscaled and became white; the sync now rescales | F — `painter_layer_stack.py` docstring; `git log` `aab929b` | Typed colour inputs with explicit range and colour space |

## 2. Painting and layers

| Card / source | Symptom → cause → fix (F) | Status | Why it matters for UzPainter (R) |
|---|---|---|---|
| `pintura-ao-falhas-de-raio-definicao` | AO not used for definition; AO bake misses painted as a dark spot → second wider AO bake on missed texels; AO in three uses (map, cavity, moderate albedo layer) | confirmed / validated | AO bake must report misses; AO must be exportable and usable as a mask |
| `pintura-barras-guia-por-painel` | Trims followed each tear → smoothed guide per panel | confirmed / validated | Mask inputs come from 3D tools; UzPainter must accept replaced masks without rebuilding the stack |
| `pintura-cor-de-amostra-nao-procedural` | Procedural dirt rejected ("pra que … procedural") → reference-derived swatches projected in 3D + 3D masks | confirmed / validated | Bitmap BaseColor fills with exact UV placement are core; procedural grunge is secondary |
| `pintura-cor-lavada-diagnostico` | "Washed" colour fixed by blind exposure/roughness edits → isolate display/HDRI/BaseColor, then normal/roughness/specular | hypothesis / pending | Needs unlit BaseColor output and per-channel diagnostics |
| `pintura-couro-manchas-craquelado` | Uniform Voronoi read as reptile; >10 % fine stains read as camouflage; `cracks_leather` without Levels lightened everything | confirmed / pending | Levels/contrast on masks and per-layer opacity are required |
| `pintura-especular-feltro-veu` | Felt read washed and plastic: default dielectric specular (F0 ≈ 4 %) under the large soft studio added a grey veil of +20–30 in G/B → OpenPBR `SpecularWeight` per layer (felt 0.5, leather/iron 1.0), exported map, Blender Specular IOR Level = 0.5 × weight, glTF `KHR_materials_specular`; global sheen rejected | confirmed / validated | A specular-weight channel is part of the material and of every export/engine mapping; without it the felt regains the veil |
| `pintura-fill-ordem-dos-canais` | Script-created fill came out white: setting `active_channels` after `set_source` resets sources | confirmed / validated | Channel activation must not reset values (API ordering hazard to avoid by design) |
| `pintura-isolamento-materiais-todos-canais` | Masks leaked into leather/metal/rim; frontal-only projection → measure limits on geometry; check ID, Height, Normal, Roughness, Metallic | confirmed / pending | Isolation per channel, including Height/Normal |
| `pintura-isolar-contribuicao-das-camadas` | Leopard spots on skull; lowering the suspected layer changed nothing → export with each layer hidden, measure | confirmed / validated | Per-layer contribution export (or difference maps) is a required diagnostic |
| `pintura-normal-height-uma-vez` | Height added to a normal that already contained it; Normal channel inactive while the substance parameter was on | confirmed / pending | Export must state whether the normal is geometry-only or combined; channel activity must be inspectable |
| `pintura-osso-cavidades-suturas-high` | Grey orbits, doubled sutures → deep regions, convex boxes, sutures from high relief | confirmed / validated | Masks derive from high geometry, not from painting |
| `pintura-pano-trama-escala-valor` | Burlap scale 32 gave 1 mm weave vs 2.5 mm reference; fibres > 15 % camouflage; `fabric_linen` Levels > 0.45 lightened | confirmed / pending | Physical-scale control of procedurals/triplanar |
| `pintura-profundidade-tres-escalas` | Gaussian mask scale 0.16 nearly subpixel vs 16 broad spots: projection scale is not metres | confirmed / pending | Procedural/projection scale must be in declared physical units |
| `pintura-projecao-tampos-lombada` | Side projection collapsed on spine caps → blend to XY by normal | confirmed / pending | Projection blending by normal (triplanar-like) is needed for bitmaps too |
| `pintura-qualidade-visual-nao-tecnica` | Technically valid paint rejected for missing cavities/detail; metrics hit while visual failed | confirmed / validated | UzPainter cannot certify quality; it must make three-scale detail and relief easy and measurable |
| `pintura-texels-projecao-resolucao` | Loss of definition blamed on resolution without measuring texel support; 2K vs 4K gave little gain on the book | confirmed / pending | Separate authoring and delivery resolution; mip/filter-aware review |
| `pintura-texture-sets-anatomia` | One 4K for the whole skeleton gave 19 px/cm on the skull → three texture sets (80/33/34 px/cm) | confirmed / pending | Multiple texture sets per project with independent resolution |
| REFERENCE: complementary group masks | Default grey appeared at every cloth/lining seam → bottom group unmasked | F — REFERENCE.md → "Armadilhas desta rodada" | Default-material bleed must not exist, or be explicit |
| REFERENCE: exposure is not colour | White Umbrella +1.6 EV made cloth with BaseColor (70,36,33) read (150,80,78) | F — same | Review lighting must be fixed and separate from paint |
| REFERENCE: sharpness limited by UV | 431 islands at 10.24 px/cm ≈ 1 texel/mm; trims got 1–2 texels | F — same | Resolution decisions belong to UV/texture-set setup |
| Skill: refreshing masks | `set_source(None, new_resource)` on existing mask effects refreshes 3D masks without rebuilding; `sync` rebuilds the group and drops later opacity tweaks | F — SKILL.md → "Carrying paint onto a changed mesh" | In-place resource replacement that keeps every other parameter |
| Skill: curvature per texture set | New islands shifted curvature range for the whole set and moved curvature-driven smart masks | F — same | Deterministic, recordable baker normalisation |

## 3. Bake

| Card / source | Symptom → cause → fix (F) | Status | Why it matters for UzPainter (R) |
|---|---|---|---|
| `bake-halo-suporte-geometrico` | Halo from a rounded low support; cage changes did not help → fix geometry first | confirmed / validated | Bake diagnostics must point to geometry, not hide it |
| `bake-invalida-malha-uv-mudou` | New mesh/UV used old bakes/masks → bind every map to file/object/UVMap/transforms/triangulation | confirmed / pending | Every map/resource needs provenance hashes; changes must invalidate dependents |
| `bake-normais-tbn-por-canto` | Coincident opposite faces with zero corner normals produced 2,641 black texels in a Painter re-export; control A (six corner normals repaired) removed them but left residuals up to 1,472/65,535 against the delivery; the internal zero → NaN stage and the production fix are not confirmed | confirmed / pending | Mesh import must validate finite, non-degenerate TBN and refuse or flag |
| `bake-raw-cobertura-estagios` | Repair modified used surface silently; centre sampling missed thin triangles → RAW + coverage + stages + per-class counts | confirmed / pending | Any UzPainter baker must expose coverage/miss maps and never silently repair used surface; the corrected helper does not retro-certify assets baked earlier or every cage-fill variant |
| `bake-triangulacao-avaliada-salva` | Same polygons, different evaluated triangulation after vertices moved | confirmed / pending | Import the exact triangulated mesh; never re-triangulate |
| `low-linhas-comuns-por-painel` | Inverted normals (black) on tab interiors from row heights chosen per column → common rows; count Z < 0 per part | confirmed / validated | Per-part Z < 0 statistics are a useful bake QA output |
| REFERENCE: AO bake with excluded collections | Selected-to-active AO did not see the high | F — REFERENCE.md | Explicit high-mesh inputs |
| REFERENCE: stitch-dot mask bake | `margin=16` merged dots into bands → margin 0, dilation later | F — REFERENCE.md | Dilation must be controllable per map |
| Patch: bake without UDIM | MCP rejected texture sets without UV tiles | F — `Pipeline/mcp/substance-painter-mcp-local.patch` | Non-UDIM single-tile sets are the norm |

## 4. UV and texture sets

| Card / source | Symptom → cause → fix (F) | Status | Why it matters for UzPainter (R) |
|---|---|---|---|
| `uv-normalizar-todas-as-ilhas` | Zero-overlap auto UV judged sufficient → normalise every island incl. single triangles; checker | confirmed / pending | UzPainter consumes UV as given; it must not repack, but should report density |
| `uv-margens-medidas-resolucao` | Pack parameter 7 px questioned vs measured gap 17.1 px / border 9.2 px at 4K | confirmed / validated | Padding/dilation must be judged on measured texels at the declared resolution |
| `uv-anatomia-cartas-espelhadas` | xatlas mirrored ~half the charts → unmirror by signed area | confirmed / validated | Import must detect and report flipped UV triangles (signed area); zero inversions is this project's certification policy, while intentional mirroring elsewhere would need explicit tangent-handedness support |
| `uv-perfil-variavel-slim` | Analytic column UV sheared where the profile changes → ABF + SLIM | confirmed / validated | Out of scope (Blender), but distortion stats matter for painting |
| `geometria-camadas-antes-da-uv` | UV passed while the low had lost layers → check construction before UV and low+normal after bake | confirmed / validated | Painting must not start on a failed construction (gate input) |
| `low-caudas-franjas-voxel` | Thin tails/fringe did not converge through voxel UV → rebuild as clean cloth or cards | confirmed / pending | Fringe/fray may need alpha cards (alpha output pending) |
| Skill UV: validate each texture set before join | Sets overlap in 0–1 after join | F — `.claude/skills/professional-uv/SKILL.md` | Per-set 0–1 tiles; no UDIM |

## 5. Export and delivery

| Card / source | Symptom → cause → fix (F) | Status | Why it matters for UzPainter (R) |
|---|---|---|---|
| `exportacao-spp-mapas-precisao-nativa` | Saved `.spp` re-exports differed from deliveries (Normal on 56 % of pixels by ±1 8-bit level on the book; black texels on the hat); Pillow hides RGB16 differences | confirmed / pending | Repeat exports of one saved project must be identical on the same build; reproducing a historical delivery and equalling Painter's output are separate properties, each tested on its own |
| `exportacao-rodada-coerente` | `.spp` advanced while `.blend`/maps/GLB stayed old | confirmed / pending | Export must stamp round/version and source project hash |
| `exportacao-round-trip-normais-microfaces` | GLB import showed shading wedges; exporter dropped micro-faces | confirmed / pending | Boundary: mesh export stays in Blender, but UzPainter must not alter the mesh it was given |
| `exportacao-escala-fisica-fonte` | Reimport kept Meshy normalisation (items ≈ 1.91 m) | confirmed / pending | Physical units must be preserved for physical-scale procedurals |
| `exportacao-pivo-empunhadura` | Pivots were modelling-relative → grip/headband pivot convention; rigid move only (shape, UV, normals, textures unchanged) | confirmed / validated | Textures must survive a rigid pivot move unchanged (UV-space data only) |
| QA05 SPP audit | Re-export of the hat changed procedural resource display names (`Mask Editor` → `mg_mask_editor` …) and produced black normal texels; grimoire Normal differed by quantisation. The audit labels resource re-evaluation as an unproven hypothesis ("Hipótese (não comprovada)"); later evidence in the same file traces the black texels to zero corner normals in the saved low and states that a resource-version change is not established as the explanation | F — `Docs/analysis/skeletal-mage-review/05-spp-audit-10-13-20261007.md` | Resource versions must be pinned inside the project as prevention, independent of the unproven cause |

## 6. Rendering and review

| Card | Symptom → cause → fix (F) | Status | Why it matters for UzPainter (R) |
|---|---|---|---|
| `render-condicoes-comuns` | Grimoire looked darker than tunic/hat under different presets → one common standard in both programs | confirmed / pending | Preview lighting must be the shared standard, versioned |
| `render-enquadramento-comparavel` | Smaller framing read as less detail → fixed camera/aspect/occupancy | confirmed / pending | Camera import/export compatible with Blender conversion |
| `render-hdri-recurso-do-projeto` | Preset failed: HDRI not a project resource | confirmed / validated | Environment resources must be portable with the project |
| `render-orientacao-entre-motores` | Same numbers, different reflections → `diag(1,1,-1)` world mapping and full camera conversion | confirmed / validated | Documented, tested coordinate conventions |
| `render-snapshot-real-do-preset` | Preset name did not restore real state | confirmed / pending | Display state must be fully serialisable |
| `geometria-camada-sob-saliencia-sombra` | Correct albedo rendered dark under an overhang → fix geometry | confirmed / validated | Diagnostic passes (unlit BaseColor vs PBR) needed |

## 7. Gates that touch painting (generated checklists)

**F** — `Docs/Gates/painting.md`, `export.md`, `bake.md`, `operation.md`, `render.md`, `uv.md` list the checks extracted from these cards, ordered from cheap to expensive, with check IDs (`manifesto-peca-v1`, `render-ref-view-crops`, `render-board-ref-vs-render`, `visual`, `medida-manual`). Examples of cheap paint checks: the manifest must show `gates/visual geometria-encaixe = pass` before the Painter project is created; save the `.spp` before export and confirm all listed files were written; after each sync read the full output and compare exported map hashes with the previous round; re-read uniform sources and active channels after fill creation.

## 8. Why these lessons mattered (synthesis)

| Theme | What went wrong repeatedly | Type | Source |
|---|---|---|---|
| Hidden state | Session-scoped resource URLs, stale captures, previous job status, dirty flags, cached UIDs | F | Section 1 cards |
| Silent success | Exit code 0 on failed batch, filtered logs, "SYNC_DONE" with unchanged maps | F | `operacao-sync-estado-por-sessao`; REFERENCE.md |
| Non-reproducible exports | Cross-session Normal/Height drift; resource display names changed on re-export (cause not established); black normal texels from zero corner normals in the saved low | F | Section 5 |
| Painting over defects | Paint started before geometry/UV/bake gates passed and was lost | F | `gate-nao-pintar-geometria-reprovada` |
| Technical ≠ visual | All checks green, user rejected paint for missing depth | F | `pintura-qualidade-visual-nao-tecnica` |
| Lighting confusion | Presentation presets, exposure, orientation and viewport light masked material errors | F | Section 6 cards |
