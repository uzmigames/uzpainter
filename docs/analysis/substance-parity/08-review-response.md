# 08 — Response to the Astra technical review (as of 2026-10-10)

Finding-by-finding response to `docs\analysis\reviews\substance-parity-astra-review.md` (Astra, GPT-based reviewer; 20 numbered findings, 81 fact-validation records, 140 matrix-row dispositions, 15 architect questions). Each claim was checked against the primary sources before any change; corrections were applied in place in files 01–07.

## Conventions

- `PAINTER` = `C:\Program Files\Adobe\Adobe Substance 3D Painter`; `PYSRC` = `PAINTER\resources\python\modules\substance_painter`; `PYDOC` = `PAINTER\resources\python-doc\substance_painter`; `MODS` = `PAINTER\resources\python\modules`; `OPS` / `SRV` / `CLIENT` = `E:\UzmiGames\Assets3D\Tools\SubstancePainterMCP\src\substance_painter_mcp\{operations,server,client}.py`; `PIPE` = `E:\UzmiGames\Assets3D\Pipeline\mcp`; `CUBE` = `MODS\automated_tests\resources\layerstack-cube.spp`. `X:n` = line n of file X.
- Verdicts: **accepted** (source confirms; correction applied), **partially accepted** (part confirmed and applied, the rest already present or not supported), **rejected** (source contradicts), **forwarded to architecture** (a decision, not a documentation fix).
- Method (**Fact**): every cited line was read in the shipped `.py` wrappers, HTML/JS docs, Adobe tests, `OPS`/`SRV`/`CLIENT` and the local patch; `CUBE` was spot-checked with a byte read. Nothing was executed in Painter and the bridge was not called; "Fact (static)" means the code path establishes the behaviour without a run.

## 1. Summary

| Item | Count |
|---|---|
| Numbered findings accepted | 16 |
| Numbered findings partially accepted | 4 (F06, F08, F16, F20) |
| Numbered findings rejected | 0 (one sub-claim of F16 rejected) |
| Numbered findings forwarded to architecture | 0 as a whole; the decision parts of F07 and F08 go to the questions in §5 |
| Fact-validation records needing a change / already handled | 35 (§3) |
| Fact-validation records confirmed by the review, no change | 46 (§3) |
| Matrix rows reclassified / added | 16 / 7 (`07-parity-matrix.md`, now 147 rows) |
| Architect questions | 15, all forwarded; source-supported input in §5 |

## 2. Numbered findings

