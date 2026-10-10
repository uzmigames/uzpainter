# Astra final review of the UzPainter documentation set

## Executive summary

1. **Verdict: REJECT for archival as the final build contract; resubmit after correction.**
2. **23 findings: 3 blockers, 15 major, 5 minor.** Counts are unique findings; the document table counts affected documents.
3. The supervisor/worker, SQLite/JSON, Zig-first, asynchronous facade and explicit owner-exception decisions are reflected in the architecture.
4. The five original disagreements are resolved in architectural principle; that does not certify the remaining contracts or clean-room compliance.
5. Blockers concern publishable preset provenance, prohibited implementation-detail prose and public exposure of recorded oracle data.
6. The DAG has 40 unique, correctly formatted task IDs and 60 edges; it is acyclic, but required acceptance dependencies are missing.
7. All 91 pipeline rows with a MUST component retain their IDs and MUST priority; several normative clauses and acceptance obligations were abbreviated.
8. Root `LICENSE` is a complete Apache-2.0 license with a UzmiGames notice; dependency closure is not yet fully inventoried.
9. Phase 0 has useful experiments and artifacts, but its entry/gates, approved source set and private-data boundary need the corrections below.
10. Review was read-only except for this report: no application/build/test execution, bridge operation, Adobe-internal inspection or Assets3D post.

## Document verdicts

**Scope and counting.** All 24 requested files were reviewed. A01–A14 below are citation aliases for the full paths in this table; other aliases work the same way. A finding can affect several documents and is counted once in each applicable row, so column totals are not global finding totals. “Approve” means no separate correction identified in that file, not that software has been implemented or tested. Severity means: **blocker** prevents accepting the final set under an explicit owner rule; **major** changes behavior, acceptance, recovery, dependency closure or execution order; **minor** corrects scope wording or traceability without changing the chosen architecture.

Paths are relative to `E:/UzmiGames/UzPainter` unless stated otherwise. `UZE` denotes `E:/UzmiGames/UzEngine` in the non-Adobe dependency-license evidence.

| Document | Verdict | Blocker | Major | Minor |
|---|---|---:|---:|---:|
| README — `docs/README.md` | Approve with corrections | 0 | 2 | 1 |
| VISION — `docs/vision.md` | Approve with corrections | 0 | 1 | 0 |
| PRD — `docs/prd.md` | Approve with corrections | 0 | 2 | 2 |
| LIC — `docs/licensing-and-clean-room.md` | Approve with corrections | 0 | 2 | 0 |
| ROAD — `docs/roadmap.md` | Approve with corrections | 0 | 3 | 1 |
| DAG — `docs/dag.md` | Approve with corrections | 0 | 4 | 0 |
| QUEST — `docs/open-questions.md` | Approve with corrections | 0 | 0 | 1 |
| INDEX — `docs/analysis/README.md` | Approve with corrections | 0 | 1 | 0 |
| A01 — `docs/architecture/01-overview.md` | Approve with corrections | 0 | 0 | 1 |
| A02 — `docs/architecture/02-runtime-topology.md` | Approve with corrections | 0 | 2 | 0 |
| A03 — `docs/architecture/03-project-model.md` | Reject | 1 | 1 | 0 |
| A04 — `docs/architecture/04-layer-stack-and-compositing.md` | Approve | 0 | 0 | 0 |
| A05 — `docs/architecture/05-procedural-content.md` | Reject | 1 | 0 | 0 |
| A06 — `docs/architecture/06-baking.md` | Reject | 1 | 1 | 1 |
| A07 — `docs/architecture/07-preview-and-render-parity.md` | Approve with corrections | 0 | 1 | 1 |
| A08 — `docs/architecture/08-export.md` | Approve with corrections | 0 | 2 | 0 |
| A09 — `docs/architecture/09-project-file-format.md` | Reject | 1 | 2 | 0 |
| A10 — `docs/architecture/10-python-api.md` | Approve with corrections | 0 | 3 | 0 |
| A11 — `docs/architecture/11-mcp-server.md` | Approve with corrections | 0 | 2 | 0 |
| A12 — `docs/architecture/12-mesh-import.md` | Approve | 0 | 0 | 0 |
| A13 — `docs/architecture/13-engine-integration.md` | Approve with corrections | 0 | 3 | 0 |
| A14 — `docs/architecture/14-parity-testing.md` | Reject | 1 | 1 | 0 |
| RESOLUTION — `docs/analysis/architecture-discussion/05-resolution.md` | Reject | 1 | 0 | 2 |
| LICENSE — `LICENSE` | Approve | 0 | 0 | 0 |

## Findings

### F01 — Blocker — Observing a preset is not sufficient provenance for a shipped replacement asset

**Documents:** A05 §3, especially line 34; RESOLUTION D4.

**Evidence:** the prescribed process takes preset structures and parameter collections observed through the reference API and describes the resulting public JSON as newly authored UzmiGames content. The observation method is permitted; the transition from observed asset content to independently authored distributable content is not established. Decision 002 permits behavioral reproduction and private oracles, while LIC §§1–2 forbids copying or redistributing Adobe assets/data. An API access path, renamed identifiers or a different serialization do not themselves establish independent authorship. This is a contradiction within the adopted route, not a request to reopen the rejected route.

