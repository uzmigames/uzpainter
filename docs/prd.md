# Product Requirements Document — UzPainter v1

Consolidated requirement list. Sources: the owner's requirements (`vision.md`), decision 001 (output parity), decision 002 (Apache-2.0, clean room), the owner's answers of 2026-10-10 (`open-questions.md`), `docs/analysis/assets3d-pipeline/08-requirements-for-uzpainter.md` (its IDs are kept; its rows carry the traces and evidence), and the architecture discussion (`docs/analysis/architecture-discussion/05-resolution.md`). The text of this document is the binding contract: an implementer does not need the source file to find a required behaviour. A row changed by the owner's answers carries its new text and names "owner 2026-10-10" with the question in its Source column; §19 lists every change. Priority: **MUST** = owner requirement, binding pipeline rule, or the pipeline cannot run without it; **SHOULD** = used today on some pieces or avoids a recorded failure; **COULD** = useful, not exercised. "Doc" names the architecture document that satisfies the requirement. Acceptance criteria name the parity tier or test that proves them (`architecture/14-parity-testing.md`).

## 1. Personas

| Persona | Role | What they need |
|---|---|---|
| AI agents (Claude, Codex, others) | The only operators; drive UzPainter through MCP or the Python API, headless or with the read-only preview | Typed tools with reliable results, structured errors, job ids, capability manifest, recipe dumps, captures they can look at |
| The owner | Approves scope, exceptions (there are no preset tolerances), pilots, legal route; watches the preview; signs gates | Recorded answers (`open-questions.md`), parity reports, exception register, decision records |
| Assets3D pipeline scripts | Integration clients (`painter_create.py`, `painter_layer_stack.py`, `painter_export.py`, successors) | The `substance_painter` facade with Painter's documented behaviour; same inputs and outputs as today |
| Downstream consumers | Blender delivery/review scripts, the review panel, UzEngine, Unreal Engine 5.6 | Maps and presets they can consume unchanged, with explicit metadata |

## 2. Owner requirements and acceptance

