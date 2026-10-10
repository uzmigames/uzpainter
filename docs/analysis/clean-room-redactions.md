# Clean-room redactions of `docs/analysis/` (2026-10-10)

Record of the sanitisation pass that applied the clean-room policy (`docs/licensing-and-clean-room.md`, owner decision 002) to the analyses written before that decision. Every disallowed passage was replaced in place by a note of the form `[Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: <file path>.]`; allowed facts that were mixed into a passage were kept, rewritten where needed. No file was deleted or renamed. Reviews and discussion records written by others were only redacted; their arguments and verdicts are unchanged.

Scope: every file under `docs/analysis/` except `architecture-discussion/05-resolution.md`. Files with no redaction: all of `assets3d-pipeline/`, `technology-options/`, `uzengine-renderer/`, `reviews/assets3d-pipeline-astra-review.md`, `reviews/technology-options-astra-review.md`, `reviews/uzengine-renderer-astra-review.md`, `architecture-discussion/04-astra-critique.md`. No code fence in the scanned files contained Adobe GLSL or Python.

Categories: **1** = verbatim or near-verbatim Adobe code (shader library, shipped Python modules, Adobe test modules) beyond public signatures; **2** = description of the internals of those implementation files (algorithms, constants, sampling, formulas, code structure, private names, test logic); **3** = content of Adobe data files (`.spp`, `.spt`, `.spsm`, `.spexp` internals, byte offsets, stored values).

## Summary

| File | Notes |
|---|---:|
| `architecture-discussion/01-claude-proposal.md` | 9 |
| `architecture-discussion/02-astra-position.md` | 1 |
| `architecture-discussion/03-claude-reconciliation.md` | 1 |
| `substance-parity/01-python-api-inventory.md` | 12 |
| `substance-parity/02-layer-stack-model.md` | 10 |
| `substance-parity/03-baking.md` | 11 |
| `substance-parity/04-export.md` | 17 |
| `substance-parity/05-project-and-spp.md` | 4 |
| `substance-parity/06-mcp-tools-inventory.md` | 2 |
| `substance-parity/07-parity-matrix.md` | 2 |
| `substance-parity/08-review-response.md` | 7 |
| `reviews/substance-parity-astra-review.md` | 26 |
| **Total** | **102** |

## Redactions

Line numbers are those of the sanitised files.