**Exact replacement for the publication rule:**

> Public smart presets are independently designed UzmiGames recipes expressed in the documented layer/effect model. Adobe preset trees, parameter collections and serialized readbacks obtained during observation remain private oracle or per-project migration data; changing their format or names does not qualify them for publication. Each shipped recipe records independently authored provenance and passes output-parity tests.

**Closure:** apply the distinction in both A05 and RESOLUTION; require a provenance record for each public recipe and transitive resource. Keep private extracted state available for permitted migration/testing, without treating it as a public asset-library source.

### F02 — Blocker — The final storage document still describes prohibited implementation internals

**Document:** A09 §3, line 36.

**Evidence:** that paragraph describes Adobe's proprietary project representation and cites historical internal-format analysis as its basis. Its contents are deliberately not repeated here. The owner's new rule and LIC §1.5 prohibit that kind of implementation description in final documentation. The compactness argument does not need it.

**Exact replacement:**

> Compactness is measured from file sizes and dependency inventories obtained through permitted public APIs and filesystem metadata. No assumption about Painter's internal project representation is used. UzPainter stores original dependencies once, authoritative raster state and retained manifests, with regenerable caches optional. Compare matched content and retained-history policies after the reference application's documented compact-save operation; report project bytes plus external dependencies on both sides.

**Closure:** remove the prohibited characterization and its use as implementation evidence; retain the measured-census requirement and the explicitly hypothetical size budget. This review neither consulted nor reproduces the underlying Adobe representation.

### F03 — Blocker — Recorded oracle data is simultaneously private and public/shipped

**Documents:** A14 §6, lines 39–42; A03 §2; A06 §2.

**Evidence:** A14 prohibits Painter-produced oracle records in the repository, but its hosted-CI description places recorded API readbacks in public manifests. A03 says captured template data is shipped as JSON; A06 specifies a shipped defaults capture. Decision 002 and PRD CLR-05 place recorded oracle outputs outside the public repository. This partition cannot depend on whether the output is a PNG or JSON. Independently authored compatibility facts and public-documentation-derived expectations are a different category from captured records and need explicit provenance.

**Exact replacement policy:**

> Public manifests contain independently authored test inputs, public-documentation-derived expectations, schemas, software identities and hashes of private oracle records. Every recorded Painter output, including API readbacks, default/template captures and asset recipes, stays in the private store. Public templates and default tables are independently authored from permitted documented semantics with provenance; raw captured records are never shipped. Hosted CI compares independently authored public expectations. Comparisons against Painter's recorded values require private-store access.

**Closure:** define the permitted public schema and private record schema, then test representative JSON records as well as images. A filename/signature guard alone cannot prove that public recipe JSON or renamed files contain no restricted data. Conversely, it must not reject independently authored fixture images merely because they are images.

This distinction does not prohibit learning compatibility facts through permitted observation or publishing independently derived behavioral implementations and fitted formulas. It prohibits treating the recorded oracle files or extracted asset content themselves as public implementation data merely because they were serialized as JSON.

### F04 — Major — Historical-source quarantine is unfinished and not enforceable from the reading guide

**Documents:** LIC §2; INDEX introduction; README reading/use instructions.

**Evidence:** LIC and INDEX acknowledge a separate sanitization pass still in progress, while final documents cite historical analyses and discussion as implementation evidence. INDEX warns against opening prohibited source files, but a reader could still use their unsanitized descriptions second-hand. README's general evidence convention does not identify which historical revisions have been cleared. No itemized completed provenance audit is supplied in this set.

**Exact addition:**

> Historical analyses and discussion files are not implementation inputs until an itemized clean-room provenance audit approves their exact revision. Do not use descriptions derived from off-limits implementation files, including descriptions repeated by an intermediary. The implementation reading guide links only to approved summaries, permitted public documentation and approved behavioral observations.

**Closure:** publish an approved-source index with document revisions/hashes, provenance and cleared scope. Until then, quarantine the historical material for implementation; keep it as restricted historical context. Record prior exposure where a contributor's independent-provenance claim depends on it. This review does not infer that merely avoiding another direct read erases prior exposure.

### F05 — Major — The dependency inventory does not cover the selected source slice

**Documents:** LIC §3; A13 §2.

**Evidence:** read-only inspection of the non-Adobe engine/dependency sources identifies these omitted components in selected source families:

| Component | Selected-source evidence under `E:/UzmiGames/UzEngine/runtime` | License evidence |
|---|---|---|
| D3D12MA | `engine/rhi/dx12/dx12_device.cpp:16`; `dx12_d3d12ma.cpp:22` | `thirdparty/d3d12ma/LICENSE.txt` — MIT |
| EnTT | `engine/ecs/core/world.h:27` | `thirdparty/entt/LICENSE` — MIT |
| Bundled fmt | `build.zig:624`; spdlog's bundled format implementation | `thirdparty/spdlog/include/spdlog/fmt/bundled/fmt.license.rst` — MIT |
| SPIRV-Reflect | `engine/shader/shader_reflection.cpp:20` | `thirdparty/spirv-reflect/LICENSE` — Apache-2.0 |

