# Astra critique of Claude's architecture proposal — round 2

## 0. Summary

1. **Recommendation:** disposition of D1–D14: **0 agree, 9 agree with changes, 5 disagree**; the five disagreements are D1, D2, D4, D8 and D9.
2. **Recommendation:** replace my CMake/MSVC-first position with Claude's **Zig-first integration**, because the inspected MSVC target excludes essential rendering and job sources.
3. **Recommendation:** adopt Claude's **Embree CPU-first** choice over an initial custom BVH, without promising cross-machine determinism or Painter-equivalent sampling.
4. **Recommendation:** adopt **Wand v1 → Belt v5 → Tunic v10**, with procedural/native-bake feasibility investigated early and separate multi-set coverage.
5. **Recommendation:** adopt Claude's four-tier corpus organization and explicit intermediate-format tests; retain equality unless the owner explicitly approves a bounded exception.
6. **Recommendation:** retain a supervisor/worker boundary, SQLite project storage, behavioral API compatibility and an explicit gate for proprietary content.
7. **Hypothesis:** neither a GLSL port nor independent numerical calibration currently proves render parity; neither access to source nor ownership of Painter establishes the necessary permissions.
8. **Fact (C, entire file; A, entire file):** this critique compares the two round-1 positions; it does not incorporate the concurrent reconciliation.

### Evidence notation and scope

**Recommendation:** read **Fact** as an observation supported by the named source, **Hypothesis** as an inference or unmeasured claim, and **Recommendation** as a proposed decision or future verification. Unconfirmed capabilities remain **not confirmed**. Tests below are proposed settlement evidence, not tests performed in this round.

**Fact (source paths):** the following aliases expand to these exact locations; section/finding identifiers following an alias narrow the citation. `P`, `U`, `AS` and `AD` respectively denote `E:/UzmiGames/UzPainter`, `E:/UzmiGames/UzEngine`, `E:/UzmiGames/Assets3D`, and `C:/Program Files/Adobe/Adobe Substance 3D Painter`.

| Alias | Evidence path |
|---|---|
| C | `P/docs/analysis/architecture-discussion/01-claude-proposal.md` |
| A | `P/docs/analysis/architecture-discussion/02-astra-position.md` |
| Decision 1 | `P/.rulebook/decisions/001-acceptance-criterion-output-parity-with-substance-painter.md` |
| SP1 | `P/docs/analysis/substance-parity/01-python-api-inventory.md` |
| SP2 | `P/docs/analysis/substance-parity/02-layer-stack-model.md` |
| SP3 | `P/docs/analysis/substance-parity/03-baking.md` |
| SP4 | `P/docs/analysis/substance-parity/04-export.md` |
| SP5 | `P/docs/analysis/substance-parity/05-project-and-spp.md` |
| SP6 | `P/docs/analysis/substance-parity/06-mcp-tools-inventory.md` |
| SP7 | `P/docs/analysis/substance-parity/07-parity-matrix.md` |
| AP2 | `P/docs/analysis/assets3d-pipeline/02-painter-usage.md` |
| AP3 | `P/docs/analysis/assets3d-pipeline/03-bake-settings.md` |
| AP4 | `P/docs/analysis/assets3d-pipeline/04-painting-recipes-and-materials.md` |
| AP5 | `P/docs/analysis/assets3d-pipeline/05-export-and-consumers.md` |
| AP6 | `P/docs/analysis/assets3d-pipeline/06-review-render-standard.md` |
| AP7 | `P/docs/analysis/assets3d-pipeline/07-lessons-and-pitfalls.md` |
| AP8 | `P/docs/analysis/assets3d-pipeline/08-requirements-for-uzpainter.md` |
| UE2 | `P/docs/analysis/uzengine-renderer/02-headless-rendering.md` |
| UE3 | `P/docs/analysis/uzengine-renderer/03-rhi-capabilities-for-texturing.md` |
| UE4 | `P/docs/analysis/uzengine-renderer/04-material-and-texture-standard.md` |
| UE5 | `P/docs/analysis/uzengine-renderer/05-mesh-import.md` |
| UE6 | `P/docs/analysis/uzengine-renderer/06-thirdparty-and-image-io.md` |
| UE7 | `P/docs/analysis/uzengine-renderer/07-build-and-packaging.md` |
| T1–T4 | `P/docs/analysis/technology-options/01-python-embedding-and-packaging.md`, `02-texture-compression-and-containers.md`, `03-project-container-format.md`, `04-mcp-server-options.md` |
| RS | `P/docs/analysis/reviews/substance-parity-astra-review.md` |
| RP | `P/docs/analysis/reviews/assets3d-pipeline-astra-review.md` |
| RE | `P/docs/analysis/reviews/uzengine-renderer-astra-review.md` |
| RT | `P/docs/analysis/reviews/technology-options-astra-review.md` |

**Fact (read-only inspection of `U/runtime/build.zig`, `U/runtime/CMakeLists.txt` and Git metadata):** the observed UzEngine HEAD is `19ffb9b94333f56d624eb1485192cf5c6d174bd0`; the inspected working tree contains staged changes, including both build descriptions. HEAD and the working snapshot are different evidence sets. The current search in `runtime/engine` and `runtime/shaders` found no merge-marker lines, whereas RE recorded them in an earlier snapshot. Neither observation proves a successful build.

## 1. Per-decision critique

### D1 — Runtime topology

**(a) Claude's position — Fact (C, D1):** one C++ process embeds UzEngine, CPython and the Python MCP SDK; one GPU thread, a CPU job pool, checkpoints and minidumps provide recovery.

**(b) Agreement level — Recommendation: disagree.**

**(c) Arguments**

**Fact (`U/runtime/engine/rhi/dx12/dx12_command_list.cpp`, `DX12CommandList::FatalErrorLoop`, approximately lines 1068–1086):** repeated RHI errors lead to crash reporting and `std::abort()`. **Fact (`U/runtime/engine/rhi/dx12/dx12_fence.cpp`, `DX12Fence::WaitCPU`, approximately lines 70–95):** the watchdog reports prolonged waits and the device-removal reason, but its timeout loop has no termination deadline. These are concrete failure paths in our own engine, independent of any Adobe crashes.

**Hypothesis:** with C's topology an abort terminates MCP together with the document, and a stuck GPU operation can prevent the in-process document owner from completing work. SEH/minidumps diagnose a crash; they do not make arbitrary native heap corruption recoverable. Checkpoints preserve committed progress, not the transport connection or the pending job's outcome. CPU document survival after every device-removal path is not confirmed by these sources.

**Recommendation:** keep the supervisor free of GPU initialization; it owns MCP connectivity, admission control and the job ledger. The worker owns the document, native engine and embedded compatibility-script interpreter. Use the same distributed executable with different launch modes, so a process boundary does not require another product installation. Serialize typed commands, revisions, progress and artifact references; transfer large buffers only when necessary, using files or explicitly managed shared memory. Whole images need not cross IPC for every API call, contrary to C's principal cost argument.

**Hypothesis:** a single process is simpler for stepping through Python/native calls and avoids protocol/version/lifetime code. A worker adds startup, memory and cancellation/recovery complexity; none of those costs has been measured. A GPU reset may affect other processes using that GPU, so worker isolation is not device isolation. It does, however, permit an unaffected CPU-only supervisor to report failure and terminate a stalled worker.

**(d) Revised position — Recommendation:** retain supervisor/worker in the shipping architecture, with a single-process diagnostic mode if useful. Adopt C's one GPU-owner thread, bounded CPU jobs, native GIL release, minidumps and checkpoints. Serialize document commits, evaluate immutable revisions, and identify a job's committed revision before recovery; never blindly replay a mutation after losing its acknowledgement. Do not give the supervisor a second authoritative copy of the document.

**(e) Settlement evidence — Recommendation:** compare both topologies using the same command corpus: startup/RSS, small-command latency, large-artifact transfer, cancellation, native abort, device removal and an indefinitely stalled fence. Record MCP responsiveness, last durable revision, duplicate-commit prevention, recovery time and debugger usability. An in-process design must demonstrate the required external recovery behavior, not merely generate a dump. No performance or reliability winner has been measured.

