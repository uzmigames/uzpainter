## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery` (parent input), `phase3.1_uze-uztexture-writer` — recorded scope split, decision 344: phase3.1 is archived (decision 343); phase2.10 is NOT accepted, and its open items (Tunic fixture manifest, input inventory and preservation, MCP rebuild, dump-and-rebuild, Tier 1) are the Tunic's own inputs and parity, which this preset does not read

## 2. Implementation
- [x] 2.1 `.uzmat` writer: `TextureSample → PBROutput` pins 0..6 and the inline scene-material block — `src/export/uzmat_writer.{h,cpp}`, independent byte writer; publication/preset integration remains open below
- [x] 2.2 Preset `assets/export-presets/uzengine.json` with the seven outputs of the UzEngine preset table (`08-export.md` §4): the asset is authored, see section 7; this claims nothing about executing the full preset, which is refused on `AO_Mixed`
- [x] 2.3 Canonical 16-bit/float maps written beside every cooked derivative (EXP-10) — section 10: the full shipped preset publishes all six derivatives, the ORM's BC7 included, each beside its linked canonical PNG 16 (`test_canonical_maps_sit_beside_every_derivative`); the one derivative without a canonical file is decision 420's synthesized black emissive, stated in the receipt
- [x] 2.4 Normal output in the convention settled by `phase0.9_normal-convention-fixture`, tagged `geometry_only` or `combined` with the relief round — `Normal_DirectX` (phase0.9 §8: UzEngine reads green as -v); `test_normal_is_directx_with_its_relief_round`, section 8
- [x] 2.5 Opacity in albedo alpha; receipt reports the SM5 route as unsupported for opacity — `test_receipt_lists_formats_bindings_and_gaps`, `test_canonical_maps_equal_the_png_route`, section 8
- [x] 2.6 Receipt fields per file: engine format, colour space, bit depth, binding slot, normal tag, consumer gaps; manifest `exportacao` fields (INT-21): the receipt fields and schema are implemented, see section 7; they are exercised on authored sets, not on the full shipped preset
- [x] 2.7 SpecularWeight exported as `<set>_specularweight` and listed as a consumer gap with no engine slot — section 9: PNG16 canonical and BC4 derivative published on the observed template/format scope, with binding null; unobserved combinations remain refused
  - Authored evidence preparation (2026-10-23): `specularweight-empty-base-{default,alpha-blend}-{l8,l16,l32f}` requests cover six fresh plane256 projects under Legacy, with no inserted layers or assigned sources (Painter's initial empty Layer1 remains; decision 348), repeated EXR32F and PNG16 exports, and the recorder's save/reopen. An absent channel is a skipped preset map; these probes concern an existing empty channel and authorise no fallback for absent channels or unobserved template/format combinations. Factory/schema/recorder-job checks passed (12 tests); Painter recording, derived defaults and published-file acceptance remain pending.
- [x] 2.8 Provenance record `assets/export-presets/uzengine.provenance.json` with the `08-export.md` §4 fields
- [x] 2.9 Preset resolvable by name in `defaultExportPreset`; dry run lists every output with its resolved format — section 10: `test_full_preset_plans_every_output_in_ao_mixed_scope` (plan and list), and on wand v1 `list_project_textures` plus `uzpainter.export.plan` (the MCP `export` dry run returns the same `ListProjectTextures` and `PlanJson`)

## 3. Tests
- [x] 3.1 Plan test: the dry run on wand v1 lists exactly the table's files with formats, colour spaces and bindings — section 10: `tests/parity/tier1/test_uze_wand.py` (GPU, opt-in), 12 files listed and then published, emissive and SpecularWeight maps skipped as absent channels, the black emissive synthesized (decision 420)
- [x] 3.2 `.uzmat` test: pins 0..6 reference the matching `.uztexture` files and the inline block matches the file — `tests/export/test_uzmat_writer.py`, authored CPU fixtures, section 6
- [x] 3.3 Canonical-map test: canonical maps equal, in decoded values, the same channels exported through the proven PNG route on wand v1 — section 10: 0 of 4,194,304 texels differ for the canonical albedo, ORM and height against the same rebuild's glTF and script maps; the DirectX normal's R and B are equal and its green mirrored within one code
- [x] 3.4 Receipt test: SpecularWeight and SM5 opacity gaps present; every file has hash, size, format and binding — existing authored opacity receipt tests plus section 9's published SpecularWeight canonical/derivative receipt; full shipped-preset acceptance remains item 4.1
- [x] 3.5 Publication interruption test across the new file types: interrupting after each `.uztexture`/`.uzmat` write leaves the previous generation selected (EXP-06) — `test_interrupting_each_uztexture_and_uzmat_write_keeps_the_previous_generation`, section 8
- [x] 3.6 Provenance record validates against its schema on the local CPU lane (decision 200): `tests/export/test_uze_preset.py::test_provenance_validates_and_names_the_preset`

## 4. Acceptance
- [x] 4.1 Child acceptance met and reported to `phase3.4_uzengine-preset`: complete preset with explicit bindings, canonical maps, receipts and provenance — section 10; reported in the parent's item 2.2

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation — `src/export/EXPORT.md` §5, `docs/architecture/08-export.md` §4, decision 420, this task's export spec
- [x] 5.2 Write tests covering the new behavior — `tests/export/test_uze_preset.py`, `tests/parity/tier1/test_uze_wand.py`
- [x] 5.3 Run tests and confirm they pass — affected tests only, section 10; the full suite stays the coordinator's gate

## 6. Material writer evidence (2026-10-20)
- The writer follows approved `U-UZE-RUNTIME` commit `a703c95ada45002a774db9d9cf82b3b7964d09d6`. The seven pins are BaseColor, Metallic, Roughness, Normal, Emissive, Opacity and AO, fed by four texture samples. Height has no pin in that definition; the spec's earlier mention of height among pins 0..6 was corrected by source review and Claude/Codex consensus (SUP-091, ACK 95).
- The graph and inline block use one mounted delivery root, matching texture paths, explicit ORM and emissive multipliers of one. Normal remains encoded for the engine's downstream decode. Invalid UTF-8, traversal/device paths (including spaces before the extension), unsupported blend values and case-insensitive path matches across sRGB/linear slots are refused. Optional height and non-opaque SM5 opacity gaps are returned explicitly; no engine keys are invented.
- `zig build uzp-material-tests -j4`: Debug passed with warnings as errors, CPU only. `tests/export/test_uzmat_writer.py`: 40 passed, 0 skipped, 1.37 s; stable source/executable identities in `tmp/scratch/uzmat-audit/run2/{run.json,junit.xml}`. Executable SHA-256: `ef17469f6c7e7dd2a7d4ddafa78ac1e7718bdd580d38680d6b3b268058a29091`. Ruff check/format, mypy, source citation/revision audit and Zig formatting passed.
- Usage and limits: `src/export/EXPORT.md` section 5. These tests verify authored bytes and bindings, not real publication, Wand, Painter parity or engine rendering. The pinned shader reconstructs positive normal Z from XY even with an RGB texture; negative-Z render support and a height binding remain external consumer concerns. All other implementation, acceptance and prerequisite items remain open.

## 7. Preset and publication integration (2026-10-20, wt/uzpreset)
- **Assets (2.2, 2.8, 3.6).**
  - `assets/export-presets/uzengine.json` holds the six maps of the table, the three PNG 16 canonical companions `canonical/$textureSet_{albedo,orm,emissive}` of its PNG 8 maps, and a preset-level `uzengine` block with each texture's binding, BC4/BC5/BC7, sRGB flag, mip class and negative-Z policy, plus the `$textureSet.uzmat` material. The normal map is `Normal_DirectX`: phase0.9 §8 found green = -v for uzmesh OBJ at f4dcfc46, a descendant of a703c95 with no gbuffer, uzmesh, tangent, scene_loader or material change between them.
  - `uzengine.provenance.json` has the new layout `consumer` (`src/export/preset-provenance.schema.json`) and is pending R-131 (AO_Mixed, decision 131).
  - Evidence: `test_shipped_preset_loads_with_its_targets`, `test_provenance_validates_and_names_the_preset` and `tests/export/test_export_presets.py::test_provenance_records_are_complete`.
- **Code.**
  - `src/export/{config,preset_aliases,plan,write,publish,receipt,fault,uzmat_writer}` and `schema/receipt.schema.json`.
  - Plan-time refusals: the canonical file must be a PNG 16 at power-of-two sides; the layout must fit the format; the declared sRGB flag must match the encoder's flags, luma included; an engine output must not collide with any other output as Windows compares names, across stacks.
  - The receipt gained a generalised `uztexture` block (source = canonical, delivery, binding or null, format, srgb, mips, negative_z), a `uzmat` entry with its inline block, the Opacity (SM5), Height, SpecularWeight and authored-`blend` gaps, and the actual colour space plus each channel's `transfer`. Earlier every receipt said `linear`; only sRGB-encoded PNGs change (`test_receipt_colour_space_follows_the_written_encoding`).
- **Still open.**
  - The full shipped preset is refused before planning, because `<set>_orm` reads `AO_Mixed` (decision 131, `phase3.2_unreal-ue56-packed-preset` item 2.10). On wand v1 the island rule also refuses the normal (decision 245).
  - So the full dry run (2.9, 3.1), canonical maps beside *every* derivative, the ORM included (2.3), and the wand v1 comparison (3.3) are not evidenced.
  - 2.4, 2.5, 2.7, 3.4 and 3.5 are implemented, and their tests pass on authored sets: the shipped preset with its ORM maps filtered out, and a test-only variant whose ORM R reads `ambientOcclusion` (`.uzmat`, interruption after each `.uztexture` and `.uzmat` write). They stay unticked, because filtered or variant results are not shipped-preset acceptance (Codex review).
  - No template gives SpecularWeight a base, so its derivative's gap is checked through the receipt builder only, without evaluation.
  - The `.uzmat` blend rule (`Masked` when the albedo has alpha) is authored, not an engine fact, and is reported as a gap.
  - The height "sidecar" is read as the BC4 companion; no engine sidecar format exists in the approved source.

## 8. Offline closure pass (2026-10-21, wt/uzmat-preset)
- **Checked.**
  - 1.1: scope split, decision 344. phase2.10 is not accepted.
  - 2.4: the shipped normal is `Normal_DirectX`, the convention phase0.9 §8 settled (UzEngine reads green as -v). `test_normal_is_directx_with_its_relief_round` exports the same authored set's `Normal_OpenGL` through the PNG route. Red and blue are equal, green is mirrored within one code of rounding over a green that varies, and the PNG and its `.uztexture` carry the same `combined` tag with its relief round (revision, height hash, method).
  - 2.5: the albedo's A is the opacity, in the RGBA canonical map and the BC7 derivative. That canonical map equals the PNG route's same channels byte for byte (`test_canonical_maps_equal_the_png_route`). The albedo derivative's only gap is `Opacity`, and it names SM5 as unsupported. The manifest block's open items repeat it (`test_receipt_lists_formats_bindings_and_gaps`).
  - 3.5: `test_interrupting_each_uztexture_and_uzmat_write_keeps_the_previous_generation` kills the export after each of the five `.uztexture` writes and after the `.uzmat` write. After each kill, the previous generation stays selected and reads whole. The run uses the test-only variant whose ORM R reads `ambientOcclusion`. That variant writes the same file types through the same publication code; it is not shipped-preset acceptance (4.1).
  - Scope of 2.4, 2.5 and 3.5: they rest on the shipped preset with its ORM maps filtered out (`outputMaps`), or on that variant. They claim no shipped-preset acceptance, no wand v1 result and no Painter parity, since the UzEngine outputs are UzPainter's own formats.
- **Still open, each with its blocker.**
  - 2.3, 2.9, 3.1 and 4.1: every plan that writes `$textureSet_orm` is refused on `AO_Mixed` before anything is listed (decision 131, `phase3.2_unreal-ue56-packed-preset` item 2.10, R-131). So no dry run lists every output, and no canonical ORM sits beside a shipped-preset BC7 derivative.
  - 2.7 and 3.4: the plan lists `<set>_specularweight` (PNG 16, its own canonical, BC4, binding null), and the receipt builder lists its `SpecularWeight` gap (`test_specularweight_is_a_consumer_gap`). But no generation can write the file: no template or channel default records a SpecularWeight base value, so evaluation fails with `missing_base_value` (decision 097). That needs a Painter recording. So the published receipt has the SM5 gap and every file's hash, size, format and binding, but no SpecularWeight file.
  - 3.1 and 3.3 on wand v1: besides `AO_Mixed`, wand v1's normal is refused by the island rule under every padding (decision 245), and its `infinite` padding on islands is refused (decision 259). Building wand v1 also needs the app run of the Assets3D pipeline scripts, a GPU-lane job. The canonical-map comparison stands on the authored set only.
  - 5.1 to 5.3: `src/export/EXPORT.md` §5 (UzEngine preset) and `tests/export/test_uze_preset.py` cover what is implemented. The tail stays open until the blocked items land their own tests and docs.
- **Run.** `python -m pytest tests/export/test_uze_preset.py -k "<the five cases above and test_uzmat_binds_the_generation_derivatives>"`: 5 passed, exit 0, 82 s, CPU only. Logs: `tmp/scratch/uzmat-preset/{pytest.log,junit.xml}`. `uzp-export-tests` was built with `-j2` (`tmp/scratch/uzmat-preset/build.log`). Ruff check, ruff format and mypy on the test file are clean (`tmp/scratch/uzmat-preset/lint.log`).

## 9. Recorded SpecularWeight base and publication (2026-10-23)

- Six `specularweight-empty-base-{default,alpha-blend}-{l8,l16,l32f}` goldens are admitted in the current Painter 12.2.0 envelope. All 48 exported maps are stable across repeated exports and save/reopen: EXR32F stores 1.0 and PNG16 stores 65535 throughout. This supersedes the missing-base blocker of section 8 within those six combinations.
- `channel-defaults.json` gives each observed format its own evidence and restricts it to the two recorded project templates through `project_templates`. Library loading rejects empty, duplicate, malformed and unknown template scopes. No channel is inserted by this default; absent maps stay skipped and unobserved combinations retain `missing_base_value`.
- `test_specularweight_base.py` verifies exports in separate processes, all 48 native-depth oracle comparisons, refusal boundaries and actual publication of the shipped SpecularWeight output. Its PNG16 is canonical; its BC4 derivative has no material binding. Both receipt entries retain the consumer gap, and every published file's byte count and hash are checked against the generation.
- Validation: 23 tests passed on a fresh export build, with Ruff and mypy clean. Independent review found no scope or cache regression. Evidence: `scripts/tmp/commits/specularweight-base-final.xml`.
- Items 2.7 and 3.4 close on this bounded implementation. AO_Mixed still blocks 2.3, 2.9, 3.1 and full-preset acceptance; Wand normal/padding still blocks 3.3. No parent acceptance or archive follows from this result alone.

## 10. Closure (2026-11-09): items 2.3, 2.9, 3.1, 3.3 and 4.1 hold

- **AO_Mixed unblocked.** Decisions 411, 418 and 419 compute AO_Mixed in a scope that covers the pilots: OCIO with Painter's substance config, no AO channel and a 16-bit grey AO mesh map. Legacy colour management with an L16 AO channel and a bound mesh map is in that scope too. So the full shipped preset plans. Outside the scope it is still refused before anything is planned, naming the AO mesh map and decision 411. The provenance record keeps that remainder as its only pending item (R-131).
- **Decision 420 (coordinator-approved, after decision 380 §6).** The pilots have no Emissive channel, so `<set>_emissive` was skipped and with it the `.uzmat`.
  - Now a stack whose emissive map is skipped as absent binds the black emissive derivative `cook-uzengine` cooks without `--emissive`: the preset's emissive target from (0, 0, 0), alpha 1, at the albedo canonical's size.
  - No canonical or delivered PNG is written for it.
  - The receipt marks it `synthesized`, with `source` and `delivery` null, and lists it as an open item. The receipt schema admits null only together with `synthesized`.
  - The dry run lists it right before the `.uzmat`, and publication writes it right before the `.uzmat` (fault point `kill_after_synthesized`).
  - An emissive map filtered out of a stack that has the channel is not synthesized.
  - Code: `src/export/{plan,write,publish,receipt,fault}`, `schema/receipt.schema.json` (4cbf9ae7).
- **CPU evidence** (`tests/export/test_uze_preset.py`, shipped preset, no variant).
  - Full dry run: all 16 paths in plan order, each derivative's format, sRGB flag, binding and canonical, the `.uzmat` binding the four derivatives and the height. Refused without the AO mesh map.
  - Synthesized-emissive plan; a filtered emissive is not synthesized.
  - Full publication on an in-scope authored set: default template, L16 AO channel with a 16-bit grey bitmap fill, the ramp as AO mesh map, an L16 SpecularWeight channel, no Opacity channel (no default-template base of it is recorded).
  - All 16 files are published, each of the six derivatives beside its linked PNG 16 canonical map. The ORM canonical holds AO_Mixed, roughness and metallic, its PNG 8 within one code.
  - The `.uzmat` (Opaque) binds the generation's derivatives.
  - Interruption after each of the six `.uztexture` writes and after the `.uzmat` keeps the previous generation.
  - On a set without Emissive, the synthesized `.uztexture` and the `.uzmat` are byte-identical to `cook-uzengine` on the same generation's canonical maps, and interruption after the synthesized write keeps the previous generation.
  - The opacity-in-alpha (Masked) path stays covered by the filtered-preset tests and `test_uze_png_cook.py`.
- **Wand v1** (`tests/parity/tier1/test_uze_wand.py`, opt-in `UZP_TIER1_PRODUCTION=1`, one production rebuild of the `phase3/tier1/wand-v1-gltf` job on DX12 with the ReleaseFast `UzPainter.exe`; 1 passed, 99 s).
  - The dry run (`list_project_textures` and `uzpainter.export.plan`) lists exactly 12 files: albedo PNG/derivative/canonical (RGB: no Opacity channel), normal PNG/derivative, ORM PNG/derivative/canonical, height PNG/derivative, the synthesized emissive derivative and `11-Varinha-Madeira.uzmat`. The emissive, canonical emissive and SpecularWeight maps are skipped as absent.
  - The export publishes exactly those files, with each derivative's format, colour space, binding and canonical source. The `.uzmat` (Opaque) binds the four derivatives and the height. Exceptions relied on: EXC-013 and EXC-014 only, EXC-014 on normal files only.
  - Item 3.3, against the same rebuild's proven PNG route (the glTF closing export and the script's maps, equal to Painter under EXC-013/014 per `phase3.1_unreal-gltf-pbr-preset`): canonical albedo = glTF baseColor, canonical ORM = glTF occlusionRoughnessMetallic (G and B also = the script's Roughness and Metallic), height = the script's Height, each 0 of 4,194,304 texels differing. The DirectX normal's R and B equal the glTF normal's, and its green mirror sum lies in [-1, 0].
- **Tests run** (affected only, once each; reruns by node id after fixes).
  - `tests/export/test_uze_preset.py`, `test_uze_png_cook.py` and `test_export_publication.py`: 83 passed. The five full-publication cases first errored because AO_Mixed is computed on the default template only (the spec used Alpha-blend). After the fix, 4 passed and one assertion about PNG 8 rounding was wrong; after its fix it passed.
  - `test_export_presets.py::test_provenance_records_are_complete` fails on `unreal-engine-packed`'s record, which names `test_unreal_presets_load_unconfirmed`. That test is gone from the other session's uncommitted `test_unreal_preset.py` (`phase3.2_unreal-ue56-packed-preset`). The `uzengine` record was checked by hand: schema-valid, packing in map order, every named test exists.
  - GPU: `test_uze_wand.py`. Ruff and mypy are clean on both test files.
- **Not claimed.**
  - Whether UzEngine loads and renders these files, the black emissive included, stays with `phase3.3_uze-consumer-fixture`.
  - The Sash and Tunic end-to-end runs, the gap report and EXP-05 byte identity stay with the parent (`phase3.4_uzengine-preset` items 3.1, 3.2 and 4.2).
  - The Opacity (Masked) route is not exercised on a full in-scope set, because no default-template Opacity base is recorded.