A07/A14 also require FLIP but do not identify the selected implementation or its notices. The Python SDK row marks compatibility before the actual wheel closure has been pinned and verified. These are incomplete inventory claims, not evidence that an incompatible library has already been linked.

**Exact inventory preface:**

> Compatibility means distribution alongside Apache-2.0 UzPainter code while retaining each component's own license and notices; it does not relicense third-party code as Apache-2.0. Record license, notices, source/package hash, selected features and distribution role for every direct and transitive dependency in the qualified build. Unverified entries are release blockers. Excluded vendor folders are not release dependencies unless they enter the selected closure.

**Closure:** add the omitted rows, identify FLIP's implementation, inventory the pinned wheels and verify the actual source/link/DLL closure during qualification. Preserve the current “not confirmed” status for package-specific Microsoft redistribution until verified. The license checks supporting this assessment are summarized in “Clean-room findings.”

### F06 — Major — A private facade entry contradicts the documented-only API boundary

**Documents:** A10 §0 and §4, especially the private-symbol row at line 52; A14 §2.

**Evidence:** A10 adds an undocumented private compatibility route while promising that the facade mirrors only the documented interface. This is a scope/provenance contradiction; it is not a claim that its implementation was copied. A14 also restricts its recorder to documented APIs, without closing the end-to-end route for the required reference captures.

**Correction:** remove the private entry from the documented Painter facade. Put any necessary adaptation in an explicitly UzmiGames-owned transport adapter targeting the native UzPainter capture API. State:

> The compatibility facade contains documented Painter symbols only. Pipeline adaptations for unsupported or private reference calls live in a separate UzmiGames adapter and are identified as migrations. The reference recorder uses documented APIs for state and an explicitly permitted, documented capture procedure for pixels; a private interface is not inferred from historical implementation files.

**Closure:** specify and qualify the actual permitted live-reference capture procedure in Phase 0, including readiness/current-frame verification, before admitting render goldens. This can be an approved external observation procedure; it need not falsely be advertised as an Adobe public API call.

### F07 — Major — WARP investigation became a mandatory Phase 0 success requirement

**Documents:** ROAD G0; DAG P0-TOOLCHAIN; A13 §§3/7.

**Evidence:** RESOLUTION D13/Q9 and QUEST Q9 say WARP is investigated, not assumed; A14 describes a conditional lane. ROAD line 13, DAG line 134 and A13 line 60 instead require green hardware **and WARP** selftests. That silently adds a platform requirement.

**Exact replacement:**

> The hardware-adapter qualification slice must pass. The WARP probe must report supported capabilities, executed checks and explicit unsupported reasons. WARP failure leaves that software-render path unsupported and does not fail G0 unless the owner separately makes it mandatory under Q9.

**Closure:** use the same wording in all three gates and distinguish “probe completed” from “backend qualified.” Keep the physical-GPU comparison lane mandatory for the currently assumed deployment profile.

### F08 — Major — Idempotency is not committed atomically with the project mutation

**Documents:** A02 §§3/5; A09 §§1/4; A11 §4.

**Evidence:** A02 stores key/outcome information in the supervisor ledger. A09's schema and commit sequence do not include a worker-side operation record committed with the project revision. A worker can commit and then die before the supervisor receives the acknowledgement. A last revision number alone cannot establish which request produced it. Reporting an unknown outcome is honest, but does not supply the promised safe retry/reconciliation contract.

**Exact addition:**

> Each document transaction persists `{project_uuid, idempotency_key, request_hash, outcome, committed_revision}` atomically with its revision. After restart, the supervisor reconciles its ledger from these records before admitting a retry. Reusing a key with different arguments is rejected. An unresolved outcome is never treated as a new mutation.

**Closure:** specify key scope, record retention and reconciliation. Inject failure immediately after durable project commit and before supervisor acknowledgement; retry the same request and a changed request with the same key. The supervisor ledger remains a control-plane record, not a second editable document.

### F09 — Major — Script-error rollback promise conflicts with per-call transactions

**Document:** A02 §5, Python-exception row.

**Evidence:** A02 promises an unchanged document after a tool/script exception. A03 §6 and A10 §5 commit one transaction per API call; the facade's grouped-modification context explicitly does not roll back earlier calls. A script can commit several mutations and then raise.

**Exact replacement:**

> A failed individual mutation leaves that mutation unapplied. A script exception may follow previously committed calls; its error receipt reports the last committed revision and partial changes. Atomic multi-call execution is available only through an explicitly declared native Transaction. The Painter facade preserves its documented grouped-modification and non-rollback behavior.

**Closure:** compare single-call failure, an unwrapped multi-call script failure and explicit native-transaction failure. Do not hold a document lock across arbitrary callbacks or claim facade rollback that the compatibility contract does not provide.

### F10 — Major — The authoritative-plane schema cannot distinguish two paint layers in the same tile/channel

**Document:** A09 §1, SQL `plane` table and explanatory paragraph.

**Evidence:** the primary key contains revision, set, stack, channel and UV tile, but no owning node/source/output or independent plane ID. The document assigns authoritative paint and frozen-snapshot planes to that table. Two independently editable layers in the same stack/channel/tile cannot be represented as separate rows under the stated key. A final composite does not preserve each layer's authored state.