| # | File | Section (line) | Cat. | What was removed (general terms) | Allowed facts preserved |
|---|---|---|---|---|---|
| 1 | 01-claude-proposal | D3 compositing, normal channel (147) | 2 | Pointer to, and function name of, the shader library's normal-blend formula | Normal-map blend modes = whiteout / reoriented normal mapping / swapped operands (public `BlendingMode` documentation) |
| 2 | 01-claude-proposal | D3 compositing (148) | 2 | Height-to-normal function name, method selector and the two filter schemes | Height is converted to normal detail for export and preview (observable) |
| 3 | 01-claude-proposal | D3 "Where reference formulas come from" (151) | 2 | Exact colour-transfer constants attributed to the shader library | The argument listing reference sources, unchanged |
| 4 | 01-claude-proposal | same paragraph (151) | 3 | Serialization type names read from an Adobe sample project | The argument that project-file names served only as naming cross-checks |
| 5 | 01-claude-proposal | D5 baker parameters, defaults (199) | 3 | Parameter values stored in an Adobe sample project | They are specimen values, not 12.1 defaults; parameter key names kept (see borderline 5) |
| 6 | 01-claude-proposal | D6 position (223) | 2 | Description of the environment-lighting implementation and internal uniform names | Shader source file names; exposure and rotation follow Painter's display settings |
| 7 | 01-claude-proposal | D6 risks (234) | 2 | Viewport sampling scheme | Sparse virtual texturing, possible temporal accumulation, the argument that pixel-exact equality is not achievable |
| 8 | 01-claude-proposal | §3 table, pixel-exact viewport (436) | 2 | Same sampling scheme | Same as 7 |
| 9 | 01-claude-proposal | D8 compactness (294) | 3 | Internal member names of the project container | Adobe's public explanation: the project stores decoded resources, the processed mesh, baked maps and a texture cache |
| 10 | 02-astra-position | D6 position (256) | 2 | What the two shader source files import, reference and expose | Both files exist; their SHA-256 values |
| 11 | 03-claude-reconciliation | D6 (c) arguments (94) | 2 | Contents of three shader-library files and internal engine-side input names | Library ships as `lib-*.html` (~346 K characters, 57 files); the inputs must be rebuilt from the HDRI; Astra's argument and the two legal routes unchanged |
| 12 | 01-python-api-inventory | Conventions, method (9) | 2 | Name of a private helper that exposes native enums | Enum members come from the docstrings and match the HTML |
| 13 | 01-python-api-inventory | §3 row 8 (66) | 1, 2 | Names and signatures of private functions used only by Adobe's test suites | Private `_substance_painter` functions exist and are unsupported; `save_viewport` is known from the Assets3D pipeline |
| 14 | 01-python-api-inventory | §3 row 9 (67) | 1 | Private call in a function body | Public `List[...]` annotation versus a single returned node |
| 15 | 01-python-api-inventory | §4 kind values (72) | 2 | Private helper name | `enum (native)` = C++ enum exposed by the native module |
| 16 | 01-python-api-inventory | `CylindricalProjectionParams` (394; also 11) | 1 | Verbatim private class-attribute declaration with an internal name mapping | It is private metadata, not a field or constructor parameter |
| 17 | 01-python-api-inventory | `logging` constants (442) | 1 | Six verbatim assignments to a private enum | Constant names; documented in prose in `logging.html` |
| 18 | 01-python-api-inventory | `project` save functions (479–481, 496) | 1 | Private module-constant name used as the default | Default is `ProjectSaveMode.Incremental` (HTML signatures) |
| 19 | 01-python-api-inventory | `StandardQuery` (548) | 1 | Literal values of the class constants | Field names |
| 20 | 01-python-api-inventory | `SourceFontParams`, `SourceVectorialParams` (620, 625, 667) | 2 | Private base-class name | Deprecated attributes come from a private base |
| 21 | 01-python-api-inventory | `UVTile`, `TextureSet` bases (687, 709) | 2 | Private base-class names | Bases are private |
| 22 | 01-python-api-inventory | `UVTile.u`, `.v`, `__init__` (688–690) | 2 | Private base names, source line ranges, generated-constructor description | Public fields; HTML constructor signature |
| 23 | 01-python-api-inventory | `TextureSet.material_id`, `__init__` (710–711) | 1, 2 | Private names and a wrapper code excerpt | Public integer field; HTML constructor signature |
| 24 | 02-layer-stack-model | §2.1 layer colour tag (59) | 3 | Serialized field and type names from an Adobe test project | Not exposed through Python |
| 25 | 02-layer-stack-model | §5 serialization (103) | 3 | Blending type and field names from the project serialization | — |
| 26 | 02-layer-stack-model | §7.2 intro (157) | 2 | Private dispatch method names | Value type → source class mapping (public pages) |
| 27 | 02-layer-stack-model | §7.3 resolution (180) | 1, 2 | Enum aliasing read from source lines | Members, deprecations, resolution bounds; run-time check proposed |
| 28 | 02-layer-stack-model | §7.4 `NormalColorSpace` (189) | 2 | Expectations of an Adobe test | `NormalXYZRight` = OpenGL, `NormalXYZLeft` = Direct3D (public `colormanagement.html`) |
| 29 | 02-layer-stack-model | §11 file format (237) | 3 | Internal entry list of a shipped smart material | HDF5 signature of `.spsm`/`.spmsk`/`.spt`/`.spp` |
| 30 | 02-layer-stack-model | §12 locations (246) | 1 | Context-matching expression from the implementation | `ResourceLocation` members and their public descriptions |
| 31 | 02-layer-stack-model | §12 contexts (247) | 3 | Resource URL strings found in an Adobe test project | `starter_assets` and project contexts (public examples) |
| 32 | 02-layer-stack-model | §12 search (251) | 1 | Literal `StandardQuery` values | Public query examples; `StandardQuery` named |
| 33 | 02-layer-stack-model | §14 (274) | 3 | Internal project type names and their hypothesised mapping | The project stores the stack in its own serialization |
| 34 | 03-baking | §1 table and "Sources and labels" (17–29) | 3 | Ten internal baker identifiers | `MeshMapUsage`, export/effect identifiers, UI parameters |
| 35 | 03-baking | §1 rows Height/BentNormals/Opacity and export identifiers (24–26, 30) | 1 | A name-mapping table from an Adobe test module | Output file names of the shipped `Mesh Maps` preset |
| 36 | 03-baking | §2 common/per-baker parameters (40–41) | 1, 2 | Names of native functions the wrapper calls | `common()`/`baker()` return short-name dictionaries; high-poly keys are in `common()` (public example) |
| 37 | 03-baking | §3 intro (51) | 3 | Serializer marker, byte offset and group ordering | Grouping is a Hypothesis; specimen-versus-default distinction |
| 38 | 03-baking | §3.1 `HipolyMesh` (61) | 1 | Test variable detail | Pipe-joined `file:///` URLs (community bridge); QUrl example (public) |
| 39 | 03-baking | §3.1 `CageMode` (62) | 1 | Enum integer used by an Adobe test | Three cage modes (release notes, bridge) |
| 40 | 03-baking | §3.2 last row (90) | 3 | Stored parameter count in an Adobe test project | The caveat |
| 41 | 03-baking | §4 choose sources (104) | 1 | Private helper name in a test scenario | Pipe-joined URLs; meaning of `LowAsHigh` (public) |
| 42 | 03-baking | §4 high-poly file types (111) | 1 | Private call used by tests | Not documented; the bridge's accepted list |
| 43 | 03-baking | §5 UI mode (126) | 2 | How Adobe's tests bake | `UIMode.Baking` exists; "not required" stays Hypothesis |
| 44 | 03-baking | §6 project-level blending (143) | 3 | Material field names from the project serialization | No public Python accessor |
| 45 | 04-export | §2 `srcMapName` meshMap (37) | 1 | Map names from an Adobe test | `Mesh Maps` outputs bent normals, height and opacity |
| 46 | 04-export | §2 undocumented keys and stored values (44; four rows merged) | 1, 3 | Undocumented configuration keys known from tests and stored project/template data, their stored values and a template's preset URL | A project from the `Unreal Engine` template is expected to default to `Unreal Engine (Packed)` (Hypothesis) |
| 47 | 04-export | §3 format table and test remarks (58, 60; §11 dithering label) | 1 | Format / bit-depth / dithering cases transcribed from an Adobe test module | `bitDepth` must suit `fileFormat`; float depths named `16f`/`32f`; EXR changelog fix; bridge limits |
| 48 | 04-export | §4.2 document-channels preset (73) | 1, 3 | Project-stored default and test usage | Generator URL; pairing Hypothesis |
| 49 | 04-export | §7.1 (120; §11 bit-depth row) | 3 | Decoded binary schema, field layout, reader description and code tables of the preset format | `.spexp` file signature; layouts in §7.2–7.6 stated as behaviour, Hypothesis |
| 50 | 04-export | §7 label paragraph (124) | 3 | Raw decoded tuples and identifiers | Labels are Hypothesis; limits of boundary agreement |
| 51 | 04-export | §7.2 normal and height notes (133–134) | 3 | Raw bit-depth flag values | Bit depth may differ (to confirm) |
| 52 | 04-export | §7.3 SSS sentence (146) | 3 | Raw channel identifier | BaseColor alpha carries scattering (Adobe's public description) |
| 53 | 04-export | §7.6 table (182) | 3 | Raw bit-depth column | Output files and their composition |
| 54 | 04-export | §7.6 paragraph (184) | 1, 2 | Export parameters and grayscale-rewrite logic of an Adobe test | Grayscale-versus-RGB form matters and is not confirmed |
| 55 | 04-export | §8 (191) | 3 | Exporter values stored in an Adobe sample project | New-project defaults not confirmed |
| 56 | 04-export | §9 combined export (201) | 1 | Undocumented USD key and test behaviour | glTF route through the predefined preset |
| 57 | 04-export | §10 single-node export (207) | 1 | Private function name and signature | No public equivalent |
| 58 | 04-export | §10 dependency-list export (208) | 1 | Private function name and test status | No public equivalent |
| 59 | 04-export | §11 export defaults (220) | 3 | Method of reading a project-internal exporter entry | Check through the export window or an export without overrides |
| 60 | 04-export | §11 undocumented keys (225) | 1 | Key names from tests | — |
| 61 | 04-export | Appendix (230) | 3 | Decoded composition of all 34 shelf presets, including raw format, bit-depth and dither fields | Blender (Principled BSDF) layout stated as behaviour (used by Assets3D); other layouts via `list_output_maps()` |
| 62 | 05-project-and-spp | §1 glTF row (18) | 2 | Adobe test fixture and expected results | glTF accepted; `GltfSettings.invert_normal_maps` (public) |
| 63 | 05-project-and-spp | §3 save row (82) | 1 | Verbatim private default-constant line | Default `Incremental` (public) |
| 64 | 05-project-and-spp | §6 rows 4–14, merged (114) | 3 | Internal entry names, embedded-format markers, stored paths, serialized settings and type names, hash identifiers and the hypotheses built on them | Public row 3; mesh path through `last_imported_mesh_path()` |
| 65 | 05-project-and-spp | §6 row 16 (116) | 2 | Content of an Adobe test resource and the test's expectations | The test resource exists |
| 66 | 06-mcp-tools-inventory | §8 bridge gaps (182) | 1 | Undocumented USD key name | The bridge does not offer USD export |
| 67 | 06-mcp-tools-inventory | §9 Paint active channels (195) | 2 | Behaviour of a private helper in Adobe's wrapper | The bridge's write creates a plain Python attribute and its readback reads it back |
| 68 | 07-parity-matrix | M12 (205) | 1 | Undocumented key name | USD export: undocumented, No |
| 69 | 07-parity-matrix | M16 (209) | 1 | Private function name | Private API, N/A |
| 70 | 08-review-response | F01 evidence (28) | 2 | Private helper behaviour | Remaining evidence |
| 71 | 08-review-response | F04 evidence (31) | 2 | Exit behaviour read from the implementation | `ScopedModification` groups calls (public) |
| 72 | 08-review-response | F05 evidence (32) | 3 | Serializer marker, byte offsets, group names | HDF5 signature spot-check |
| 73 | 08-review-response | F06 evidence (33) | 1 | Adobe test's grayscale rewrite | — |
| 74 | 08-review-response | F06 changes (33) | 3 | Raw decoded preset tuples and identifiers | List of changed sections |
| 75 | 08-review-response | §5 Q4 (127) | 1 | Private function name | A fresh lookup returns a new wrapper |
| 76 | 08-review-response | §5 Q6 (129) | 2 | Exit behaviour read from the implementation | Public description of `ScopedModification`; no public undo; atomic commit not provided |
| 77 | substance-parity-astra-review | F01 (126) | 2 | Private helper behaviour | Finding and recommendation |
| 78 | substance-parity-astra-review | F05 (150) | 3 | Block offset, marker and stored values | Specimen values are not defaults |
| 79 | substance-parity-astra-review | F14 (204) | 1 | Dithering cases from an Adobe test | Test definitions are not a run |
| 80 | substance-parity-astra-review | F18 (228) | 3 | Embedded mesh-format marker | Specimen contains internal strings |
| 81 | substance-parity-astra-review | inventory corrections, cylindrical row (256) | 1 | Private attribute name and type | The finding (private metadata mislabelled) |
| 82 | substance-parity-astra-review | `get_node_by_uid` paragraph (265) | 1 | Body line and private function name | A single node is returned |
| 83 | substance-parity-astra-review | signature-difference paragraph (267) | 1 | Private constant name | The default difference itself |
| 84 | substance-parity-astra-review | documentation-defaults paragraph (269) | 2 | Private documentation helper and how it alters defaults | Recommendation |
| 85 | substance-parity-astra-review | V24 (302) | 1 | Enum integer from an Adobe test | Pipe-separated URLs, `CageMesh` |
| 86 | substance-parity-astra-review | V25 (303) | 3 | Byte offsets and record format | Specimen values, not defaults |
| 87 | substance-parity-astra-review | V26 (304) | 3 | Byte offsets | Verdict |
| 88 | substance-parity-astra-review | V27 (305) | 3 | Byte offsets and stored counts | Verdict |
| 89 | substance-parity-astra-review | V28 (306) | 3 | Specimen value | Examples are not defaults; public JS example value |
| 90 | substance-parity-astra-review | V36 (314) | 1 | Dithering cases from an Adobe test | Recommendation |
| 91 | substance-parity-astra-review | V40 (318) | 3 | Byte ranges, raw tuples, dither byte | ORM packing and dithered DirectX normal as decoded values |
| 92 | substance-parity-astra-review | V41 (319) | 3 | Record offset and raw identifiers | SSS alpha source differs |
| 93 | substance-parity-astra-review | V42 (320) | 1 | Test export parameters and grayscale rewrite | Grayscale-versus-RGB form matters |
| 94 | substance-parity-astra-review | V43 (321) | 2 | Test fixture expectations | Tests were not run |
| 95 | substance-parity-astra-review | V51 (329) | 3 | Entry names, mesh-dump markers and offsets | Strings confirmed; layout unverified |
| 96 | substance-parity-astra-review | V52 (330) | 3 | Field names with offsets | Strings are not schema or API guarantees |
| 97 | substance-parity-astra-review | R03 (368) | 2 | Test resource content and expectations | Recommendation |
| 98 | substance-parity-astra-review | R05 (370) | 3 | Serializer description | Recommendation |
| 99 | substance-parity-astra-review | R06 (371) | 3 | Pointer to the format description | Counts of matched boundaries |
| 100 | substance-parity-astra-review | U03 (375) | 3 | Serialized type name | Hypothesis list |
| 101 | substance-parity-astra-review | stored-values table (379) | 3 | Record format and stored baker values by group, with offsets | — |
| 102 | substance-parity-astra-review | preset-decoding paragraph (381) | 3 | Binary encoding rules of the preset format | Hypothesis sentence |

## Borderline passages kept

| Passage | Where | Why kept |
|---|---|---|
| Adobe file names, counts, sizes, SHA-256 values, the presence of the "ADOBE CONFIDENTIAL" notice, the size of `shader-doc` | 01 §0/D6/Q2, 02 D6, 03 D6, 04-critique D6, 02 §11–12, 05 §6 rows 1–2 | Observable from outside; policy §1.5 allows stating that the off-limits files exist |
| Positions proposing to port the shader library, extract smart-material/mask recipes, capture procedural outputs or use the shader library as a formula reference | 01 D3/D4/D6/§3/Q2–Q3, 02 D6, 03 Q4, 04-critique | Arguments, not disclosures; superseded by decision 002; discussion records are redact-only |
| A shader-library file name used to support an ordered-dither hypothesis | 01 D7 | File name only |
| "Env-prefilter compute (SH projection, mip chain)" and the Route B references | 01 D6 rationale, 03 D6 | Standard published techniques, not sourced from Adobe files |
| Baking parameter identifiers (dotted ids, short keys, per-baker keys, suffix values) | 03 §2–§4, 01 D5 | The documented `Property.name()`/`common().keys()`/`baker().keys()` return them; the Assets3D reports (`SM/18-Tunica/report.json`, `SM/10-Chapeu/report.json`) record the common/detail set and the suffix values. Per-baker keys still need the Phase 0 capture |
| Signatures, enum members, type-alias unions, `:meta private:` markers and `P/<file>.py:<line>` pointers | 01 inventory, 06 §9, 08, review | Public API shape; the review found every signature equal to the HTML; line pointers carry no content. Policy item 4 still applies: the facade is written from the HTML |
| Predefined-preset generator URLs and glTF suffix strings found in the executable | 04 §4.2, §7.5 | Returned by `PredefinedExportPreset.url` and visible in exported glTF files |
| Output file-name patterns and §7.2–7.6 packing tables, including "dithering on" | 04 §5, §7 | Functional output layouts stated as behaviour, Hypothesis until `list_output_maps()` |
| Counts of decoded records and flags; the `.spexp` file signature | 04 §7.1, 08 V39, review F06/V38/R06 | Counts and a file-type signature, no content |
| `srcPath: ''` in export channels | 04 §2 | Present in the public `export.html` example |
| `16f`/`32f` attributed to an Adobe test | 04 §8, 06 §9 | The names are public (changelog 0.2.10) |
| `.assbin` cache files next to high-poly meshes; bake values and smart-material colours | assets3d-pipeline 01, 03, 04 | Observed by the Assets3D pipeline on disk or through the API; no recipe dump |
| Base-class name `ReadOnlyUid`; "frozen dataclass", no `get`/`__getattr__` remarks | 06 §9, 08 F09, review F09/R01 | API-shape statements visible at run time |
| `shelf.ini` contents | 02 §12 | The user's own configuration file, not Adobe-shipped data |
| `_substance_painter.display.save_viewport` | 01, 07 N6, inventory | Used by the Assets3D pipeline |
| Statement that Adobe's test suites exist and were used as sources | 01 inventory §3 row 10, 08 method | Existence only; derived content redacted |
