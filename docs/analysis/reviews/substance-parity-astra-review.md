# Substance Painter parity analysis: Astra technical review

## Executive summary

- **Fact:** This static review covers D01–D07, 545 installed Python HTML symbol anchors, the shipped Python source, 79 MCP tool definitions, local tests/assets, and all 140 matrix rows; no Painter/MCP operation or shipped test was executed.
- **Fact:** D01 omits three inherited public fields and two inherited constructor signatures; no documented top-level function, class, or enum is missing.
- **Fact:** The 45 HTML names without standalone inventory rows are covered by inheritance or aggregate enum/field rows; they are not 45 missing capabilities.
- **Fact — blocker:** MCP Paint-layer active-channel writes can report success after creating an ordinary Python attribute, without reaching the native channel setter.
- **Fact — major:** Mask Fill procedural-input and mask blend/opacity routes have static failure paths; recipe cleanup and baking rollback are best effort, not atomic.
- **Fact:** Historical specimen values, test expectations, binary encoding, native semantics, and current defaults require distinct evidence labels; structural snapshots cannot establish material-output equivalence.
- **Recommendation:** Retain these documents as a useful source inventory, apply the corrections below, and define the required parity surface and output oracle before treating them as an implementation contract.
- **Fact:** Only this review file was authored; the seven reviewed documents retain their recorded SHA-256 hashes.

## Scope, source aliases, and evidence rules

**Fact:** All paths below are local. An alias followed by a relative path expands to the full path in this table. Line numbers locate the installed/reviewed copy; an HTML fragment names its exact anchor.

| Alias | Full path |
|---|---|
| ROOT | E:/UzmiGames/UzPainter |
| D | E:/UzmiGames/UzPainter/docs/analysis/substance-parity |
| D01 | D/01-python-api-inventory.md |
| D02 | D/02-layer-stack-model.md |
| D03 | D/03-baking.md |
| D04 | D/04-export.md |
| D05 | D/05-project-and-spp.md |
| D06 | D/06-mcp-tools-inventory.md |
| D07 | D/07-parity-matrix.md |
| PAINTER | C:/Program Files/Adobe/Adobe Substance 3D Painter |
| R | C:/Program Files/Adobe/Adobe Substance 3D Painter/resources |
| H | R/python-doc |
| PH | R/python-doc/substance_painter |
| P | R/python/modules/substance_painter |
| A | R/python/modules/automated_tests |
| E | R/python/modules/engine_tests |
| J | R/javascript-doc |
| X | R/starter_assets/export-presets |
| CUBE | R/python/modules/automated_tests/resources/layerstack-cube.spp |
| MCP | E:/UzmiGames/Assets3D/Tools/SubstancePainterMCP |
| OPS | MCP/src/substance_painter_mcp/operations.py |
| SRV | MCP/src/substance_painter_mcp/server.py |
| CLIENT | MCP/src/substance_painter_mcp/client.py |
| PIPE | E:/UzmiGames/Assets3D/Pipeline/mcp |

**Fact:** In tables, “confirmed” means that the stated local source supports the claim, not that a live operation succeeded. Test definitions establish expected behavior, not a successful run. A byte offset is decimal and zero-based. Short HTML fragments such as `#Stack.from_name` expand to `#substance_painter.textureset.Stack.from_name` in that row's module; the inventory appendix supplies complete fragments.

**Recommendation:** Preserve three labels throughout downstream design: **Fact** for supported local observations, **Hypothesis** for unverified semantics or runtime behavior, and **Recommendation** for the proposed engineering decision. A public Python capability, a named MCP route, an optional raw-script route, and a Painter product capability are separate surfaces.

## Reproducibility and coverage

**Fact:** The review parsed source with Python AST and HTML with a local parser, inspected source and test bodies without importing or executing them, independently decoded local preset/specimen structures, and reconciled documentation claims with these sources. It opened both H/genindex.html and H/py-modindex.html. No temporary scripts, task metadata, changelog entries, network requests, Painter launches, SDK imports, or MCP bridge calls were required.

| Fact / counting unit | Result |
|---|---:|
| Package source files parsed, including __init__ and private helpers | 22 |
| Additional top-level plugin source file parsed | 1 |
| Public implementation modules inventoried: 18 package submodules plus substance_painter_plugins | 19 |
| Installed Python HTML files parsed | 53 |
| Distinct documented symbol anchors beginning substance_painter | 545 |
| Distinct genindex symbol references; unresolved targets | 545; 0 |
| Distinct py-modindex symbol references; unresolved targets | 395; 0 |
| py-modindex module entries: package root, 16 indexed submodules, plugin module | 18 |
| Inventory physical rows, including setter and grouped/note rows | 572 |
| Distinct simple symbol cells | 542 |
| Explicit named inventory symbols after recognizing the annotated Node.uid cell | 543 |
| Explicit named inventory symbols also possessing an HTML anchor | 500 |
| Inventory names without their own HTML anchor | 43 |
| HTML names lacking standalone named rows: inherited / enum members / aggregate fields | 45 = 40 + 2 + 3 |
| Missing documented top-level functions, classes, or enums | 0 |
| Omitted inherited public fields | 3 |
| Omitted inherited constructor signatures | 2 |
| Direct callable/property signatures compared to source AST; transcription mismatches | 378; 0 |
| Direct callable/property signatures compared to HTML; substantive mismatches after normalization | 330; 0 |
| Native enum member sets / Python enum member sets compared; membership mismatches | 38 / 11; 0 |
| Annotated class-attribute entries transcribed in D01 | 200 |
| Direct actual dataclass fields / dataclasses, excluding one ClassVar | 197 / 78 |
| MCP registered tools / schema tools; signature-schema differences | 79 / 79; 0 |
| MCP test definitions / additional parametrized cases; executed | 62 / 2; 0 |
| Matrix rows: Yes / Partial / No / N/A | 140: 59 / 24 / 51 / 6 |
| Exact duplicate matrix rows | 0 |
| Fact-validation records below for D02–D06 | 81 |

**Fact:** Colormanagement and levels lack separate entries in py-modindex, but their symbols occur in installed HTML. D01's 19 implementation-module sections are therefore not contradicted by the 18 module-index entries. Getter/setter pairs share one qualified property name; enum members represented in enum rows, aliases, inherited methods, and generated dunders do not create additional missing-capability counts.

**Fact:** The 200 copied annotated attributes consist of 198 entries in dataclasses, including one ClassVar, plus two Color attributes. Their source annotations/default expressions match; labeling every entry a dataclass field is incorrect. Three inherited public fields and UVTile's private constructor parameter are outside that direct-class extraction.

| Module represented by HTML anchors | Fact: unique anchors |
|---|---:|
| application | 6 |
| async_utils | 3 |
| baking | 31 |
| colormanagement | 9 |
| display | 18 |
| event | 34 |
| exception | 3 |
| export | 16 |
| js | 1 |
| layerstack | 168 |
| levels | 3 |
| logging | 4 |
| project | 39 |
| properties | 9 |
| resource | 64 |
| source | 58 |
| textureset | 52 |
| ui | 16 |
| `substance_painter_plugins` | 11 |
| Total | 545 |

## Verdict by reviewed file

| File | Recommendation: verdict | Fact: basis |
|---|---|---|
| D01 | Accept after inventory/scope corrections; retain static-source qualification | Three inherited public fields and two constructors omitted; one private ClassVar mislabeled; five helpers explicitly marked private. Direct signatures and enum membership match. |
| D02 | Usable with targeted qualifications | Node/type/insertion/channel tables are supported; UID lifetime stability, instance wording, Stack.name contradiction, and numerical output semantics need care. |
| D03 | Useful baking inventory; insufficient as a complete reproducible baking specification | Typed property discovery and workflows are supported; old saved values, examples, current defaults, native enum meanings, and output behavior are not interchangeable. |
| D04 | Correct the dithering table and preserve unresolved semantics | Export API/test-case/preset structure evidence is strong; binary codes and current output equivalence are not established by structural decoding. |
| D05 | Use as an observational project/persistence model, not an SPP implementation specification | Settings/lifecycle facts are supported; magic bytes and strings do not establish container hierarchy, codecs, entry sizes, or writable schema. |
| D06 | Revise route behavior and completeness claims before architecture consumes it | 79 tools/schema match, but Paint writes, masks, transactions, capability probes, call lists, and patch scope have consequential qualifications. |
| D07 | Reclassify affected rows and define the support denominator | All 140 rows reviewed; several Yes/Partial/No entries conflate operation/class/context, named versus raw access, or structure versus semantic output. |

## Numbered findings

### F01 — blocker — Paint active-channel writes can return false success

**Fact:** D07 H4 (line 124) and D06 lines 160/162 overstate Paint support. OPS:2225–2244 accepts Fill and Paint nodes, assigns node.active_channels, and echoes that attribute. P/layerstack.py:1205–1211 defines PaintLayerNode with only a docstring atop LayerNode; its ancestry through LayerNode:842, Node:636, and ReadOnlyUid has no active_channels property. [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: P/_utility.py.] The real native setter is P/source.py:319–321 in ActiveChannelsMixin, which applies to FillLayer/FillEffect/Generator/Filter, not Paint. OPS:2390–2391 repeats the assignment in recipes, and :4757–4761 validates Paint for it. A recipe file's HandPaintedDetails channel configuration is not evidence of a native effect.

**Recommendation:** Mark Paint active-channel editing unsupported by this route; distinguish the actually supported classes and empty-set policy. Require readback from a freshly resolved native-backed object, plus persisted/output behavior where relevant, before declaring a mutation supported.

### F02 — major — Monochannel mask Fill input routes dereference None

