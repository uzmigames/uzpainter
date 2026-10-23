## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery` (parent input); for the DDS items also `phase3.1_uze-uztexture-writer`

## 2. Implementation
- [ ] 2.1 Record the private observed outputs: Painter's files for `Unreal Engine (Packed)` on a UzmiGames fixture project and the documented `list_output_maps()` result, stored in the private oracle store with hashes in `parity/manifests/`
- [x] 2.2 Author `assets/export-presets/unreal-engine-packed.json` by hand from documented semantics (BaseColor+opacity, ORM linear, `Normal_DirectX`, Emissive)
- [ ] 2.3 Provenance record `assets/export-presets/unreal-engine-packed.provenance.json` with public sources, observed-output hashes, packing decisions and parity status
- [x] 2.4 Compatibility alias so `defaultExportPreset: "Unreal Engine (Packed)"` resolves to the shipped preset (CLR-06)
- [ ] 2.5 TGA 8-bit output path through stb for the default encoding
- [ ] 2.6 DDS header writer and the DDS variant: BC7 for BaseColor, ORM and Emissive, BC5 for Normal, through the BC encoder adapter
- [ ] 2.7 `_SpecularWeight` written as a separate map when the channel exists and listed as a consumer gap in the receipt
- [ ] 2.8 UE 5.6 import fixture manifest `parity/manifests/consumers/unreal/wand-v1.json` and runner, run locally on the owner's machine (decision 028), consuming through the delivery adapter or publication lock

- [ ] 2.9 (decision 103, from phase1.18_export-engine item 6.1) Fit and implement exactly, against the admitted recordings `export-dither`, `export-resize` and `export-padding*` (R-090 P3, P4, P5): dithering at PNG 8 (deterministic, not a threshold matrix) and in OpenEXR; resize (partial fit: upscale is the evaluation at the target size, downscale a 2x2 box stored in the channel format; sRGB8, virtual normals after downscale and BilinearHQ normal magnification open); the `color`, `transparent` and `diffusion` paddings with `dilationDistance`. Until then each is refused before writing
- [ ] 2.10 (decision 131, from phase1.15_export-plan-compiler items 3.6, 4.1) Fit and implement the `AO_Mixed` virtual map (the ORM's R) exactly in the plan (`src/export/virtual_maps.cpp`) against recordings R-086a (`ao-mixed`, `ao-mixed-opacity` and its OpenEXR 32f twin) and the R-092 isolation goldens (`ao-mixed-isolation`, `-float`, `-8bit`), every texel of r1 at PNG 8, PNG 16 and OpenEXR 32f; the best model of decision 092 misses r1 at 31 values. If the isolation goldens do not identify the operator, record R-131 (decision 131 §2: the 256x256 grid of mesh-map and channel codes at the missed opacities and at opacity 1). Until then the plan refuses AO_Mixed before writing (also `phase3.2_uze-uzmat-preset`'s `<set>_orm`)
  - Follow-up control (2026-10-23, authored only): `ao-mixed-mesh-float-product` compares PNG16/EXR mesh paths and an authored float32 product supplied through the mesh. Exact exported-operand preconditions and conditional predictions are frozen in `parity/reports/phase1/ao-mesh-product-control.md`. All 58 CPU controls/catalog tests pass, with Ruff/mypy green; capture and operator acceptance remain pending.