### D2 — API scope for v1

**(a) Claude's position — Fact (C, D2):** mirror the non-UI Python surface, omit `ui`, `js`, plugins and selected UI-related symbols, add native output controls, and defer strokes.

**(b) Agreement level — Recommendation: disagree.**

**(c) Arguments**

**Fact (SP1, API reachability table and module tables):** `js.evaluate()` reaches shader parameters and export functions; plugin startup runs Python code; stack selection is distinct from widget highlighting. Removing these routes can change which instructions execute and which stack they address. Therefore the blanket assertion that all omitted symbols affect no texture or pixel is unsupported. C correctly adds native shader controls, but a replacement function does not by itself make an existing JS call compatible.

**Fact (RS, inventory recount):** 572 is the inventory's physical row count, including setters and grouped/note rows, not a proven count of unique public callable symbols. **Recommendation:** maintain an explicit symbol/behavior capability manifest instead of using that number as the completeness criterion.

**Fact (SP1; SP2; Decision 1; user product requirements):** the public Python API lacks general stroke authoring, while the requested product includes Painter functionality and AI operation. **Hypothesis:** a fills-only milestone can replace many current recipes, but absence from Adobe's Python API cannot establish that a painting instruction is impossible or outside the product. Native AI stroke commands and preservation of existing raster state remain separate requirements.

**(d) Revised position — Recommendation:** omit actual human widget construction and panel manipulation. Preserve script context, output-affecting lifecycle/events, non-UI plugin execution and the required JS behaviors, through a documented compatibility subset or explicit migration adapter. Unsupported syntax must fail before mutation. A native counterpart alone should be advertised as migration support, not unchanged-script compatibility. Allow staged delivery, but list strokes and any deferred output-affecting features as open release gates rather than redefining full replacement.

**(e) Settlement evidence — Recommendation:** build a call-and-effect matrix from the three production scripts, their injected Python/JS and plugin startup dependencies, plus adversarial fixtures for active-stack changes, shader edits and callback-driven mutations. For each omission, show that no required sequence loses behavior or document the owner's explicit scope amendment. A module's name or apparent UI association is insufficient evidence.

### D3 — Layer stack and composition

**(a) Claude's position — Fact (C, D3):** a typed tree/DAG mirrors nodes and blend modes, with per-channel formats, opacity, masks, anchors, resources and a tile dimension; numerical oracle tests establish formulas.

**(b) Agreement level — Recommendation: agree with changes.**

**(c) Arguments**

**Fact (SP2; C, D3; A, D3):** both proposals cover the twelve node kinds, thirty-two listed blend modes, channel-specific behavior, groups, effect ordering and anchors. C makes the decision between high-precision intermediate evaluation and Painter-like per-node storage quantization especially explicit. **Recommendation:** adopt that explicit experimentally selected evaluator profile; it is stronger than leaving quantization points implicit in a general high-precision implementation.

**Hypothesis:** a generic alpha-composition equation does not prove every blend/group/pass-through/height/normal interaction. Public blend definitions are candidate formulas; undocumented ordering, color space and quantization require oracle evidence. Viewport GLSL cannot automatically establish layer-compositor semantics, and the source-provenance decision in D6 also applies to copied constants or expressions in D3.

**Fact (C, D3 and roadmap; SP2, UV tiles):** C models tile identity but restricts the first workflow to the default tile. **Recommendation:** that is acceptable milestone scheduling, not completed UV-tile parity. Preserve explicit texture-set/stack/tile addressing, mask `None` versus channel sources, resource hashes and per-node aliases from the first schema. Stable native IDs should be a documented UzPainter guarantee, not an assumed persistence guarantee of Painter's session objects.

**(d) Revised position — Recommendation:** merge the typed model and C's intermediate-format experiment with my dependency/revision model. Keep semantic evaluator versions in the project because changing a kernel can change old projects' appearance. Certify single-tile workflows first while retaining multi-tile behavior as a required release gate. Use public formulas and permitted oracle experiments unless the separate shader/source route is cleared.

**(e) Settlement evidence — Recommendation:** compare intermediate and final channels for blend/value/opacity sweeps, nested groups, pass-through, mask effects, anchor dependencies, Height/Normal interactions and tile boundaries. Include save/reopen and changed-node invalidation. Select the quantization profile from these results; changing the profile after published projects requires a versioned migration or retained evaluator.

### D4 — Procedural content and captured assets

**(a) Claude's position — Fact (C, D4):** use captured procedural bitmaps at recorded parameters plus calibrated HLSL generators and extracted smart-material recipes; reject general `.sbsar` execution.

**(b) Agreement level — Recommendation: disagree.**

**(c) Arguments**

**Fact (C, D4; SP2, resolution modes; AP4, resource families):** C proposes 4096-square captures while its generator corpus includes 1024-square evaluations, and recipes use procedural parameter changes and mesh-dependent generators. **Hypothesis:** evaluating a procedural at one resolution and resampling it is not generally equal to evaluating it at another; frequency, filtering, noise and precision can differ. “Exact by construction” is defensible only for a specific captured output, not the whole resource or all uses of that bitmap.

**Recommendation:** a frozen asset's identity must include graph/resource version, effective parameters and defaults, seed, output channel, output resolution, bit depth/color space and all relevant mesh-map/tile/projection inputs. Capture all required outputs, not just a color thumbnail. Mark the node as a frozen snapshot with an explicit supported signature. Retain it as authoritative data when regeneration is unavailable; parameter edits outside that signature cannot silently remain a bitmap.