**Correction:**

> Each authoritative raster has a persistent `plane_id`, explicitly referenced by its owning node/source/output in the manifest. Plane metadata retains UV-tile identity and native format. Chunk rows are keyed by plane identity, retained revision and chunk coordinates; evaluator chunk coordinates are distinct from UV-tile coordinates. Multiple authoritative planes may belong to the same set/stack/channel/tile.

**Closure:** publish the corresponding manifest/table relationship, foreign-key/integrity rules and chunk layout before the store task closes. Save, reopen, edit and recover two layers with separate planes on the same channel/tile without aliasing or flattening them.

### F11 — Major — Per-file rename does not atomically publish a multi-map delivery

**Document:** A08 §5, line 54.

**Evidence:** the document promises that temporary writes and renames preserve the previous complete delivery. Replacing several maps independently can expose a mixed generation if interruption occurs between replacements. EXP-06 requires the previous delivery to remain complete on failure.

**Exact replacement:**

> Write every file and the receipt into a new generation directory, verify the generation, then publish it through one atomic durable manifest/pointer update. A failure leaves the previously published generation selected; incomplete generations remain unreferenced and recoverable.

**Closure:** if downstream consumers require fixed filenames, specify an equivalent journal/recovery protocol or an adapter to the generation manifest. Test interruption between every publication step, including receipt publication, and verify that consumers select either the old complete generation or the new complete generation.

### F12 — Major — The facade accepts color configuration while imposing one fixed color model

**Document:** A10 §4, Color row, line 50.

**Evidence:** the facade fixes all projects to linear working space and sRGB I/O while accepting/recording configuration inputs. A03 §1 retains a project color-management mode, working space and input rules; A07 §2 captures the actual configuration/view. A default pipeline profile does not establish compatibility with every accepted project configuration.

**Exact replacement:**

> The facade preserves the project's declared color-management mode, working space, input rules and display/view transform. Each supported configuration is pinned and tested using permitted public specifications and private oracle outputs. Unsupported configurations fail explicitly before evaluation. Merely recording configuration variables does not constitute support.

**Closure:** keep linear/sRGB as a named supported/default profile where appropriate, not a silent rewrite of other profiles. Include color-managed and raw channels, configuration changes, save/reopen and view-transform fixtures in the capability matrix.

### F13 — Major — All-mode windowless capture conflicts with the hidden-window consumer path

**Documents:** A07 §4, lines 32–39; A13 §2, platform row.

**Evidence:** A07 applies a no-swapchain/no-window capture contract to both render modes. A13 retains a hidden-window path for `engine_preview` until a swapchain-less renderer target exists. The latter is a stated transitional limitation, not evidence that the former contract already holds. PRD NFR-01 also tests operation without a window.

**Exact clarification:**

> `painter_viewport` and its diagnostic captures are window-independent. Until its separate swapchain-less route is qualified, `engine_preview` uses the explicitly identified hidden-window consumer path and reports its Windows session requirements. That transitional path does not satisfy a no-window acceptance test. Any mandatory headless consumer test must wait for the qualified offscreen route or an explicitly recorded scope decision.

**Closure:** either make the swapchain-less engine-consumer route a prerequisite of the relevant headless release gate, or accurately scope the interim capability. Do not infer service-session support from an offscreen texture or hidden-window launch alone.

### F14 — Major — An acyclic DAG still permits acceptance without required predecessors

**Documents:** DAG graph, Inputs table and gate labels; ROAD G2/G3/G5.

**Verified:** the current DAG has **40 nodes, 60 edges, no cycle, no duplicate canonical task IDs**, and matching Mermaid/table edges. All 40 values in the `Rulebook task id` column match `phase<N>_<kebab-name>`. The short `P0-…` labels are legitimate diagram aliases. Structural validity does not establish prerequisite completeness.

**Evidence and minimum corrections:**

| Node/gate | Missing dependency or acceptance distinction | Correction |
|---|---|---|
| P2-BELT, DAG line 150 | Requires an MCP-only round with Python disabled but depends only on P1-WAND | Add P2-MCP; remove belt from the group claimed parallel with its own MCP prerequisite |
| P2-TUNIC, line 151 | Includes render evidence without depending on P2-VIEWPORT | Add P2-VIEWPORT; distinguish passing maps from a blocked initial render comparison |
| P5-REPORT, line 166 | Can be reached without P2-VIEWPORT, P4-TILES or P4-STROKES; these nodes have no outgoing path to cutover | Add those mandatory prerequisites, with strokes removable only by a recorded scope decision under Q5 |
| G3 / P3-BRACERS, line 157 | Labels the fixture node G3 although ROAD G3 also requires UzEngine and Unreal/glTF consumers | Join P3-BRACERS, P3-UZE and P3-UNREAL before closing G3 |
| P5-PACKAGE, line 165 | Can finish before later bakers, procedural assets and completeness work | Bind final package verification to the same complete immutable build/dependency lock as P5-REPORT; any later change reopens both gates |

**Exact G2 wording:**