**Fact:** D07 H7 (line 127) is too broad. OPS:2945 and :3041 evaluate node.source_mode.name. P/source.py:332–347 and PH/layerstack/layereffect/fill.html:1266 document None for a mask's monochannel source context; PH/source/index.html:954–958 lists only Split/Material enum members. The dereference occurs before the valid get_source(None) operation.

**Recommendation:** Split FillLayer, content FillEffect, and mask FillEffect support. Treat the current mask procedural-input route as broken, and specify None handling explicitly. Assignment/reset support also does not imply Color/anchor inputs or remove_source support.

### F03 — major — Named mask blend/opacity routes pass the wrong channel

**Fact:** D07 G3 (line 115) overstates support. OPS:3714–3717 converts absent/null/empty channel to BaseColor; :3721/:3725 and :3730/:3731 pass a ChannelType to setters/readbacks. P/layerstack.py:726–798 requires None for mask contexts and raises ValueError when a channel is supplied. No alternate named route for the four blend/opacity operations was found. A visibility-only set_layer_properties call can mutate visibility before its unconditional blend readback fails.

**Recommendation:** Mark G3 “No named mask blend/opacity route”; retain public API/raw-script availability separately. Specify mutation/readback failure behavior and avoid describing a failed response as proof that nothing changed.

### F04 — major — Cleanup and rollback are not atomic transactions

**Fact:** D06:161 and D07 D12:79 say more than OPS:2425–2433 guarantees: reverse cleanup suppresses deletion failures, with no ScopedModification/native transaction in the recipe path. OPS:989–1001 similarly suppresses baking rollback failures. Optional backup and best-effort cleanup do not establish atomicity.

**Recommendation:** Use “best-effort cleanup/rollback with optional backup.” Choose an explicit contract among best effort, backup restoration, and atomic mutation; include linked Texture Set effects and partial-failure reporting.

### F05 — major — Baking baselines mix current defaults, examples, and old specimen values

**Fact:** D03:51–108 relies partly on CUBE's serialized groups, not current initialization. [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: R/python/modules/automated_tests/resources/layerstack-cube.spp.] Its stored values are specimen values, not Painter 12.1 defaults. API Property metadata supports typed discovery, but internal enum/UI correspondences and the full current parameter surface are not proved.

**Recommendation:** Separate documented defaults, test/example inputs, old specimen values, and inferred UI mappings. Define a later controlled oracle capture for current initialization, types, ranges, enum IDs, linked-set behavior, and bake output. Do not use this old file as the default configuration contract.

### F06 — major — Preset structure is decoded more strongly than preset semantics

**Fact:** D04:139–173 is supported for 34 preset roots, 209 map records, and matched boundaries, but structural correctness does not prove all destination codes, native channel IDs, bit-depth flags, or derived-map semantics. Unreal packed raw tuples and SSS's differing channel ID are observed bytes; their human channel labels rely on inferred mappings.

**Recommendation:** Preserve raw values and inference labels. Establish packing, color conversion, normal/AO derivation, alpha, quantization, padding, and filename behavior through a semantic output oracle before treating decoded presets as a complete exporter specification.

### F07 — major — Structural snapshots cannot serve as a material-output equivalence oracle

**Fact:** D07 D13 covers OPS:2014–2057 structural snapshot/diff data, which omits source/procedural parameters, per-channel blend/opacity, and projection details. Source/tool success and structural equality therefore leave material-producing inputs unobserved.

**Recommendation:** Define a richer semantic snapshot and an output comparison protocol. A scene graph hash or successful MCP response alone must not certify equivalent materials, textures, or rendered output.

### F08 — major — Matrix support labels combine different surfaces and contexts

**Fact:** D07 counts 140 rows, but 11 overlap clusters and multiple bundled operations prevent interpreting that as 140 independent product features. Named tools, public API, raw Python, raw JavaScript, private APIs, and product behavior differ. Existing effect read/edit routes do not imply content-effect insertion; resource binding does not imply vector/font parameter editing; composition does not imply a direct native wrapper.

**Recommendation:** State the denominator and split class, context, operation, and route. Interpret “No” only as no named route for the stated operation unless a stronger scope is explicitly evidenced. Apply the full row dispositions and gaps below.

### F09 — major — The baking-presets feature probe is a false negative

**Fact:** D06:167's hypothesis is locally resolvable. OPS:604 probes BakingParameters.get; P/baking.py:139–413 has no such method, inherited implementation, or metaclass provision. Named capture/apply operations exist independently. D07 A2/L10 must distinguish a broken probe from absent functionality.

**Recommendation:** Replace the probe with the actual required symbols/operations and report native symbol availability, named route availability, and verified runtime behavior separately.

### F10 — major — Bitmap color-space support is misclassified

**Fact:** D07 H10:130 claims readback that OPS:2960–2984 only implements for SourceUniformColor.get_color().color_space. P/source.py:483 exposes SourceBitmap.get_color_space, but the MCP source contains no calls to get_color_space, set_color_space, reset_color_space, or list_available_color_spaces. Uniform input validation at OPS:5060 also limits RGB to 0..1; it is not arbitrary HDR/raw Color input.

**Recommendation:** Mark named bitmap color-space read/write unsupported. Distinguish recipe-specific explicit color spaces, implicit setter behavior, normalized colors, bitmap settings, and general conversion/selection.

### F11 — major — Inventory completeness and support-surface classification need correction

**Fact:** D01 omits UVTile.u, UVTile.v, and TextureSet.material_id inherited from private dataclass bases, plus their inherited constructors. D01:393 labels a private ClassVar as a dataclass field. Five non-underscore helper classes contain :meta private: in their source docstrings. Exact evidence appears in the inventory correction table.

**Recommendation:** Add the inherited public fields/constructors, remove the ClassVar from constructor fields, and mark helpers as implementation evidence rather than supported public API. Retain the accurate 0 missing documented top-level function/class/enum count and the 45 covered name-level differences.

### F12 — minor — Async, busy-state, and identity wording overstates guarantees

**Fact:** D06:31/D07 A9 incorrectly groups mesh reload with dispatcher completion: OPS:1846–1864/:1906 uses project.reload_mesh(..., on_loaded), retaining the callback in builtins. Other creation/bake/shelf paths use events. D07 A10 has polling/read access, not a named execute_when_not_busy route. PH/layerstack/navigation.html#substance_painter.layerstack.Node.uid promises an internal integer identifier, not identity persistence across reload, recreation, or undo.

**Recommendation:** Name each completion mechanism and lifecycle separately; distinguish latest retained state from a queue and define concurrency/reentrancy. Replace “stable UID” with the supported identifier/invalidation guarantee.

### F13 — minor — Layered-stack and naming claims need narrower evidence

**Fact:** PH/textureset/stack.html's Stack.name paragraph conflicts with examples/from_name over empty names; the examples establish ordinary unnamed versus layered named stacks. OPS:2011–2012 selects get_stack() with an empty name when a Texture Set is supplied; P/textureset.py:1004–1030 does not guarantee this resolves a layered stack. D05:59's cited from_name documentation supports Texture Set/stack case sensitivity, not resource-name case sensitivity.

**Recommendation:** Note the upstream text contradiction, define explicit layered stack addressing independent of UI selection, and remove the resource case-sensitivity extension unless a resource-specific source is supplied.

### F14 — minor — “Dithering tested” obscures enabled versus disabled cases

**Fact:** D04:71/:76/:77 does not distinguish enabled from disabled dithering cases: [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: A/test_export_fileformats_bitdepth.py.] These are test definitions, not a locally successful run.

**Recommendation:** List exact format/depth/dither combinations and label them expected test behavior. Do not infer enabled-dither support from a disabled-dither case.

### F15 — minor — Raw-code registration, environment propagation, and path guards need precise scope

**Fact:** SRV:814–822 always registers execute_python and gates invocation on the environment value 1. PIPE/painter_mcp_client.py:12 preserves inherited environment; :13–14 forces enablement for direct execute_python, while other modes do not force it off. An inherited enabled flag can therefore allow raw Python through batch. Selected file-operation root checks at OPS:4792–4808 and namespace wrapping in CLIENT:66–99 are not process/security isolation.

**Recommendation:** Document registration versus invocation, inherited environment behavior, and the scope of file guards. Treat raw-code support as an explicit architectural route choice, not an accidental substitute for missing named operations.

### F16 — minor — MCP call lists and patch effects are not fully represented

**Fact:** D06's completeness claim misses BakingParameters.set, LayerNode.enable_mask, Shelf.refresh, and recipe color-space references (OPS:982/:988/:1103/:1188/:2414/:4087). Four local patch postimages match OPS:1359/:1610/:2396/:2486, which does not establish identity with an entire upstream checkout. The fill-mask resource-assignment/UV patch at :2486–2491 applies only to effect_type fill; apply_smart_mask at :2657–2658 passes smart_mask and is unaffected. execute_python directly calls execute_python_json (SRV:822), and useful return data requires assigning result in the wrapper contract.

**Recommendation:** Complete call lists, attribute exact patch scope, and describe JSON-result wrapping accurately. Keep generic layer editing separate from creation-by-name/context.

### F17 — minor — Installed source versions and author-reported runtime observations must remain distinct

**Fact:** P/_version.py:24/:26 declares 0.3.5; P/__init__.py:46 exports it. The executable version resource identifies installed Painter 12.1.0 without launch. MCP/README.md:43–50 attributes 12.1.1/runtime 0.3.5 to the bridge author. Shipped new symbols/changelog entries coexist with the older source version string.

**Recommendation:** Describe static declarations and second-hand runtime observations separately. Prefer feature-specific detection over a stale version string, without claiming this review verified a running application's imports.

### F18 — major — HDF5 identification is not an SPP storage implementation contract