## 3. Tests
- [ ] 3.1 Output parity on wand v1, belt v5 and tunic v10: every preset file equals Painter's export of the same preset in decoded values
- [ ] 3.2 Consumer-matrix row 8 on wand v1, PNG/TGA variant: BaseColor sRGB, ORM linear, Normal as DirectX normal map, Emissive sRGB
- [ ] 3.3 Consumer-matrix row 8 on wand v1, DDS BC7/BC5 variant: same bindings; whether UE re-encodes on cook is recorded
- [ ] 3.4 Defect detection: an ORM map with swapped G/B channels fails the packing check
- [ ] 3.5 Fixed-name interruption test: interrupting each fixed-name copy and immediately running the UE import through its adapter yields one complete generation or fails before consumption (EXP-06)
- [x] 3.6 Provenance record validates against its schema on the local CPU lane (decision 200)

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase3.3_unreal-gltf-presets`: UE 5.6 fixture loads both variants; ORM packing confirmed; SpecularWeight gap reported

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. DDS leaf evidence (2026-10-20)

Item 2.6's CPU writer/cook is implemented in `src/export/dds.{h,cpp}` and
`src/export/cook_dds.{h,cpp}`; contract and public-source provenance:
`docs/DDS.md`, approved source `S-DDS-MS`. It writes DX10 BC5/BC7/BC7-sRGB,
validates headers/mips/limits, reuses the existing mip/BC policies, and refuses
negative-Z BC5 normals before compression. Canonical inputs retain their supplied
green convention. No Painter/default/backend claim follows from these tests.

`tests/export/test_dds_writer.py`: 56 CPU cases pass in Debug, ReleaseSafe,
ReleaseFast and ReleaseSmall. Pillow 12.2.0 independently opens all generated
formats and every mip. Coverage includes channel/block orientation, alpha,
exact encoder-boundary samples, malformed inputs, colour transfer, normal
filtering, negative Z, and byte-identical 1/4/max-thread output. Debug also passes
all 11 existing `test_uze_texture.py` regressions. The fixed BC7 encoder's mode-6
endpoint quantization is kept distinct from exact canonical samples.

Local evidence: `tmp/scratch/dds/evidence.json` indexes four run records/JUnits,
source hashes and executable hashes; each run verifies unchanged identities.
Ruff, mypy, source audit and Rulebook validation pass. Item 2.6 remains open:
the optional preset variant and its observation/provenance prerequisites are
not delivered by a library alone. UE import/cook acceptance remains in 3.3.

## 7. Native DDS export integration (2026-10-20)

`RequestDds` explicitly attaches a DDS to its own planned PNG16 canonical.
Plan hashes, dry-run lists, in-memory cooking, direct writing, generational
publication, receipts and fixed-name delivery carry it end to end. It refuses
incompatible colour/mip classes, non-PNG16 input, non-DirectX normal mapping,
negative-Z BC5 and Windows path conflicts before publishing. Conflict checks
include an output used as another output's parent directory; failed requests
retain their prior plan/hash. The DDS receipt names canonical source, stored
channels, BC format, encoder/settings, mip count and lossy status separately
from the canonical file's hash and values.

`tests/export/test_dds_publication.py`: all 16 cases pass in Debug, ReleaseSafe,
ReleaseFast and ReleaseSmall. Real files are independently decoded by Pillow;
canonical bytes and every delivered hash match. Interruption at `kill_after_dds`
and negative-Z refusal keep the previous generation selected. The suite also
checks plan/list/write ordering, semantic refusals, case-insensitive path
conflicts in both ancestor directions and non-conflicting textual prefixes.

Debug regression run `debug-2` produced 83 passes and one test-only Windows
separator comparison failure; correcting that assertion to compare `Path`
values produced 16/16 DDS passes in `debug-3`. Native sources, remaining tests
and executable identity are identical across those runs. This is coverage
across two runs, not one claimed 84-pass run. Final four-mode records each
verify stable source and executable identities; index:
`tmp/scratch/dds-integration/evidence.json`. Ruff, mypy and diff checks pass.
The pinned Assets3D schema comparison also passes with Git trust scoped to the
test process, without changing the external checkout or global Git config.

Item 2.6 remains open for the shipped DDS preset variant: no admitted
`Unreal Engine (Packed)` observation/provenance was found for items 2.1-2.3.
The native opt-in does not impersonate Painter JSON or establish UE 5.6
import/cook acceptance, and no task acceptance is claimed here.

## 8. AO_Mixed recording request (authorship only, 2026-10-20)

Decision 321 supplies the missing R-131 request `ao-mixed-grid` for item 2.10.
It reuses the 65,536 operand pairs already covered by R-086a, now with explicit
Nearest/identity UV controls, one BilinearHQ comparison, and PNG 8/OpenEXR 32f
plus immediate repeats from the same project. Four full-UV sets cover opacities
0.5, 0.75 and 1; AO channel and mesh-map exports accompany AO_Mixed.

The request uses the existing fixtures and recorder vocabulary. It remains
under the envelope's `requests/` with no private records. Recording, admission,
the exact operator fit and consumer parity remain open; the production refusal
and item 2.10's checkbox are unchanged. Recording instructions: `parity/RECORDER.md`
section 11.2.

Validation: eight targeted tests pass (12.29 s), covering the operand/UV grid,
node state, format repeats, committed request versus generator/input hashes,
request schema/job parsing and the provenance guard. Ruff and mypy pass for
the three Python files. Evidence: `tmp/scratch/r131/junit.xml` and
`tmp/scratch/r131/evidence.json`. These are authorship checks, not a Painter
recording or output-parity verdict.

## 9. Preset, provenance and DDS variant, offline (2026-10-20, decision 322)

Delivered in 7f7db23e:
- `assets/export-presets/unreal-engine-packed.json`, written by hand from 08-export §4, decision 023 and the UE 5.6 texture documentation (X-CONSUMERS). It has five `$mesh_$textureSet_<map>` maps at PNG 8.
- `assets/export-presets/unreal-engine-packed-dds.json`, the same maps at PNG 16. Its shipped-only `dds` block names the targets: BC7_SRGB for BaseColor and Emissive, BC7 for ORM, BC5 for Normal. SpecularWeight has none.
- Both provenance records, with layout `unconfirmed` and pending R-322. Every packing entry is `hypothesis`, and `privateRecords` is empty.
- The alias `Unreal Engine (Packed)` and its `resource://starter_assets/` URL. An unrecorded `?version=` names R-322.
- `CompilePlan` attaches each DDS target through `RequestDds`.
- A `cook` consumer gap on every DDS receipt entry: BC pass-through through UE 5.6 cooking is undocumented, so item 3.3 records it.
- TGA refused before writing, naming item 2.5 and R-322.