> G2 requires passing Tier 1 map comparisons and dump-and-rebuild checks under the approved exception policy. Initial render measurements may be reported as blocked; this does not certify render parity and cannot satisfy G5.

**Exact gate rule:**

> Each phase gate joins every mandatory acceptance item named in the roadmap. A work package carrying a gate label cannot close that gate by itself. G5 additionally requires every in-scope capability to be supported or covered by an explicit owner scope decision; reporting a gap is not equivalent to accepting it. Packaging verification and the final parity report refer to the same immutable build hash and dependency lock.

**Closure:** introduce explicit gate nodes or publish complete prerequisite sets for G0–G5; update graph, Inputs, parallel groups and roadmap together. Re-run static graph validation after the changes and demonstrate reachability from each mandatory capability to G5. Optional DXR need not become a mandatory predecessor merely because it has a node.

### F15 — Major — MUST identifiers survive, but some normative clauses and proof obligations do not

**Documents:** PRD §§1–15, especially LAY-06/07, BAK-07, INT-02/11 and ARC-14; the interfaces/tests delegated to A03 §6, A06 §4, A08 consumer contract, A10 §6 and A11 §7.

**Evidence:** every one of the pipeline's **91 rows containing a MUST component** appears in the PRD under the same ID and retains MUST. However, the PRD introduction delegates full text to the historical requirements file. A new implementer should not need that file to discover binding behavior missing from the final contract.

| Requirement | Concrete loss or weak acceptance | Required amendment |
|---|---|---|
| LAY-06 | The source requires name-addressed idempotency; PRD line 83 retains name addressing and persistent IDs but tests only save/reopen | Add: “Name-addressed operations are idempotent within an explicit project/set/stack/parent scope. Ambiguous matches fail before mutation. Repeating the same named operation does not create duplicate nodes.” Test ambiguity and repeats, not only persistence |
| LAY-07 | The source's preservation of other root groups is abbreviated; pointing at the production script is not a standalone specification | Add: “Rebuild only the named group; hide, never delete, other root groups unless an explicit supported option preserves their visibility.” Test that unrelated roots/resources survive and only the addressed group is rebuilt |
| BAK-07 | “Receipt schema tests” does not prove surface accounting or complete lineage | Publish the receipt fields for RAW, straight/cage hits, center/conservative coverage, center misses, extensions, hidden-flat texels, fallbacks, padding/repairs, changed used texels, parts/highs/cages and tool versions. Test accounting/conservation on an analytic fixture, not merely JSON validity |
| INT-11 | “Consumer fixture runs” does not enumerate all current required handoffs | Publish a final-document consumer matrix for staff delivery, hat delivery, specular augmentation, the PBR renderer, applicable paint-render scripts, the Blender render standard and the review panel's Blender-built GLB; each row names the actual script/version, fixture and expected channel/precision/metadata bindings |
| INT-02 / ARC-14 | A Python-disabled belt round cannot exercise every required typed operation | Add: “The belt round is an integration smoke test. Release also requires a requirement-to-typed-operation matrix and a Python-disabled conformance fixture for every required operation family.” Include native bake, reload, later node/effect/source kinds, export targets and strokes where in scope |

**Source evidence:** `docs/analysis/assets3d-pipeline/08-requirements-for-uzpainter.md`, LAY-06/07 near lines 59–60, BAK-07 near line 47, INT-11 near line 145; PRD lines 71, 83–84, 155, 162 and 211. These are UzPainter product/pipeline requirements, not prohibited Adobe implementation evidence.

**MUST trace audit:** the following groups account for all 91 rows. Architecture numbers are the PRD's declared mapping, not proof of implementation.

| Source MUST group | PRD section | Architecture mapping / disposition |
|---|---|---|
| G-02…G-04 | §3 | A03/A04/A10/A14; preserved |
| PRJ-01…PRJ-10 | §4 | A03/A04/A08/A12; preserved, including the 2K/4K MUST versus 8K SHOULD distinction |
| BAK-01…BAK-08 | §5 | A02/A03/A06/A08; BAK-07 needs the stronger evidence contract above |
| LAY-01…LAY-14 | §6 | A03/A04/A05/A10/A11/ROAD; restore LAY-06/07 clauses; LAY-12 remains a visible MUST scope question |
| MAT-01…MAT-05 | §7 | A04/A05; preserved, with decision 002 governing implementation provenance |
| RES-01…RES-04 | §8 | A03/A05/A07/A09; preserved |
| EXP-01…EXP-10 | §9 | A02/A04/A08/A14; preserved; publication contract corrected by F11 |
| SAV-01…SAV-04 | §10 | A03/A09/A14; preserved |
| VIS-01…VIS-06 | §11 | A07; preserve unresolved render scope as required by F16 |
| DIA-01…DIA-02 | §11 | A04/A08/A11; preserved; native statistics remain SHOULD |
| INT-01…INT-05 and INT-07 | §12 | A02/A03/A10/A11; preserve full typed coverage, not only belt coverage |
| INT-10…INT-13 | §12 | A06/A08/A10/A12; make INT-11's consumer matrix explicit |
| INT-20…INT-23 | §12 | A03/A08/A09/A10; preserved |
| QG-01…QG-05 | §13 | A03/A07/A08/A09/A11/A12/ROAD; preserved |
| NFR-01…NFR-04, NFR-06, NFR-08 | §14 | A02/A03/A04/A09/A13/A14; preserve separate workload provenance under F23 |