**Fact:** D05's inspected spp/spt/spsm/spmsk specimens begin 89 48 44 46 0d 0a 1a 0a. CUBE contains internal strings ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: R/python/modules/automated_tests/resources/layerstack-cube.spp.]). These observations do not establish hierarchy, entry sizes, compression codecs, hash algorithms, cache semantics, or writable schema. Full-save fragmentation removal is separately documented by J/alg.project.html:1666–1670. A/test_project_open.py:37–49 resolves the future-version test's intent.

**Recommendation:** Preserve the supported format-family and lifecycle observations, explicitly leave storage semantics unverified, and choose whether UzPainter needs behavioral interoperability or binary compatibility. Absence of h5py in one Python environment does not prove no local HDF5 reader exists.

### F19 — major — Several output-relevant operations are hidden by bundled matrix rows

**Fact:** Native export supports per-root preset overrides, filename tokens, derived map families, and scalar or rectangular size settings (PH/export.html:1322–1375/:1401–1415/:1466–1470). MCP takes a scalar size, restricts depth to 8/16/32, and uses a single default preset with limited overrides (OPS:3786/:3791/:3816–3827). Explicit rootPath strings can pass through unchanged, including possible TextureSet/Stack addressing, but this is not a dedicated validated layered-stack picker.

**Recommendation:** Split the export rows and add the gaps below. Treat passthrough as Partial/static route evidence, not live proof. Separate source reset/removal, main graph replacement, per-class active channels, and existing Fill-effect editing because each changes material output.

### F20 — minor — Enum aliases, resolution limits, and instance semantics need scoped claims

**Fact:** P/textureset.py:136–173 and the 0.3.7 changelog establish channel names and alias policy, not every native alias equality. Source procedural overrides document 128–4096/power-of-two constraints, which do not establish a universal bake/render/export cap. Instance documentation supports synchronized content, while examples rename instances and mesh-dependent output can vary.

**Recommendation:** Keep exact native equality mappings as Hypothesis, state each resolution domain separately, and limit “only the source can be modified” to synchronized instance content rather than every Node property.


## Missing or wrongly classified inventory declarations

**Fact:** This table identifies three omitted public fields, two omitted constructor signatures, one private ClassVar incorrectly presented as a dataclass field, and five explicitly private helper classes. **Fact:** It identifies no missing documented top-level function, class, or enum. **Recommendation:** Apply the stated corrections while keeping inherited/aggregate anchor accounting separate.

| Module | Symbol | Problem | Source |
|---|---|---|---|
| textureset | substance_painter.textureset.UVTile.u | Fact: inherited public field omitted at D01:692. Recommendation: add u: int. | P/textureset.py:330; PH/textureset/uvtile.html:831#substance_painter.textureset.UVTile |
| textureset | substance_painter.textureset.UVTile.v | Fact: inherited public field omitted at D01:692. Recommendation: add v: int. | P/textureset.py:331; same class anchor |
| textureset | substance_painter.textureset.TextureSet.material_id | Fact: inherited public field omitted at D01:711. Recommendation: add material_id: int. | P/textureset.py:805; PH/textureset/textureset.html:830#substance_painter.textureset.TextureSet |
| textureset | substance_painter.textureset.UVTile constructor | Fact: inherited signature absent. Recommendation: add `UVTile(u: int, v: int, _material_id: int)`. `_material_id` is not an additional public field. | P/textureset.py:328–335; PH/textureset/uvtile.html:831#substance_painter.textureset.UVTile |
| textureset | substance_painter.textureset.TextureSet constructor | Fact: inherited signature absent. Recommendation: add TextureSet(material_id: int). | P/textureset.py:803–808; PH/textureset/textureset.html:830#substance_painter.textureset.TextureSet |
| layerstack | substance_painter.layerstack.CylindricalProjectionParams (private class attribute; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: P/layerstack.py.]) | Fact: D01:393 labels a private ClassVar as a dataclass field; it is private class metadata, excluded from constructor. Recommendation: remove from public fields or mark private metadata. | P/layerstack.py:1846; PH/layerstack/layereffect/fill.html:1746#substance_painter.layerstack.CylindricalProjectionParams |
| layerstack | substance_painter.layerstack.FillParamsEditorMixin | Fact: non-underscore class explicitly marked :meta private:. Recommendation: mark implementation evidence, not supported public API. | P/layerstack.py:518; D01:299 |
| source | substance_painter.source.ActiveChannelsMixin | Fact: explicitly :meta private:. Recommendation: retain only with private classification. | P/source.py:300; D01:604 |
| source | substance_painter.source.SourceEditorMixin | Fact: explicitly :meta private:. Recommendation: retain only with private classification. | P/source.py:324; D01:607 |
| source | substance_painter.source.OutputMappingIterator | Fact: explicitly :meta private:. Recommendation: retain only with private classification. | P/source.py:709; D01:635 |
| source | substance_painter.source.ChannelMappingIterator | Fact: explicitly :meta private:. Recommendation: retain only with private classification. | P/source.py:983; D01:658 |

**Fact:** No enum-member transcription error was found in the 38 native and 11 Python enum rows. ResourceID's three anchored fields and ReloadMeshStatus's two anchored members already occur in aggregate rows. All 378 directly transcribed callable/property signatures match source AST after excluding implicit self/cls.

**Fact:** P/layerstack.py:1530 annotates `get_node_by_uid(node_id: int)` as `List[Union[HierarchicalNode, EffectNode]]`, and PH/layerstack/navigation.html:1010 renders that same list. It returns a single node; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: P/layerstack.py.] D01:67 already records this upstream discrepancy; it is not a transcription error. **Recommendation:** Preserve the shipped signature with the behavior-consistent single-node return noted separately.

**Fact:** Five HTML/source signature differences reduce to equivalent defaults: `project.create` (P/project.py:824; PH/project.html:1133) uses `Settings()` versus its expanded instance representation; `save`/`save_as`/`save_as_copy` use a private module constant versus `ProjectSaveMode.Incremental` ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: P/project.py.]) (P/project.py:718/:684/:742; PH/project.html:1621/:1653/:1690); `Shelf.resources` uses `StandardQuery.ALL_RESOURCES` versus the empty string (P/resource.py:946; PH/resource.html:2485). HTML alias expansion, forward-reference formatting, module-prefix removal, and optionality inferred from None defaults do not create wrong signatures.

**Fact:** [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: P/_utility.py; P/layerstack.py; P/project.py.] **Recommendation:** Preserve real default_factory expressions rather than copying display-only mutable lists or quoted class names into an implementation.

**Fact:** OutputMapping.__getitem__ is annotated ChannelType at P/source.py:751; __setitem__ accepts str at :754; surrounding examples/prose mix these concepts. D01:671 does not assert a return type. **Hypothesis:** The native output identifier may follow a more specific contract than these inconsistent annotations suggest. **Recommendation:** Resolve that contract separately rather than silently changing the inventory.

## Fact-validation table: D02–D06

**Fact:** The 81 records below are review observations tied to inspected local evidence. “Confirmed” remains static/documentary confirmation. “Qualified,” “incorrect,” and “unresolved” delimit exactly what the source supports.