Ticked:
- **2.2.** Evidence: `test_unreal_preset_packs_the_documented_layout`.
- **2.4.** Evidence: `test_unreal_presets_load_unconfirmed`. The Painter name and its URL resolve to `unreal-engine-packed`, which is then refused on R-322 as decision 095 requires.
- **3.6.** Both records validate against the schema on the CPU lane. Evidence: `test_unreal_presets_load_unconfirmed` and `test_export_presets.py::test_provenance_records_are_complete`.

Still open:
- **2.1.** Recording R-322 is not made, and its request is not authored yet.
- **2.3.** The record has no observed-output hashes until R-322 is admitted.
- **2.5.** No TGA writer exists, because stb is not vendored, and Painter's TGA files are not recorded.
- **2.6 and 2.7.** The shipped presets cannot export: they are refused on R-322, and their ORM reads AO_Mixed.
- **2.10.** AO_Mixed is unchanged and still refused.
- **2.8, 3.1 to 3.5 and 4.1.** These need Painter, UE 5.6 or the fitted ORM.

The dry run, the DDS companions, the receipts and the SpecularWeight gap are exercised only on a test-only copy, `variant_presets`. That copy's provenance says `confirmed`, and its ORM R reads `ambientOcclusion`. This is not shipped-preset, Painter-parity or UE 5.6 evidence (the decision 318 pattern).

Validation, CPU only, Debug `uzp-export-tests` built with `-j2`:
- First run, 18 node ids: 16 passed and 2 failed. The failures were test-side: a skeleton without Emissive, and an inline `dds` key that is NotYetSupported (undocumented), not a ValueError. Exit 1.
- The 2 failed ids, re-run after the fix: both passed, exit 0.

The 18 node ids:
- all 10 cases of `tests/export/test_unreal_preset.py`;
- from `test_export_presets.py`: `test_provenance_records_are_complete`, `test_shipped_presets_pass_the_guard`, `test_painter_names_resolve_to_shipped_presets` and `test_preset_references_resolve_inline_first`;
- `test_export_plan.py::test_refused_formats_raise_before_any_file`;
- `test_dds_publication.py::test_dds_real_write_publication_receipt_and_fixed_copy`;
- from `test_uze_preset.py`: `test_shipped_preset_loads_with_its_targets` and `test_dry_run_lists_outputs_with_formats`.

Logs: `tmp/scratch/ue-preset/run1.{log,xml}` and `run2.{log,xml}`. Ruff and mypy pass on the two Python files.

## 10. AO_Mixed stability controls (2026-10-23, decision 131 amendment)

The current Painter 12.2.0 envelope now admits `ao-mixed-grid-l32f` and
`ao-mixed-grid-l16-reopen3`. Their private record hashes and aggregate results are
recorded in decision 131's 2026-10-23 amendment. L16 r2, r3 and r4 are identical,
while r1 differs in AO_Mixed despite identical channel and mesh exports. L32F
exposes a channel change after reopen at opacity 0.75; the product of exported
operands still does not reproduce all AO_Mixed texels. Same-session repeats and
PNG/OpenEXR twins are consistent. No exact operator is established, no acceptance
requirement is weakened, and item 2.10 and the production refusal remain open.

Recorder preparation preserves the default two recordings and accepts an explicit,
bounded `recorder.reopen_count` of 1 through 3, validated before connecting. Its
549 recorder tests, 93 focused recorder/grid checks, Ruff, mypy and the private-store
guard passed. These validate capture machinery; they do not claim export parity.

The follow-up `ao-mixed-precomposed-half-l32f` is also admitted. Its equal-operand
precondition fails: the replicated RGB EXR source gains one-ULP differences from
RGB-to-scalar conversion at 68 rows, exactly explained by float32 sum times the
float32 reciprocal of three. The paired AO_Mixed outputs agree, but their channel
operands differ, so no operator conclusion follows. Decision 131 records the
hashes, scope and failed precondition. Item 2.10 and the refusal remain unchanged.