**Closure:** each MUST needs a final-document normative statement, source, priority, owning interface, named test/fixture and pass condition covering its complete behavior. A tier label, schema-validation test or one successful asset is not sufficient when the requirement is broader.

### F16 — Major — Product non-goals silently close the still-open Iray requirement

**Documents:** VISION Non-goals; PRD §16.

**Evidence:** both documents unconditionally exclude Iray reproduction. RESOLUTION D6/Q2 and QUEST Q2 retain the reference choice as open and require an unresolved gate if the owner requires that output. The architecture may choose the viewport as its current implementation target without asserting that the owner has waived the other acceptance domain.

**Exact replacement:**

> The current implementation target is the pinned real-time viewport. Iray-equivalent output remains an unresolved owner requirement under Q2; it is not silently waived by this architecture and blocks any claim whose approved scope requires it.

**Closure:** use that scope consistently in the vision, PRD, release report and capability manifest. Do not reopen the rejected Adobe-source implementation route; reference-output scope and source-provenance route are separate decisions.

### F17 — Major — Phase 0 reintroduces blanket owner approvals despite usable defaults

**Documents:** DAG P0-OWNER/P0-CONTRACT/P0-PIN; ROAD Phase 0.

**Evidence:** QUEST says work assumes the documented defaults until answered. DAG requires every Q1–Q14 default confirmed or replaced before its owner node can close; both the contract and engine pin depend on it. Q3/Q4 are already closed, and several others concern later gates or nonbinding planning preferences. This blocks work already consistent with the documented decisions/defaults.

**Exact replacement:**

> Record the binding owner decisions and the defaults currently assumed for open questions. Unanswered questions do not block work consistent with those defaults. Block only the affected operation when it would change a default or when an explicit owner decision is a prerequisite to that operation.

**Closure / executable Phase 0 entry:** the first package records decision 002 and the active defaults; it does not seek renewed approval for them. With F01–F04 corrected, a new implementer can begin from an approved public-source index, independently authored fixture inputs, the public/private manifest schemas, a private-store prototype and the Zig qualification slice. Numerical formulas, captured reference state, oracle stability, supported CPU/GPU configurations and ABI qualification remain legitimate experiment outputs, not facts the documents must invent. Acceptance-changing exceptions remain owner decisions at their actual point of need.

### F18 — Major — The package DAG is not yet a task-sized execution plan

**Documents:** DAG Nodes/critical path/parallel groups; README task-creation guidance.

**Evidence:** P1-COMPOSITOR combines scheduling, source evaluation, groups/masks, all blend kernels, quantization, height/normal and diagnostics; P3-BAKER combines ten bakers with requests, evidence, publication and events; P3-PROC combines families, two backends and the library; P4-NODES groups several distinct semantic families. Each has independently testable interfaces and acceptance dependencies, but the guide says to create one Rulebook task directly per node. No decomposition or child acceptance order is provided.

**Exact addition:**

> Retain the current IDs as stable parent work packages. Before creating implementation tasks, split large parents into independently reviewable child tasks with their own artifact, acceptance fixture and prerequisite edges. Child IDs follow `phase<N>_<kebab-name>`; a parent closes only when all mandatory children pass. The `Rulebook task id` column is canonical; `P0-…` labels are diagram aliases.

**Suggested child boundaries:** blend kernels, mask effects and height/normal conversion; baker request model, normal baker, AO baker and bake-evidence publication; snapshot matching versus independent procedural families; separate remaining-node/projection/source families. These are decomposition recommendations, not measured effort estimates. Keep full Tier 0 **reference capture** separate from acceptance of the smaller implemented Phase 1 subset; name the tests each package owns so a partial compositor is not required to pass later-feature tests prematurely.

**Critical-path correction:** DAG's printed chain skips P3-SMART between P3-PROC and P3-BRACERS. Include that required node and label the chain “provisional dependency chain, pending task decomposition and duration estimates.” Without per-node durations, the longest-duration critical path is not established. The engine qualification leg is a genuine prerequisite, not an optional side project.

### F19 — Minor — Pilot order is correct, but phase labels disagree

**Documents:** ROAD Pilot order/Phase 1; RESOLUTION §2 D14.

**Evidence:** ROAD line 7 says all three pilots are inside Phase 2, while its phase table and DAG put Wand in Phase 1. RESOLUTION says all belong to the first pilot phase. The intended ordering remains Wand → Belt → early Tunic; the disagreement is the phase allocation language.

**Exact aligned wording:**

> Wand v1 is the Phase 1 smoke fixture; Belt v5 and Tunic v10 complete the first production-parity pilot sequence in Phase 2.

Apply that wording to the resolution and roadmap, explicitly preserving the settled ordering and early tunic gate.

### F20 — Minor — Rejected-route descriptions remain in the index/overview

**Documents:** README document table, procedural-content row; A01 §2, procedural component row.