| ID | Reviewed claim | Inspected source | Fact: validation result / Recommendation where stated |
|---|---|---|---|
| V01 | D02:17 ordinary versus layered stack names | `PH/textureset/stack.html#substance_painter.textureset.Stack` and `#substance_painter.textureset.Stack.from_name` | Confirmed by examples: ordinary stack unnamed; layered stacks named, e.g. Mask1. Stack.name prose contradicts those examples. Recommendation: annotate upstream inconsistency. |
| V02 | D02:18 one channel per type; no add_channel under material layering | Same file #substance_painter.textureset.Stack.add_channel | Confirmed; duplicate addition raises. |
| V03 | D02:24 stable integer UID and stale ValueError | `PH/layerstack/navigation.html#substance_painter.layerstack.Node`, `#substance_painter.layerstack.Node.uid`, `#substance_painter.layerstack.get_node_by_uid` | Qualified: integer internal ID and invalidation are documented; persistence across reload/recreation/undo is not promised. |
| V04 | D02:28–43 twelve node types | PH/layerstack/navigation.html#substance_painter.layerstack.NodeType; P/layerstack.py | Confirmed all 12 types. |
| V05 | D02:42 instance synchronization/source-only editing | PH/layerstack/layereffect/instance.html introduction and #substance_painter.layerstack.instantiate | Qualified: synchronized content is source-driven; examples rename instances; mesh-dependent results can differ. |
| V06 | D02:63–82 insertion rules | PH/layerstack/edition.html, both “Insertion rules” tables | Confirmed cell by cell: Paint/Fill all three contexts; CompareMask/ColorSelection/SmartMask mask-only; Group/SmartMaterial/Instance not relative to an effect. |
| V07 | D02:88 mask colors and duplicate-mask failure | `PH/layerstack/navigation.html#substance_painter.layerstack.MaskBackground` and `#substance_painter.layerstack.LayerNode.add_mask` | Confirmed Black/White and ValueError for second mask. |
| V08 | D02:91 monochannel mask Fill semantics | `PH/layerstack/layereffect/fill.html#substance_painter.layerstack.FillEffectNode.set_source`, `#substance_painter.layerstack.FillEffectNode.source_mode`, `#substance_painter.layerstack.FillEffectNode.get_material_source` | Confirmed None channel/mode; multichannel violation raises EditionContextException; material getter raises RuntimeError outside Material mode. |
| V09 | D02:99–100 channel blend/opacity versus mask None | `PH/layerstack/navigation.html#substance_painter.layerstack.Node.get_blending_mode`, `#substance_painter.layerstack.Node.set_blending_mode`, `#substance_painter.layerstack.Node.set_opacity` | Confirmed; opacity 0..1 and wrong channel presence raises ValueError. |
| V10 | D02:102 blending modes and normal descriptions | PH/layerstack/navigation.html#substance_painter.layerstack.BlendingMode | Confirmed 32 modes; Combine/Detail/InverseDetail descriptions supported. Complete numerical formulas are not supplied. |
| V11 | D02:111–114 OpenPBR/user/legacy channels | PH/textureset/index.html#substance_painter.textureset.ChannelType; P/textureset.py:136–173; H/index.html 0.3.7 changelog | Confirmed names and alias policy; exact native alias equality mapping remains unproved. |
| V12 | D02:122–132 channel formats | PH/textureset/index.html#substance_painter.textureset.ChannelFormat; P/textureset.py:115–133 | Confirmed nine formats, color/grayscale, integer/float depth, and sRGB8 versus linear RGB8. |
| V13 | D02:138 Texture Set/tile resolution rules | PH/textureset/index.html#substance_painter.textureset.Resolution | Confirmed powers of two and square tiles; no universal range established. Source-procedural limits are a different domain. |
| V14 | D02:175 procedural boolean parameter caveat | PH/source/substance.html#substance_painter.source.SourceSubstance.set_parameters warning | Confirmed documented int32/bool caveat despite the annotation. |
| V15 | D02:180 source resolution overrides | PH/source/index.html#substance_painter.source.ResolutionOverride and #substance_painter.source.ResolutionMode; PH/source/substance.html#substance_painter.source.SourceSubstance.resolution | Confirmed 128–4096/power-of-two, Auto log2, and filter restriction; text says deprecated Manual while enum says Custom. Not a global output cap. |
| V16 | D02:207 symmetry bounds | `PH/layerstack/layereffect/fill.html#substance_painter.layerstack.RadialSymmetryParams` and `#substance_painter.layerstack.MirrorSymmetryParams` | Confirmed clamping: count 2..16, angle -360..360, axis position -10..10. |
| V17 | D02:258 user assets empty | C:/Users/Bolado/Documents/Adobe/Adobe Substance 3D Painter/assets, recursively inspected | Confirmed only README.txt in the inspected user asset tree. |
| V18 | D03:13 ten bake maps | P/textureset.py:176–183; PH/baking.html | Confirmed ten MeshMapUsage names; does not establish internal baker-ID equivalence. |
| V19 | D03:30 map source identifiers | E/test_baking.py:113–127; X/Mesh Maps.spexp | Confirmed all ten identifiers, with bent_normals/height/opacity naming differences. |
| V20 | D03:33 Curvature From Map migration | H/index.html 0.3.5 changelog | Confirmed PerVertex removal and min/max to TonemappingBounds for that baker. |
| V21 | D03:40–41 common versus baker properties | P/baking.py:210–243; PH/baking.html#substance_painter.baking.BakingParameters.common and #substance_painter.baking.BakingParameters.baker | Confirmed detail/common merge, high-poly/cage properties, and short-name keys. |
| V22 | D03:43 enum and metadata discovery | PH/properties.html#substance_painter.properties.Property.enum_values and #substance_painter.properties.Property.properties | Confirmed labels-to-integers and metadata examples for ranges, steps, values, and tooltips. |
| V23 | D03:57 OutputSize [10,10] | J/tutorial-baker_parameters.html example; A/test_baking.py:55–70 | Confirmed log2 encoding for 1024 square. |
| V24 | D03:61–63 cage/mesh representation | E/test_baking.py:34–53; PH/baking.html QUrl example | Confirmed pipe-separated URLs and CageMesh; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: E/test_baking.py.] Not all UI enum pairs. |
| V25 | D03:70–72 low/high/backface defaults | CUBE ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: R/python/modules/automated_tests/resources/layerstack-cube.spp.]) | Qualified: stored specimen values, not current initialization defaults. |
| V26 | D03:83–90 internal baker fields | CUBE ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: R/python/modules/automated_tests/resources/layerstack-cube.spp.]) | Confirmed structural group membership in this saved specimen; not the complete 12.1 surface. |
| V27 | D03:90 no individual Normal/NormalWS/Opacity fields | CUBE ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: R/python/modules/automated_tests/resources/layerstack-cube.spp.]) | Confirmed for this saved specimen; does not prove no native options in every version/context. |
| V28 | D03:92 AO examples versus defaults | J/alg.baking.html textureSetBakingParameters, around 1403–1429; CUBE | Confirmed examples are not defaults: the specimen value ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: R/python/modules/automated_tests/resources/layerstack-cube.spp.]) differs from JS example Max_Occluder_Distance 0.1. |
| V29 | D03:119 creation-time common links | PH/baking.html example comment | Confirmed documented creation example; not an executed universal workflow guarantee. |
| V30 | D03:120 async cancellation handle | `PH/baking.html#substance_painter.baking.bake_async` and `#substance_painter.baking.bake_selected_textures_async` | Confirmed StopSource return and BakingProcessEnded completion. |
| V31 | D04:16 export failures/cancelled files | `PH/export.html#substance_painter.export.export_project_textures` | Confirmed documented exception/cancellation behavior and possible Error end event. |
| V32 | D04:20–21 predefined versus resource presets | `PH/export.html#substance_painter.export.PredefinedExportPreset` and `#substance_painter.export.ResourceExportPreset`, list_output_maps methods | Confirmed dynamic/noneditable versus editable resource JSON distinction; predefined map listing requires open project/valid stack. |
| V33 | D04:34–39 packing JSON source families | PH/export.html “Full json_config dict possibilities” code | Confirmed transcription; legacy names, baseColor/basecolor inconsistency, and shorter mesh-map list mean it is not an exhaustive native schema. |
| V34 | D04:53–56 overrides, size, padding | Same PH/export.html JSON block | Confirmed override rules, scalar/aspect and pair sizing, padding/dilation; D04 appropriately corrects apparent 4086 typo to 4096. |
| V35 | D04:65–77 format/depth matrix | A/test_export_fileformats_bitdepth.py:118–284, AST | Confirmed defined cases and expectations; no claim of local test execution. |
| V36 | D04:71/:76/:77 dithering evidence | Same test file:174–181/:246–262 and format cases | Incorrect/ambiguous if “tested” means enabled: [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: A/test_export_fileformats_bitdepth.py.] Recommendation: enumerate actual combinations. |
| V37 | D04:85 shipped export presets | X directory listing | Confirmed 34 .spexp files. |
| V38 | D04:139 binary magic/schema/bounds | Independent struct decoding of all X/*.spexp | Confirmed dd2f7c1b, 209 map records, 34 roots, and exact boundaries; not all numeric semantics. |
| V39 | D04:149 PNG and bit-depth flags | Same 209 decoded maps | Confirmed 209 png strings; observed bit-depth flags 0 in 160 maps and 1 in 49 maps. Human interpretation of flags requires separate evidence. |
| V40 | D04:169–170 Unreal packed ORM/normal | X/Unreal Engine (Packed).spexp | Confirmed, as decoded values, the ORM packing (Mixed AO, roughness, metallic) and a dithered DirectX normal; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: X/Unreal Engine (Packed).spexp.] Human numeric-channel meanings remain inference. |
| V41 | D04:173 SSS alpha channel | X/Unreal Engine SSS (Packed).spexp, comparison across maps | Confirmed that the BaseColor alpha source differs from the non-SSS preset; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: X/Unreal Engine SSS (Packed).spexp.] Scattering semantics remain separate inference. |
| V42 | D04:209 mesh-map export test | E/test_baking.py | [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: E/test_baking.py.] The grayscale-versus-RGB form of written files matters for output comparison. |
| V43 | D05:17–18 GLB and normals | PH/project.html#substance_painter.project.create; A/test_project_create.py; A/resources/__init__.py | [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: A/test_project_create.py; A/resources/__init__.py.] Tests were not run. |
| V44 | D05:20 templates and setting overrides | R/starter_assets/templates; PH/project.html#substance_painter.project.create | Confirmed 26 templates, 12,826,593..13,170,192 bytes, and settings overriding template behavior. |
| V45 | D05:22 project color configuration | PH/project.html#substance_painter.project.create | Confirmed OCIO/ACE/Legacy environment selection, OCIO precedence, and invalid ProjectError. |
| V46 | D05:36/:38 units and unwrap omission | PH/project.html#substance_painter.project.Settings | Confirmed centimeters, zero/None file-unit semantics, None no unwrap, and UsdSettings/GltfSettings support. |
| V47 | D05:46–48 auto-unwrap defaults/limits | `PH/project.html#substance_painter.project.AutoUnwrapSettings`, `#substance_painter.project.AutoUnwrapUVTilesSettingsUVTilesCount`, `#substance_painter.project.AutoUnwrapUVTilesSettingsTexelDensity` | Confirmed actual documented defaults, margin 0..20, tiles 1..1024, density .01..1e6, reference 128..4096, orientation fallback. |
| V48 | D05:59 case-sensitive set/stack/resource names | `PH/textureset/stack.html#substance_painter.textureset.Stack.from_name` | Only set/stack case sensitivity supported. Recommendation: remove resource extension or provide resource-specific evidence. |
| V49 | D05:86–87 Full versus Incremental save | PH/project.html#substance_painter.project.ProjectSaveMode; J/alg.project.html:1666–1670 | Confirmed Full rewrite and removal of incremental fragmentation; no codec/layout proof. |
| V50 | D05:111 HDF5 family signatures | CUBE; R/samples/MeetMat.spp; R/starter_assets/templates/Unreal Engine.spt; R/starter_assets/smart-materials/Effect/Dirt.spsm; R/starter_assets/smart-masks/Cavity Rust.spmsk | Confirmed each inspected first-eight-byte signature 894844460d0a1a0a; not schema/compression/writability. |
| V51 | D05:115 mesh storage strings | CUBE ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: R/python/modules/automated_tests/resources/layerstack-cube.spp.]) | Confirmed strings; entry extraction and layout remain unverified. |
| V52 | D05:119 material/layer field names | CUBE ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: R/python/modules/automated_tests/resources/layerstack-cube.spp.]) | Confirmed strings, not formulas, schema, or public API guarantees. |
| V53 | D06:9 79 matching tools | SRV:25–822; MCP/tool-schema.json tools array | Confirmed identical names, argument names, required/default values, and full nested JSON types. |
| V54 | D06:16 bridge release metadata | MCP/pyproject.toml:7; MCP/CHANGELOG.md:5–7; SRV AST | Confirmed version 1.0.0, 2026-07-28 release attribution, and 79 definitions. |
| V55 | D06:17 author's runtime version | MCP/README.md:43–50 | Confirmed author attribution to Painter 12.1.1/API 0.3.5, not this installation's runtime validation. |
| V56 | D06:18 installed application version | PAINTER/Adobe Substance 3D Painter.exe FileVersion/ProductVersion | Confirmed 12.1.0 from resource metadata without launch. |
| V57 | D06:19 declared dependencies | MCP/pyproject.toml:10–15 | Confirmed Python >=3.10 and mcp >=1.28,<2. |
| V58 | D06:20 64 tests | MCP/CHANGELOG.md:28; MCP/tests files; test_operations.py:34 | Confirmed 62 test functions plus two extra cases from one three-case parametrization; no tests executed. |
| V59 | D06:26 server transport/name | SRV:14–19/:825–826 | Confirmed FastMCP “SubstancePainter” and stdio. |
| V60 | D06:27 remote protocol | CLIENT:33–43/:50–51/:101–110 | Confirmed defaults and POST /run.json with base64 Python/JavaScript payloads. |
| V61 | D06:28 each operation is a Painter snippet | CLIENT:66–99; OPS:2174; OPS:90–101 | Qualified: local diff/composition exists; status uses raw Python plus JS. Namespace wrapper is not a security sandbox. |
| V62 | D06:29 error handling | CLIENT:16–29/:113–132 | Confirmed connection, HTTP, and script-error classes/handling. |
| V63 | D06:30 status uses Python/JS | CLIENT:56–58; OPS:90–101 | Confirmed source calls. |
| V64 | D06:31 all long jobs use dispatcher | OPS:1846–1864/:1906 | Incorrect for mesh reload: callback retained in builtins; creation/bake/shelf use events. Latest-state retention confirmed. |
| V65 | D06:32 all mutations use UIDs | SRV:375–433, new-layer/recipe signatures | Incorrect as blanket statement: existing-node writes use UIDs; creation uses names/context. |
| V66 | D06:33 raw Python gate | SRV:814–822 | Confirmed invocation requires environment value 1; registration is unconditional. |
| V67 | D06:39–45 env/root guards | CLIENT:33–43; OPS:4792–4808 and validators | Confirmed selected-operation guards; Windows os.pathsep is semicolon. Not process isolation. |
| V68 | D06:46 import usages/extensions | OPS:56–74 | Confirmed import restrictions, not restrictions on arbitrary raw code. |
| V69 | D06:47 six export profiles | OPS:17–53 | Confirmed six named profile definitions, PNG8 defaults. |
| V70 | D06:51 pipeline environment/modes | PIPE/painter_mcp_client.py:8–43 | Qualified: inherited enabled raw flag is preserved; direct execute_python forces it on; other modes do not force it off, so batch can retain it. |
| V71 | D06:55 confirmation guards | OPS:261/:856/:1428/:3961; schema | Confirmed guard code; not live exercise. |
| V72 | D06:9/:59/:141 complete per-tool API calls | OPS:982/:988/:1103/:1188/:2414/:4087 | Incomplete: missing BakingParameters.set, LayerNode.enable_mask, Shelf.refresh, recipe color-space references. |
| V73 | D06:139 raw execution direct route | SRV:822; CLIENT:66–99 | Qualified: directly execute_python_json, which wraps eventual raw execution; assign result for useful returned JSON data. |
| V74 | D06:145 four local patch hunks | Local patch postimages at OPS:1359/:1610/:2396/:2486 | Confirmed exact postimages; not proof of full upstream checkout identity. |
| V75 | D06:149–150 non-UDIM guard | Local patch lines 5–21; OPS:1362/:1613 | Confirmed enabled-tile checks only when has_uv_tiles. |
| V76 | D06:151 recipe color spaces | Local patch lines 23–35; OPS:2399–2406 | Confirmed explicit choices/fallback code; not proof Raw is semantically correct for every non-BaseColor channel. |
| V77 | D06:152 Fill-mask resolution/UV patch | Local patch lines 39–45; OPS:2486–2491/:2657–2658 | Confirmed fill-only branch; apply_smart_mask passes smart_mask and is unaffected. Recommendation: narrow affected-tool claim. |
| V78 | D06:154 unspecified Color inference | P/colormanagement.py:153–186/:205–215 | Confirmed some conversions reject unspecified color-space state. |
| V79 | D06:161 recipe failure removes everything | OPS:2425–2433 | Incorrect guarantee: cleanup is best effort and suppresses failures. |
| V80 | D06:162 shipped recipe | MCP/examples/recipes/vrchat_outfit.json; OPS:2390–2391 | Confirmed file configuration; Paint active-channel native effect is not established and the assignment path is defective. |
| V81 | D06:163 portable baking preset | OPS:1222–1309/:1245–1249 | Confirmed substance-painter-mcp/baking-preset@1 schema, fields, and widget restrictions. |


## Resolved hypotheses and remaining uncertainty

| Item | Fact: resolution and evidence | Recommendation / Hypothesis boundary |
|---|---|---|
| R01 — baking preset capability | OPS:604 checks nonexistent BakingParameters.get; P/baking.py:139–413 has no method/inheritance/metaclass supplying it, while named capture/apply exists. | Recommendation: replace the false-negative probe. It is not evidence that native property-based preset capture/apply is unavailable. |
| R02 — content-stack effects | OPS:2014–2050/:2937–2994/:3033–3088 and generic UID edits can inspect/edit existing content effects. | Recommendation: replace D06:175's blanket absence claim with absence of a named content-effect insertion route. |
| R03 — future_binary_data | A/test_project_open.py ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: A/test_project_open.py.]) | Recommendation: mark this intent Fact; it is not evidence of unknown ordinary project data semantics. |
| R04 — Full-save compaction | J/alg.project.html:1666–1670 explicitly describes incremental fragmentation/disk growth and removal by Full save. | Recommendation: resolve the fragmentation-removal hypothesis; keep codec/layout/all-UI-side-effect claims separate. |
| R05 — saved baker grouping | [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: R/python/modules/automated_tests/resources/layerstack-cube.spp.] | Recommendation: classify grouping/stored values as Fact; current defaults and numeric UI enum meanings remain Hypothesis. |
| R06 — preset encoding | Independent decoding matched 209 map boundaries and 34 root boundaries in X/*.spexp; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: X/*.spexp.] | Recommendation: classify structural encoding as Fact; native numeric semantics remain Hypothesis unless separately evidenced. |
| R07 — inherited API fields | P/textureset.py:328–335/:803–808 and both HTML constructor signatures resolve UVTile/TextureSet fields statically. | Recommendation: add fields/constructors; no runtime experiment is needed to resolve this documentation omission. |
| U01 — exact native channel alias equalities | P/textureset.py:136–173 and H/index.html 0.3.7 provide names/policy, but native enum objects are exposed rather than defined here. | Hypothesis: precise equality mappings require additional native/runtime evidence; do not infer every mapping by naming. |
| U02 — predefined glTF packing | X has no glTF .spexp; PH/export.html documents dynamic predefined map listing without furnishing this exact map list. | Hypothesis: exact predefined glTF packing remains unverified locally by this static evidence. |
| U03 — SPP hierarchy/semantics | CUBE strings/magic support the limited observations in V50–V52. | Hypothesis: serialized type semantics ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: R/python/modules/automated_tests/resources/layerstack-cube.spp.]), hash algorithm, cache rules, hierarchy, compression, and entry sizes remain unverified. |
| U04 — native OutputMapping return contract | P/source.py:751/:754 and nearby example disagree in type/usage emphasis. | Hypothesis: actual native return semantics require separate evidence; no silent signature correction is justified. |
| U05 — current defaults and numerical equivalence | Old specimen values, shipped examples, and unexecuted tests do not report a controlled current initialization/output run. | Recommendation: define a reproducible oracle capture and acceptance criteria instead of upgrading these observations into verified runtime parity. |

[Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: R/python/modules/automated_tests/resources/layerstack-cube.spp.]

[Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: X/*.spexp.] **Hypothesis:** Numeric channel/destination/bit-depth meanings beyond independently evidenced cases remain semantic mappings, not consequences of boundary agreement.

## Parity matrix: row dispositions

**Fact:** Every one of D07's 140 rows was reviewed. The original counts are 59 Yes, 24 Partial, 51 No, and 6 N/A, with zero exact duplicate rows. The grouped ID ranges below cover each original row exactly once. “No additional discrepancy” is a review observation about the cited document/evidence, not runtime validation. **Recommendation:** Preserve a row only within its stated route/context; “No named route” must not imply Painter product impossibility.

| D07 row(s) | Fact: reviewed evidence / qualification | Recommendation: disposition |
|---|---|---|
| A1 | D07 A1 and MCP/README.md:43–50 mix installed/source metadata with author runtime attribution. | Keep Partial with explicit attribution. |
| A2 | OPS:604 false-negative baking preset probe; native symbol and usable named operation differ. | Split native availability, named route, runtime verification. |
| A3–A6 | D07 A3–A6 and D06 source inventory reveal no additional discrepancy. | Retain bounded static claims. |
| A7 | SRV:814–822 always registers raw Python, with invocation gate. | Retain gated support; correct registration wording. |
| A8 | SRV tool inventory has no named raw-JS tool; enabled Python can call js.evaluate. | Keep no named JS route; distinguish optional raw composition. |
| A9 | OPS:1846–1864/:1906 uses callback for mesh reload. | Remove mesh reload from dispatcher-event examples. |
| A10 | Named operations read/poll busy state; no execute_when_not_busy route found. | No named “wait until not busy” operation. |
| B1 | D07 B1 and project workflow evidence V43–V47 show no additional discrepancy. | Retain scope. |
| B2 | Project settings evidence concerns creation; existing-state edits are different. | Explicitly label creation-only settings. |
| B3–B12 | D07 B3–B12 and V43–V49 show no additional discrepancy. | Retain bounded operation claims. |
| B13 | OPS:103–120 returns open/name/path/sets; dirty state appears via plans, not is_in_edition_state. | Partial bundle or remove claimed edition-state exposure. |
| B14–B16 | D07 B14–B16 and project source evidence show no additional discrepancy. | Retain scope; avoid SPP schema inference. |
| C1–C7 | D07 C1–C7 read/write distinctions are defensible against Texture Set API evidence. | Retain explicit read/write scope. |
| C8 | OPS:2011–2012 calls get_stack() with empty name; P/textureset.py:1004–1030 does not guarantee layered resolution. | Partial; specify explicit layered stack addressing and UI active-stack dependency. |
| C9 | Existing route is read-only. | Keep Partial/read-only. |
| C10 | OPS:641–643 returns channel key names, not Channel.format/label/metadata; P/textureset.py:654–672 exposes richer mapping. | Partial, or rename to “list channel type names.” |
| C11–C12 | D07 C11–C12 show no additional discrepancy. | Retain bounded claims. |
| D1 | OPS snapshot traverses selected stack and summarizes effects, without complete parent/sibling queries. | Narrow traversal claim. |
| D2 | Existing-node writes use UIDs; new creation uses names/context (SRV:375–433). | Narrow UID mutation claim. |
| D3–D6 | D07 D3–D6 show no additional discrepancy. | Retain scope. |
| D7 | OPS:3714–3731 can mutate visibility before mask blend readback fails. | Qualify failure-after-mutation behavior. |
| D8 | Snapshot reads collapse state; no named collapse write found. | Preserve read versus write distinction. |
| D9–D11 | D07 D9–D11 show no additional discrepancy. | Retain scope. |
| D12 | OPS:2425–2433 suppresses cleanup failures; no atomic transaction. | Best-effort cleanup, not Atomic. |
| D13 | OPS:2014–2057 provides structural snapshot/diff, omitting important material values. | Yes only for structural comparison; not output-equivalence oracle. |
| D14 | Public Python does not expose strokes; product painting output remains relevant. | N/A only for this public API surface, never a product-parity exemption. |
| E1 | OPS:2014–2050/:2937–2994/:3033–3088 handles existing content effects, not named insertion. | Partial broad row, or narrow “insert content effect” to No. |
| E2 | Fill insertion sets fixed UV at creation; no general existing Fill-effect editing implied. | Keep insertion support and narrow editing scope. |
| E3 | D07 E3 insertion claim is defensible. | Retain scope. |
| E4–E5 | Mask-only insertion differs from input-image editing on an existing UID; main graph replacement/removal and numeric parameter support are absent. | Partial, with operation/context split. |
| E6–E9 | D07 E6–E9 show no additional discrepancy. | Retain scope. |
| E10 | Native methods are get_levels/set_levels, not get_set_levels; no named reference mapping/alpha/levels edits. | Keep Partial; correct symbol and enumerate missing operations. |
| F1–F3 | Mask operations exist, but OPS:3668–3674 removes a mask when enabled=false. | Do not describe this as preserving a disabled mask. |
| F4 | export_smart_mask plus import_shelf_resource(usage SMART_MASK) composes shelf creation; no direct native create wrapper. | Partial/composed support, not blanket raw-only absence. |
| F5–F6 | D07 F5–F6 show no additional discrepancy. | Retain scope. |
| G1–G2 | Native-backed blend/opacity calls work only in accepted node/channel contexts. | Keep Yes with context limits. |
| G3 | OPS:3714–3731 always supplies ChannelType; mask requires None. | No named mask blend/opacity route. |
| H1 | OPS:5060 limits RGB to 0..1. | Yes for normalized basic colors, not arbitrary HDR/raw Color values. |
| H2–H3 | Basic named operations accept FillLayer context. | Keep basic FillLayer-only support. |
| H4 | OPS:2225–2244 falsely accepts Paint; empty set rejected at :2217–2218; FillEffect/Generator/Filter not accepted. | Partial by class; explicitly flag Paint false success. |
| H5–H6 | Named parameter/preset routes reject effects/generators/filters. | Partial broad substance editing, or narrow rows to FillLayer. |
| H7 | Resource assignment/reset exists; no Color/anchor/remove_source route; monochannel .name bug at OPS:2945/:3041. | Partial with broken mask Fill path explicit. |
| H8–H9 | D07 H8–H9 no named read/write route found. | Keep No named support. |
| H10 | OPS:2960–2984 reads uniform Color space only; no bitmap color-space calls. | No named bitmap color-space read/write. |
| H11–H12 | OPS:3158–3191 accepts unrestricted ResourceID; FONT import exists at :64; specialized vector/font parameter editing absent. | Separate binding Partial from specialized parameter editing No. |
| H13 | No dedicated fill-preset application route found. | Keep No dedicated route. |
| I1–I3 | OPS:2665/:2799–2801 restrict projection editing to FillLayer and reject FillEffect; I3 physical-scale limit is accurate. | Preserve FillLayer-only support and physical-scale restriction. |
| I4–I6 | No named setters; existing FillLayer inspection can report mode/common fields. | No named mutation, with readback noted separately. |
| J1 | D07 J1 support claim is defensible. | Retain scope. |
| J2 | export_smart_material plus import_shelf_resource composes shelf creation. | Partial/composed route; no direct native create wrapper. |
| J3 | D07 J3 support claim is defensible. | Retain scope. |
| K1–K8 | D07 K1–K8 show no additional discrepancy. | Retain scope. |
| K9 | Shelf.refresh is called; Shelves.refresh_all is not wrapped. | Partial bundled refresh claim. |
| K10 | No named route found. | Keep No named support. |
| L1 | Native-backed baking configuration access exists. | Retain Yes within documented property surface. |
| L2 | File/FileList/Resource widgets are rejected by generic mutation; L3/L4 are dedicated routes; OPS:989–1001 rollback is best effort. | Narrow “any property” or Partial; remove transactional guarantee. |
| L3–L9 | D07 L3–L9 and V18–V30 show no additional discrepancy. | Retain bounded static support. |
| L10 | Named capture/apply exists despite OPS:604 false-negative probe. | Distinguish usable route from capability flag. |
| L11 | Public control absent in examined API. | N/A only to stated public-control surface. |
| M1–M2 | D07 M1–M2 support claims are defensible. | Retain scope. |
| M3 | No named packing read route found. | Keep No named support. |
| M4 | Resource/URL presets work with scalar global overrides (OPS:3816–3827). | Limit claim to those routes/overrides. |
| M5 | No inline preset definition or packing editor, but resource/URL presets are accepted. | No inline definition/editing; do not claim all custom presets absent. |
| M6 | PH/export.html:1401–1415 supports scalar or pair; OPS:3786/:3791 accepts integer size and depths 8/16/32. | Partial against full native dimensions/format contract. |
| M7 | Fixed default settings are not exposed user controls. | State defaults separately from adjustable support. |
| M8–M9 | No direct rule/subset control found. | Keep No direct named control. |
| M10 | OPS:3799/:3836/:4322/:4331 passes supplied strings unchanged to rootPath; PH/export.html:1437–1443 supports TextureSet/Stack paths. | Partial implicit passthrough, without dedicated picker/enumeration or live validation. |
| M11–M16 | D07 M11–M16 show no further discrepancy; M12 depends on an undocumented private key. | Retain named/public limits; do not promote M12 private behavior to a supported contract. |
| N1–N8 | D07 N1–N8 show no further discrepancy; N5 is public JS, N6 private. | Preserve route distinctions; absence from public Python is not product absence. |
| O1 | Some recipe colors use explicit spaces; other setters retain implicit behavior. | Partial, route-specific color-space support. |
| O2 | No general named selection/conversion; reporting a Color's space string is different. | No general named conversion/selection. |

## Matrix gaps, overlap, and output implications

**Fact:** No exact duplicate row was found. **Recommendation:** Do not automatically delete intentional overlap or count all 140 rows as independent features. The 11 overlap clusters are application/jobs; project creation/settings; Texture Set resolution/read/write/tiles; channel listing/editing; layer insertion/recipes; effect location/kind; uniform colors/color management; projection modes/transforms; import/shelves; baking configuration/presets; and export presets/packing/rules. D07 row dispositions above establish the corresponding scopes.

| Gap | Fact: local evidence | Recommendation: missing distinction |
|---|---|---|
| Source reset/removal/mode changes | P/source.py:388–435 reset_source/reset_material_source; :882 SourceSubstance.remove_source | Separate reset, remove, and source-mode transition contracts. |
| Main Generator/Filter graph replacement | P/layerstack.py:1255–1272/:1425–1443 | Separate main resource replacement/removal from insertion and graph image-input editing. |
| Existing Fill effects | OPS:2665/:2799–2801/:2945/:3041 and native Fill methods | Split layer/content-effect/mask-effect contexts for source, parameters, projection, and symmetry. |
| Active channels | OPS:2217–2244; P/source.py:308–321 | State each supported node class and empty-set behavior, including false Paint assignment. |
| Bake mutation/links/rollback | OPS:960–970/:989–1001 | Separate native property writes, linked Texture Set propagation, and rollback scope. |
| Export filename tokens | PH/export.html:1322–1334 | Cover $project, $mesh, $textureSet, $sceneMaterial, $udim, $uvTileName, and $colorSpace; preset-driven availability differs from direct MCP template input. |
| Export derivations/normal convention | PH/export.html:1350–1375 | Separate document/mesh/virtual/constant sources, `Normal_OpenGL`/`Normal_DirectX`, `AO_Mixed`, Glossiness, and f0 from mesh import normal format. |
| Rectangular export sizing | PH/export.html:1401–1415; OPS:3786/:3791 | Separate pair sizing from scalar/aspect behavior and MCP scalar limitations. |
| Per-root presets | PH/export.html:1466–1470 exportList.exportPreset | Separate per-root preset selection from one MCP default and from parameter-rule overrides. |
| Semantic snapshots | OPS:2014–2057 | Capture omitted material-producing values before using snapshots as an equivalence oracle. |
| Existing versus new project | PH/project.html#substance_painter.project.Settings; project creation routes | Split creation settings from existing-project mutation. |
| Vector/font binding versus parameters | P/source.py:531–704; OPS:3158–3191/:64 | Preserve generic resource binding while marking specialized parameter editing absent. |


## Coverage appendix: all 45 HTML names without standalone inventory rows

**Fact:** These are name-level inventory differences, not missing capabilities. The first 40 are inherited methods/properties acknowledged by D01's conventions or generic inheritance rows; the final five are enum members/fields already present in aggregate rows. D01:421 covers Fill mixins, :422 covers Generator/Filter active channels, and :9 acknowledges inherited uid on source classes. Node.uid is explicitly named at D01:420 and is excluded from these 45.

**Fact:** For rows A01–A34, the HTML file is PH/layerstack/layereffect/fill.html; the complete anchor is the fully qualified name shown. Signatures use the existing source aliases Source, ProjectionParams, and SymmetryParams. Getter/setter pairs remain one qualified property symbol.

| ID | Full HTML symbol / anchor | Fact: declaration or inherited signature | Fact: HTML line; source implementation |
|---|---|---|---|
| A01 | `substance_painter.layerstack.FillLayerNode.active_channels` | `property active_channels: Set[ChannelType]`; setter accepts `channels: Set[ChannelType]` | fill.html:943; P/source.py:308/:320 |
| A02 | `substance_painter.layerstack.FillLayerNode.get_material_source` | `get_material_source() -> SourceSubstance \| SourceReference` | fill.html:959; P/source.py:398 |
| A03 | `substance_painter.layerstack.FillLayerNode.get_projection_mode` | `get_projection_mode() -> ProjectionMode` | fill.html:980; P/layerstack.py:525 |
| A04 | `substance_painter.layerstack.FillLayerNode.get_projection_parameters` | `get_projection_parameters() -> ProjectionParams \| None` | fill.html:994; P/layerstack.py:542 |
| A05 | `substance_painter.layerstack.FillLayerNode.get_source` | `get_source(channeltype: ChannelType \| None = None) -> Source` | fill.html:1016; P/source.py:349 |
| A06 | `substance_painter.layerstack.FillLayerNode.get_symmetry_parameters` | `get_symmetry_parameters() -> SymmetryParams` | fill.html:1041; P/layerstack.py:595 |
| A07 | `substance_painter.layerstack.FillLayerNode.is_symmetry_enabled` | `is_symmetry_enabled() -> bool` | fill.html:1062; P/layerstack.py:573 |
| A08 | `substance_painter.layerstack.FillLayerNode.reset_material_source` | `reset_material_source() -> None` | fill.html:1081; P/source.py:429 |
| A09 | `substance_painter.layerstack.FillLayerNode.reset_source` | `reset_source(channeltype: ChannelType \| None = None) -> None` | fill.html:1095; P/source.py:388 |
| A10 | `substance_painter.layerstack.FillLayerNode.set_material_source` | `set_material_source(source: ResourceID \| layerstack.AnchorPointEffectNode) -> SourceSubstance \| SourceReference` | fill.html:1113; P/source.py:409 |
| A11 | `substance_painter.layerstack.FillLayerNode.set_projection_mode` | `set_projection_mode(projection_mode: ProjectionMode)` | fill.html:1136; P/layerstack.py:533 |
| A12 | `substance_painter.layerstack.FillLayerNode.set_projection_parameters` | `set_projection_parameters(projection_parameters: ProjectionParams)` | fill.html:1150; P/layerstack.py:558 |
| A13 | `substance_painter.layerstack.FillLayerNode.set_source` | `set_source(channeltype: ChannelType \| None, source: ResourceID \| Color \| layerstack.AnchorPointEffectNode) -> Source` | fill.html:1169; P/source.py:362 |
| A14 | `substance_painter.layerstack.FillLayerNode.set_sources_from_preset` | `set_sources_from_preset(preset: ResourceID) -> None` | fill.html:1196; P/source.py:437 |
| A15 | `substance_painter.layerstack.FillLayerNode.set_symmetry_enabled` | `set_symmetry_enabled(enabled: bool)` | fill.html:1213; P/layerstack.py:584 |
| A16 | `substance_painter.layerstack.FillLayerNode.set_symmetry_parameters` | `set_symmetry_parameters(symmetry_parameters: SymmetryParams)` | fill.html:1229; P/layerstack.py:609 |
| A17 | `substance_painter.layerstack.FillLayerNode.source_mode` | `property source_mode: SourceMode` | fill.html:1258; P/source.py:332 |
| A18 | `substance_painter.layerstack.FillEffectNode.active_channels` | `property active_channels: Set[ChannelType]`; setter accepts `channels: Set[ChannelType]` | fill.html:1285; P/source.py:308/:320 |
| A19 | `substance_painter.layerstack.FillEffectNode.get_material_source` | `get_material_source() -> SourceSubstance \| SourceReference` | fill.html:1301; P/source.py:398 |
| A20 | `substance_painter.layerstack.FillEffectNode.get_projection_mode` | `get_projection_mode() -> ProjectionMode` | fill.html:1322; P/layerstack.py:525 |
| A21 | `substance_painter.layerstack.FillEffectNode.get_projection_parameters` | `get_projection_parameters() -> ProjectionParams \| None` | fill.html:1336; P/layerstack.py:542 |
| A22 | `substance_painter.layerstack.FillEffectNode.get_source` | `get_source(channeltype: ChannelType \| None = None) -> Source` | fill.html:1358; P/source.py:349 |
| A23 | `substance_painter.layerstack.FillEffectNode.get_symmetry_parameters` | `get_symmetry_parameters() -> SymmetryParams` | fill.html:1383; P/layerstack.py:595 |
| A24 | `substance_painter.layerstack.FillEffectNode.is_symmetry_enabled` | `is_symmetry_enabled() -> bool` | fill.html:1404; P/layerstack.py:573 |
| A25 | `substance_painter.layerstack.FillEffectNode.reset_material_source` | `reset_material_source() -> None` | fill.html:1423; P/source.py:429 |
| A26 | `substance_painter.layerstack.FillEffectNode.reset_source` | `reset_source(channeltype: ChannelType \| None = None) -> None` | fill.html:1437; P/source.py:388 |
| A27 | `substance_painter.layerstack.FillEffectNode.set_material_source` | `set_material_source(source: ResourceID \| layerstack.AnchorPointEffectNode) -> SourceSubstance \| SourceReference` | fill.html:1455; P/source.py:409 |
| A28 | `substance_painter.layerstack.FillEffectNode.set_projection_mode` | `set_projection_mode(projection_mode: ProjectionMode)` | fill.html:1478; P/layerstack.py:533 |
| A29 | `substance_painter.layerstack.FillEffectNode.set_projection_parameters` | `set_projection_parameters(projection_parameters: ProjectionParams)` | fill.html:1492; P/layerstack.py:558 |
| A30 | `substance_painter.layerstack.FillEffectNode.set_source` | `set_source(channeltype: ChannelType \| None, source: ResourceID \| Color \| layerstack.AnchorPointEffectNode) -> Source` | fill.html:1511; P/source.py:362 |
| A31 | `substance_painter.layerstack.FillEffectNode.set_sources_from_preset` | `set_sources_from_preset(preset: ResourceID) -> None` | fill.html:1538; P/source.py:437 |
| A32 | `substance_painter.layerstack.FillEffectNode.set_symmetry_enabled` | `set_symmetry_enabled(enabled: bool)` | fill.html:1555; P/layerstack.py:584 |
| A33 | `substance_painter.layerstack.FillEffectNode.set_symmetry_parameters` | `set_symmetry_parameters(symmetry_parameters: SymmetryParams)` | fill.html:1571; P/layerstack.py:609 |
| A34 | `substance_painter.layerstack.FillEffectNode.source_mode` | `property source_mode: SourceMode` | fill.html:1600; P/source.py:332 |
| A35 | `substance_painter.layerstack.FilterEffectNode.active_channels` | `property active_channels: Set[ChannelType]`; inherited, D01:422 | PH/layerstack/layereffect/filter.html:957; P/source.py:308/:320 |
| A36 | `substance_painter.layerstack.GeneratorEffectNode.active_channels` | `property active_channels: Set[ChannelType]`; inherited, D01:422 | PH/layerstack/layereffect/generator.html:952; P/source.py:308/:320 |
| A37 | `substance_painter.source.SourceBitmap.uid` | `uid() -> int`; inherited | PH/source/bitmap.html:934; P/_utility.py:262 |
| A38 | `substance_painter.source.SourceFont.uid` | `uid() -> int`; inherited | PH/source/font.html:912; P/_utility.py:262 |
| A39 | `substance_painter.source.SourceUniformColor.uid` | `uid() -> int`; inherited | PH/source/uniformcolor.html:892; P/_utility.py:262 |
| A40 | `substance_painter.source.SourceVectorial.uid` | `uid() -> int`; inherited | PH/source/vectorial.html:917; P/_utility.py:262 |
| A41 | `substance_painter.project.ReloadMeshStatus.ERROR` | `ERROR = 2`; already in D01:491 enum row | PH/project.html:1910#substance_painter.project.ReloadMeshStatus.ERROR |
| A42 | `substance_painter.project.ReloadMeshStatus.SUCCESS` | `SUCCESS = 0`; already in D01:491 enum row | PH/project.html:1916#substance_painter.project.ReloadMeshStatus.SUCCESS |
| A43 | `substance_painter.resource.ResourceID.context` | `context: str`; already in class fields | PH/resource.html:1706#substance_painter.resource.ResourceID.context; P/resource.py:101 |
| A44 | `substance_painter.resource.ResourceID.name` | `name: str`; already in class fields | PH/resource.html:1717#substance_painter.resource.ResourceID.name; P/resource.py:102 |
| A45 | `substance_painter.resource.ResourceID.version` | `version: str = None`; already in class fields | PH/resource.html:1728#substance_painter.resource.ResourceID.version; P/resource.py:103 |

**Fact:** The raw comparison against only simple symbol cells produces 46 differences because D01:420 appends explanatory text to Node.uid. Recognizing that explicitly named row yields the correct 45. PH/layerstack/navigation.html:1327#substance_painter.layerstack.Node.uid and P/_utility.py:262 support it.

## Scope appendix: source-only names, aliases, and dunders

**Fact:** The following 43 inventory names have no same-name HTML anchor. Several are constructors described by a class signature or helper methods documented through inherited concrete classes; this is not a count of 43 undocumented capabilities. Each module expands to P/<module>.py. A leading member suffix continues the fully named class in that cell; property setters do not add unique symbol names.

| Module | Fact: complete source-only name list and declaration lines |
|---|---|
| colormanagement | ColorColorSpace:116; ResourceColorSpace:117; Color.__init__:192 |
| event | Dispatcher.__init__:457 |
| layerstack | GeometryMaskParams:239; ScopedModification.__init__:483; FillParamsEditorMixin:518; FillParamsEditorMixin.get_projection_mode:525; FillParamsEditorMixin.set_projection_mode:533; FillParamsEditorMixin.get_projection_parameters:542; FillParamsEditorMixin.set_projection_parameters:558; FillParamsEditorMixin.is_symmetry_enabled:573; FillParamsEditorMixin.set_symmetry_enabled:584; FillParamsEditorMixin.get_symmetry_parameters:595; FillParamsEditorMixin.set_symmetry_parameters:609 |
| logging | INFO:60; WARNING:61; ERROR:62; DBG_INFO:63; DBG_WARNING:64; DBG_ERROR:65 |
| project | AutoUnwrapUVTilesSettings:246; Settings.usd_settings:439; MeshReloadingSettings.usd_settings:482; Metadata.__init__:1061 |
| properties | PropertyValue:29 |
| resource | ReloadResourcesFilter:1245 |
| source | ActiveChannelsMixin:300; ActiveChannelsMixin.active_channels:308; SourceEditorMixin:324; SourceEditorMixin.source_mode:332; SourceEditorMixin.get_source:349; SourceEditorMixin.set_source:362; SourceEditorMixin.reset_source:388; SourceEditorMixin.get_material_source:398; SourceEditorMixin.set_material_source:409; SourceEditorMixin.reset_material_source:429; SourceEditorMixin.set_sources_from_preset:437; OutputMappingIterator:709; OutputMappingIterator.__init__:716; ChannelMappingIterator:983; ChannelMappingIterator.__init__:990; Source:1118 |

**Fact:** D01's declared non-underscore extraction scope excludes ordinary dunders. It selectively summarizes two ScopedModification context-manager methods and ten OutputMapping/ChannelMapping dictionary-like methods. The 17 additional directly declared true dunders below lack standalone coverage, but are outside that stated extraction scope. Private name-mangled Color helpers, generated dataclass dunders, inherited object methods, and imported typing names are not missing public capabilities.

| Source | Fact: additional dunder declarations |
|---|---|
| P/async_utils.py | StopSource.__bool__:33 |
| P/layerstack.py | Node.__eq__:650; Node.__hash__:653 |
| P/project.py | AutoUnwrapUVTilesSettingsUVTilesCount.__setattr__:222; AutoUnwrapUVTilesSettingsTexelDensity.__setattr__:242; AutoUnwrapSettings.__setattr__:294 |
| P/resource.py | Resource.__eq__:319; Resource.__hash__:325 |
| P/source.py | ResolutionOverride.__setattr__:223; SourceFontParams.__setattr__:573; SourceVectorialParams.__setattr__:660; OutputMappingIterator.__iter__:720; OutputMappingIterator.__next__:723; ChannelMappingIterator.__iter__:994; ChannelMappingIterator.__next__:997 |
| P/textureset.py | Stack.__str__:613; TextureSet.__str__:914 |

**Recommendation:** Do not add these 17 dunders, the 43 anchorless names, aggregate enum members, or aliases to the three omitted inherited-public-field count. If downstream architecture needs mutation validation, iteration semantics, or equality/hash behavior, document those contracts explicitly as a separate scope choice.

## Numbered architect questions

1. **Recommendation — parity target:** Is the product contract parity with Painter's product behavior, the public Python API, named MCP operations, or a defined subset of each? Which outputs remain required when no public API exposes the feature?
2. **Recommendation — AI-only interface:** Which Qt/UI/menu/layout/plugin helpers may be omitted from an AI-only product, while preserving active-stack dependencies, asynchronous lifecycle/events, and camera/display/color state that affects output?
3. **Recommendation — painting and rendering:** How will product-level strokes, shaders, and Iray-equivalent rendering be addressed when the examined public Python surface is absent or incomplete? N/A for an API surface should not exempt an output-relevant product feature.
4. **Recommendation — mutation acceptance:** Must supported mutations survive readback from a freshly resolved object and, when relevant, save/reload and output comparison? How will false Python-only attribute writes be rejected?
5. **Recommendation — class and context model:** Will every operation declare its supported node classes and layer/content-effect/mask-effect contexts, including None channel/source-mode behavior and empty active-channel sets?
6. **Recommendation — failure guarantees:** Is the required transaction model best effort, restoration from a backup, or atomic commit? How are cleanup failures, linked-set changes, and mutation-before-readback failure reported?
7. **Recommendation — stack addressing:** What explicit layered TextureSet/Stack address replaces reliance on the current UI active stack or the empty default stack name?
8. **Recommendation — raw-code policy:** Is raw Python/JavaScript an official supported route or an escape hatch? How should unconditional registration and gated invocation, inherited environment flags, private APIs, and composed named operations affect support labels?
9. **Recommendation — equivalence threshold:** Must outputs be bitwise identical, or within specified numerical/perceptual tolerances? What acceptance rules cover alpha, normal vectors, seams, padding, quantization, and color conversions?
10. **Recommendation — reproducible oracle:** What complete fixture records scene, mesh, asset and preset versions, seed where applicable, camera, lighting, color configuration, export settings, renderer/backend, and execution environment? What determinism is required, without assuming undocumented native internals are deterministic?
11. **Recommendation — semantic state:** Which material-producing values must a snapshot include beyond structure: sources, graph parameters, channel mappings, per-channel blending/opacity, projections, masks, symmetry, resolution overrides, and color spaces?
12. **Recommendation — defaults and capability discovery:** How will current default/property captures be versioned separately from old specimens and examples, and how will native symbol presence, named route support, and verified runtime behavior be reported independently?
13. **Recommendation — shading/export contract:** Which OpenPBR/legacy alias mappings, shader conventions, source derivations, rectangular export sizes, per-root presets, tokens, and bitmap color-space controls are necessary for the chosen output target?
14. **Recommendation — asynchronous ownership:** How are job concurrency, cancellation, callback lifetimes, event ordering, and retained latest-state slots handled? Is a queue required, or must callers serialize jobs?
15. **Recommendation — persistence scope:** Is SPP-family binary interoperability required, or is behavioral project save/load sufficient? If binary compatibility is required, what additional hierarchy/schema/codec evidence must precede implementation?

## Verification record

**Fact:** This review was written as an English Markdown artifact. The final static checks verify the seven file verdicts, 20 numbered findings, 81 fact-validation rows, coverage of all 140 original matrix row IDs without duplication, 45 explicit HTML names, 15 architect questions, Markdown table widths, and unchanged SHA-256 hashes for D01–D07. Source declarations, test expectations, and static route analysis remain distinct from runtime validation.

**Fact:** The authorized review file is ROOT/docs/analysis/reviews/substance-parity-astra-review.md. No reviewed document, temporary script, task metadata, or changelog was written. The workspace did not expose a Git repository to the read-only status check; write-scope assurance uses the actual single output target and the reviewed-file hash comparison rather than a claimed Git diff.

| Fact: unchanged reviewed file | SHA-256 |
|---|---|
| D01 | 5CF0D28F7B486FDFEDE56846955E6E9BA0018A9E665835FDF256657AC05AC2E1 |
| D02 | 9C37047CA34AB552C07DC17DB5747A6D02F8A5EA198C121E6A73ECE0F493C422 |
| D03 | 534E34032ECB9819543B330685605E713FA4BC65E014E896F8BD611650A39AE3 |
| D04 | DE89BDBBD02BB148E8809862932350375B82D720E0ADF6798EBB028422529197 |
| D05 | 190E490E2F8EB2FF1EFB86EE96B1123EDEF295C4EB9FE67162DB9B6E35970E62 |
| D06 | 34FF51FB586A45807F934210EC01072ED05F2F0C657F17D68F49EF4D28F998BF |
| D07 | 4DA69B66982B48E357408052479706A47516EEB92F04B14713971C3D986FC87C |