| ID — short title | Severity | Verdict | Evidence verified | What changed and where |
|---|---|---|---|---|
| F01 — Paint active-channel writes return false success | blocker | accepted | `OPS:2226`, `2240`, `2244`, `2390–2391`, `4757–4761`; `PYSRC\layerstack.py:1205–1211` (no `active_channels` on `PaintLayerNode` or its bases); `PYSRC\source.py:300–321` (only native setter); [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PYSRC\_utility.py.]. Added evidence: `OPS:2053–2054` records `active_channels` for Fill layers only, so snapshots cannot reveal the false write. | `06` §9 row 1; `06` rows 35, 52, §6 recipe rows; `07` H4 Yes → Partial; `01` `ActiveChannelsMixin` row names the classes that inherit it. |
| F02 — mask Fill procedural-input routes dereference `None` | major | accepted | `OPS:2945`, `3041`, `2949–2957`, `3045–3053`; `PYSRC\source.py:332–347`; `PYDOC\layerstack\layereffect\fill.html` example ("None is mono-channel (ex: a fill in the mask stack)"). | `06` §9 row 2, rows 41, 42, 54; `07` H7 Yes → Partial, E2 note, new E12. |
| F03 — named mask blend/opacity routes pass the wrong channel | major | accepted | `OPS:3714–3731`; `PYSRC\layerstack.py:726–798`. | `06` §9 row 3, row 56; `07` G3 Partial (Hypothesis) → No (Fact, static), D7, G1, G2 notes. |
| F04 — cleanup and rollback are not atomic | major | accepted | `OPS:2425–2433`, `2441–2449`, `2348–2351`, `989–1001`, `1104–1108`, `1189–1193`. Added evidence: `ScopedModification` groups calls into one undoable command (`PYDOC\layerstack\edition.html`); [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PYSRC\layerstack.py.] | `06` §6 Transaction row, §9 rows 5–6, rows 12–14, 16, 35; `07` D12 Yes → Partial, capability renamed "Multi-node creation with rollback on failure"; L2 note. |
| F05 — baking baselines mix defaults, examples and specimen values | major | accepted | `CUBE`: HDF5 signature (spot-checked); [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: MODS\automated_tests\resources\layerstack-cube.spp.] | `03` §3 intro (specimen vs default vs example), header "Value seen (…not a confirmed 12.1 default)", rows `LowpolySuffix`/`HipolySuffix`/`BackfaceCullingSuffix`, §3.2 last row, §4 match row, §5 linking row, new Recommendation for a current-default capture. The review's per-group stored-value table was not copied (not re-decoded here). |
| F06 — preset structure decoded more strongly than semantics | major | partially accepted | `04` §7.1 already labelled the decoded meanings **Hypothesis** and the Appendix already pointed to it; §7.2–7.6 tables carried no label. Added evidence: [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: MODS\engine_tests\test_baking.py.] | `04` label paragraph before §7.2 ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\starter_assets\export-presets\Unreal Engine (Packed).spexp; PAINTER\resources\starter_assets\export-presets\Unreal Engine SSS (Packed).spexp.]); `04` §7.6 note on grayscale triplets; new `04` §11 "Validation needed inside Painter". |
| F07 — structural snapshots are not a material-output oracle | major | accepted | `OPS:2014–2058` captures names, types, visibility, masks, effect lists, geometry masks, Fill active channels, collapse only. | `07` D13 note; new row D15 (semantic snapshot, No). The oracle definition is forwarded (§5 Q9–Q11). |
| F08 — matrix labels combine surfaces and contexts | major | partially accepted | Route/context differences confirmed per row (see F01–F03, F10, F19). | `07` Conventions: status scope (named route, static, not product capability), surfaces, overlap clusters, "composed"; notes per row. Rows were not split into class/context/operation sub-rows, to keep the matrix structure; that choice is forwarded (§5 Q1, Q5). |
| F09 — baking-presets feature probe is a false negative | major | accepted | `OPS:604`; `PYSRC\baking.py:138–413` (frozen dataclass; no `get`, no `__getattr__`). | `06` §7 Hypothesis → Fact, row 8, §9 row 7; `07` A2 Yes → Partial, L10 note. |
| F10 — bitmap colour space misclassified | major | accepted | No `get/set/reset_color_space` or `list_available_color_spaces` call in `OPS`; `describe()` (`OPS:2960–2984`) reports colour only for objects with `get_color`; `SourceBitmap` has none (`PYSRC\source.py:469–528`); `OPS:5060–5064` limits colours to 0..1. | `07` H10 Partial → No, H1 note; `06` §8 bitmap row. |
| F11 — inventory omissions and private helpers | major | accepted | `PYSRC\textureset.py:328–335`, `803–808`; HTML signatures `UVTile(u: int, v: int, _material_id: int)`, `TextureSet(material_id: int)`; `:meta private:` at `layerstack.py:518–523`, `source.py:300–305`, `324–329`, `709–714`, `983–988`; `ClassVar` at `layerstack.py:1846`. | `01` Conventions (correction note); `textureset` table: `UVTile.u`, `UVTile.v`, `UVTile.__init__`, `TextureSet.material_id`, `TextureSet.__init__`; five helper rows marked private; `CylindricalProjectionParams` row; module map 44 → 46. All 11 rows of the review's inventory-correction table applied. |
| F12 — async, busy-state and identity wording | minor | accepted | `OPS:1846–1864`, `1906` (mesh reload callback); `PYDOC\layerstack\navigation.html` (`Node`, `Node.uid`). | `06` §2 Long jobs row; `07` A9, A10; `02` §1 uid paragraph. |
| F13 — layered-stack and naming claims | minor | accepted | `PYDOC\textureset\stack.html` (`Stack.name` text vs examples and `from_name`); `PYSRC\textureset.py:1004–1030`; `OPS:2011–2012`, `2357–2358`. | `02` §1 Stack row (upstream contradiction); `05` §1.2 (resource case sensitivity removed); `07` C8; `06` §9 last row (Hypothesis). |
| F14 — "dithering tested" hides disabled cases | minor | accepted | `MODS\automated_tests\test_export_fileformats_bitdepth.py:118–284`. | `04` §3 intro and table: exact depth/dithering combinations, labelled test definitions. |
| F15 — raw-code registration, environment, path guards | minor | accepted | `SRV:814–822`; `PIPE\painter_mcp_client.py:12–14`; `OPS:4792–4808`; `CLIENT:66–99`. | `06` §2 rows (execution model, arbitrary code), §2.1 variable row and guard note, §2.2, row 79; `07` A7. |
| F16 — call lists and patch effects | minor | partially accepted | Accepted: `settings.set(...)` at `OPS:982`, `988`, `1103`, `1188`; `shelf.refresh()` at `OPS:4087`; `apply_smart_mask` passes `"smart_mask"` (`OPS:2657–2658`); patch hunk headers `+1359/+1610/+2396/+2486`. Rejected sub-claim: `LayerNode.enable_mask` and the recipe colour-space references were already listed in `06` row 35 (`enable_mask`, `colormanagement.DataColorSpace`, `GenericColorSpace`, `LegacyColorSpace`). | `06` rows 12, 13, 14, 16 (`set`), row 68 (`refresh`), table note, §5 patch-scope sentence and hunk 4 row, hunk 3 note, row 79. |
| F17 — installed versions vs second-hand runtime reports | minor | accepted | `PYSRC\_version.py`; `MCP\README.md` "Compatibility". | `01` §1 version-string row; `07` A1. |
| F18 — HDF5 identification is not an SPP contract | major | accepted | Signatures of the five specimens; `PAINTER\resources\javascript-doc\alg.project.html:1666–1670`; `MODS\automated_tests\test_project_open.py:37–49`; `h5py` not importable in the Python checked. | `05` §3 "Save and compact" row (fragmentation removal now Fact); `05` §6 rows 1, 15, 16. |
| F19 — bundled rows hide output-relevant operations | major | accepted | `PYDOC\export.html` json_config block (tokens, `srcMapType`, `sizeLog2` pair, `exportList[].rootPath`/`exportPreset`); `OPS:3786–3839`; source reset/removal calls (`OPS:3113`, `3124`, `2495`, `2497`). | `07` M6, M10 reclassified; new rows E11, E12, H14, M17, M18, M19; `06` §8 rows; `04` §8 MCP row. |
| F20 — enum aliases, resolution limits, instance semantics | minor | partially accepted | `PYDOC\layerstack\layereffect\instance.html` (example renames instances; "mesh dependent result"); `PYSRC\source.py:152–165`, `213–222`. The alias pairing was already a **Hypothesis** in `02` §6.1. | `02` §2 Instance row; `02` §7.3 resolution row (domain and `Asset`/`Custom` aliases); no change to §6.1. |