**Evidence:** the README still advertises two legal routes, and the overview retains a reserved runtime-adapter slot. Decision 002 and RESOLUTION D4 close the Adobe-runtime/source-port routes; an extensible interface does not need to suggest that those product options remain active.

**Exact replacement:**

> Independently implemented certified resource families and project-private frozen snapshots behind `IProceduralBackend`; no Adobe runtime adapter or redistributed Adobe content.

Use “two backends,” where needed, to refer to the selected independent/snapshot implementations, not to two legal routes.

### F21 — Minor — The proposed neutral render fixture is called owner-ratified

**Document:** A07 §2, line 18.

**Evidence:** the fixture is described as ratified while the same document and QUEST Q2 say the reference remains open. No supplied decision ratifies these particular neutral settings.

**Exact replacement prefix:** “Proposed neutral fixture, not yet ratified under Q2: …” Keep it distinct from the captured production-project profile. Decision 002 ratified the implementation route, not every render parameter.

### F22 — Minor — CPU-first is still described as universal machine support

**Documents:** A06 §1; PRD §17; QUEST Q9; RESOLUTION D5/Q9.

**Evidence:** these passages say CPU baking runs anywhere/on any x64 Windows machine while the same design pins ISA/tasking/build choices and leaves the deployment matrix for qualification. CPU execution removes a DXR requirement for baking; it does not establish universal OS/CPU compatibility or repeatability.

**Exact replacement:**

> CPU baking runs on the Windows/CPU/ISA configurations qualified for the pinned Embree build. Unsupported configurations receive an explicit capability error. Cross-machine repeatability is measured separately.

### F23 — Minor — Separate capacity workloads are collapsed into an apparent single baseline

**Document:** PRD NFR-03, line 187.

**Evidence:** the source requirements' NFR-03 explicitly distinguishes separate recorded workloads. The PRD concatenates their dimensions without that qualification. This can make one unmeasured combined workload appear to be a demonstrated production baseline.

**Exact replacement:**

> Support each recorded workload separately: three 4096-square texture sets; 30–45-layer stacks; more than twenty 4K 16-bit masks; seven delivered maps per set. A combined worst-case workload is a proposed stress fixture, not an observed baseline.

## Clean-room findings

**Policy disposition:** decision 002 is binding and closes the implementation-route choice. This review accepts Apache-2.0, independently sourced implementations, documented API shape, no Adobe dependency/content redistribution and private oracles. It does not reopen the rejected port or propose a licensed Substance runtime. Permitted black-box observation does not automatically make its recorded content public, and product-owner authorization does not relicense third-party content.

**Compliance findings:** F01 separates private observed asset state from public independent presets; F02 removes prohibited internal-description prose; F03 repairs the public/private oracle partition; F04 closes indirect reliance on unsanitized history; F06 separates the documented facade from a private historical compatibility need. The report cites the relevant UzPainter documents/sections only when identifying prohibited implementation material; it does not repeat that material or inspect the underlying files.

**Provenance of the review:** architectural/pipeline evidence came from the requested UzPainter documents and permitted project requirements. License checks used non-Adobe dependency notices and official public license sources. None of the forbidden Adobe implementation/binary-format files was used as a source for this review.

### License verification

