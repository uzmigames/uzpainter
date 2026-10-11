# 03 — Reconciliation of the two architecture positions (Claude, round 2, 2026-10-10)

Inputs: `01-claude-proposal.md` (mine) and `02-astra-position.md` (Astra, read in full for this round). Labels as before: **Fact** (path), **Hypothesis**, **Recommendation**. "Astra's strongest point" quotes or paraphrases the argument I found hardest to answer. Paths: `UZP`, `A3D`, `UZE`, `PAINTER` as in 01.

## 0. Summary

- Agreed as written: **5** — D3 (data model), D5, D6, D7, D11.
- Agreed with changes to my position: **8** — D1 (adopt Astra's supervisor/worker split as the `--mcp` mode; my single process becomes the worker), D2 (capability manifest with a third category; selection kept as inert state), D4 (procedural backend seam; captures demoted to a migration/snapshot mechanism; three-way owner question), D8 (adopt SQLite + per-blob zstd; my JSON manifest stays the canonical document; ZIP becomes an export/inspection view), D9 (facade must reproduce output-affecting Painter quirks; native API may be safe), D10 (idempotency keys and revision preconditions; job ids before Tasks), D12 (CMake/MSVC-family toolchain decided by a Phase 0 build test; fork + patch queue with upstream submission), D13 (zero unexplained divergence as the default gate; my numbers become proposed exceptions the owner ratifies per domain).
- Disagreed: **1** — D14 (pilot order and whether to publish duration estimates); narrowed to an owner preference, settling evidence stated.
- Both papers converge on: dedicated Painter-semantic evaluator on UzEngine RHI, realtime-viewport (not Iray) render reference, CPU baker first, `uzpainter` + `substance_painter` facade, official Python MCP SDK in-process, raw mesh import bypassing `.uzmesh`, clean engine pin, Painter golden corpus.
- Consolidated owner questions: 16 (§2), 13 of them marked as owner decisions by both architects.

## 1. Decisions

### D1 — Runtime topology

(a) **Astra:** one executable with two roles — an MCP/CLI supervisor (embedded CPython + official SDK, job journal) and an isolated engine worker (same exe, private framed IPC) that alone owns the project, GPU and commits.

(b) **Agree with changes.**

(c) Arguments.
- Astra's strongest point: a native fault or GPU device removal inside the worker must not kill the MCP session; the supervisor "keeps MCP responsive, reconciles the last durable commit, reports interrupted/unknown outcomes honestly and recovers a checkpoint" (`02-astra-position.md` D1 Position). With stdio MCP, a dead server process ends the AI host's session with the tool; whether the host relaunches it mid-session is **not confirmed** for Claude Code or other clients, so an in-process crash can end the agent's working session. DX12 device removal also forces device re-creation, which is cleaner in a fresh process (**Hypothesis**).
- My points, still valid: a single process is simpler to debug and ship; large rasters never cross IPC; one interpreter instance; the pipeline's recorded crashes were inside Adobe's code, not ours (`A3D\Docs\Lessons\operation-painter-export-mixed-ao.md`). Astra concedes the overhead risk: "duplicated interpreter/runtime overhead and IPC ordering can outweigh isolation for small jobs; measurements are not confirmed" (D1 Risks).
- Evidence on IPC cost: commands and results are small JSON; only `capture` returns an image, and an image can be a file reference plus a downscaled block (both papers already say rasters travel as artifact references). Debuggability: two processes, but the worker is exactly my single-process design and runs standalone under `run`.

(d) Revised position: keep my single-process design as the **worker**, and add Astra's supervisor as a thin relay for the `--mcp` entry point. The supervisor forwards `tools/call` to the worker over a private pipe using the same JSON shapes the tool handlers already consume (no second protocol vocabulary), keeps a durable job journal, relaunches the worker after a crash and answers in-flight calls with "interrupted/unknown, last committed revision = N". `UzPainter.exe run script.py` and the CLI stay single-process (worker role only). Changed because the session-survival argument is decisive for an AI-operated tool and the cost is bounded by reusing the tool-call shapes as the IPC vocabulary. Mutations carry idempotency keys so a relaunch never replays a non-idempotent mutation (Astra D1/D10).

(e) Settling evidence for what remains (overhead): Phase 2 prototype — kill the worker during a bake and during a save; assert the MCP session continues, the autosave revision is restored and the interrupted call reports correctly; measure added latency per tool call and per 4K capture (file reference vs inline image). If per-call overhead exceeds a few milliseconds or recovery fails, revisit.

### D2 — API scope for v1

(a) **Astra:** inventory-driven output-compatible facade; every symbol classified as *supported*, *desktop-only omitted* or *output-affecting release gap*; keep selection/active-stack as script context; keep all `display`, `application` toggles, plugin loader; omit Qt objects; typed unsupported errors; a verified `js` compatibility subset.

(b) **Agree with changes.**

(c) Arguments.
- Astra's strongest point: a third category is needed — "output-affecting release gap … blocks the affected parity claim; it is not silently removed from the product requirement" (D2 Position). My two-way rule (mirror or omit) hid strokes, warp projection and UV tiles behind "v1 scope"; they are gaps, and the capability manifest must say so.
- On selection: Painter's `set_selected_nodes` changes no output (**Fact**, inventory `UZP\docs\analysis\substance-parity\01-python-api-inventory.md`, selection functions act on the UI), so keeping it as inert, readable state breaks fewer scripts than raising; it is not "pretending success" because the state reads back. Same for `set_collapsed`.
- On `js.evaluate`: Astra wants "a documented compatibility subset"; the pipeline's only JS uses are `alg.version.painter` and `alg.project.isOpen()` inside the community bridge (**Fact**, `UZP\docs\analysis\substance-parity\06-mcp-tools-inventory.md` §2), which UzPainter replaces entirely. A string-matched JS subset is machinery with no caller; I keep `js.evaluate` raising, with the native typed equivalents for shader/display state we both propose.
- On `switch_to_mode`: Painter's Visualisation mode pauses the layer engine (**Fact**, `A3D\Docs\Lessons\operation-painter-exclusive-mode.md`); UzPainter evaluates lazily and has no mode, so the call stores a logical mode and affects nothing — documented, not silent.

(d) Revised position: adopt the three-way capability manifest (generated from the inventory plus the Substance review's inherited-member corrections, `UZP\docs\analysis\reviews\substance-parity-astra-review.md` F11), keep selection/collapse/mode as inert stored state, keep Qt and `js` raising. What changed: the manifest and the explicit "release gap" status for strokes, warp, UV-set projection, UV tiles, vector/font sources until implemented.

(e) No remaining disagreement.

### D3 — Layer stack model and compositing semantics

(a) **Astra:** dedicated Painter-semantic document with all 12 node kinds, stable native ids plus checked compatibility handles, full blend set calibrated by oracle, per-node resource bindings (tunic C07/F03), incrementally invalidated tile/channel DAG with memory admission, precision by channel format (UNORM16 preserved; FP16 not an automatic replacement), quantization at defined boundaries, UV tiles first-class.

(b) **Agree** (data model and semantics identical in substance).

(c) Astra's strongest point: "FP16 is not an automatic replacement for UNORM16" and evaluation must be "by tile/channel with finite memory admission" (D3 Position). My paper said fp32 math with storage-format emulation but evaluated whole channels; 8K sets or the body's three 4K sets need tiling.

(d) Revised position: same data model; evaluator structured as a tile/channel DAG with a VRAM budget (engine review G05), fp32 or integer intermediates, quantisation only at the storage-format boundaries Painter uses (decided by Tier 0). Per-node resource bindings by content hash with explicit migration aliases (`A3D\...\18-Tunica\report.json → painting_v10.source_recovery`, **Fact** via the pipeline review finding 4). UV tiles: model from day one (both agree); shipping order is a D14/owner question.

(e) None.

### D4 — Procedural content strategy

(a) **Astra:** a procedural backend interface; an independently implemented HLSL subset for the migration corpus (Mask Builder Legacy, Mask Editor, Metal Edge Wear, Dirt, Sharpen, felt/leather/burlap sources, Leather Damaged, Bronze Armor, forged-iron recipe and transitive inputs), certified per resource over meshes/resolutions/parameters; a licensed runtime only if distribution rights are established; frozen outputs preserve snapshots but cannot certify re-evaluation; "parity means equal native channel outputs from equal effective inputs, not similar appearance".

(b) **Agree with changes.**

(c) Arguments.
- Astra's strongest point: "frozen outputs can preserve an old approved snapshot, but cannot certify editable reevaluation after a mesh, seed or parameter change" (D4 Position). True: my captures reproduce the recipe corpus exactly only at the captured parameter sets; a new instruction with other parameters is unsupported.
- My point, still valid: captures are the cheapest exact mechanism for migrating the approved/locked assets (tunic has no procedurals; bracer r9 is LOCKED with fixed parameters — **Fact**, pipeline review finding 3), and mesh-map generators cannot be captured at all, so both papers reimplement the same eight generators.
- Legal (both routes, parity cost; the owner decides):
  - **Route A — derived content.** Capture procedural outputs and extract smart-material recipes through the owner's Painter licence; ship them with UzPainter. Parity: exact for captured parameter sets, calibrated for generators. Exposure: redistribution of Adobe-derived content; terms **not confirmed** by either paper ("installation access does not establish redistribution rights", Astra D4 Risks).
  - **Route B — clean room.** Ship no Adobe-derived content; implement generators and the top-used noises from parameter semantics and public descriptions, calibrate black-box against Painter; provide a local `capture-assets` command so a user who owns Painter can create captures on their own machine for their own projects. Parity cost (Hypothesis): grunges exact only when captured locally; generator calibration longer; no shipped smart materials, only locally extracted ones.

(d) Revised position: adopt Astra's backend seam (`IProceduralBackend` with `captured`, `hlsl`, and a reserved `substance_runtime` slot) and the per-resource certification. Captures remain the migration/snapshot mechanism and are labelled exactly that; they never carry a "supported for re-evaluation" status. Sharpen joins the reimplementation list (hat v8 uses it — **Fact**, `UZP\docs\analysis\assets3d-pipeline\04-painting-recipes-and-materials.md` §4). The route (A vs B) is an owner question (§2 Q4).

(e) Settling evidence for the remaining gap (whether calibrated generators can reach equality): Tier 2 sweeps on the eight generators; report per-parameter-set max |Δ|; if any resource cannot reach the ratified bar, it stays a visible release gap (both agree).

### D5 — Baking

(a) **Astra:** both backends under one baker contract, CPU first as the reference, DXR certified separately; all ten bakers with oracle-discovered property descriptors and current defaults; AA as explicit sample accumulation; automatic cage flagged as a gap; transactional settings across linked sets; atomic publication per input revision; diagnostics separate from the compatible maps.

(b) **Agree.**

(c) Astra's strongest point: "publish all maps atomically for their input revision or report failure/cancellation without a partial authoritative bake" and "transactional native bake-setting changes must cover every affected linked set" (D5 Position) — my paper had jobs and evidence outputs but not these two guarantees.

(d) Revised position: unchanged backend choice (Embree is my concrete pick for Astra's "CPU BVH"; Painter ships `embree3.dll` — **Fact**, `PAINTER\embree3.dll`); add linked-set transactional settings, atomic per-revision publication, and "automatic cage = release gap". Record the oracle's bake backend (Painter CPU) in every golden (Adobe documents CPU/GPU AO differences — **Fact** via `UZP\docs\analysis\reviews\technology-options-astra-review.md` finding 1).

(e) None.

### D6 — Preview and render parity

(a) **Astra:** dedicated Painter-compatible viewport on engine RHI; owner ratifies the realtime viewport (not Iray) as the reference; record the actual shader hash; fixture = 1200×1200, `Studio White Soft.exr` by hash, rotation/exposure 0, no ground/shadows, RGB 89 background, `ToneMappingFunction.Linear`, pinned OCIO config, Default/sRGB; "shader text alone is insufficient" (host libraries, sparse textures, IBL data); resolve derivative/distribution permissions before shipping translated source.

(b) **Agree.**

(c) Arguments.
- Astra's strongest point: "shader text alone is insufficient … reproduce its supporting libraries, sparse-texture semantics, BRDF/LUT/IBL data and final composition" and the shipped loose `.glsl` files do not include every imported library (D6 Position, Fact). Complement from my session: the library source *is* shipped, inside `PAINTER\resources\shader-doc\lib-*.html` as `<pre>` blocks (~346 K characters across 57 files, **Fact**), [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\shader-doc\lib-env.html; PAINTER\resources\shader-doc\lib-normal.html; PAINTER\resources\shader-doc\lib-utils.html.] Engine-side inputs the shader expects must be reproduced from the HDRI by UzPainter — Astra is right that this is more than a port.
- Legal routes (owner decides): **Route A** port the shipped GLSL to HLSL (headers say "ADOBE CONFIDENTIAL" — **Fact**); highest parity. **Route B** clean room from Adobe's public shader-API documentation and standard references (GGX/Smith/Schlick, SH irradiance, importance-sampled IBL) calibrated black-box; parity cost (Hypothesis): larger residuals in specular/IBL lobes and longer calibration; both papers agree Iray is not reproducible either way.

(d) Revised position: unchanged target and fixture (identical in both papers); add Astra's requirements to record the shader hash (`pbr-metal-rough.glsl` SHA-256 `A434A2B2…`, `open-pbr.glsl` `327CE488…`, **Fact** per Astra) and to include shader/display state in project recovery and capture receipts.

(e) None on architecture; the legal route is §2 Q4.

### D7 — Export

(a) **Astra:** Painter JSON compiled into a typed, inspectable export plan; per-root presets, tokens, all padding modes, exact dithering/resize vs oracle; mandatory inline PNG16, PBR MR, Unreal packed ORM, glTF; translate the 34 presets through verified semantics; reject unknown sources (`Mixed_AO`) before dispatch; `.uztexture` generated directly with correct mips; PNG16/float sidecars where the engine cannot hold precision; negative-Z normals cannot survive positive-Z reconstruction; SpecularWeight and opacity preserved; staged outputs and atomic manifest.

(b) **Agree.**

(c) Astra's strongest point: the pipeline's crash came from the identifier `Mixed_AO`, while the documented virtual map is `AO_Mixed` (**Fact**, `UZP\docs\analysis\substance-parity\04-export.md` §2 vs `A3D\Docs\Lessons\operation-painter-export-mixed-ao.md`); validating the plan before any GPU work would have turned a crash into an error. Also the negative-Z point: BC5 + Z reconstruction discards information the authoring normal may carry.

(d) Revised position: unchanged presets and UzEngine mapping (both papers derive the same ORM/BC5/albedo-alpha contract from `UZP\docs\analysis\uzengine-renderer\04-material-and-texture-standard.md`); add plan validation before dispatch, the negative-Z domain check (reject or route to an extended format), and "SpecularWeight has no slot in the engine's fixed-PBR path → reported as a consumer gap, not exported silently".

(e) None.

### D8 — Project file format

(a) **Astra:** SQLite as the single portable `.uzp` at rest, zstd per independently addressable chunk, canonical JSON document plus typed tables, content-hashed immutable resources and per-node bindings, authoritative raster planes at native precision, transactional incremental saves (insert changed chunks, commit a revision), rollback journal (no WAL for portable files), current and previous checkpoints addressable, inspection through the app and plain SQLite; compact budget only after a measured census.

(b) **Agree with changes** (I move to SQLite).

(c) Arguments.
- Astra's strongest point: "recipe-only saving is insufficient for paint strokes, unavailable resources and unproved procedural reevaluation" so authoritative raster planes must be stored, and "implement incremental saves by inserting changed immutable chunks and committing a new document revision transactionally" (D8 Position). My own D1 recovery story depends on an autosave after every mutating command; with a ZIP rewritten per save, autosave cost scales with the project (the body's masks alone are hundreds of MB of originals, **Fact** sizes in `UZP\docs\analysis\assets3d-pipeline\05-export-and-consumers.md` §5), while a SQLite commit of a changed manifest row and new blobs is kilobytes.
- Corruption/atomicity: ZIP temp+rename is atomic at file level but offers only per-member CRC; SQLite's journal gives transaction recovery (both cite `UZP\docs\analysis\reviews\technology-options-astra-review.md` findings 19–21).
- Random access: equivalent (central directory vs indexed rows).
- AI inspectability (my original argument for ZIP): `unzip -l` and viewable PNGs are convenient, but `sqlite3` is equally ubiquitous and the canonical document is JSON in both designs; the convenience can be preserved as a derived view.
- Tooling: miniz is already vendored via tinyexr (**Fact**, `UZP\docs\analysis\uzengine-renderer\06-thirdparty-and-image-io.md` §1); SQLite is one public-domain amalgamation file to add (Hypothesis on effort: hours).

(d) Revised position: `.uzp` = SQLite (rollback journal for portable files; a `checkpoint` closes any WAL before a file is called portable), tables `document(revision, json)`, `blob(sha256, mime, zstd bytes)`, `binding(node_id, slot, sha256, alias)`, `plane(set, channel, tile, revision, zstd bytes)` for authoritative rasters, `revision` history with current/previous retained and bounded. My JSON manifest remains the canonical document (stored as a row; `uzpainter inspect` prints it). `uzpainter export-bundle` writes the ZIP + JSON + PNG view for humans/AIs who want files. What changed: the container, because incremental transactional saves are what make per-command autosave affordable and crash recovery provable; what did not change: the storage-independent canonical document, content-addressed originals, no raster cache by default, and the measured size census before any budget is promised (my "≤ 10 %" stays a Hypothesis to validate on hat v8 and the three body versions, not a target).

(e) None on container; the compact budget is §2 Q7, settled by the census Astra proposes (lossless dependency census vs a compacted `.spp` of the same content).

### D9 — Python API shape

(a) **Astra:** `uzpainter` native + `substance_painter` facade; scripts run in the worker unchanged where supported; preserve signatures, enums, events, readiness (`ProjectOpened` ≠ edition readiness), callbacks on the worker's Python event thread; typed errors; mutation validation by fresh readback; "do not silently fix a Painter quirk in the compatibility namespace when it can change subsequent output".

(b) **Agree with changes.**

(c) Astra's strongest point: the quirk rule. Setting `active_channels` after `set_source` resets sources in Painter (**Fact**, `A3D\Docs\Lessons\painting-fill-channel-order.md`); a replayed instruction sequence that triggers it must produce the same (white) output in UzPainter, or parity breaks. My paper proposed the safe behaviour everywhere (LAY-01); that is right for `uzpainter` and wrong for the facade.

(d) Revised position: the facade reproduces output-affecting quirks verified in Tier 0 (channel toggle reset, mask-context `None` rules, insertion constraints); the native API keeps values on toggle. Everything else as in 01 (mutation contract, explicit stack addressing, persisted uids, synchronous callbacks). Added from Astra: `execute_python`/`run` capture `result`, stdout and stderr separately; `ProjectOpened` fires before `ProjectEditionEntered` even in the synchronous emulation.

(e) None.

### D10 — MCP server

(a) **Astra:** official SDK in the supervisor's embedded interpreter; stdio default, loopback HTTP optional with auth/origin policy; typed tools plus `sync`/batch as transparent transactions; durable job ids (`job_status/result/cancel`) first, Tasks adapter only after a demonstrated SDK/client pair (the SDK v2 migration guide says the redesigned Tasks extension is not implemented yet — **Fact** per Astra's citation); one mutation lease per project; idempotency keys and revision preconditions; independent allowlists; arbitrary Python opt-in.

(b) **Agree with changes.**

(c) Astra's strongest point: "include idempotency keys and revision preconditions so AI retries do not duplicate mutations" and "cancellation acknowledges intent, while the final receipt reports whether work actually stopped or committed" (D10 Position). My tool list lacked both; with the supervisor relaunching workers (D1), they become necessary.

(d) Revised position: my ~25 task-shaped tools plus `run_python` stand; add `idempotency_key` and `expected_revision` to every mutating tool, per-project mutation lease instead of a global lock, receipts with `committed_revision`. Tasks deferred as both papers say.

(e) None.

### D11 — Mesh import and texture sets

(a) **Astra:** raw import on vendored parsers, OBJ first, complete FBX/glTF scene ingestion before advertising; MikkTSpace per-fragment target proven by fixtures; no cooker transformations; auto-unwrap treated as an output-affecting requested operation (release gap until proven); per-set certification; transactional reload.

(b) **Agree.**

(c) Astra's strongest point: `project.Settings(auto_unwrap_settings=…)` is a documented, output-affecting import operation; xatlas in the engine is not Painter's unwrapper, so it is a release gap, not a convenience (D11 Position). I had not classified it.

(d) Revised position: unchanged; add auto-unwrap to the release-gap list and the mirrored-UV supported-domain note.

(e) None.

### D12 — Engine integration and packaging

(a) **Astra:** selective UzPainter target from a resolved engine pin with a documented patch queue; add no-swapchain targets, UV raster, compute composition, dilation, precise readback, 16-bit UNORM formats, mip/subresource UAV, array-vs-cube descriptors; **CMake/MSVC, C++20, one compiler/runtime family**; C ABI at any mixed boundary; one folder, verified on a clean offline machine.

(b) **Agree with changes** (toolchain and fork policy).

(c) Arguments.
- Astra's strongest point: "one consistent native compiler/runtime family for the standalone embedding target". `python313.dll` and the vendored MCP SDK's native wheels are MSVC-CRT builds; the engine's Zig build targets the GNU/libc++ ABI and "carries its own libc++ so an MSVC host links only the C ABI" (**Fact**, `UZE\docs\engine\06-build-toolchain\04-napi-bridge.md` via `UZP\docs\analysis\uzengine-renderer\07-build-and-packaging.md` §2). Embedding CPython and compiling pybind11 from a libc++/MinGW-ABI toolchain against an MSVC-built interpreter is a less-trodden combination (Hypothesis on risk; CRT-object crossing is the known failure mode). My Zig choice optimised for the engine's primary build, not for the Python boundary that is central to the product.
- My point, still valid: the CMake build is a "mirror" (**Fact**, `UZE\runtime\CMakeLists.txt` exists with msvc/clang presets per `07-build-and-packaging.md` §1); whether it builds the pinned commit today is **not confirmed**. Mixing MSVC objects with Zig archives fails (LNK1143), so if the mirror is broken the only MSVC route is the engine as a Zig-built DLL behind the C ABI.
- Fork policy: Astra's "fork/pin and documented patch queue" vs my "PR-only": UzPainter cannot block on engine maintainers, so a patch queue is operationally required; PR submission keeps it short.

(d) Revised position: toolchain decided by a Phase 0 build test — build the pinned commit with the CMake `msvc-release` preset; if green, UzPainter is CMake/MSVC (or clang-cl, same ABI family) and links the engine's CMake static targets; if not, UzPainter is CMake/MSVC against `uzengine_runtime.dll` built by Zig (`-Ddll=true`) through the C ABI, with a UzPainter-owned C API extension for the texturing passes. Fork + documented patch queue, every patch also submitted upstream and dropped when merged. Pin `19ffb9b` only once the working-tree conflicts are resolved and the pinned tree builds and passes its own tests (Astra: "a commit hash from a dirty/conflicted worktree is insufficient"; my grep found 15 conflicted files — **Fact**).

(e) Settling evidence: the Phase 0 CMake build of the pinned commit (pass/fail), plus a smoke test embedding CPython from that toolchain (import `uzpainter`, round-trip a 16-bit buffer).

### D13 — Parity testing

(a) **Astra:** immutable instruction-to-output goldens; decoded native pixels and rendered pixels equal by default — "no unexplained changed texel/pixel passes"; diagnostics (max/mean/LSB/angular/FLIP) are measurements, not allowances; any tolerance exists only through an explicit owner-ratified amendment; floats bit-equal where the oracle supports it; CPU-only CI for non-GPU checks, GPU lanes for compositor/render/DXR; WARP unconfirmed; failure injections; never regenerate goldens from the implementation under test.

(b) **Agree with changes.**

(c) Arguments.
- Astra's strongest point: "existing approximate render residuals are not owner-approved tolerances" and "report an unstable oracle as a blocked comparison requiring a tighter reference or an explicit owner contract, not as a free divergence budget" (D13 Rationale/Risks). My paper put proposed numbers (p99 ≤ 4/255, FLIP ≤ 0.02) in the gate table, which reads as if the tolerances were already decided.
- Both can be true, as the coordinator asks: the **default gate is zero unexplained divergence**; a divergence becomes *explained* only when it is classified (oracle non-repeatability measured in Phase 0; GPU float/filtering differences in renders; lossy runtime derivatives), bounded by a number the owner ratifies, and recorded as a `.rulebook/decisions` entry. Until then the affected comparison is **blocked**, not passing. My numbers survive only as the proposed values inside the owner question.

(d) Revised position: adopt Astra's framing and table; keep my four tiers as the corpus structure; add failure-injection tests (cancel, disk-full, stale revision, worker death, device removal, save/reopen/export) and oracle-repeatability runs (same session, after reopen, after reboot) as the first Tier 0 item. CI lanes as both describe; WARP is an investigation item, not a lane, until exercised.

(e) Settling evidence for whether any tolerance is needed: the oracle-repeatability measurement per channel type on Painter 12.1.0 (expected from `A3D\...\00-Corpo\report.json → painting_v6.validacao.reproducao`: 8-bit channels identical, 16F channels drift — **Fact**); the measured floor defines what "explained" can mean for floats and renders.

### D14 — Delivery roadmap

(a) **Astra:** evidence-first vertical slices after feasibility gates; tunic v10 as the principal painting pilot (recovered per-layer sources), wand as a smaller smoke fixture, then locked bracers, hat v8, body v6b; no calendar estimates until the proprietary/render feasibility gate and the engine pin are resolved.

(b) **Disagree** (narrowly), on two points.

(c) Arguments.
- Astra's strongest point: tunic v10 is "approved … using its recovered per-layer sources and exact material recipe"; passing it proves the owner-relevant property (approved work reproduced), while the wand proves only that the mechanism works. Also: "a successful modern bitmap workflow can conceal unsolved procedural, brush, native bake and Iray requirements" (D14 Risks) — a fair warning against labelling the fills milestone "v1".
- My points: the tunic carries 22 fills, a `replace_height` group, 4K, OCIO colours and the C07/F03 alias (**Fact**, `UZP\docs\analysis\assets3d-pipeline\04-painting-recipes-and-materials.md` §6; pipeline review finding 4); as the *first* slice its failures are hard to attribute. The wand (one set, 2048, uniform fills + bitmap masks, external normal/AO — **Fact**, `02-painter-usage.md` §6) isolates the compositing/export contract. On estimates: the owner asked for a roadmap; ranges labelled Hypothesis are planning aids, not commitments, and I prefer to publish them with that label rather than none.

(d) Revised position: wand as the smoke fixture (Astra accepts this), tunic v10 as the first *parity pilot that counts*, belt v5 demoted to a regression fixture; then bracers (procedurals), hat v8 (SpecularWeight, seven maps, Sharpen), body v6b (stress). Milestone names say what they prove ("fills recipe milestone", not "v1"). Durations stay in my roadmap labelled Hypothesis and non-binding; Astra would omit them.

(e) Settling evidence: owner preference (§2 Q5 and Q16). If the owner wants dates, mine stand as labelled; if the owner prefers gates only, Astra's phrasing is adopted.

## 2. Consolidated owner questions

"Both" = both architects state it as an owner decision; otherwise the column names who raised it and the other's view.

| # | Question | Raised by | Owner decision? |
|---|---|---|---|
| Q1 | Render reference: the realtime Painter viewport with pinned shader/state (both propose), or the existing Iray review output (not reproducible by either design)? Confirm `open-pbr` primary, `pbr-metal-rough` secondary, Linear tone map, `Studio White Soft` by hash | Astra 1, Claude Q12 | Both |
| Q2 | Equality definition: native decoded values and rendered pixels (default, no allowance); encoded bytes separately; what happens when the controlled Painter oracle is itself non-repeatable (16F drift); who ratifies any per-domain tolerance (Claude's proposed values: fixed-point exact; floats ≤ 2·2⁻¹⁰; calibrated procedurals mean ≤ 1/255, p99 ≤ 4/255; renders FLIP ≤ 0.02, p99 ≤ 2/255) | Astra 2, Claude Q1 | Both |
| Q3 | Procedural route: establish a distributable Substance runtime (confirm it is not an option), fund independent resource-by-resource reproduction, or explicitly change the art/instruction corpus (a changed acceptance, not parity) | Astra 3, Claude Q4 | Both |
| Q4 | Legal stance for Adobe-derived material: port the "ADOBE CONFIDENTIAL" GLSL vs clean room; capture procedural outputs and smart-material recipes for internal use, under Painter's asset names, and/or ship them (Route A vs Route B in D4/D6, each with its parity cost) | Claude Q2–Q3; Astra D4/D6 distribution notes | Both (both say source access is not permission) |
| Q5 | Pilot and corpus: tunic v10 as principal pilot with wand as smoke fixture (reconciled order), then bracers, hat v8, body v6b; existing technical/artistic pending statuses stay distinct from software tests | Astra 4, Claude Q7 | Both |
| Q6 | Migration mechanism: version-pinned extraction/rebuild from recipe + resources with proven output equality (both prefer) vs a native `.spp` reader; future operation independent of Painter either way | Astra 5, Claude Q13 (part) | Both |
| Q7 | Compact-save budget: ratify after the lossless dependency census vs a compacted `.spp` of the same content (Claude's "≤ 10 %" is a Hypothesis to validate); portable embedding vs linked projects; retained-checkpoint policy | Astra 6, Claude Q13 | Both |
| Q8 | Unreal/UzEngine handoff contract beyond ORM: SpecularWeight, Height/Thickness, opacity channel, normal handedness/domain, precision, compression, mips; which Unreal version/importer and which consumer fixture is authoritative; DDS pass-through wanted? | Astra 7, Claude Q11 | Both |
| Q9 | Supported Windows/hardware matrix for "anyone runs locally"; is a certified software-render/compute path (WARP) mandatory; is a self-hosted DX12 GPU CI runner available | Astra 8, Claude Q9 | Both |
| Q10 | Packaging: one folder (exe + private CPython + DLLs + assets) for v1; is a single-file exe required later | Claude Q10; Astra "one folder" | Both |
| Q11 | Arbitrary Python (`run_python`/`run`): trusted opt-in local capability (both default) or an OS-enforced restricted execution boundary | Astra 9 | Astra: owner; Claude: architect default, owner may override |
| Q12 | Keep Painter 12.1.0 installed and licensed as the golden oracle through the procedural phase | Claude Q5; Astra assumes an oracle | Both |
| Q13 | UzEngine baseline: who resolves the dirty working tree; approve pin `19ffb9b` only after it builds and tests clean; approve fork + patch queue with upstream submission | Claude Q6; Astra D12 | Both |
| Q14 | Milestone labelling and v1 scope: strokes, UV tiles, warp/UV-set projections, auto-unwrap, vector/font sources as visible release gaps until implemented; which gaps may be open when the owner calls it "v1" | Claude Q8; Astra D2/D14 | Both |
| Q15 | Governance: when to amend the Assets3D rule "painting is always in Substance Painter" (`A3D\AGENTS.override.md`) | Claude Q14 | Claude: owner; Astra: administrative, later, not a blocker |
| Q16 | Does the owner want dated milestone ranges now (labelled Hypothesis) or gate-only phases until the feasibility gate and engine pin are resolved | Claude D14; Astra D14 | Both (preference) |

Not an owner question: the toolchain (CMake/MSVC vs Zig DLL + C ABI) — settled by the Phase 0 build test (D12 e).

## 3. Review-response files

Two of the four responses existed when this round closed and were read in full: `docs/analysis/assets3d-pipeline/09-review-response.md` and `docs/analysis/technology-options/05-review-response.md`. The Substance-parity and UzEngine responses had not landed; round 3 will read them. What the two responses alter here:

| Response item | Effect on this reconciliation |
|---|---|
| Pipeline 09 §2: requirements re-classified in `08-requirements-for-uzpainter.md` — BAK-03 native bake, MAT-02…04 used procedurals/materials, LAY-11 portable smart materials, **LAY-12 paint layers**, EXP-08 Unreal ORM + UzEngine presets, VIS-06 render equal to Painter, NFR-04 compact save, DIA-02, INT-13, INT-23, QG-02 all now MUST; G-01 governance down to SHOULD; new G-04 (parity protocol), PRJ-10 (per-set UV certificate), BAK-07/BAK-08 (bake accounting; one corrected AO for mesh map, delivery and albedo), LAY-13 (per-layer bindings), LAY-14 (isolation in every channel), EXP-09 (relief once), EXP-10 (engine format/binding metadata), INT-07 (target identity, coherent async snapshots), QG-05 (approved-state protection) | Consistent with D2's three-way manifest: strokes (LAY-12) are a visible **release gap**, not an omission; this strengthens Astra's D14 warning against labelling the fills milestone "v1" (§2 Q14 stands). BAK-08 adds a rule to D5/D7: the same corrected AO feeds generators, the exported AO map and the albedo AO layers. QG-05/INT-07 are already covered by D9/D10 (revision preconditions, receipts). |
| Pipeline 09 F13 (forwarded): UzEngine's FBX importer recomputes normals by default (`r.Mesh.NormalImportMode = 1`, `fbx_importer.cpp` lines cited there) | New fact for D7/D11: validating the UzEngine preset through the engine's cooked FBX route must set that CVar (or use a route that preserves corner normals), otherwise the engine_preview fixture tests a different tangent frame. Added to the Phase 0 normal-convention fixture. |
| Pipeline 09 F5/ADD-10: `glb_add_specular.py` writes `KHR_materials_specular`; `painter_add_channel.py` adds an `L8` SpecularWeight channel; the delivered PNG is 8-bit RGBA; the `.blend` link is still a comment | D7: SpecularWeight export is mandatory (PRJ-06 MUST) and the UzEngine side remains a consumer gap (no fixed-PBR slot); the glTF side has a working consumer path. |
| Pipeline 09 F6/B16 and §3.3: the AO remaining-count discrepancy (76,518 vs 77,588) stays a Hypothesis; decision 001 is "proposed" in the `.md` but "accepted" in its `.metadata.json` | D13: the hat AO counts are fixture inputs, never golden expectations (Astra D5 Risks, agreed). Owner question Q2 should also confirm decision 001's status. |
| Pipeline 09 EXP-05 split: same-build byte identity MUST; cross-session/cross-machine SHOULD | Matches D13 (d): same-build repeatability is a UzPainter guarantee; cross-machine identity is measured, not promised. |
| Technology 05 findings 9–17: every size/speed figure withdrawn; BC7 4096² = 16,777,216 bytes (+ mips ≈ 21.33 MiB) | D8: my "≤ 10 % of `.spp`" remains a Hypothesis for the census, as §1 D8 (d) already states; no figure in this reconciliation is a measurement. |
| Technology 05 findings 19–22 and M7: HDF5 moved into the benchmark set; SQLite row added with atomic-commit evidence; libzip rewrites the archive on modification (copy-without-recompression **not confirmed**) | Supports the D8 move to SQLite (incremental transactional commits vs archive rewrite). HDF5 stays a benchmark candidate for the census only if the owner wants a three-way comparison; neither architect proposes it as the format. |
| Technology 05 finding 29 and topology table: the drafted Python-subprocess MCP topology is "not viable as drafted"; state-owner choice open | Resolved by D1 (d): the AI host launches `UzPainter.exe --mcp`; the supervisor relays to the worker; no third process. |
| Technology 05 findings 26–27: Python SDK v2 does not implement the redesigned Tasks extension; the client matrix has no Tasks column; SDK requires Python ≥ 3.10, MIT | Confirms D10: job ids first, Tasks adapter later; the pinned SDK release and Claude Code's Tasks support are **not confirmed**. |
| Technology 05 finding 11: ISPC Texture Compressor archived (2024-09-23); DirectXTex GPU encoding is D3D11-only; NVTT 3 has CPU fallbacks but unconfirmed licence | D7: etcpak (vendored) stays the deterministic CPU encoder behind an adapter; bc7enc_rdo is the candidate replacement if quality tests demand it. |
| Technology 05 finding 13: UE 5.6 documents DDS "Cubemap or 2D" import; BC pass-through through cooking undocumented; no KTX | D7/Q8: DDS BC7 remains optional and "already compressed" for Unreal means compact interchange, not guaranteed cooked-block preservation, until an Unreal fixture proves otherwise. |