## 3. Fact-validation records (V01–V81) and resolved items

Records that needed a change, or that the documents already handled:

| Record | Review result | Verdict | Where |
|---|---|---|---|
| V01 | Stack-name upstream inconsistency | accepted | `02` §1 |
| V03 | uid persistence not promised | accepted | `02` §1 |
| V05 | instance rule scope | accepted | `02` §2 |
| V10 | blend formulas not supplied | accepted | `02` §5 |
| V11 | alias equality unproved | already Hypothesis | `02` §6.1 (no change) |
| V13 | no universal resolution range | already stated | `02` §6.3 (no change) |
| V15 | source resolution is a separate domain | accepted | `02` §7.3 |
| V25 | specimen values, not defaults | accepted | `03` §3.1 |
| V26 | grouping is Fact for the specimen | accepted (spot-checked) | `03` §3 intro |
| V27 | zero stored count ≠ no options | accepted | `03` §3.2 |
| V28 | examples are not defaults | already stated | `03` §3.2 (no change) |
| V29 | linking is a documented example | accepted | `03` §5 |
| V33 | json_config list not exhaustive | already stated | `04` §2 (no change) |
| V36 | dithering cases | accepted | `04` §3 |
| V39 | bit-depth flag counts 160 / 49 | not adopted (not re-decoded); flag meaning stays not confirmed | `04` §7.1, §11 |
| V40, V41 | raw tuples vs human labels | accepted | `04` §7 label paragraph |
| V42 | grayscale triplet normalization | accepted | `04` §7.6 |
| V48 | resource case sensitivity unsupported | accepted | `05` §1.2 |
| V49 | Full save removes fragmentation | accepted | `05` §3 |
| V50 | signature only | accepted | `05` §6 row 1 |
| V58 | 62 functions + parametrization = 64 | no change (`06` cites the changelog count) | `06` §1 |
| V61 | namespace is not a sandbox | accepted | `06` §2 |
| V64 | mesh reload uses a callback | accepted | `06` §2 |
| V65 | creation takes names/context | accepted | `06` §2 |
| V66 | registration unconditional | accepted (wording) | `06` §2 |
| V67 | guards are not isolation | accepted | `06` §2.1 |
| V70 | inherited raw flag in batch | accepted | `06` §2.2 |
| V72 | call lists incomplete | partially accepted (see F16) | `06` rows 12–14, 16, 68 |
| V73 | `execute_python_json` and `result` | accepted | `06` row 79 |
| V74 | postimages ≠ checkout identity | accepted | `06` §5 |
| V76 | Raw for non-BaseColor is a choice | accepted | `06` §5 |
| V77 | hunk 4 is fill-only | accepted | `06` §5 |
| V79 | recipe cleanup best effort | accepted | `06` §6, §9 |
| V80 | Paint active channels not native | accepted | `06` §6, §9 |