**Root license:** `LICENSE` contains Apache-2.0 sections 1–9 and the application appendix, with `Copyright 2026 UzmiGames`; no missing section or unfilled copyright placeholder was identified. Its text was checked against [Apache's official license](https://www.apache.org/licenses/LICENSE-2.0.txt). No separate finding is raised against the root file.

| Dependency/family | Verified license status | Evidence and limit |
|---|---|---|
| UzEngine | Apache-2.0 | `E:/UzmiGames/UzEngine/LICENSE`; select the qualified immutable revision |
| CPython | PSF license with historical/incorporated notices | [CPython 3.13 LICENSE](https://raw.githubusercontent.com/python/cpython/3.13/LICENSE); preserve the complete pinned distribution's notices |
| pybind11 / MCP SDK | BSD-3-Clause / MIT | [pybind11](https://raw.githubusercontent.com/pybind/pybind11/master/LICENSE), [MCP SDK](https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/LICENSE); the SDK's license does not certify its whole wheel closure |
| Embree | Apache-2.0 | [Versioned Embree license](https://raw.githubusercontent.com/RenderKit/embree/v4.4.0/LICENSE.txt); qualify the chosen version/build and optional tasking dependency |
| SQLite | Public domain | [SQLite copyright statement](https://www.sqlite.org/copyright.html) |
| zstd / lz4 library | BSD-3-Clause branch / BSD-2-Clause | [zstd](https://raw.githubusercontent.com/facebook/zstd/dev/LICENSE), [lz4 library](https://raw.githubusercontent.com/lz4/lz4/dev/lib/LICENSE); choose the BSD route explicitly where dual-licensed |
| OpenColorIO | BSD-3-Clause | [OpenColorIO license](https://raw.githubusercontent.com/AcademySoftwareFoundation/OpenColorIO/main/LICENSE); this does not license Adobe-supplied configurations |
| etcpak / bundled bc7enc | BSD-3-Clause / local component MIT-or-public-domain terms | [etcpak license](https://raw.githubusercontent.com/wolfpld/etcpak/master/LICENSE.txt) and the selected non-Adobe component notice; retain component notices independently |
| spng, ufbx, fastgltf, MikkTSpace, stb | Compatible permissive component terms | Local non-Adobe notices under `UZE/runtime/thirdparty/`: `spng/LICENSE`, `ufbx/LICENSE`, `fastgltf/LICENSE.md`, the MikkTSpace license header, `stb/LICENSE`; use each component's actual terms rather than labeling all “MIT” |
| libjpeg-turbo, Tracy, astcenc, basis_universal | Respective IJG/BSD/zlib, BSD-3-Clause and Apache-2.0 terms | Corresponding local third-party license files; unused codecs remain outside the release closure unless actually linked |
| D3D12MA, EnTT, bundled fmt, SPIRV-Reflect | MIT / MIT / MIT / Apache-2.0 | Selected-source and local-license paths in F05; missing inventory entries |
| FLIP, if the upstream implementation is selected | BSD-3-Clause | [Upstream FLIP license](https://raw.githubusercontent.com/NVlabs/flip/main/LICENSE); identify the actual implementation rather than assuming a metric name supplies a dependency license |
| DXC / DXIL package | Inventory's LLVM/NCSA attribution is plausible for the inspected package, with component notices | Non-Adobe `UZE/runtime/thirdparty/dxc/ReleaseNotes.md`, Licenses section, and [upstream DXC license](https://raw.githubusercontent.com/microsoft/DirectXShaderCompiler/main/LICENSE.TXT); do not infer the selected binary's terms merely from an unrelated/stale license file also in the folder |
| Agility SDK and Microsoft CRT binaries | Exact-package redistribution qualification remains open | Retain “not confirmed” until the actual chosen package, files and distribution conditions are recorded; do not call these DLLs Apache-2.0 |
| Other listed direct libraries and transitive packages | Final closure remains a pin-time obligation | Record source/wheel hashes and notices for every selected component, including embedded compression, formatting/reflection helpers and Python wheels |

**Conclusion of the license audit:** no definitely incompatible linked dependency was established by this read-only review. Most stated direct licenses are correct; the defect is incomplete closure and premature certainty for unverified package sets. Apache compatibility concerns combination/distribution under each component's obligations, not relabeling every component. The actual binary closure remains unconfirmed until the expressly deferred build qualification; this review does not pretend to have performed it.

## Remaining disagreements

**Interpretation:** “Resolved” below means the response in RESOLUTION answers the architectural objection. It does not mean every final-document contract is correct, all owner questions are closed or numerical parity has been demonstrated. The owner-selected route replaces my previously open options; it is not subject to another vote between the architects.

| Round-2 disagreement | Status | Does the response convince me? What remains? |
|---|---|---|
| D1 — single process versus supervisor/worker | **Resolved in architecture** | Yes. The GPU-free supervisor and document-owning worker accept the required failure boundary. F08/F09 still need precise durable-retry and partial-script semantics; these are completion defects within the chosen topology, not a reason to reopen it. |
| D2 — blanket omissions and strokes | **Resolved in architecture; final facade needs correction** | Yes. Per-symbol capability decisions, retained script context, a bounded JS surface, non-UI plugin behavior and visible stroke gaps answer the objection. F06 removes the later private-surface contradiction; F14/F15 ensure mandatory capability coverage reaches release. Q5 remains an owner scope question, with its stated default binding meanwhile. |
| D4 — frozen content, editable parity and runtime route | **Resolved by owner decision; compliance not yet closed** | The selected independent-family route and exact-signature private snapshots are accepted. The owner has rejected the other routes. F01/F03 must still separate private observed content from independently authored public assets/data. Numerical feasibility and unsupported families remain visible gates; a snapshot does not certify editable procedural parity. |
| D8 — ZIP versus SQLite | **Resolved in architecture** | Yes. SQLite, canonical JSON, transactional revisions and a matched-content size census answer the objection. F02/F08/F10 correct provenance and storage/recovery contracts; none requires returning to ZIP as the working format. |
| D9 — synchronous/no-op facade | **Resolved in architecture; final behavior needs correction** | Yes. Asynchronous lifecycle, dispatcher, readiness barriers and explicit computation state answer the objection. F09/F12 correct remaining inconsistent error/color behavior. Compatibility evidence still has to be generated by the planned tests. |

**Other D1–D14 dispositions:** D3's measured evaluator profile, D5's Embree-first backend, D7's canonical-versus-delivery distinction, D10's typed MCP coverage, D11's raw import contracts and D12's Zig-first qualification are accepted. D6's clean-room route is settled, while reference selection under Q2 remains unresolved and must not be erased by a non-goal. D13's exact acceptance sentence and versioned owner exceptions are accepted; WARP is an investigation until qualified. D14's Wand → Belt → early Tunic order is accepted; F14/F18/F19 repair its executable plan and phase labels.

**Archival condition:** resubmit the corrected final set with a provenance-cleared source index, the repaired public/private data boundary, a reconciled DAG/gate matrix and consistent interfaces for transactions, persistence, capture and export. The present rejection is of the documentation set as an archival build contract, not of the resolved architectural direction.

