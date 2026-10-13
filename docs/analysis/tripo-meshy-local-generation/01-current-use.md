# 01. How the pipeline uses commercial generators today

Scope: the Assets3D repository (`E:/UzmiGames/Assets3D`, cited as `Assets3D/…`). Image-to-3D generation is an Assets3D stage; UzPainter's vision lists replacing it as a non-goal (`docs/vision.md:54`).

## F-001 - Meshy 7.1 is the only funded high-poly source; Tripo and Hitem3D are wired in but have no balance

**Evidence:**
- Production setting: Meshy 7.1 image-to-3D, Ultra 4K geometry for a single image, an estimated 25 credits per piece (`Assets3D/Docs/Pipeline-Guide.md:35`, `:40`). Multi-view uses Ultra 2K, because the multi-image endpoint rejects 4K (`:48`, `:182`).
- The client already supports Tripo v3.1 (`--version v3.1-20260211 --quality detailed`, texture and PBR off) and Hitem3D (`hi3dv3.0`, `2048quality`) (`Assets3D/Pipeline/generation/generators_3d.py:8-9`, `:120-122`, `:203-205`).
- Tripo's API balance is 0 (its 200 web credits sit in a separate wallet) and Hitem3D's is 0. Rodin and Hunyuan3D were left out by the user's decision. Meshy went from 5,045 to 4,599 credits in one bench session (`Assets3D/Docs/analysis/skeleton-reconstruction-meshy/08-hand-workbench.md:73-76`; `Assets3D/.rulebook/tasks/phase5_skeletal-mage-body-rebuild/tasks.md:8`).

**Impact:** Any local model has to beat Meshy 7.1: Ultra 4K for a single image, Ultra 2K for multi-view. The pipeline has no measured Tripo or Hitem3D output, so it has no second commercial baseline. The earlier exclusion of Hunyuan3D bears on which local candidates can be tested (F-013).

**Confidence:** High.

## F-002 - In this pipeline, "high-poly" means 0.16-1.8 M triangles per piece as delivered

**Evidence:** These are the triangle counts the pipeline recorded for the Meshy sources:

| Piece | Triangles | Source (`Assets3D/Creatures/Undead/Skeletal Mage/Models3D/…`) |
|---|---:|---|
| 12 Bone wand | 160,514 | `12-Varinha-Osso/report.json` → `source.import_observed.triangles` |
| 09 Staff | 162,908 | `09-Cajado/report.json` → `source.triangles` |
| 13 Grimoire v2 (4 views, 2K) | 606,526 | `13-Grimorio/report.json` → `regeneration_multiview.source_inspection.triangles` |
| 10 Hat | 667,248 | `10-Chapeu/report.json` → `source_data.high_triangles` |
| 24 Chest straps | 766,050 | `24-Tiras-Peito-Gema/report.json` → `sources.meshy_high.tris` |
| 00 Body | 817,720 | `00-Corpo/report.json` → `source.high_triangles` |
| 14 Ritual lantern | 1,816,804 | `14-Lanterna-Ritual/report.json` → `v2.geometry.computed_metrics.source_triangles` |

**Impact:** Triangle count is not the hard target. A local model that works on a 1024³ grid or finer produces millions of raw triangles, which then have to be simplified down to this range (F-018). What decides parity is how much real surface detail a model produces, and what it does at points where parts touch (F-003). Its face count is secondary.

**Confidence:** High (measured by the pipeline).

## F-003 - The main defect is parts fusing into one sealed surface, and higher resolution does not fix it

**Evidence:**
- Each Meshy output is a single closed (watertight) surface. Bones that touch, such as the carpus, tarsus, teeth and a closed mandible, fuse because of how the surface is built, at any resolution. The project calls this a limit of the output format, not of quality (`Assets3D/Docs/Colaboracao/Topicos/creatures-undead-skeletal-mage-00-corpo.md:958`).
- The audited body high has 1,341,366 triangles but only 2 connected components (`Assets3D/Docs/analysis/skeleton-reconstruction-meshy/01-local-diagnosis.md:15-22`).
- The model panel held that Tripo, Rodin, Hunyuan3D 2.x and TRELLIS share the defect, and concluded "do not switch vendor" (`…/07-multi-ai-panel.md:133-138`; `…/creatures-undead-skeletal-mage-00-corpo.md:972`).
- Highs are "dense, fused single surfaces, metal without material ID" (`docs/analysis/assets3d-pipeline/03-bake-settings.md:17`).

**Impact:** The open models that output a signed distance field (Hunyuan3D, TripoSG, Direct3D-S2) describe the whole object with one field, so they are expected to inherit the fusion: where parts touch or overlap, one field cannot keep them apart, and the learned shape prior may also close real gaps narrower than about 2 voxels. One field can still yield separate pieces where a clear gap exists. TRELLIS.2's field-free voxels carry no part labels either ([06](06-model-panel.md), claim 12). Running locally does not fix it. Local generation can still help in two ways. First, generating each part separately costs nothing extra. Second, part-aware tools can be tested freely (F-009, plan phase 4). The pipeline's split by rig unit already limits how many generations it needs (`…/08-hand-workbench.md:80`).

**Confidence:** High that the defect exists. Medium that every alternative shares it: this is the panel's opinion, and nobody has tested it.

## F-004 - Vendor models are retired, so the same input cannot be regenerated later

**Evidence:**
- Meshy's API marks `meshy-7` as deprecated in favour of `meshy-7.1`, and `lowpoly` retires on 2026-10-30 ([image-to-3d API](https://docs.meshy.ai/en/api/image-to-3d)). Meshy-5 was discontinued in August 2026 ([Meshy help](https://help.meshy.ai/en/articles/15697060-meshy-6-vs-meshy-5-which-ai-model-should-you-use)), and the API retired `meshy-5` on 2026-10-10 ([changelog](https://docs.meshy.ai/en/api/changelog)).
- Tripo has no default model: every request must name a dated `model_version` such as `v3.1-20260211`, and leaving it out returns HTTP 400 ([Tripo v3.1](https://developers.tripo3d.com/en/models/v3-1); [v2→v3 migration notes](https://developers.tripo3d.com/assets/developer/tripo-v2-to-v3-migration/SKILL.md)). The H3.1 page itself labels `v3.1-20260211` "Default"; which of the two holds was not tested.
- Assets3D keeps the task id, hashes and downloaded bytes, and never resubmits automatically (`Assets3D/Docs/Pipeline-Guide.md:50`).

**Impact:** The pipeline can only reproduce a vendor high from the bytes it stored. Once the vendor retires the model, the same reference cannot produce the same high again. A local checkpoint pinned by hash, together with the seed and settings, can be run again; GPU non-determinism may still make it not bit-exact. This is a benefit of running locally that is separate from cost.

**Confidence:** High for the retirements. Medium for local repeatability, which has not been tested.