Confirmed by the review with no change requested (not individually re-verified beyond the checks in §2): V02, V04, V06–V09, V12, V14, V16–V24, V30–V32, V34, V35, V37, V38, V43–V47, V51–V57, V59, V60, V62, V63, V68, V69, V71, V75, V78, V81.

| Item | Verdict | Where |
|---|---|---|
| R01 baking-preset probe | accepted | `06` §7, `07` A2, L10 |
| R02 existing content effects editable | accepted | `06` §8, `07` E1 |
| R03 `future_binary_data` intent | accepted | `05` §6 row 16 |
| R04 Full-save compaction | accepted | `05` §3 |
| R05 saved baker grouping | partially accepted (grouping Fact for `CUBE`; stored-value table not re-decoded) | `03` §3 |
| R06 preset encoding structure Fact, semantics Hypothesis | accepted (already the `04` position) | `04` §7 |
| R07 inherited API fields | accepted | `01` `textureset` |
| U01 alias equalities | Hypothesis kept | `02` §6.1 |
| U02 predefined glTF packing | not confirmed kept; added to validation list | `04` §4.2, §11 |
| U03 SPP hierarchy/semantics | Hypothesis kept | `05` §6 |
| U04 `OutputMapping` return contract | no change (`01` asserts no return type) | `01` `source` |
| U05 current defaults and numerical equivalence | forwarded to architecture | §5 Q10, Q12 |

## 4. Matrix changes (`07-parity-matrix.md`)

| Change | Rows |
|---|---|
| Yes → Partial | A2, B13, C10, D12, H4, H5, H6, H7, K9, M6 |
| No → Partial | E1, F4 (composed), J2 (composed), M10 |
| Partial → No | G3, H10 |
| Added | D15 (No), E11 (No), E12 (Partial), H14 (Partial), M17 (Partial), M18 (Partial), M19 (No) |
| Notes or symbols corrected, status kept | A1, A7, A8, A9, A10, B2, C8, D1, D2, D7, D8, D13, D14, E2, E4, E5, E10 (`get_levels`/`set_levels`), F1, F2, F3, G1, G2, H1, H2, H3, H11, H12, I1, I2, L2, L10, L11, M4, M5, M7, M12, N5, O1, O2 |
| Totals | 140 rows (59 / 24 / 51 / 6) → 147 rows (Yes 49, Partial 40, No 52, N/A 6) |

## 5. Questions for the architect

All 15 are decisions and are forwarded. The second column holds only what the sources support.