| ID | Requirement | Priority | Source | Acceptance criterion | Doc |
|---|---|---|---|---|---|
| OWN-01 | UzPainter SHALL provide Substance Painter's functionality (layers, smart materials, rendering, export, Python scripting, native MCP), operated 100 % by AI; no human editing UI; a read-only preview at most; headless/CI as the primary mode. Brush strokes are out of scope because Painter's Python API does not expose them | MUST | Owner 2026-10-09; owner 2026-10-10 (Q5) | Capability manifest shows every output-affecting Painter capability `supported` or an explicit gap (arbitrary `.sbsar`, UV tiles, warp, auto-unwrap and the others stay visible); milestones are named by proven scope and nothing is called a full replacement while a required gap is open; all operations reachable without a GUI | 01, 10, 11 |
| OWN-02 | The render system SHALL be built from UzEngine's rendering code, copied (vendored) from a clean UzEngine commit; UzPainter SHALL have zero dependency on UzEngine: no linking of `runtime.lib`, no pin, no patch queue, no upstream obligation, no submodule | MUST | Owner 2026-10-09; owner 2026-10-10 (Q8) | The vendored render core builds and runs in UzPainter's own build without any UzEngine checkout or artifact; Apache-2.0 headers kept and the source commit recorded in `NOTICE` | 07, 13 |
| OWN-03 | UzPainter SHALL completely replace Substance Painter in the Assets3D pipeline | MUST | Owner; owner 2026-10-10 (Q5, Q7, Q13) | Pilots in the order Wand v1 → Belt v5 → Tunic v10, then the rest of the corpus (bracers, hat v8, body) reproduced with equal maps; the Assets3D "painting is always in Substance" rule amended after Tunic v10 passes its parity gate (G2); no full-replacement claim while a required gap is open; release gate G5 signed | roadmap, 14 |
| OWN-04 | UzPainter SHALL mirror Substance's Python API and MCP structures without inventing unnecessary processes | MUST | Owner | Facade runs the three pipeline scripts unchanged; MCP tools map to the pipeline's calls | 10, 11 |
| OWN-05 | UzPainter SHALL bake from a high-poly mesh (AO, detailed normal and the other mesh maps) like Substance | MUST | Owner | Ten bakers; Tier 2b | 06 |
| OWN-06 | UzPainter SHALL export PBR like Substance plus Unreal's ORM standard and UzEngine's standard, preferably compressed | MUST | Owner; owner 2026-10-10 (Q10) | Presets with consumer fixtures: Unreal Engine 5.6 with PNG/TGA by default and optional DDS BC7/BC5; UzEngine `.uzmat` + compressed `.uztexture` (BC7/BC5/BC4); SpecularWeight reported as a consumer gap | 08 |
| OWN-07 | UzPainter SHALL save progress in a self-contained, portable project file far more compact than `.spp` (baseline 879 MB–1.19 GB for the body) | MUST | Owner; owner 2026-10-10 (Q11) | Size census vs the matched `.spp`; candidate budget 10 % of the matched `.spp`, ratified after the census; retention = current and previous checkpoints plus the last 50 mutation revisions | 09 |
| OWN-08 | UzPainter SHALL ship as a standalone one-folder distribution for Windows 10/11 x64 that anyone can run locally | MUST | Owner; owner 2026-10-10 (Q9) | A clean offline Windows 10/11 x64 machine runs the release folder without Python/Painter/Blender/SDKs; a GPU is required for compositing, preview and path tracing (DX12 primary, Vulkan second backend); no Linux/macOS build | 13 |
| ACC-01 | Given the same instruction sequence, UzPainter SHALL produce the same textures and the same render as Painter at the build of the current oracle envelope (decision 037, which replaces decision 001's pin to 12.1.0): equal native decoded texture values, and a render equal to Painter's Iray output under the fixed render pipeline (decision 038). Exact equality is the rule; every divergence fails unless an owner-approved, versioned exception with evidence covers it; there are no preset tolerances. Iray is stochastic, so pixel-exact render equality is not achievable: the render is compared with converged Iray references and every residual is accepted only through the exception register | MUST | Decision 001; 05-resolution D13; owner 2026-10-10 (Q1, Q2); owner 2026-10-11 (decision 037) | Tiers 0–2 equal; Tier 3 compared with converged Iray references; every divergence covered by a recorded exception | 14 |
| LIC-01 | UzPainter SHALL be released under the Apache License 2.0 (root `LICENSE`, copyright UzmiGames) | MUST | Decision 002 | `LICENSE` present; every source file header compatible | licensing |
| LIC-02 | Every third-party dependency, including the code vendored from UzEngine, SHALL have a confirmed Apache-2.0-compatible licence and be listed with its notice in `NOTICE`/`LICENSES/` | MUST | Decision 002; owner 2026-10-10 (Q8) | Inventory complete; no "not confirmed" entry at release | licensing, 13 |
| LIC-03 | No Adobe binary, asset, preset, capture or documentation text SHALL be linked, bundled or redistributed | MUST | Decision 002 | Repository and release scanned; pre-commit guard | licensing, 14 |
| CLR-01 | Behaviour SHALL be implemented from public documentation and literature plus black-box calibration against Painter outputs; nothing SHALL be copied from Adobe. For the path tracer, NVIDIA's MDL specification and the open-source MDL SDK (BSD-3-Clause) are permitted sources; nothing from Adobe or Iray internals is used | MUST | Decision 002; owner 2026-10-10 (Q2) | Provenance recorded per formula in `parity/semantics/*.json` | licensing, 04, 05, 06, 07 |
| CLR-02 | Contributors and agents SHALL NOT consult Adobe's shipped shader library, shader sources or `.py` sources as implementation sources | MUST | Decision 002 | Review checklist; provenance notes name no off-limits file | licensing |
| CLR-03 | The `substance_painter` facade SHALL mirror the documented API shape only, written from `python-doc` | MUST | Decision 002 | Facade provenance recorded; symbol set matches the public docs | 10 |
| CLR-04 | Documentation SHALL NOT describe the internals of Adobe's confidential or shipped implementation files | MUST | Decision 002 | Doc review | licensing |
| CLR-05 | Painter outputs recorded as oracles, in every form (images, API readbacks, default and template captures, Iray references), SHALL be private test data stored outside the public repository, in the private oracle store on the owner's machine (hashes in-repo, blobs private) | MUST | Decision 002; owner 2026-10-10 (Q2, Q9b) | `parity/` contains no Painter output; private store configured | 14 |
| CLR-06 | Compatibility aliases for Painter asset names SHALL be internal only; shipped assets carry UzPainter names and provenance | MUST | Decision 002 | Asset library inventory | 05 |

## 3. Governance (G)

| ID | Requirement | Priority | Source | Acceptance criterion | Doc |
|---|---|---|---|---|---|
| G-01 | Amend the Assets3D governance text ("painting is always in Substance Painter") to the replacement decision after Tunic v10 passes its parity gate | SHOULD | 08 §0; owner 2026-10-10 (Q13) | Text amended once G2 is signed | roadmap |
| G-02 | Support the approved paint standard as a first-class workflow (imported 3D masks, swatches, uniform fills with one bitmap mask each, grouped by material, Height at three scales) | MUST | 08 §0 | Tunic v10 Tier 1 | 04, 10 |
| G-03 | Migrate approved deliveries with proof: rebuilt from recipes through Painter's documented API while Painter is installed, with per-layer resource bytes and overrides, and equal maps and renders; no `.spp` reader; Painter is a temporary reference only | MUST | 08 §0; owner 2026-10-10 (Q6) | Tunic v10 dump-and-rebuild equal | 03, 14 |
| G-04 | Output-parity protocol: record reference build, instruction sequence, inputs, effective defaults, channel math and render state; compare decoded textures, encoded bytes and renders separately; no preset tolerance: a divergence passes only through an owner-approved exception with evidence in the exception register | MUST | 08 §0; owner 2026-10-10 (Q1) | `parity/CONTRACT.md`, golden manifests | 14 |

## 4. Project (PRJ)

| ID | Requirement | Priority | Source | Acceptance criterion | Doc |
|---|---|---|---|---|---|
| PRJ-01 | Create a project from a triangulated low-poly OBJ preserving corners, winding and materials without re-triangulation, welding, normal recomputation or UV repacking; verify after import | MUST | 08 §1.1 | Import fixtures; corner hashes equal source | 12 |
| PRJ-02 | One texture set per mesh material; several sets per project; single 0–1 tile per set (UV tiles are a release gap) | MUST | 08 §1.1 | Body v6b three sets | 03, 12 |
| PRJ-03 | Per-set resolution 2048 and 4096 (8192 SHOULD) | MUST / SHOULD | 08 §1.1 | VRAM admission test | 03 |
| PRJ-04 | OpenGL (+Y) normal convention for the Assets3D contract; MikkTSpace per-fragment frame validated by a fixture; engine conversions per preset | MUST | 08 §1.1 | Phase 0 normal fixture | 12, 08 |
| PRJ-05 | Colour management fixed at creation and recorded: linear working space, sRGB inputs/outputs for colour channels, raw data channels | MUST | 08 §1.1 | Tier 0 colour goldens | 03, 04 |
| PRJ-06 | Channels BaseColor, Roughness, Metallic, Height, Normal, SpecularWeight (per set), double-sided flag; storage format recorded | MUST | 08 §1.1 | Hat v8 Tier 1 | 03 |
| PRJ-07 | Physical units preserved and effective projection units recorded | MUST | 08 §1.1 | Tier 0 projection goldens | 12, 04 |
| PRJ-08 | Mesh reload preserving the stack, reporting changed regions, invalidating dependent maps and evidence | MUST | 08 §1.1 | Reload fixtures | 12 |
| PRJ-09 | Import validation that flags (never repairs) degenerate TBN, coincident faces, flipped/zero UV triangles, UVs outside 0–1 | MUST | 08 §1.1 | Certificate fixtures | 12 |
| PRJ-10 | Per-set UV certificate (overlap, density, anisotropy, measured gap/border); no repacking | MUST | 08 §1.1 | Certificate fixtures | 12 |

## 5. Mesh maps and bake (BAK)

| ID | Requirement | Priority | Source | Acceptance criterion | Doc |
|---|---|---|---|---|---|
| BAK-01 | Accept external mesh maps per set (16-bit normal/AO at least; curvature, WSN, position, thickness) with role and provenance | MUST | 08 §1.2 | Wand v1 Tier 1 | 06, 03 |
| BAK-02 | Provide the generator mesh maps with recorded algorithm, source role and effective normalisation; never silently auto-rescale | MUST | 08 §1.2 | Tier 2b bounds recorded | 06 |
| BAK-03 | Native high-poly bake with Painter's settings (highs per set, cage/distance, match by name, subsampling, dilation, backface, units) | MUST | 08 §1.2; Owner | Tier 2b | 06 |
| BAK-04 | AO miss evidence from ray hits (second wider pass SHOULD) | MUST / SHOULD | 08 §1.2 | Evidence maps in bake receipts | 06 |
| BAK-05 | Bake and other long operations as jobs with unique ids and unambiguous terminal status | MUST | 08 §1.2 | Job tests | 02, 06 |
| BAK-06 | Provenance on every mesh map; mesh/UV/normal changes invalidate it and downstream gates | MUST | 08 §1.2 | Reload fixtures | 03 |
| BAK-07 | Bake surface accounting and lineage: keep RAW; record straight and cage hits separately, pixel-centre and conservative used-surface coverage, centre misses, ring extensions, hidden-flat texels, fallbacks, padding and any repair; count every changed used texel; bind parts, highs, cages and tool versions. A low normal Z is an inspection signal, not permission to replace values; counts never grant visual approval | MUST | 08 §1.2 | Receipt fields published (`06-baking.md` §4); accounting and conservation checked on an analytic fixture, not only schema validity | 06 |
| BAK-08 | One corrected AO per set feeds generators, delivery and albedo layers; exported for glTF occlusion | MUST | 08 §1.2 | Hat v8 fixture | 06, 08 |

## 6. Layers and stack (LAY)

| ID | Requirement | Priority | Source | Acceptance criterion | Doc |
|---|---|---|---|---|---|
| LAY-01 | Fill layers with uniform values per channel; active flags that never reset values in the native API; effective values readable | MUST | 08 §1.3 | Tier 0 API probes | 04, 10 |
| LAY-02 | Bitmap BaseColor fill in final-UV space (sRGB, UV projection, scale 1, no repeat, BilinearHQ) | MUST | 08 §1.3 | Belt v5 Tier 1 | 04 |
| LAY-03 | Nested groups with optional mask; per-group Height blend override; effective Height blend readable | MUST | 08 §1.3 | Tunic v10 Tier 1 | 04 |
| LAY-04 | Layer masks: background, bitmap fill effect, Levels, subtraction, sharpen; mask opacity and blend; ordered typed effects | MUST | 08 §1.3 | Tier 0 mask goldens | 04 |
| LAY-05 | Per-channel opacity and the documented blend modes with Painter's exact semantics | MUST | 08 §1.3 | Tier 0 blend goldens exact | 04 |
| LAY-06 | Stable persistent layer identities (they survive save/reopen) and name-based addressing. Name-addressed operations are idempotent within an explicit project/set/stack/parent scope; an ambiguous match fails before mutation; repeating the same named operation creates no duplicate node. Painter's own UIDs are stable only within one project | MUST | 08 §1.3 | Save/reopen tests; ambiguous-name and repeated-operation tests | 03, 10 |
| LAY-07 | Declarative stack sync from the existing stack JSON (`title`, `groups`, `layers`; fields `base`, `base_tex`, `rough`, `metal`, `spec`, `height`, `op`, `mask`), loaded without editing it: rebuild only the named group; hide, never delete, the other root groups unless an explicit supported option keeps them visible; migration differences are explicit per-layer overrides, never a global filename replacement | MUST | 08 §1.3 | Scripts run unchanged; tunic bindings; unrelated roots and resources survive and only the addressed group is rebuilt | 10, 11 |
| LAY-08 | Replace a mask/bitmap resource in place on a node instance without rebuilding | MUST | 08 §1.3 | API probe | 04, 10 |
| LAY-09 | Visibility toggle and per-layer contribution diagnostics restoring prior state | MUST | 08 §1.3 | Diagnostics tests | 04 |
| LAY-10 | Defined base under complementary masks; no unintended default bleed | MUST | 08 §1.3 | Tier 0 base-value goldens | 04 |
| LAY-11 | Portable smart-material folders with identical parameters and resources | MUST | 08 §1.3 | Bracer fixture | 05 |
| LAY-12 | Paint layers and paint effects driven through the API as layers that receive bitmaps and projections; no human editing UI. Brush strokes are out of scope because Painter's Python API does not expose them; no stroke engine is built | MUST | 08 §1.3; owner 2026-10-10 (Q5) | Tier 0 goldens for paint layers and paint effects receiving bitmaps and projections (Phase 4) | 10, roadmap |
| LAY-13 | Per-node resource bindings by content hash so same-named masks can differ | MUST | 08 §1.3 | Tunic C07/F03 | 03, 04 |
| LAY-14 | Material isolation diagnostics in every authored channel | MUST | 08 §1.3 | Diagnostics tests | 04 |

## 7. Materials and procedural sources (MAT)

| ID | Requirement | Priority | Source | Acceptance criterion | Doc |
|---|---|---|---|---|---|
| MAT-01 | Triplanar projection with physical-unit scale and normal-weighted blending | MUST | 08 §1.4 | Tier 0 projection goldens | 04 |
| MAT-02 | Mesh-map generators (edge wear, cavity dirt, ground dirt/dust) with Painter's parameters; those used by delivered/locked recipes evaluate identically | MUST | 08 §1.4 | Tier 2a exact or exception | 05 |
| MAT-03 | Exact evaluation of the procedural sources used by recorded recipes (generic noise library SHOULD) | MUST / SHOULD | 08 §1.4 | Tier 2a | 05 |
| MAT-04 | Identical evaluation of the starter assets used by locked/delivered recipes, via UzPainter's own certified implementations | MUST | 08 §1.4; Decision 002 | Tier 2a; bracer r9 Tier 1 | 05 |
| MAT-05 | Height in declared units with the height→normal conversion reproduced | MUST | 08 §1.4 | Tier 0 height goldens | 04 |

## 8. Resources (RES)

| ID | Requirement | Priority | Source | Acceptance criterion | Doc |
|---|---|---|---|---|---|
| RES-01 | Import 16-bit grayscale masks and 8/16-bit sRGB textures as embedded, content-deduplicated resources | MUST | 08 §1.5 | Store tests | 03, 09 |
| RES-02 | Resource identifiers valid across sessions and machines | MUST | 08 §1.5 | Save/reopen on another machine | 03 |
| RES-03 | Environments stored as bytes plus hash; missing resource is an explicit error | MUST | 08 §1.5 | Display preset tests | 03, 07 |
| RES-04 | Procedural asset versions pinned inside the project | MUST | 08 §1.5 | Reopen reproduces evaluation | 03, 05 |

## 9. Export (EXP)

| ID | Requirement | Priority | Source | Acceptance criterion | Doc |
|---|---|---|---|---|---|
| EXP-01 | Export per set: BaseColor, Roughness, Metallic, Height, combined Normal, geometry-only normal, SpecularWeight, AO | MUST | 08 §1.6 | Tier 1 | 08 |
| EXP-02 | PNG 16-bit (8-bit SHOULD), per-export resolution, infinite padding, no dithering, checked on decoded pixels | MUST / SHOULD | 08 §1.6 | Tier 0 export goldens | 08 |
| EXP-03 | Configurable naming reproducing the patterns in use, with collision checks | MUST | 08 §1.6 | Plan tests | 08 |
| EXP-04 | Export of any channel, mesh map, mask, isolated layer and unlit BaseColor | MUST | 08 §1.6 | Diagnostics tests | 08, 04 |
| EXP-05 | Same build ⇒ identical decoded pixels and bytes (cross-session/machine identity SHOULD) | MUST / SHOULD | 08 §1.6 | Repeatability lane | 08, 14 |
| EXP-06 | Atomic, verified export with paths, sizes and hashes; last delivery kept on failure; host never dies | MUST | 08 §1.6 | Fault injection at every publication step: files and receipt go to a new generation directory published by one atomic pointer update, so consumers see the old or the new complete delivery. Every supported consumer reads one complete published generation; a fixed-name consumer runs through a delivery adapter that pins that generation, or under a coordinated publication lock that completes recovery before consumption and excludes writers for the entire read. Staging filenames are never advertised as a committed delivery; a raw fixed-name directory updated by separate copies is not an atomic delivery and does not satisfy this requirement. Interrupting each fixed-name copy and immediately invoking the supported consumer through its prescribed adapter yields one complete generation or a failure before consumption | 08, 02 |
| EXP-07 | Opacity/alpha channel and export capability (asset adoption SHOULD) | MUST / SHOULD | 08 §1.6 | Tier 0 alpha goldens | 08 |
| EXP-08 | Presets: Unreal ORM for Unreal Engine 5.6 (PNG/TGA by default, optional DDS BC7/BC5), UzEngine standard (`.uzmat` + compressed `.uztexture`), Painter-equivalent PBR (glTF metallic-roughness SHOULD); a channel the consumer cannot bind (SpecularWeight) is exported and reported as a consumer gap | MUST / SHOULD | 08 §1.6; Owner; owner 2026-10-10 (Q10) | Consumer fixtures: UE 5.6, the external UzEngine fixture, glTF | 08 |
| EXP-09 | Authored relief applied exactly once; normals tagged geometry-only or combined | MUST | 08 §1.6 | Receipt tags; adapter refusal test | 08, 04 |
| EXP-10 | Explicit engine format and binding metadata per map; no filename heuristics; signed normals kept at authoring precision | MUST | 08 §1.6 | `.uztexture` fixture; receipt schema | 08 |

## 10. Save and recipe (SAV)

| ID | Requirement | Priority | Source | Acceptance criterion | Doc |
|---|---|---|---|---|---|
| SAV-01 | Single self-contained, portable project file with dependency closure, compact (candidate budget 10 % of the matched `.spp`, ratified after the census); `save`, `save_as`, `open`, `close`; exact dirty flag; no silent discard | MUST | 08 §1.7; owner 2026-10-10 (Q11) | Store tests; census | 09 |
| SAV-02 | Checkpoint after each step; the current and previous checkpoints plus the last 50 mutation revisions retained; approved baseline never overwritten | MUST | 08 §1.7; owner 2026-10-10 (Q11) | Revert and retention tests | 09 |
| SAV-03 | Machine-readable recipe dump with deterministic digest | MUST | 08 §1.7 | Dump schema tests | 03 |
| SAV-04 | Rebuild from recipe + resources with identical exports | MUST | 08 §1.7 | Tunic v10 rebuild | 03, 14 |
| SAV-05 | Autosaves and lock files configurable and cleaned on close | SHOULD | 08 §1.7 | Store tests | 09 |

## 11. Preview, capture, diagnostics (VIS, DIA)

| ID | Requirement | Priority | Source | Acceptance criterion | Doc |
|---|---|---|---|---|---|
| VIS-01 | Read-only live viewer capability; opening it optional; no mouse/keyboard needed | MUST | 08 §1.8 | Preview window never pauses evaluation | 07 |
| VIS-02 | Native headless capture reflecting the latest state with explicit camera/resolution/convergence | MUST | 08 §1.8 | Capture receipts | 07 |
| VIS-03 | Preview modes: lit, unlit BaseColor, single channel, mask/ID | MUST | 08 §1.8 | Capture modes tested | 07 |
| VIS-04 | Serialisable display preset implementing the common standard and `ref_match`, separate from presentation snapshots | MUST | 08 §1.8 | Preset round-trip | 07 |
| VIS-05 | Camera import/export in the Blender convention | MUST | 08 §1.8 | Conversion fixture | 07 |
| VIS-06 | Render output equal to Painter's Iray output for the same state under the fixed render pipeline (the Assets3D render comparison standard: v2 common block, `ref_match` v3, `base_color` diagnostic; decision 038), produced by UzPainter's clean-room path tracer (DX12 DXR primary, Vulkan ray tracing second backend). Every other Iray or display setting is pinned, not a supported variable (decision 042). References are converged Iray renders captured on the owner's machine into the private oracle store, with the same scene and camera, the environment and render settings set by that pipeline and its per-view variations, and Iray at min = max = 256 samples; Iray's seed is not exposed and is `uncontrolled` (decision 039). Iray is stochastic: pixel-exact equality is not achievable, so the comparison uses converged references and every residual passes only through an owner-approved exception (Q1). The realtime viewport is the human preview and a fast check, not the parity target | MUST | 08 §1.8; Decision 001; owner 2026-10-10 (Q1, Q2); owner 2026-10-11 (decision 038) | Tier 3 against converged Iray references, with the oracle's measured noise floor and recorded exceptions | 07, 14 |
| DIA-01 | Paint-gate evidence access (faithful maps and masks for region statistics; native statistics SHOULD) | MUST / SHOULD | 08 §1.8 | `region_stats` tests | 04, 11 |
| DIA-02 | Relief evidence access (geometry-only and combined normals, material masks) | MUST | 08 §1.8 | Export tests | 08 |

## 12. Integration (INT)

| ID | Requirement | Priority | Source | Acceptance criterion | Doc |
|---|---|---|---|---|---|
| INT-01 | Native MCP (stdio) plus in-process Python API; structured results with reliable error flags; CLI non-zero exit on failure | MUST | 08 §2.1 | Tool/CLI tests | 11, 10 |
| INT-02 | MCP tools covering the calls the pipeline makes today: status/project info; create (mesh, settings, mesh maps, colour management); open/close/save/save_as; list texture sets; import resource; set mesh maps; stack sync from JSON; smart materials and procedural layers; get/set layer properties; replace mask resource; snapshot/recipe dump; export (preset or inline config); capture; mesh reload; bake + job status; per-layer isolation | MUST | 08 §2.1; owner 2026-10-10 (Q12) | Belt round through MCP only with Python disabled (integration smoke test); at release, a requirement-to-typed-operation matrix and a Python-disabled conformance fixture for every required operation family, including native bake, mesh reload, the later node/effect/source kinds and every export target | 11 |
| INT-03 | Filesystem roots allowlist on canonical paths; Windows paths handled | MUST | 08 §2.1 | Path tests | 11 |
| INT-04 | Single writer per project; conflicts rejected, never crashes | MUST | 08 §2.1 | Lease tests | 02, 11 |
| INT-05 | Explicit busy state; timeouts fail explicitly | MUST | 08 §2.1 | Busy tests | 02, 11 |
| INT-06 | Batch execution with stop-on-error and per-call results | SHOULD | 08 §2.1 | `batch` tool tests | 11 |
| INT-07 | Target identity on every operation/result (project, set, round, job, revision); preview never pauses evaluation | MUST | 08 §2.1 | Receipt schema | 02, 03 |
| INT-10 | Accept today's inputs (low OBJ, high OBJ, PNG16 maps/masks, sRGB textures, stack JSON) with explicit metadata | MUST | 08 §2.2 | Wand/belt fixtures | 12, 10 |
| INT-11 | Exported maps consumable by the current consumers with their script code unchanged (each consumer's host adapter and invocation requirements, EXP-06, are part of its fixture), tested on each: staff `deliver.py` (four maps), hat `deliver_v8.py` (AO in the glTF occlusion slot; SpecularWeight loaded, its Blender link commented out), `glb_add_specular.py`, `render_pbr_asset.py`, `paintrender*.py`, `blender_render_standard.py` and the review panel (through a Blender-built GLB) | MUST | 08 §2.2 | Consumer matrix in `08-export.md`: each row names the script and version, the fixture (including its delivery adapter or publication-lock invocation) and the expected channel/precision/metadata bindings; every row runs | 08 |
| INT-12 | Image orientation convention documented and verified | MUST | 08 §2.2 | Directional fixture | 12 |
| INT-13 | Mesh maps exportable back to Python tools at stated precision and normalisation | MUST | 08 §2.2 | Export tests | 08, 06 |
| INT-14 | glTF/FBX mesh import | COULD | 08 §2.2 | Fixtures | 12 |
| INT-20 | `painter_recipe`-equivalent JSON block with defaults, evaluator version and content identity | MUST | 08 §2.3 | Dump schema | 03 |
| INT-21 | Manifest `exportacao` block fields per export | MUST | 08 §2.3 | Receipt schema | 08 |
| INT-22 | Project file and maps hashable and registrable; native project type identified | MUST | 08 §2.3 | Receipt schema | 09 |
| INT-23 | Library recipes replayed through adapters with explicit overrides, tested | MUST | 08 §2.3 | Recipe replay tests | 10 |

## 13. Quality gates (QG)

| ID | Requirement | Priority | Source | Acceptance criterion | Doc |
|---|---|---|---|---|---|
| QG-01 | Paint-gate evidence cheap to produce; evidence does not grant approval | MUST | 08 §3 | Capture/diagnostic tools | 07, 08 |
| QG-02 | Production adapter refuses rounds whose upstream gates did not pass; diagnostic imports flagged | MUST | 08 §3 | Adapter tests | 12, roadmap |
| QG-03 | Never report success on partial results; no-op distinguished from failure | MUST | 08 §3 | Result schema tests | 03, 11 |
| QG-04 | Records technical facts only; never grants artistic approval | MUST | 08 §3 | Doc/API review | 03 |
| QG-05 | Approved-state protection and scoped invalidation | MUST | 08 §3 | Protected checkpoint tests | 09 |

## 14. Non-functional (NFR)

| ID | Requirement | Priority | Source | Acceptance criterion | Doc |
|---|---|---|---|---|---|
| NFR-01 | Fully headless on Windows 10/11 x64 for CI/batch (no window, no focus); opening the live viewer is optional | MUST | 08 §4; owner 2026-10-10 (Q9, Q9b) | Local CPU lane (decision 200) and the local GPU run on the owner's machine (decision 028), both without a window | 02, 13, 14 |
| NFR-02 | Determinism: identical inputs + recipe + seed + resources + build ⇒ identical exports | MUST | 08 §4 | Repeatability lane | 14 |
| NFR-03 | Scale, supported for each recorded workload separately: three 4096² texture sets in one project; 30–45-layer stacks; more than twenty 4K 16-bit masks; up to seven delivered maps per set. A combined worst case is a proposed stress fixture, not an observed baseline | MUST | 08 §4 | Body v6b (sets), bracer 21 and hat v8 (layers), hat v6 (masks), hat v8 (maps), each measured separately | 04, 13 |
| NFR-04 | Compact project file; candidate budget 10 % of the matched `.spp`, ratified after the census | MUST | 08 §4; owner 2026-10-10 (Q11) | Census report | 09 |
| NFR-05 | Speed targets set after equal outputs, measured on a fixed corpus | SHOULD | 08 §4 | Phase 5 budgets | roadmap |
| NFR-06 | Robustness: failing jobs isolated; last checkpoint intact | MUST | 08 §4 | Fault injection | 02, 09 |
| NFR-07 | Offline operation | SHOULD | 08 §4 | Clean offline machine | 13 |
| NFR-08 | Version pinning of resources and evaluator in every project and export | MUST | 08 §4 | Manifest fields | 03, 09 |

## 15. Architecture-derived requirements (ARC)

| ID | Requirement | Priority | Source | Acceptance criterion | Doc |
|---|---|---|---|---|---|
| ARC-01 | Supervisor/worker topology: the client-launched process never initialises a GPU; the MCP session survives a worker fault; recovery to the last committed revision | MUST | 05-resolution D1 | Kill/stall tests | 02 |
| ARC-02 | Idempotency keys and revision preconditions on every mutation. Each mutating transaction persists `{project_uuid, idempotency_key, request_hash, outcome, committed_revision}` in the same project-store transaction as its revision; after a restart the supervisor reconciles its ledger from these records before admitting a retry; reusing a key with different arguments is rejected; an unresolved outcome is never treated as a new mutation; no silent replay; receipts name the committed revision | MUST | D1, D10 | Lost-acknowledgement tests with a failure injected after the durable commit and before the acknowledgement; retry of the same request and of a changed request with the same key | 02, 09, 11 |
| ARC-03 | Capability manifest with statuses supported / desktop-only-omitted / release-gap; omitted symbols raise; nothing is silently a no-op | MUST | D2 | Manifest generated and tested | 10 |
| ARC-04 | Evaluator profile (quantisation and colour-space rules) selected by Tier 0 and versioned in every project and golden | MUST | D3 | Profile recorded; old projects re-evaluable | 04, 09 |
| ARC-05 | Procedural backend seam with per-asset parity status; no silent substitution of a similar asset | MUST | D4 | Asset library tests | 05 |
| ARC-06 | `painter_iray`, a clean-room path tracer on DX12 DXR (primary) and Vulkan ray tracing (second backend), is the render-parity target against converged Iray references captured on the owner's machine; the realtime `painter_viewport` is the human preview and a fast check, never parity evidence; the UzEngine preset is validated by an external UzEngine consumer fixture | MUST | D6; owner 2026-10-10 (Q2, Q8) | Tier 3 with the oracle noise floor and recorded exceptions | 07 |
| ARC-07 | Vendoring policy: the render core is copied from a clean UzEngine commit, never from files of an in-progress merge; Apache-2.0 headers kept, attribution and source commit recorded, local modifications marked; known defects (glTF 32/48 stride) fixed in the copy or the path avoided; no link, pin, patch queue, upstream obligation or submodule | MUST | D12; owner 2026-10-10 (Q8) | Origin record and `NOTICE` entry; the build references no UzEngine path or artifact | 13 |
| ARC-08 | Own build, Zig-first unless the vendored subset dictates otherwise, with Phase 0 qualification of the CPython/Embree boundaries and a documented fallback | MUST | D12; owner 2026-10-10 (Q8) | `selftest` | 13 |
| ARC-09 | Goldens recorded by UzmiGames recorder scripts through Painter's documented API for state and through a qualified, documented capture procedure for pixels (Iray settings the API does not expose are read from Painter's settings panel and recorded); never through the community bridge or a private interface; stored in the private oracle store on the owner's machine | MUST | D13; 08-review-response; owner 2026-10-10 (Q2, Q9b) | Recorder provenance; capture procedure qualified in Phase 0 | 14, 07 |
| ARC-10 | Exception register: a non-zero difference passes only through an owner-approved, versioned exception with evidence and a defect-detection test; no preset tolerances; every Tier 3 residual against converged Iray references goes through it | MUST | D13; owner 2026-10-10 (Q1, Q2) | `parity/exceptions.json` | 14 |
| ARC-11 | Every result (export, capture, bake, dump) carries revision, evaluator profile, compatibility profile, build and resource hashes | MUST | D3, D7 | Receipt schema | 03 |
| ARC-12 | Project store: SQLite container with canonical JSON manifest, content-addressed blobs, incremental transactional commits, closed portable files | MUST | D8 | Store tests | 09 |
| ARC-13 | The facade reproduces Painter's observable quirks that change output; the native API may be safer; both documented | MUST | D9 | Tier 0 quirk goldens | 10 |
| ARC-14 | Typed MCP operation families cover every required operation; `run_python` is a trusted opt-in registered only with `--allow-python` | MUST | D10; owner 2026-10-10 (Q12) | Requirement-to-typed-operation matrix; a Python-disabled conformance fixture for every required operation family; belt round with Python disabled | 11, 10 |

## 16. Non-goals

Human editing UI; brush strokes and any stroke engine (Painter's Python API does not expose strokes; owner Q5); `.spp` reading/writing (migration rebuilds through Painter's documented API; Q6); `.sbsar` execution or any Adobe binary (arbitrary `.sbsar` content stays a visible gap in the capability manifest); anything taken from Adobe or Iray internals; redistribution of Adobe content; any build or run-time dependency on UzEngine (Q8); Linux and macOS builds for now (Q9); replacing the non-painting Assets3D stages (`vision.md`). Iray output is not a non-goal: it is the render-parity target (Q2, VIS-06, ARC-06).

## 17. Constraints

Windows 10/11 x64 only for now (owner Q9); DX12 primary (SM6.6 for compositor and viewport, DXR for the path tracer) and Vulkan as the second backend on Windows (Vulkan ray tracing for the path tracer); a GPU is required for compositing, preview and path tracing; CPU baking runs on the Windows/CPU/ISA configurations qualified for the pinned Embree build, unsupported configurations receive an explicit capability error, and cross-machine repeatability is measured separately; render core vendored from a clean UzEngine commit with zero dependency on UzEngine (Q8); own build, Zig-first unless the vendored subset dictates otherwise; Apache-2.0 and clean room (LIC, CLR); private oracle store on the owner's machine with the licensed Painter, where GPU and oracle checks run locally (Q9b, decision 028; there is no hosted CI, the CPU lane also runs locally, decision 200); one-folder distribution; no network dependency at run time.

## 18. Release criteria for v1

Release is gated by evidence, not by date: roadmap durations are labelled Hypotheses and revised at each gate (owner Q14). Packaging verification and the final parity report refer to the same immutable build hash and dependency lock.

1. Tiers 0–2 equal in a local run on the owner's machine (decision 028) for the certified corpus (wand, belt, tunic v10, bracer r9, hat v8, body v6b), and Tier 3 compared with converged Iray references; every divergence, including every Tier 3 residual, covered by a recorded owner exception; the exception register published.
2. Capability manifest published; every in-scope, output-affecting Painter capability is `supported` or covered by an explicit owner scope decision (reporting a gap is not accepting it); brush strokes are out of scope; nothing is called a full replacement while a required gap is open (Q5).
3. The three pipeline scripts run unchanged under `UzPainter.exe run`; the belt round completes through MCP with Python disabled; the requirement-to-typed-operation matrix and a Python-disabled conformance fixture cover every required operation family (Q12).
4. Worker-fault recovery, lost-acknowledgement retry (including a failure after the durable commit and before the acknowledgement) and project-store fault injection pass.
5. Export presets validated by their consumers (the INT-11 Blender/panel matrix, Unreal Engine 5.6, the external UzEngine consumer fixture, glTF) with SpecularWeight and any other consumer gaps reported (Q10).
6. Compact-save census reported against the matched `.spp` and the budget ratified (candidate 10 %; Q11).
7. One-folder distribution runs on a clean offline Windows 10/11 x64 machine; `LICENSE`, `NOTICE` (including the UzEngine attribution) and `LICENSES/` complete; no Adobe content in repository or release.
8. Git history recreated clean before the repository is made public: the private repository's first commit contains pre-sanitisation text, so the history is rebuilt without it at that moment (owner 2026-10-10).
9. Release gate G5 signed by the owner (`roadmap.md`), after the Assets3D governance text was amended once Tunic v10 passed G2 (`P3-CUTOVER`, Q13).

## 19. Changes recorded on 2026-10-10

| Source | Requirements changed |
|---|---|
| Owner Q1 (exact equality, exceptions only through the register, no preset tolerances) | ACC-01, G-04, VIS-06, ARC-10 |
| Owner Q2 (Iray is the render-parity target; clean-room path tracer on DXR and Vulkan RT; converged references) | ACC-01, CLR-01, CLR-05, VIS-06, ARC-06, ARC-09, ARC-10, §16 |
| Owner Q5 (brush strokes out of scope; milestones named by proven scope) | OWN-01, OWN-03, LAY-12, §16, §18 item 2 |
| Owner Q6 (rebuild through the documented API; no `.spp` reader) | G-03, §16 |
| Owner Q7 (Wand v1 → Belt v5 → Tunic v10) | OWN-03 |
| Owner Q8 (zero dependency on UzEngine; vendored render core; own build) | OWN-02, LIC-02, ARC-06, ARC-07, ARC-08, §16, §17 |
| Owner Q9, Q9b (Windows 10/11 x64; DX12 + Vulkan; oracle store and local GPU/oracle runs on the owner's machine, hosted CI CPU-only — decision 028) | OWN-08, CLR-05, NFR-01, ARC-09, §17 |
| Owner Q10 (UE 5.6, UzEngine `.uzmat`/`.uztexture`, SpecularWeight consumer gap) | OWN-06, EXP-08, §18 item 5 |
| Owner Q11 (portable file, 10 % candidate budget, retention) | OWN-07, SAV-01, SAV-02, NFR-04, §18 item 6 |
| Owner Q12 (`run_python` only with `--allow-python`; typed MCP covers every required operation) | INT-02, ARC-14, §18 item 3 |
| Owner Q13 (governance text amended after Tunic v10 passes G2) | G-01, OWN-03, §18 item 9 |
| Owner Q14 (durations are Hypotheses) | §18 |
| Owner, repository history | §18 item 8 |
| Astra final review (`docs/analysis/reviews/docs-set-astra-review.md`): source text and proof obligations restored | LAY-06, LAY-07, BAK-07, INT-02, INT-11 (F15); NFR-03 (F23); ARC-02 (F08); EXP-06 (F11); CLR-05 (F03); §17 CPU baking (F22); §18 gate rule (F14) |

## 20. Changes recorded on 2026-10-11

| Source | Requirements changed |
|---|---|
| Owner, fixed render pipeline (decision 038; scope of display, facade and material model, decision 042) | ACC-01, VIS-06 |
| Owner, rolling Painter oracle (decision 037: acceptance follows the build of the current oracle envelope) | ACC-01 |