**Fact (official [Adobe Developer Terms of Use](https://www.adobe.com/go/developer-terms), dated June 18, 2024, sections 4.1(A), 5 and 22.1):** the published terms contemplate distribution of the Substance Engine under conditions; the developer-tools distribution right is subject to approval. **Hypothesis:** an applicable commercial arrangement, SDK access and approval for UzPainter are not confirmed. This evidence refutes an unconditional claim that the engine is inherently non-redistributable, without establishing that UzmiGames may distribute it. Sections 6.9 and 6.16 also require review for this particular integration and use of AI; their applicability cannot be settled by architecture preference.

**Fact (official [Adobe General Terms](https://www.adobe.com/legal/terms.html), sections 3.6 and 17; [Substance 3D Assets terms](https://www.adobe.com/go/substance3dassets), sections 3.1–3.3):** the published terms distinguish content use from standalone redistribution and contain restrictions relevant to modification, reverse engineering and certain uses of outputs. **Hypothesis:** which agreement governs each installed starter asset, downloaded asset, capture and oracle experiment is not confirmed. A finished textured model and a reusable replacement library of grunges or smart materials are different distribution cases; baking an asset into a bitmap does not automatically remove its provenance or restrictions. Mere AI operation of a deterministic painter should not be assumed equivalent to training a model, or automatically exempt from applicable terms.

**Hypothesis:** C's bounded HLSL corpus is a useful implementation plan, but its proposed nonzero error thresholds do not prove the current equality requirement. A small mesh/parameter sweep is evidence for those samples, not arbitrary graphs. A licensed evaluator could improve procedural coverage but would still need version, engine-backend, input and output calibration; it would not supply Painter's entire compositor or viewport.

**(d) Revised position — Recommendation:** retain three explicitly separate routes: a confirmed distributable runtime if available; independently implemented, certified resource families; and permitted frozen snapshots for exact historical-state preservation. Keep the runtime adapter option open while availability and terms are investigated. Treat arbitrary editable `.sbsar` support as unresolved until demonstrated. Accept C's concrete resource-family inventory as the starting corpus, extended with parameter boundaries, seeds, resolutions, channel outputs and actual mesh maps. No route may claim full replacement by silently substituting a visually similar material.

**(e) Settlement evidence — Recommendation:** obtain applicable written SDK/content/oracle terms and a representative feasibility result for Leather Damaged, Bronze Armor, required grunges and mesh-dependent masks. Replay parameter changes, resolution changes and save/reopen; compare native outputs against a stable oracle. The owner chooses funding and scope after seeing measured errors and the available rights. Choosing a route does not itself confer third-party rights.

### D5 — Bake backend

**(a) Claude's position — Fact (C, D5):** CPU Embree first, all ten bakers behind one interface, DXR later, external Blender maps accepted, with asynchronous jobs and Painter-style parameters/events.

**(b) Agreement level — Recommendation: agree with changes.**

**(c) Arguments**

**Recommendation:** Claude's Embree-first choice is stronger than my initial custom-BVH direction. Use an established intersection library and spend implementation effort on Painter-compatible ray generation, cages, matching, samples, coverage, filtering, normalization and reduction. Retain a backend interface so a custom implementation is possible if evidence eventually requires it.

**Fact (`AD/embree3.dll`, file-version metadata):** the installed library reports version 3.13.5. **Hypothesis:** presence in Painter's installation does not prove which bakers use it, which settings they use, or whether it serves another component such as Iray. Embree 4 is not the installed Embree 3 build. Common ancestry of an intersection library is not proof of bake equality.

**Fact (upstream [Embree 4.4.0 license](https://github.com/RenderKit/embree/blob/v4.4.0/LICENSE.txt) and [versioned README](https://raw.githubusercontent.com/RenderKit/embree/v4.4.0/README.md)):** Embree is Apache-2.0 licensed; its build configuration has ISA and tasking choices, including TBB, PPL and internal tasking, and warns about fast-math. **Recommendation:** acquire an upstream dependency with its notices, rather than extracting Adobe's DLL. Select and pin the tested version/configuration; 4.4.0 is evidence for these options, not a version already qualified for UzPainter.

**Hypothesis:** deterministic sample IDs, fixed seeds and ordered reductions can make our bake implementation reproducible on a defined configuration. Cross-machine bit identity remains unconfirmed because ISA dispatch, intersection edge cases, compiler math and floating-point environment also matter. CPU-first removes the DXR requirement for baking; it does not mean every Windows machine supports the chosen Embree build or the GPU compositor.

**Fact (SP3; RS, F05; C, D5):** C correctly distinguishes stored cube-project parameters from fresh-project defaults and preserves the dynamic property model. **Recommendation:** adopt this distinction unchanged. Preserve all ten map domains and mapped cage/match/AA parameters; external normal/AO equivalence must never certify native bake parity. Record the Painter backend actually used for each golden instead of choosing an easier reference after a mismatch.

**(d) Revised position — Recommendation:** Embree CPU first; DXR only after capability checks and independent qualification under the same semantic baker interface. Keep fixed sample addressing and reduction order, explicit working units, cancellation boundaries, per-map diagnostics and the compatibility `StopSource`/events distinct from the richer native job API. Do not promise universal CPU determinism or use similarity of ray libraries to waive calibration.

**(e) Settlement evidence — Recommendation:** bake analytic fixtures and real high/low/cage assets with controlled reference settings; repeat across thread counts, supported CPUs/ISAs and save/reopen. Compare first-hit/coverage diagnostics before AO/curvature/normal maps. Qualify packaging without an installed Painter or developer environment. Measure DXR separately; a faster backend must meet the same approved output contract.

### D6 — Viewport parity, source provenance and rendering

**(a) Claude's position — Fact (C, D6):** port Painter viewport GLSL to a dedicated HLSL forward renderer on UzEngine; retain a separate UzEngine preview and exclude Iray from the proposed parity target.

**(b) Agreement level — Recommendation: agree with changes.**

**(c) Arguments**

**Fact (`AD/resources/starter_assets/shaders/pbr-metal-rough.glsl`, `open-pbr.glsl`, headers; `AD/resources/shader-doc/lib-pbr.html`, header):** the installed shader sources/documented library carry an `ADOBE CONFIDENTIAL` notice and ownership/restriction text. **Fact (official [Painter Shader API](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/scripting-and-development/shader-api-reference/shader-api)):** shader authors supply material shader code within Painter's rendering environment. **Hypothesis:** visibility of that fragment interface and its helpers does not establish permission to redistribute a replacement renderer or disclosure of all host-side sampling, texture processing and display behavior.

| Route | Technical assessment and remaining uncertainty |
|---|---|
| **Hypothesis — direct GLSL-to-HLSL port** | Access to expressions can reduce formula inference. It creates an evident source-provenance/derivative-work question and still leaves GLSL/HLSL numerical differences, texture sampling, IBL preprocessing, host parameters, precision and color management to reproduce. No measured implementation effort or parity result exists. |
| **Hypothesis — independent implementation from public mathematical references** | Public BRDF/color/tangent formulas plus permitted oracle tests avoid deliberate copying of Adobe expressions. Exact constants, filtering and host behavior may need more experiments. The achievable error and extra cost are unmeasured; “necessarily lower parity” is not established. Public availability of Adobe's own confidential-marked code is not independent provenance. |
| **Recommendation — controlled independent-development process** | If the owner selects a formal clean-room route, separate behavior/specification gathering from implementation, preserve provenance and use implementers who have not studied the restricted code where that process requires it. Both architects have already inspected source; calling our subsequent rewrite “clean room” would not establish that separation. |

**Recommendation:** apply the contract review in D4 to oracle calibration as well as copied code. Independent derivation can address expression provenance; it does not automatically answer contractual restrictions on use of the reference software or outputs. This is a technical exposure assessment, not a conclusion about enforceability or the owner's applicable agreement.

**Fact (AP2, shader-identity qualification; RP, Q6; C, D6):** channel names and double-sided parameters do not confirm the active shader; C labels an inference about `open-pbr` as Fact while citing a source that marks it Hypothesis. **Fact (AP6):** the pipeline's render evidence includes Iray/Cycles comparison practices. **Recommendation:** agree on an actual captured Painter viewport profile before excluding Iray from acceptance. A proposed 1200-square, White Soft, Linear profile is a useful test specification, not proof that it reproduces the existing review profile.

**Hypothesis:** a dedicated forward parity path avoids unrelated deferred-renderer postprocessing, so I retain our common architectural choice. Neither the “few hundred lines” estimate nor categorical impossibility of pixel equality across GPUs is established. RGBA16F is a candidate intermediate, not a proven match to the reference's precision. Hidden-HWND startup evidence does not prove service/CI operation without a desktop; genuine offscreen capture still needs qualification.

**(d) Revised position — Recommendation:** retain dedicated `painter_viewport` and separately validated `engine_preview`. Default the implementation plan to independently sourced formulas and provenance records, subject to confirmation that the planned oracle use is permitted; keep a licensed port as an owner-selectable route after applicable rights are established. Freeze actual shader/resource/configuration hashes, camera, HDRI, orientation, exposure, display transform, tone mapping and sampling state. If Iray remains required, report that gate as unresolved rather than certifying the viewport as its replacement.

**(e) Settlement evidence — Recommendation:** first resolve the rights and render-reference questions, then compare controlled single-material BRDF/normal/IBL fixtures and real assets. Record linear buffers and display output separately, repeat the oracle to characterize instability, and measure both viable implementation routes on the same fixtures. Qualify headless capture on the supported Windows session/hardware matrix. This establishes parity and cost; the presence of GLSL files does not.

### D7 — Export and downstream consumers

**(a) Claude's position — Fact (C, D7):** accept Painter export JSON and preset semantics, implement lossless/source formats plus packed engine presets, and verify compressed artifacts through consumers.

**(b) Agreement level — Recommendation: agree with changes.**

**(c) Arguments**

**Fact (SP4; C, D7):** C explicitly covers per-root presets, parameter overrides, wildcard expansion, channel-source kinds, non-square sizes, padding and dithering. **Recommendation:** adopt that explicit resolution order; a preset-name list alone is too weak. Preserve decoded source pixels as the primary comparison so encoder metadata and compression choices do not masquerade as texture differences.

**Fact (RE, F07/F12/F17; `U/runtime/engine/asset/importers/png_codec.h` and `png_codec.cpp`):** the memory PNG encoder exposes 16-bit support while the inspected file encoder hardcodes an 8-bit IHDR; existing cooking paths reduce precision. C correctly selects the memory encoder. **Recommendation:** retain the native authoring/export precision before any BC conversion; test byte order, color metadata, padding and deterministic dithering independently. BC4 height is a delivery derivative, not a lossless replacement for a native 16-bit height channel.

**Fact (AP5; RP, ADD-10; `AS/SM/10-Chapeu/report.json`, `v8.specular` and export notes):** current hat output requires SpecularWeight. **Fact (RE, F12; `U/runtime/engine/ecs/loaders/scene_loader.cpp`, graph/inline material loading):** declared material fields do not establish every reader binding, and the reviewed graph ORM path can be overwritten by an absent inline field. **Recommendation:** C's `.uzmat` pin table must be validated against the selected reader, including SpecularWeight, height/thickness and opacity. Do not certify the preset by producing syntactically valid files alone.

**Fact (UE4; RE, normal/opacity findings):** RG normal reconstruction and the fixed-PBR opacity sampler impose domain/channel requirements. **Recommendation:** use BC7 albedo with the required alpha interpretation, BC5 RG normals only within the verified reconstruction domain, linear ORM and explicit scalar metadata. Test normal handedness, positive-Z assumptions, mip filtering, roughness filtering and alpha coverage. Avoid filename-based inference of linear versus sRGB data.

**Fact (C, D7):** several Painter file formats are deferred. **Recommendation:** label this an initial supported-format subset; any required format remains a release gate. glTF packing and Unreal DDS support need the actual preset/importer contract, not an assumption that all ORM-looking images are interchangeable.

**(d) Revised position — Recommendation:** adopt C's JSON resolution detail and memory-encoder route; retain my distinction between lossless canonical maps and lossy delivery, and require full consumer-channel closure. Export errors must identify unsupported fields/formats before committing a partial output set. Publish each file's effective preset, channel mapping, precision, color interpretation and compression settings.

**(e) Settlement evidence — Recommendation:** decode oracle/native exports for each parameter/preset case; compare dimensions, channels and pixels before and after packing. Load the actual `.uztexture`/material in the selected UzEngine route and the selected Unreal/glTF consumer, including SpecularWeight and opacity fixtures. Measure compression error separately. No current source proves the complete proposed engine preset roundtrip.

### D8 — Project container and saving

**(a) Claude's position — Fact (C, D8):** ZIP64 `.uzpaint` with JSON recipe, content-addressed original resources and Zstandard mesh maps; omit regenerable raster caches, save by atomic full-archive rewrite with `.prev`, and target 10% of `.spp` size as a hypothesis.

**(b) Agreement level — Recommendation: disagree.**

**(c) Arguments**

**Recommendation:** Claude's separation of recipe, original resources and disposable caches is strong and should be adopted regardless of container. Its manifest layout is also a better inspection contract than exposing internal SQL tables as the public project schema. I retain SQLite for the mutable working project, with a canonical JSON manifest and content-addressed compressed chunks shared by both representations.

**Fact (C, D1 and D8):** D1 proposes checkpoints after mutating commands, while D8 justifies full ZIP replacement by infrequent large saves. Copying unchanged compressed members avoids recompression, but the proposed writer still constructs a complete new archive. **Hypothesis:** checkpoint frequency and stored resources could make that I/O significant; neither “tens of MB” nor negligible save latency is established by a lossless census of the real assets.

**Fact (official [SQLite application-file guidance](https://www.sqlite.org/appfileformat.html) and [atomic-commit documentation](https://www.sqlite.org/atomiccommit.html)):** SQLite supports updating parts of a project in transactions; its durability model depends on locking, filesystem and flush behavior. **Recommendation:** use it to commit the changed document/chunk index without an obligatory full-project copy, and test the selected journal configuration on supported local filesystems. SQLite is not immunity to corruption, storage failure or application bugs.

| Dimension | Comparison and disposition |
|---|---|
| **Hypothesis — incremental save** | SQLite can update changed rows/pages/chunks; ZIP as proposed rewrites the archive even if only the manifest changed. SQLite journal/WAL overhead and eventual compaction can also be material. A large monolithic compressed BLOB would undermine small raster edits in either design. |
| **Hypothesis — crash/corruption recovery** | ZIP entries make individual resources inspectable, but damaged manifest/directory data and interrupted replacement still need recovery design. `.prev` helps when a prior copy is durable and valid. SQLite transactions handle incomplete commits under their documented assumptions; B-tree corruption may affect multiple objects. Both need content hashes, validated manifests, retained known-good checkpoints and fault injection. Neither format repairs arbitrary disk corruption by itself. |
| **Hypothesis — random layer access** | A manifest can locate a resource in either container. A compressed member/BLOB may require decompression of that chunk; choose tile/chunk boundaries for access locality. Neither container creates cached layer results when caches are absent: evaluating a layer still follows its graph dependencies. SQLite indexes are useful, but do not make arbitrary procedural evaluation constant-time. |
| **Recommendation — AI inspection** | Adopt a stable JSON manifest plus `inspect`, resource listing, integrity check and recipe export. ZIP has a practical advantage for familiar archive tools; SQLite can expose the same manifest without making an AI infer a private relational schema. Inspection format and storage engine should be separate decisions. |
| **Recommendation — C++/Python tools** | Evaluate libzip or another proven ZIP64 implementation for a ZIP route; do not infer full archive support from a compression helper vendored for image decoding. SQLite's C API and Python's `sqlite3` are an alternative. Both routes need the selected Zstandard dependency and explicit tests of the embedded distribution's available modules. Neither integration is already qualified. |
| **Hypothesis — reversal cost** | With one versioned logical manifest, resource IDs and chunk schema, migration is bounded but not free: readers/writers, histories, recovery, path references and compatibility all need roundtrip tests. Once durable projects exist, changing save semantics is more consequential than changing a backend library. |

**Fact (official [libzip documentation](https://libzip.org/)):** libzip documents ZIP64 support and archive creation/modification. **Fact (official [Python 3.13 zipfile documentation](https://docs.python.org/3.13/library/zipfile.html)):** Python provides ZIP64 archive handling. **Recommendation:** store `.zst` members using the ZIP STORE method if generic ZIP tooling must extract them without understanding a ZIP-level Zstandard compression method; extraction and decompression are then explicit separate operations. These tools make Claude's route feasible, not necessarily faster for this workload.

**Fact (SP5; C, D8; A, D8):** the sources identify `.spp` structure/resource/cache categories, but provide no complete lossless byte budget for the proposed replacements. **Hypothesis:** a 90% reduction may be attainable for some recipe-heavy assets, but is not confirmed for projects containing authoritative paint, frozen procedural outputs, original/high meshes, hidden state and retained history. Those resources cannot all be reclassified as disposable cache. A linked-resource project is not comparable to a self-contained `.spp` without accounting for external bytes.

**(d) Revised position — Recommendation:** SQLite working container, canonical JSON manifest, content-addressed original resources and independently compressed tiles/chunks; omit only demonstrably regenerable caches. Preserve authored/frozen raster state and the evaluator/resource versions needed for reopening. Keep the supervisor job ledger separate from project authority. Define a closed, portable save/checkpoint with no uncheckpointed WAL dependency; provide an optional ZIP exchange/inspection export using the same manifest. Treat 10% as a candidate budget pending a matched-policy census, not a proven Phase-1 gate.

**(e) Settlement evidence — Recommendation:** prototype both writers against identical tunic, hat and multi-set body content. Measure first save, repeated one-parameter edits, a raster-tile edit, reopen, layer/resource access, compaction, bytes written, peak disk/RAM and retained-history size. Inject interruption during write/flush/replace and corrupt a resource versus an index. Verify identical state and pixels after recovery. If ZIP meets the agreed checkpoint latency, durability and size budgets with lower maintenance cost, I would accept it; no measured threshold or result exists yet.

### D9 — Python compatibility and asynchronous semantics

**(a) Claude's position — Fact (C, D9):** expose a synchronous `uzpainter` API with a `substance_painter` shim that emits immediate events, pumps callbacks on API calls and accepts computation-control calls without effect.

**(b) Agreement level — Recommendation: disagree.**

**(c) Arguments**

**Recommendation:** agree on the two namespaces, typed errors, fresh native getter state and the distinction between native jobs and the compatibility `StopSource`. C's explicit treatment of detached parameter edits and native readback is valuable and should be retained. The disagreement is observable behavior, not naming or whether a convenience API may block.

**Fact (SP1, `application` and `event` tables; `AD/resources/python/modules/substance_painter/application.py`):** computation enablement has status accessors, a disabling context manager and a status-changed event. **Fact (C, D2 and D9):** C promises no silent no-ops in D2, then makes `enable_engine_computations` a no-op in D9. Lazy evaluation does not reproduce the observable status/event contract without an explicit state model.

**Hypothesis:** synchronous create/open plus immediate callback dispatch changes reentrancy, readiness and exception timing. Pumping only on the next API call can strand a callback registered by a script that returns and waits for completion without another API call. Current recipe coverage does not establish compatibility for the broader mirrored modules or future AI scripts. Preserve actual lifecycle ordering rather than manufacturing an EditionEntered notification before the relevant readiness condition.

**Fact (SP1; C, D9):** runtime version reporting and shipped symbols already differ in the reference. **Recommendation:** publish UzPainter's own version plus a named compatibility profile and capability queries; do not suggest that choosing `0.3.7` proves behavior. **Fact (AP2, AP4, AP7):** the pipeline also has transport, resource-session and per-layer recovery assumptions, including the tunic's distinct C07/F03 masks. Mirroring Python signatures alone does not make the entire surrounding pipeline unchanged.

**(d) Revised position — Recommendation:** retain a synchronous native convenience surface where useful, backed by the same job engine and revision semantics. Implement a compatibility dispatcher with recorded lifecycle/event ordering, readiness barriers, computation-state behavior and callbacks delivered on the documented interpreter thread even when the initiating script has returned. Keep the render thread outside the GIL while computing; never hold a document mutation lock while invoking arbitrary Python callbacks. Explicitly document unavoidable deviations and required adapters.

**(e) Settlement evidence — Recommendation:** record and replay callback traces for create/open/reload/bake, idle completion, cancellation, disabled computations, nested callbacks and failure. Compare event order, state observed inside callbacks, exception class and committed revision. Run the three production scripts through their actual transport adapters, including save/reopen and fresh-resource resolution. A verified pure recipe subset may be offered early, but does not validate a deliberately altered full compatibility surface.

### D10 — MCP server and tool design

**(a) Claude's position — Fact (C, D10):** official Python SDK, stdio and optional Streamable HTTP, compact task-oriented tools, job IDs, single-writer control and an opt-in Python escape hatch.

**(b) Agreement level — Recommendation: agree with changes.**

**(c) Arguments**

**Recommendation:** accept C's focus on discoverable project/stack/bake/export recipes and its refusal to turn every inventory row into a separate tool. This is clearer for agents than a huge flat tool catalog. Retain the SDK in the supervisor from D1 and a small number of typed operation groups/batch endpoints underneath the recipes.

**Fact (C, D10):** the proposed long tail is available only through arbitrary Python. **Hypothesis:** disabling Python would therefore remove output-affecting operations that the native MCP contract is supposed to expose. A compact typed `layer`/`resource`/`project` operation family is an alternative to both hundreds of named tools and mandatory arbitrary-code execution. Native parity coverage and agent ergonomics can coexist.

**Fact (SP6; RS, raw-code findings; RT, MCP discussion):** tool registration, raw-code enablement and actual callable behavior must be distinguished. **Recommendation:** keep `--allow-python` explicit and advertise it as trusted execution, never as path-sandboxed code. Canonical path allowlists protect structured tool inputs; arbitrary Python can invoke other filesystem/process APIs unless an independently enforced execution boundary exists.

**Hypothesis:** transport cancellation, client disconnect and job cancellation are different events. A long synchronous default may be convenient for small edits, but can produce ambiguous outcomes if the client times out after commit. **Recommendation:** return persistent job IDs for long work, allow explicit waiting, keep the writer lease and revision checks precise, and reconcile reconnects by job/revision identity. Support MCP Tasks only after the chosen SDK/client capability combination is verified; retain the job-ID path.

**(d) Revised position — Recommendation:** compact high-level tools plus typed discoverable coverage of required native operations, persistent jobs and single-writer commits. Stdio is the default local transport; HTTP has explicit binding/authentication/session ownership and reconnect behavior. Python is a separate opt-in trust mode. Do not infer a filesystem sandbox from the presence of an allowed-path argument validator.

**(e) Settlement evidence — Recommendation:** complete the pilot entirely through MCP with arbitrary Python disabled, then exercise concurrent writers, lost acknowledgements, reconnect, cancellation and unauthorized paths. Check the exact SDK/client support matrix for Tasks and HTTP. If typed operations cannot express a required instruction, the MCP capability matrix must show a gap rather than silently route to code execution.

### D11 — Mesh import and texture sets

**(a) Claude's position — Fact (C, D11):** import OBJ directly and use FBX/glTF parsers into a raw texturing mesh; preserve corners, avoid cooking/simplification, use material-based sets and MikkTSpace, and retain layers during reload.

**(b) Agreement level — Recommendation: agree with changes.**

**(c) Arguments**

**Fact (UE5; RE, F03/F11):** the reviewed cooking path includes mesh selection/processing unsuitable for blindly preserving every texturing input, and the cooked UZMS-to-runtime path has a documented 32/48-byte layout mismatch. **Recommendation:** adopt C's raw low/high import boundary; this is shared ground. Position-only high-poly ingestion and bake acceleration construction must not pass through the existing opaque fixed-stride BLAS helper unchanged.

**Fact (SP5, project settings table; RS, V46):** Painter documents centimeters as its unit and `mesh_unit_scale` zero/None as using the file unit. **Recommendation:** an internal meter representation is fine, but “metres as given” is not a complete compatibility rule. Translate declared/file units and the Painter parameter semantics explicitly; preserve the effective scale in the reference manifest. Test cage and ray distances after transformation.

**Hypothesis:** “no re-triangulation” correctly protects already triangulated production meshes, but polygonal OBJ/FBX inputs still require a specified triangulation rule or explicit rejection. Material display names can collide; material identity and object/group identity need separate representation. A one-to-one relation between sets and materials is a semantic mapping, not permission to merge equal-looking names.

**Fact (AP2; SP2):** multi-set body assets and UV-tile behavior are separate coverage requirements. **Recommendation:** preserve all objects/transforms, per-corner UV/normal seams, material IDs and mirrored tangent handedness. On reload, remap by stable identities and invalidate dependent maps/caches with a machine-readable report. Reject ambiguous remaps rather than silently attach an old stack to another surface. Avoiding `.uzmesh` in painting does not waive its layout defect if the selected engine export/preview validation later consumes that route.

**(d) Revised position — Recommendation:** adopt the raw import architecture, with explicit unit/triangulation/tangent/material contracts and dependency-aware reload. Use MikkTSpace plus the recorded Painter per-fragment convention as a target, not proof that tangents match automatically. Add multi-object and multi-set fixtures before interpreting pilot success as format support. Treat high-poly RAM/VRAM estimates as unconfirmed until peak parsing, BVH and staging allocations are measured.

**(e) Settlement evidence — Recommendation:** compare imported corner streams and shading for mirrored UVs, hard edges, negative OBJ indices, nontriangles, duplicate material names, instances, unit transforms and multiple texture sets. Run reload/reorder/rename fixtures that preserve or deliberately reject bindings. Compare a baked normal across Painter, UzPainter and the actual consumer using the same triangulation and tangent profile.

### D12 — Engine integration, build and packaging

**(a) Claude's position — Fact (C, D12):** a separate UzPainter repository with its own Zig build links a trimmed UzEngine static runtime, pins clean `19ffb9b`, and takes engine changes only through upstream PRs.

**(b) Agreement level — Recommendation: agree with changes.**

**(c) Arguments**

**Fact (`U/runtime/build.zig`, runtime target near lines 980–984, source lists near 315 and 369):** Zig defines the `runtime` static library and includes the job and DX12 RHI source families. **Fact (`U/runtime/CMakeLists.txt`, approximately lines 119–139 and 235–239):** its MSVC branch empties job/ECS and DX12/DX11 sources and excludes `shader_pipeline.cpp`, `rhi_factory.cpp`, `gpu_mesh.cpp` and `runtime.cpp`, among other files. The committed HEAD also contains the important MSVC exclusions. The CMake static target exists, but that does not make it the complete required runtime.

**Recommendation:** withdraw my round-1 preference for CMake/MSVC as the first integration route. Claude's Zig-first choice is supported by the actual source coverage and is stronger for this repository. My former argument from familiar CPython/MSVC embedding underestimated the work needed to restore the renderer and jobs in the inspected CMake path.

**Fact (`U/runtime/build.zig`, common flags near line 35 and BC7 flags near 717–732; `U/runtime/CMakeLists.txt`, line 15):** the build descriptions also differ in C++ language-mode choices; Zig uses a general C++17 flag with a C++20 exception for BC7, while CMake requests C++20. **Recommendation:** pin the qualified compiler/flags and required modules explicitly rather than assuming both build systems describe interchangeable archives.

**Fact (`U/runtime/build.zig`, library/system linking near 374–380 and 1398–1402; DLL installation near 1178–1184):** the full runtime/tool recipes include Lua and FFmpeg-related dependencies. DLSS and Brix paths have conditional handling elsewhere in the same file. **Hypothesis:** a new slim target can omit unneeded subsystems, but merely linking the existing `runtime.lib` while saying “without FFmpeg/DLSS/Lua” does not prove the final dependency closure. Inspect source inclusion, reachable symbols, link maps and clean-machine DLL loading.

**Fact (`U/docs/engine/06-build-toolchain/04-napi-bridge.md`, build failure discussion; `U/runtime/build.zig`, C-ABI DLL target):** there is a documented failure for a specific Zig/MSVC/N-API static-link configuration and a DLL boundary approach. **Recommendation:** do not generalize it into “all MSVC objects cannot link with Zig archives,” or assume every C ABI combination is automatically qualified. CPython, Embree, CRT ownership, exception boundaries and debug symbols need the actual chosen build configuration tested.

**Fact (scope note above; RE, earlier snapshot):** the current working tree and `19ffb9b` are different, and merge markers reported earlier were not found in the current searched source directories. **Recommendation:** use an immutable, clean, reviewed engine revision that actually contains the required analyzed behavior. Treat `19ffb9b` as a candidate baseline, not a proven clean build of the working-tree features. Upstream PRs are the preferred ownership route; allow a narrowly recorded patch series or integration branch if needed until merges land, rather than forcing either hidden local changes or indefinite dependency on another repository's merge timing.

**Fact (UE3; RE, F08 and revised G02/G12):** format support, readback ownership/pitch/fences, typed UAV/mip access and precision are broader gaps than a feature-query function. **Recommendation:** add the smallest reusable RHI capabilities upstream, while UV rasterization, compositing, dilation and parity kernels remain UzPainter components. Qualify swapchain-free rendering; a hidden window is a transitional engine-preview route only if it passes the intended headless deployment conditions.

**(d) Revised position — Recommendation:** separate repository, custom minimal Zig target, pinned engine/third-party inputs and one-folder Windows distribution. Preserve CPU/GPU/CPython diagnostic artifacts and distribute only the verified dependency closure. Keep CMake as a future option if it is brought to functional parity and proves advantageous. No build success, DLL footprint, WARP support or standalone runtime behavior is established by this read-only critique.

**(e) Settlement evidence — Recommendation:** after execution is authorized in implementation, build a minimal slice containing jobs, shader compilation, DX12 compute/readback, PNG16, CPython and Embree, then inspect its dependencies and run it on a clean supported Windows machine. If CMake is reconsidered, require that identical slice rather than comparing a reduced MSVC test library to the full Zig renderer. Test missing-device handling, debug stacks and cross-boundary memory ownership. Compare immutable source manifests to the inspected engine evidence before declaring a pin suitable.

### D13 — Parity tests and acceptance language

**(a) Claude's position — Fact (C, D13):** four golden-corpus tiers, exact fixed-point channels, proposed tolerances for other domains, owner-controlled tolerance changes and GPU CI with a prospective WARP path.

**(b) Agreement level — Recommendation: agree with changes.**

**(c) Arguments**

**Recommendation:** adopt C's organization: primitive semantics; complete recipes; procedural/native-bake fixtures; and rendered frames. It gives clearer fault localization than a single end-to-end asset gate. My “zero unexplained divergence” is compatible only if it also prohibits explained-but-unapproved divergence. A known approximation does not cease to violate Decision 1 because its cause is understood.

**Fact (Decision 1):** the decision text defers approximate tolerances and requires same textures/render; its metadata status is still `proposed`, while the current user instruction explicitly makes output parity binding. **Recommendation:** the final document should state: **“Default acceptance is equal native decoded texture values and the agreed reference render output. Every divergence is a failure unless an owner-approved, versioned exception explicitly covers that domain and metric. Explained differences are still failures without that exception. Diagnostic metrics do not grant an exception.”**

**Fact (C, D13):** C proposes several numerical thresholds and allows a rounding exception to integer equality. **Hypothesis:** none is justified as an acceptance threshold by a repeated, controlled oracle characterization in these sources. They may be experiment parameters for reporting, not automatic pass criteria. p99 and mean errors alone can conceal bad seams, isolated IDs, alpha defects or a small badly mismatched region; maximum error and affected-pixel/domain counts must remain visible.

**Fact (AP5, native PNG comparisons; RP, precision finding):** recorded Height/Normal export drift is scoped to particular measurements; PNG16 output does not establish that the internal reference channels were 16F. **Recommendation:** classify channels by actual storage/evaluation/export evidence. Repeat the reference within and across sessions, isolate resource/backend differences and compare native values before explaining a discrepancy as harmless float rounding. Do not apply one half-float epsilon to every map by name.

**Recommendation:** use exact integer/ID/coverage checks where specified; use float ULP/absolute/relative and normal angular diagnostics with correct domains; report AO/height scale, color-space and alpha/edge metrics explicitly. For renders, report perceptual error alongside pixel/region differences under a fixed camera/environment/display profile. Qualify compression separately from canonical textures. A perceptual pass must not conceal a different instruction or missing channel.

**Fact (C, D13; UE2/UE3; RE):** WARP support for the required path is proposed, not demonstrated. **Recommendation:** CPU CI should cover schema, API, storage and CPU bake; run shader/render parity on a qualified GPU. Add WARP as another backend only after feature/output qualification, not as evidence that a physical-GPU golden must match automatically. Golden changes may also be necessary to correct a proven bad fixture, not only when Painter changes version; require explicit reviewed provenance rather than silent regeneration.

**(d) Revised position — Recommendation:** adopt the four tiers and the acceptance sentence above. Publish the exact certified corpus/profile and each explicit exception. Release fails on any required unsupported behavior or unapproved difference. Keep oracle stability, UzPainter repeatability and equality to Painter as three separate results.

**(e) Settlement evidence — Recommendation:** establish repeatability distributions and exact-input manifests, then ask the owner to approve any specifically justified exception. Demonstrate that each proposed threshold detects intentional defects in its domain, including sparse seam/alpha errors. No broad “close enough” rule should be inferred from one unstable export or from a good-looking render.

### D14 — Pilot order and delivery gates

**(a) Claude's position — Fact (C, D14 and roadmap):** begin with Wand v1, then Belt v5, recover Tunic v10 later, and expand through hat, bracers and body toward completeness.

**(b) Agreement level — Recommendation: agree with changes.**

**(c) Arguments**

**Recommendation:** change my tunic-first position to Claude's Wand → Belt → Tunic sequence. It is stronger for isolating first failures: start with the compositing/export path, add the current swatch/mask workflow, then prove the approved historical recovery case. Preserve tunic as an early binding milestone rather than postponing its state-reconstruction difficulty until after all procedural engineering.

| Fixture | What the recorded version exercises; what it does not establish |
|---|---|
| **Fact (AP2, section 6) — 11-Varinha v1** | One 2048 texture set; uniform fills/bitmap masks and external Blender normal/AO in the modern sync workflow. No Painter bake is recorded; absence of a record is not proof that it never ran. **Recommendation:** use it for import, resource binding, basic composition, export and save/reopen. |
| **Fact (AP2, section 6; AP4, belt v5 row) — 23-Cinto v5** | One 2048 set and `base_tex` leather swatches with roughness adjustments. **Recommendation:** add the production masks/swatch workflow and spatial coverage checks. Do not confuse v5 with earlier belt/bracer procedural Leather Damaged recipes, or treat imported masks as proof of native 3D generator masks. |
| **Fact (AP2; AP4, approved recovery) — 18-Tunica v10** | One 4096 set, 22 fills, cloth/lining groups, Height behavior and C07/F03 using different recovered piping resources; Blender normal and recorded Painter auxiliary maps. **Recommendation:** prove per-layer resource identity, group composition, recovery and double-sided render state. External maps do not prove native high-poly baking. |
| **Fact (AP2; AP4) — locked bracers and historical hat v5** | Bracers use Leather Damaged/Bronze Armor and mesh-dependent masks; historical hat v5 records procedural relief/generators. **Recommendation:** use them early to test the proprietary-content and 3D-mask feasibility assumptions that the first three pieces can hide. |
| **Fact (AP2; AP4; RP) — current hat v8** | A bitmap sync stack with 43 layers in five groups, added SpecularWeight and retained historical project state. **Recommendation:** use it for current channel/export and layer-state coverage; do not label its current visible recipe equivalent to the older procedural hat. Its artistic approval remains separate. |
| **Fact (AP2, body row) — body v6b and its recorded dependencies** | Three named 4096 texture sets, per-set maps and smart/sync history. **Recommendation:** use it for multi-set routing, resource closure, native-map comparisons, memory and save/reopen stress. Neither the wand, belt nor tunic supplies this coverage. |

**Hypothesis:** tunic-first reduces the risk of neglecting approved-state reconstruction, but increases the number of simultaneous failure causes. Wand-first can produce a convincing demonstration while leaving native bake, generators, proprietary materials, multi-set support and Iray unresolved. Both risks are addressed by parallel feasibility gates and explicit coverage, not by calling an easier pilot complete replacement.

**(d) Revised position — Recommendation:** order delivery as (1) contract/provenance and procedural/render/native-bake feasibility; (2) engine/runtime foundation; (3) Wand → Belt → early Tunic recovery with save/reopen and captures; (4) native bakers plus locked procedural fixtures and actual engine consumers; (5) current hat and multi-set body; (6) all remaining required features, stress and standalone packaging. Feasibility work may overlap pilot implementation, but full-replacement claims cannot precede closure of mandatory gaps. Treat Claude's week estimates as hypotheses, not committed delivery evidence.

**(e) Settlement evidence — Recommendation:** create a fixture-to-capability matrix and record which first failure each pilot exposes. Before committing to a long rollout, show a bounded feasibility result for a required proprietary material, native high/low bake and the agreed render target. If tunic resource recovery blocks or reveals a fundamental schema error, move that investigation earlier without abandoning the simpler smoke tests. Pilot success grants software evidence, not new artistic/rig/alpha approval for existing assets.

## 2. Errors or unsupported claims in the Claude proposal

**Recommendation:** distinguish a contradicted statement from an untested design hypothesis. Claude explicitly labels several estimates and raises legal questions; those are not fabricated measurements. The corrections below target the unsupported inference, conflicting behavior or prematurely assumed release result.

1. **Fact (C, D2; RS, inventory recount):** “572 public symbols” is not what the audited count establishes; it counts physical inventory rows. **Recommendation:** replace it with an enumerated behavior/symbol coverage manifest and retain 572 only as the inventory-row statistic.

2. **Fact (C, D2; SP1, reachability and plugins):** the assertion that the whole omission list has no output effects conflicts with documented JS shader/export functions and executable plugin startup. **Recommendation:** distinguish widgets from script lifecycle and output controls; justify omissions per behavior, including script-context dependencies. Native alternatives must not be described as unchanged compatibility with omitted calls.

3. **Fact (C, D2 and parity-limit table; SP1/SP2):** no public stroke-authoring Python API is documented. **Hypothesis:** C's further conclusion that an instruction sequence cannot contain strokes is unsupported; native AI instructions or preservation of painted state are different surfaces. **Recommendation:** explicitly retain or obtain a scope decision for that product requirement; do not derive its exclusion from the API inventory.

4. **Fact (C, D4; SP2, resolution modes):** the capture strategy chooses a fixed resolution despite resolution-dependent procedural evaluation. **Hypothesis:** “exact by construction” and later qualification by resampling do not establish equality at other resolutions/inputs. **Recommendation:** certify a full output signature and separate snapshot preservation from editable procedural parity, as specified in D4.

5. **Fact (C, D4 option analysis; official developer terms cited in D4):** the categorical non-redistributability premise is too strong. **Recommendation:** replace it with “UzPainter's SDK access, applicable terms, approval, compatible version and redistribution rights are not confirmed.” An authorized DLL dependency would not inherently violate a one-folder standalone requirement. **Hypothesis:** availability for this product remains unresolved, so neither categorical rejection nor assumed entitlement is justified.

6. **Fact (C, executive summary/D5; installed `AD/embree3.dll`; upstream documentation cited in D5):** the installed library is Embree 3.13.5; C proposes another major version and states CPU availability too broadly. **Hypothesis:** that presence neither proves Painter's baker implementation nor bit identity on arbitrary machines. **Recommendation:** state the qualified CPU/ISA/build matrix and test repeatability; preserve the valid CPU-first rationale without turning it into a universal guarantee.

7. **Fact (C, D6; AP2, shader-identity qualification; RP, render-contract findings):** `open-pbr` is promoted to a confirmed current/default reference although its cited pipeline evidence marks identity as inferred. **Recommendation:** capture the actual project shader and render state before selecting the profile. The proposed neutral profile and Iray exclusion are owner choices, not facts recovered from the current assets.

8. **Fact (C, D6; installed shader/library paths and official Shader API cited in D6):** source availability is established, but the complete host renderer, port effort and redistribution rights are not. **Hypothesis:** “a few hundred lines,” guaranteed inferiority of independent derivation and absolute impossibility of cross-GPU pixel equality are unmeasured claims. **Recommendation:** retain them only as explicit hypotheses, separate legal exposure from technical feasibility, and select a route through the evidence gate in D6. C's acknowledgement of legal risk is correct; it does not resolve the route.

9. **Fact (C, D3/parity-limit table; AP5, native PNG16 drift; RP, precision finding):** the measured exported differences do not prove that all implicated internal channels were 16-bit float. **Recommendation:** record actual channel formats, quantization points and stable-oracle evidence; do not convert the observed export drift into a generic float tolerance or an automatic integer rounding allowance.

10. **Fact (C, D1/D8):** per-mutation checkpoints and an infrequent-save justification coexist without a measured checkpoint workload; the stated ZIP writer rewrites the archive. **Hypothesis:** its expected size and latency are not confirmed. **Recommendation:** describe it as full replacement with reuse of compressed members, distinguish incremental logical history from incremental physical I/O, and measure both. The 10% figure is properly introduced as a hypothesis, but using it as a fixed milestone gate before a lossless content census is premature.

11. **Fact (C, D2/D9; SP1, computation status and events):** “nothing is silently a no-op” conflicts with accepted computation-control calls that have no effect. Immediate lifecycle events also intentionally change the asynchronous contract. **Recommendation:** implement observable state/readiness/dispatch behavior or disclose a restricted compatibility profile. Successful execution of a few synchronous recipes would not prove general event compatibility.

12. **Fact (C, D10; SP6/RS, raw execution):** required long-tail operations are delegated to optional arbitrary Python. **Hypothesis:** a tool path allowlist cannot constrain everything that Python code can do, and disabling it removes that operation coverage. **Recommendation:** provide typed native coverage and label arbitrary Python as trusted execution; retain any separate OS sandbox as an explicit, independently tested feature.

13. **Fact (C, D11; UE5; RE, F03/F11):** avoiding `.uzmesh` protects the painting import route, but does not prove correctness of a downstream consumer that uses it. The inspected importers also have route-specific mesh selection and conditional processing. **Recommendation:** avoid universal claims about all import paths; specify corner preservation, units and triangulation for each route, and repair/qualify any cooked route used by export validation. Required format support cannot be inferred from using a parser library.

14. **Fact (C, D12; current `U/runtime/build.zig`, `U/runtime/CMakeLists.txt` and Git metadata):** a clean HEAD pin and the analyzed modified snapshot are not interchangeable; the full Zig target also contains dependencies the proposed slim product excludes. **Recommendation:** pin the actual tested capability set and verify the slim link/DLL closure. Earlier conflict-marker evidence must be dated, not presented as a fresh observation. The specific documented Zig/MSVC failure must not be generalized to every ABI combination. **Recommendation — correction to my own proposal:** withdraw CMake/MSVC-first for the reasons documented in D12.

15. **Fact (C, D7; RE, F12; AP5/RP, current hat export):** the proposed engine-material mapping is not backed by a complete demonstrated consumer roundtrip and omits a concrete SpecularWeight disposition. **Recommendation:** publish channel-by-channel reader support, including alpha, normal domain and source-versus-cooked precision; repair or reject unsupported conversions before claiming the engine preset is complete.

16. **Fact (C, roadmap; AP2/AP4):** the first three proposed pieces each have one texture set; Belt v5 uses the modern swatch workflow, and current hat v8 differs from historical procedural hat v5. **Recommendation:** do not count these fixtures as interchangeable coverage for native bake, proprietary materials, 3D generators or multi-set behavior. Add the specifically versioned bracer/historical-hat/body fixtures. **Recommendation — correction to my own proposal:** adopt the simpler pilot order while retaining early feasibility and approved-tunic recovery gates.

## 3. Consolidated owner questions

**Recommendation:** the following questions supersede duplicates in C section 5 and A section 5. `C-Qn` and `A-Qn` identify the original question numbers; every original question is represented. They are decisions for the later architecture agreement, not requests to authorize work already performed in this critique.

1. **Recommendation — equality contract (C-Q1; A-Q2):** what exact comparison domains define acceptance: native decoded maps/render pixels, encoded-file bytes where relevant, and which reference machine/backend? If a controlled oracle is unstable, who may approve a specific bounded exception, on what evidence, and with what versioned record? Until then, retain equal output with no implicit allowance.

2. **Recommendation — render reference (C-Q12; A-Q1):** is the binding render result the actual Painter real-time viewport or the current Iray review path? Confirm the captured shader, HDRI, camera, tone/display/color-management state and comparison profile rather than assuming `open-pbr` from channel names. If Iray remains required, which demonstrated route should resolve that unclosed capability?

3. **Recommendation — shader implementation and oracle use (C-Q2/C-Q5; shader/oracle part of A-Q3):** after applicable agreements and permissions are established, choose a licensed direct port or independently sourced implementation with an appropriate provenance process. Can the licensed reference installation and exact resources remain available for authorized golden recording, migration and disputed-fixture investigation through certification? Confirm the permitted use of oracle inputs/outputs separately from permission to redistribute code or content.

4. **Recommendation — procedural engine and asset distribution (C-Q3/C-Q4; procedural part of A-Q3):** investigate a distributable Substance Engine arrangement or fund independent certification of the required resource families; which route and dependency budget should be pursued? Separately establish permitted internal captures, compatibility aliases/names and redistribution of source assets, smart-material recipes and frozen outputs. What is the disposition of unsupported editable resources? An art substitution changes the instruction/output contract and requires its own recorded decision.

5. **Recommendation — milestone versus full release scope (C-Q8; scope part of A-Q3):** may an initial release explicitly support a bounded recipe subset while strokes, arbitrary proprietary graphs, UV tiles, projections, instances or other output-affecting domains remain visibly uncertified? Identify what must be complete before calling the product a full Painter replacement; do not infer an exemption from the absence of an Adobe Python entry point.

6. **Recommendation — migration and preserved state (A-Q5):** is verified extraction/reconstruction of existing `.spp` projects acceptable, including hidden layers, authoritative raster state, resource bindings and render settings, or is direct native `.spp` reading required? Either route must prove output/state closure and leave subsequent standalone operation independent of Painter.

7. **Recommendation — pilot and corpus gates (C-Q7; A-Q4):** ratify Wand v1 → Belt v5 → early approved-Tunic v10 recovery, with early locked-bracer/historical-hat procedural feasibility, current hat v8 channel coverage and body v6b multi-set coverage. Confirm which exact versions are immutable reference fixtures and keep software certification separate from their existing artistic, alpha and rig approval status.

8. **Recommendation — engine ownership and baseline (C-Q6):** which clean engine revision or integration branch contains the required validated sources, and who owns upstreaming the RHI/build fixes? Is a reviewed, temporary patch series acceptable while upstream merges are pending? Prefer an evidenced pin to naming `19ffb9b` without demonstrating that it contains the required features.

9. **Recommendation — supported Windows deployment and CI (C-Q9/C-Q10; A-Q8):** define the minimum Windows/CPU/GPU matrix, available GPU runner and whether complete software rendering without a compatible physical GPU is mandatory. Confirm one-folder standalone distribution versus a later single-file requirement. CPU baking alone does not settle compositor/viewport support; WARP remains an unqualified candidate until tested.

10. **Recommendation — export consumers (C-Q11; A-Q7):** specify the actual Unreal version/importer and UzEngine material reader that will certify output. Confirm source precision, ORM, normal convention/reconstruction domain, alpha, SpecularWeight, Height/Thickness, mip rules and BC/DDS expectations. Which channels may a consumer omit, if any, and how must that omission be reported without claiming full material parity?

11. **Recommendation — compactness, portability and recovery (C-Q13; A-Q6):** after the matched-content census, choose the maximum project-size ratio, checkpoint latency/history policy and recovery requirements. Is 10% of the corresponding `.spp` an acceptable target if measurements support it? Confirm self-contained versus explicitly linked resources and include linked bytes in comparisons. Choose the container using the same content/durability workload, not size alone.

12. **Recommendation — script trust (A-Q9):** should arbitrary Python be a trusted opt-in local capability or run inside an independently enforced restricted environment? What functionality must remain available through typed MCP with Python disabled? A path allowlist for normal tools does not settle this execution boundary.

13. **Recommendation — pipeline cutover governance (C-Q14):** which software/corpus/consumer gates authorize the later pipeline cutover, and when should the Assets3D rule requiring painting in Substance be amended? Keep the existing production rule until the selected gate is met; changing it is a later integration action, outside this critique's write scope.

**Fact (this round's source inspection and artifact scope):** this document records architecture analysis and proposed measurements. No engine, Painter or Blender build/run, bridge operation or Assets3D collaboration post was performed; this round writes only `P/docs/analysis/architecture-discussion/04-astra-critique.md`.