The scalar Y/FLOAT follow-up `ao-mixed-precomposed-half-y-l32f` is now admitted
as private record `82e83932121173190e638a162fbf5978ba56e404c8f79ff6d7691b0cad040bef`.
All eight EXR pairs satisfy exact channel and mesh operand equality, and
AO_Mixed agrees across the two composition paths. Immediate repeats and r1/r2
are identical. The exported-operand float32 product followed by WriteUnorm8
still misses two texels per set/export, including precomposed opacity-1 sets.
Decision 131 records the scoped conclusion and private aggregate report.
The authored scalar fixture/request tests pass; no exact operator or acceptance
is claimed, and item 2.10 remains open.

## 11. Native TGA8 writer (2026-10-23)

The writer portion of item 2.5 is implemented in `src/export/tga_writer.{h,cpp}`:
`EncodeTga(TgaImage)` takes explicitly quantized L/LA/RGB/RGBA bytes, top row
first, and writes deterministic RLE TGA8 through pinned stb image_write v1.16.
Alpha is retained, including fully opaque alpha. Zero/over-65535 dimensions,
invalid layouts, sample-count mismatch and rasters exceeding stb's signed-int
indexing limit are refused before encoding. Private static stb settings are
never mutated. Build integration includes the application, Python API tests and
native export tests.

`tools/vendoring` pins upstream commit
`003501f6d7a8668ce8b6d875e34dd97ad0d5d5b5`, archive SHA-256
`a6c31950b3bdf05eb92258768ba2a11bd44449490574b1aac67028452288c40d`,
verbatim header and MIT licence. The folder manifest, licence inventory and
include checks pass.

Validation: 51 CPU tests passed, 88 unrelated cases deselected
(`scripts/tmp/tga-final.xml`): 19 writer cases, TGA/unsupported-format refusal
regressions and vendoring checks. Writer tests verify RLE/raw packet transitions,
orientation, all four layouts, alpha extremes and dimension/indexing limits,
using an independent decoder and Pillow. Ruff, mypy (three touched Python files)
and `zig fmt --check build.zig` pass.

`zig build export-tests` also passes with `-Doptimize=ReleaseSafe`, `ReleaseFast`
and `ReleaseSmall`. The same 19 authored writer cases pass against each of those
three binaries, in addition to the Debug pytest run.

Item 2.5 stays open: Painter TGA processing/file evidence R-322 and export
integration remain unadmitted. The public export configuration still refuses
TGA; no PNG processing rules were silently reused. No Painter or GPU ran, and
no Unreal preset or consumer acceptance is claimed.

## 12. TGA recorder preparation (2026-10-23)

The recorder measures TGA8 from its header and complete pixel stream. Its shared
reader preserves L/LA/RGB/RGBA codes, RLE/raw packets, alpha and both image origins;
the fit decoder uses the same samples without colour conversion. Optional TGA 2.0
extension/developer areas are explicitly outside this domain: their indirect
offsets must not let metadata satisfy missing pixels. The source fingerprint
includes this reader. Storage encoding retains the documented source basis.

Validation: 150 CPU capture/TGA/envelope regressions pass; Ruff, format and mypy
pass on all five changed Python files. Independent review also decoded 30 native
writer files byte-exactly. This prepares recording only; actual Painter metadata
compatibility, item 2.5 and R-322 acceptance remain open.

## 13. R-322 requests and shelf readiness (2026-10-23)

`export-presets-unreal-packed-legacy` and `export-presets-unreal-packed-ocio`
reuse R-314's distinct authored channel/mesh state. Five probes separately test
own defaults, padding-only defaults, matched explicit PNG8/TGA8 and pipeline
PNG16. The versioned starter-assets URL comes from the documented R-314 Legacy
r2 preset list (private record
`e729f2294b0d4acc019a2fa7b025c01df0821fa9dd9acf78ee00fcce4e4ce2fd`).
Each request captures lists/output maps and repeats after Full save/reopen.

The recorder now calls documented shelf refresh/readiness operations before
preset observations and probes. It polls actual crawling state, with one refresh
and a 120-second deadline per recording; failure prevents any preset capture.
The same gate runs after reopen. Source-API provenance checks pass.

Validation: 60 request/catalog tests and 99 shelf/recorder/provenance tests pass;
Ruff, format and mypy pass. Manifests and five recipes match the generator.
No recording ran during the full GPU suite; item 2.1 remains open until the
actual outputs are admitted, and no preset defaults are accepted by these tests.