| # | Question (short) | Source-supported input |
|---|---|---|
| 1 | Parity target: product behaviour, public Python API, named MCP operations, or a subset? | The public Python API has no strokes, shader parameters (JS only), viewport capture or Iray module (`01` §3); `07` now states that its statuses describe named routes only. |
| 2 | Which UI/Qt/plugin helpers can an AI-only product omit? | `ui` is Qt/PySide6 UI control (`01` `ui`); the bridge's layer tools depend on the UI active stack when no Texture Set is given (`OPS:2011–2012`); bake, creation, reload and shelf crawling complete through events or a callback (`06` §2). Whether display state (environment, LUT, tone mapping, camera) changes exported textures is not confirmed. |
| 3 | How are strokes, shaders and Iray-equivalent rendering handled without a public API? | "Strokes are not accessible from the Python API" (`PYDOC\layerstack\layereffect\paint.html`); shader parameters only through `alg.shaders` (`05` §5). No source answers the rendering question. |
| 4 | Must mutations survive readback from a freshly resolved object, save/reload and output comparison? | A fresh `layerstack.get_node_by_uid(uid)` returns a new wrapper ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PYSRC\layerstack.py.]), so a plain Python attribute set on an earlier wrapper is absent from it — this readback would have exposed F01. Save/reload and output checks are a policy choice. |
| 5 | Will every operation declare node classes and contexts, `None` channel/source-mode behaviour and empty active-channel sets? | Sources fix the contexts: `active_channels` exists on Fill layers/effects, Generator and Filter effects only (`source.py:300–321`); mask-stack Fill effects have `source_mode` `None` and take `set_source(None, …)`; mask-stack blending/opacity take `None` (`layerstack.py:726–798`). The setter says "channels not listed will be disabled"; an empty set is not documented as an error (the bridge rejects it). |
| 6 | Best effort, backup restore, or atomic commit? | The public API offers `ScopedModification` (one undoable command, one recompute); [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PYSRC\layerstack.py.] No public undo call exists (`01` §3). Atomic commit is not provided by the API. |
| 7 | Explicit layered Texture Set / stack addressing? | `Stack.from_name(texture_set_name, stack_name)`, `TextureSet.all_stacks()`, `get_stack(name)`; export `rootPath` "TextureSet/Stack" (`PYDOC\export.html`). Adobe's text contradicts itself on which stacks are unnamed (`02` §1). |
| 8 | Is raw Python/JavaScript an official route or an escape hatch? | `execute_python` is always registered and gated at call time; the pipeline client passes an inherited enable flag through to `batch` (`06` §2, §2.2). Policy is open. |
| 9 | Bitwise identical or toleranced outputs? | No source decides; `04` §11 lists the output properties a comparison must cover (packing, colour conversion, derived maps, dithering, padding, sizes, naming). |
| 10 | What fixture makes the oracle reproducible? | Inputs named by the sources: mesh, template, project settings and colour configuration (`05` §1), baking parameters and link groups (`03` §3 Recommendation), export configuration and preset versions (`04` §11). Native determinism is not documented. |
| 11 | Which material-producing values must a semantic snapshot hold? | Values the public API exposes beyond the current structural snapshot: Fill sources and source mode, `SourceSubstance` parameters, image inputs, output mapping, resolution override; `SourceReference` channel mapping, alpha matte, levels; per-channel blending and opacity; projection and symmetry parameters; mask enable/background and mask effects; geometry masks; bitmap colour spaces; Levels, Compare Mask and Color Selection parameters (`02` §§4–10). |
| 12 | How are current defaults and capability discovery versioned and reported? | `03` §3 Recommendation and `04` §11 define captures separate from specimen values; `get_capabilities` flags are `hasattr` presence only and one is a false negative (`06` §7). |
| 13 | Which shading/export conventions are required? | Export conventions are preset data (virtual maps, normal convention, tokens, per-root presets, `[w, h]` sizes) separate from the project's `NormalMapFormat` (`07` M17–M19, B2). The choice is open. |
| 14 | Job concurrency, cancellation, callback lifetime, event ordering? | `bake_async`/`bake_selected_textures_async` return a `StopSource`; completion is `BakingProcessEnded`; mesh reload reports through a callback; the bridge keeps one latest-state slot per job kind, not a queue (`03` §5, `06` §2). |
| 15 | Binary SPP interoperability or behavioural save/load? | Only the HDF5 signature, entry-name strings and lifecycle are established; hierarchy, codecs, entry sizes, hashes and writable schema are not (`05` §6). |
