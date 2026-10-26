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
reuse R-314's distinct authored channel/mesh state. Five configurations separately test
own defaults, padding-only defaults, matched explicit PNG8/TGA8 and pipeline
PNG16. The versioned starter-assets URL comes from the documented R-314 Legacy
r2 preset list (private record
`e729f2294b0d4acc019a2fa7b025c01df0821fa9dd9acf78ee00fcce4e4ce2fd`).
Each request captures lists/output maps and makes two consecutive export probes
per configuration (ten probes), then repeats after Full save/reopen.

The recorder now calls documented shelf refresh/readiness operations before
preset observations and probes. It polls actual crawling state, with one refresh
and a 120-second deadline per recording; failure prevents any preset capture.
The same gate runs after reopen. Source-API provenance checks pass.

Validation: 62 request/catalog tests and 99 shelf/recorder/provenance tests pass;
Ruff, format and mypy pass. Manifests and five recipes match the generator.
No recording ran during the full GPU suite; item 2.1 remains open until the
actual outputs are admitted, and no preset defaults are accepted by these tests.

The next recording batch shares at most 60 minutes with the endpoint-plane and
AO product controls, followed by at most 30 minutes initial analysis. It starts
after the full suite releases the GPU. Its private ledger records elapsed time;
timeout, identity/precondition failure or completed repeats/reopen ends the
batch. The AO prediction and R-322 processing controls stay unchanged after
observation; failed preconditions and residuals are published before another
experiment. These limits grant no tolerance or acceptance.

## 14. Bounded capture outcome (2026-10-23 local / 2026-10-24 UTC)

Both R-322 colour-session controls and the AO product control are admitted.
The four-control live batch took 118.067 seconds; initial CPU analysis took
4.885 seconds, including 3.148 seconds for R-322, with no retries or fitting.
Shared Painter lock recovery was operator-authorized; owned processes ended
and lock release committed after the separate SourceSubstance session.

Per Legacy/OCIO session, matched PNG8/TGA8 compares 16 maps, reopen compares
32 maps and immediate repeats compare 32 maps, all with zero differing samples.
Own-default configuration `unreal-own` fails four dry-run probes per session
with `ValueError: when evaluating export parameters, padding algorithm could not be resolved`.
No fallback export ran; eight comparisons per session remain unavailable.
Successful explicit settings do not supply missing own defaults or consumer acceptance.
The whole-corpus stability report classifies each complete control as unstable:
all 32 exported maps agree, but two own-default dry-run readbacks per session
differ after reopen. Its exact-golden gate remains closed despite equal pixels.

Private record hashes: Legacy
`313c261b65d68c511404e3b24a99df6f223d3110b9db6ba1d32e1f7a56f8d599`,
OCIO `fd227d2a18fec4daac9b919c4e482dc77cf2365cbce237f1f0c021c885107dc7`.
Private R-322 analysis hash:
`b963ee84cf10be871477fad66267afc498487aa43dcdac4683c2c64802e44e01`.

AO's 32 operand/product preconditions and 96 stability checks pass, but all
16 frozen predictions and 16 of 24 cross-set comparisons fail with two samples
each (`parity/reports/phase1/ao-mesh-product-control.md`). AO_Mixed remains
refused. No task acceptance or capability promotion follows from admission.

## 15. Diagnostic TGA8 processing candidate, test-only (2026-10-25)

`uzp-export-tests tga-processing-candidate <templates> <spec.json> <candidate-png8.json> <out.tga>`
(tests/export/export_test.cpp) is a diagnostic route in the test binary only. After `ParseSpec`
it sets the project's template to the spec's. It then hydrates every fill's blending with Painter's
insert defaults (`ApplyDefaultBlending`, decision 115; now inline in `python/stack_sync.h`, with the
same rule and callers) and applies the authored blending over them. It encodes the
spec's single planned PNG 8 file in memory through the diagnostic measure export (`EncodeExport`
with `DiagnosticMeasure`, decisions 286 and 308; not conformant), decodes those native PNG bytes
and writes their 8-bit codes unchanged as RLE TGA8 (`EncodeTga`). It reads no oracle. `ParseFormat`,
`FormatOwner`, the plan, provenance, presets and capabilities are unchanged: the product still
refuses TGA (R-322). No bypass or padding change.

Report: always `model: native-png8-processing-candidate` and `non_conformant: true`. Success adds
`planned` (parameters, width), `png8_sha256`, `tga` (sha256, size, width, height, channels),
`bypassed`, `undecided` and `fill_blending`. A refusal adds `error` (Setup, ValueError,
NotYetSupported, Failure or InternalError), `stage`, `message` and `blocked`. `blocked` is true only
for a NotYetSupported raised by the `CompilePlan` call (`reason_code: compile_plan_not_yet_supported`,
with any release-gap virtual maps the configuration names as context). Failure adds the render
`code` and, for an evaluator failure, `eval_kind` and `eval_class`. A diagnostic success is never
conformity.

Authored CPU evidence (`tests/export/test_tga_processing_candidate.py`, 3 tests, final run 3 passed;
earlier runs predate the error contract and the hydration): RGBA and grey candidates match the
PNG 8 bytes `export-diagnostic` writes to disk. Pillow decodes the TGA and that PNG to the same
size, layout, alpha and orientation, code for code, and reruns are deterministic. Refusals keep the
model fields and stages (Setup, AO_Mixed and TGA as typed blocked plan refusals, malformed
configuration as ValueError). Default and authored blending are hydrated. The API default-blending
test passed after the extraction. The comparison with the admitted Painter TGA8 oracles is the
router's separate replay. Channel, alias and blending hydration are resolved; it waits on the documented `SourceBitmap` colour-space defaults (a probe the router is outlining), so no oracle replay has run. Item 2.5 stays open.

## 16. Observed bitmap default colour spaces for the R-322 setup (2026-10-25)

Evidence: `tier0/api-probes/source-bitmap-defaults-unreal-legacy` and `-ocio` (85ba83ae requests,
4c8171da admitted), recorded in UzPainter's own sessions. `get_color_space` is stable in r1 and r2
(9/9 per session); `get_source` differs only in the reopened resource context.

`python/uzpainter_facade/bitmap_defaults.py` (standard library only, shared with host replays):
`describe_png` parses exactly the imported bytes strictly. It checks the signature, chunk lengths and
CRCs, IHDR first and IEND last and empty. For the observed shape only, the IDAT stream must inflate,
within a bound, to exactly the expected scanlines (filter bytes 0..4) with nothing trailing.
`lookup(DefaultContext(profile, config_sha256, template_id, canonical channel, channel format),
descriptor)` answers only the exact observed entries (16-bit grey or RGB, 256 x 256, chunks IHDR,
IDAT, IEND, the two R-322 contexts), and `native_tag` serializes the result. The facade records
the descriptor at import only when the native import stored the same bytes, and a malformed
record raises. So does a malformed stored map: a present value that is no map, or a record whose
chunks are not a list of strings, refuses `set_source` before its channel activation and an import
before the native import, with no new revision or resource. `set_source` and `reset_color_space` resolve the exact entry first and bind its
native tag (a LegacyColorSpace member keeps its class). A mask source, an unknown bitmap or one of
another kind goes straight to the older rules, which are unchanged.

Tests (`tests/python/test_bitmap_defaults.py`): strict parsing and zlib negatives, exact lookup
and misses, and the Legacy facade replay, which is typed-exact against both recordings after save
and reopen. The OCIO replay is a reported xfail: 16-bit colour bitmaps under OCIO remain a
release gap (decision 190), and the OCIO rows are recorded facts, not a capability. The
configuration string reads back as itself through one qualified native tag,
`OcioColorSpace.sRGB`: `BitmapColourSpaceIn` (sources.h) evaluates it as the plain `sRGB` tag only
under the pinned OCIO profile, on the support and DAG paths alike, and refuses it elsewhere. No
other qualified name is accepted. The evaluator `sources` case checks equal samples and the
refusals; the facade OCIO 8-bit round trip checks string and enum identity across save and reopen;
a regression checks three corrupt descriptor maps refuse before any change.

Tier 0 traces: five facade replays already differed at HEAD (mask-stack, fill-layer-readback,
p22b-host-resources, export-ocio-encode and its Legacy twin). Each passed its complete comparison
before its trace was updated (decision 112). The capability files take 10 facade promotions and 2
native evidence corrections, committed separately, and the 5 capability conformance tests pass.
Item 2.5, parity and the OCIO 16-bit bitmap gap stay open.

## 17. EmissionColor in the sRGB8 export rule (2026-10-25, decision 126 amendment)

The first real `test_r322_tga_capture_diagnostic` runs failed, and both failures stay failures,
not blocked rows. In the first, the test derived each recorded output id from the lowercased
public record id. Router fixed the selection: it now goes through the recorder's own slug, with
uniqueness and every identity check kept. In the second, the native candidate refused the
`EmissionColor` sRGB8 map at `encode_export` (`kSrgb8NotRecorded`), after 2 native runs before
the failure; no completed comparison report was retained. The classifier stays v2 (compile_plan
only).

Painter's `Emissive` is the legacy alias of `EmissionColor` (decision 295). Decision 126 is
amended to cover `EmissionColor` exactly where R-090 recorded it: an sRGB8 channel under legacy
colour management. The export follows the same sRGB8 rule. The base value comes from one channel
default restricted to template `default`, legacy colour management and sRGB8, applied by the
evaluator, the export and the recipe with the project's own colour management. An L8
`EmissionColor` in a PNG is now refused instead of written linear, and an sRGB8 one under OCIO
stays refused.

Evidence: R-090/P10 rebuilt with `EmissionColor` matches Painter byte for byte, 96 files and
192/192 comparisons. The domain controls and export refusals pass. A missing `preflight` default
on `store::OpenOptions` (since b28e25e8) had stopped `uzp-store-inspect-tests` from compiling; it
is fixed in the header. The 4 OCIO emissive TGA targets stay outside the supported domain (sRGB8
`EmissionColor` under OCIO is refused). At amendment validation, the R-322 TGA diagnostic had
not yet been rerun; the subsequent run 3 is recorded below.

Run 3 (2026-10-25, at a2106b5f, with router's partial-progress report; one run, private report
0f2d26d6c89cc3e9) is a diagnostic failure, not a parity result. 5 candidates were attempted and
returned, and 16 of 32 targets were classified. The Legacy session is complete. Its basecolor,
emissive and normal targets (12) produced candidates whose diagnostics differ under the
candidate's declared padding bypass. Its occlusionroughnessmetallic targets (4) are blocked at
compile_plan. The OCIO session stopped at its first candidate (`ocio/r1/s56/basecolor`): the
native refused at encode_export with unsupported_source (decision 190: under OCIO only an 8-bit
colour bitmap on an sRGB8 channel sampled 1:1 is recorded). That is a real failure. The remaining
16 OCIO targets are unclassified. There was no retry, and no gate changes.

## 18. Authored OCIO16 input controls (2026-10-25; capture admitted)

Five independent `ocio16-bitmap-srgb-basecolor*` requests isolate the decision 190
input gap blocking item 2.5/R-322: public RGB16 field-a and two cyclic permutations,
an RGB8 control, and a Working uniform, on BaseColor sRGB8 under pinned OCIO.
Each captures PNG8, PNG16 and EXR32f after its getter, then repeats after Full
save/reopen without setters: 15 exported-map records per condition, 30 total.
Bitmap setters preserve the literal configuration string `sRGB`, not its enum.
Final exports opt into `key_by_step` identities; existing output IDs stay unchanged.
Mock pipeline checks retain every referenced byte through inbox copying, including
stable repeats that deduplicate content blobs. All 29 new CPU cases and 21 affected
recorder/provenance regressions pass; Ruff/mypy pass.

All five controls are captured and admitted, one attempt per run. The owned Painter
process ended and its lock was released. Offline verification resolved and re-hashed
all 30 export references: 15/15 r1/reopen-r2 encoded-file pairs have identical hashes,
which also establishes identical bytes and pixels without another decode. All 5/5
primary getter pairs match exactly, preserving types and signed zero; setup and
bookkeeping readbacks are not counted as primary getters. The admitted instruction
sequences match the authored requests. This establishes capture stability only,
not UzPainter parity. No fit, domain, checklist, capability or acceptance gate changes.

Native RGB8/uniform baselines passed on 2026-10-25. The six candidates are built
only from the authored requests and inputs, before any oracle read: RGB8 sRGB into
BaseColor/sRGB8 and uniform Working, each exported as PNG8, PNG16 and EXR32f.
All six exports completed and all 12 comparisons against r1/reopen-r2 have
identical encoded bytes, establishing exact decoded pixels as well. The general
verdict compares decoded values exactly when encodings differ; signed pixel zeros
are numerically equal and NaN matches only NaN. Typed API observations retain
their separate signed-zero contract. The private count-only report hashes to
`140523b9ab2924b871e8f84b15e8a9481f20f542ffecd1d60ab45072890f2d2e`;
the explicitly supplied export-test binary hashes to
`a96968baeaa2e561bb34bc9b4b8f130d8ca7b85f803520eb07b74dfbaa2f478c`.
The replay never builds implicitly. CPU reconstruction/comparison checks and
Ruff/mypy passed; the real replay passed after the coordinated export build.
RGB16 decoding, fits, padding, item 2.5 and broader gates remain unchanged.

The test-only RGB16 candidate completed on 2026-10-25 and its hypothesis was
rejected. `ocio16-input-candidate` tests the explicitly non-conformant model
`legacy-rgb16-to-srgb8-with-ocio-export`: a validated clone changes only colour
mode and the bitmap tag, requires an identical export plan, evaluates through
the existing provider and encoder, and keeps production guards unchanged.
Its domain is the three authored RGB16 sources, full UV plane, one visible
Normal/1 Fill, identity UV Nearest/Repeat and PNG8/PNG16/EXR32f, with no extra
content, inactive source, effect, mask, padding, dither or resize. All nine
candidates are produced before reading any oracle; receipt, admission,
configuration and input identities are checked before exact comparison.

One coordinated export build and 28-node batch produced 27 passes and one
diagnostic failure, with no skips. The RGB8/uniform baseline remains exact in
all 12 comparisons; both affected synthetic Filter getters pass. RGB16
returned nine candidates and nine provider fetches. All 18 image comparisons
against r1/reopen-r2 differ in both encoded bytes and decoded values; neither
side contains non-finite pixels. Eighteen counts differing images, not differing
pixels. All 24 native outside-domain cases refuse as required. No fit or
output-dependent adjustment follows this rejected hypothesis.

The export-test binary hashes to
`fd1635de0d9a288b632d3acfd237c84f0f2c535b1f48971b2cc8b7c40e23cdd0`;
the private RGB16 report hashes to
`d607a2eb8f516578f5dc7375d48cd5adc7a7be699b4b9f8365dfbc1e41a48a6d`.
Nine candidate images and 30 input/configuration/log texts were preserved
privately with verified hashes before pytest retention could remove them;
the private evidence index hashes to
`c15da6d45a5fe8237256607a2828c84062639da7101f7d5ae3c0e80c816669f4`.
The aggregate batch JUnit hashes to
`97d8f103b7aa58a15208690f48d7324e0a43065f627fba538c86b1eff33fa913`.
The diagnostic failure remains explicit. Production RGB16, item 2.5/R-322,
padding, fits and all broader acceptance gates remain open.

Aggregate diagnosis of the preserved candidates completed without generating
another candidate or capture. Each of the 18 image comparisons differs at six
of 65536 pixels, in one channel; the affected channel follows the authored cyclic
permutations. All nine r1/reopen-r2 image pairs and all 18 fixed inverse-permutation
checks are exact. Neither side contains non-finite samples. In all nine
source/condition matrices, all 196608 EXR samples belong to the existing 256
sRGB8 operands; the corresponding PNG8 indices and PNG16 table codes have zero
mismatches. The difference is visible in the common reconstructed code across
formats. This does not identify a causal Painter stage or distinguish decode16
from quantization/storage, and the candidate remains rejected.

`tools/parity/ocio16_rejected_diagnostic.py` verifies the preserved inputs before
using the shared admitted-receipt validator, then writes measurements only to a
new private report. Its SHA-256 is
`5ce9755be03fc581fae03b80441cd4e9eebd37b88bf499f5b92337b5890b016e`.
The validator moved to `tools/parity/ocio16_bitmap_replay.py` with seven bodies
unchanged by AST, removing an accidental dependency on the installed `tests`
package. Forty-nine focused CPU tests passed, with 26 native cases deselected.
A later pre-oracle path-key failure was corrected by normalizing preserved
Windows path identities while retaining hash checks and duplicate refusal;
seven diagnostic tests then passed. Operational failures now retain a private
stage/traceback without overwriting prior evidence. Mypy, Ruff and independent
review passed. No residual threshold, fit, model adjustment or capability change
was introduced.

## 19. Authored Raw readout controls (offline preparation)

`tools/parity/tier0_semantics/ocio16_raw_readout_control.py` authors three
256-square controls independently of private differences: FLOAT EXR centers
`float32(n/65535)` with adjacent values toward zero/one in the other RGB channels,
complete cyclic RGB PNG16 codes, and the same codes normalized once to FLOAT
EXR. Native-precision decoding and FLOAT headers are checked. Cross-channel
adjacency alone cannot establish scalar collisions without a separate channel
invariance check; matching PNG/EXR outputs would establish only observed transfer.
The Color channel flag remains unobserved, not presumed false or inferred from
RGB32F storage.

Six public requests separate capability checks from later exports. The closed
context is the pinned OCIO environment, public full-UV plane, User0 RGB32F, one
visible Split Fill, Normal opacity one, neutral geometry and identity Nearest
Repeat projection. Raw must appear once in available colour-space names and
read back as the typed GenericColorSpace/Raw enum. Setup executes once; fresh
getters repeat after Full save/reopen, without round-two setters. A new bounded
delete-node selector removes only the single initial Paint immediately after
the recorder's own CREATE: owned UUID, exact type/count, fresh UID resolution
and empty roots afterward are required; ordinary deletion remains unchanged.

`tools/parity/ocio16_raw_readout_admission.py` checks the exact generated request
before loading private bytes, admitted capture and environment references,
hashes/sizes/schemas, their environment join, receipt and OCIO identity, exact
round/output inventories, imported-resource identity, cleanup receipt and closed
topology/state. Review corrected an erroneous single-reference assumption:
actual records require both golden-record and oracle-environment, selected by
kind/ID rather than array position. Thirty-one admission tests passed after the
fix; the focused recorder/control batch passed 53 cases initially and its two
remaining failures passed after harness/provenance fixes. Earlier affected
checks remain valid; mypy, Ruff and formatting passed. The separate preexisting
P22-B route-index failure was corrected with real route/owner assertions in
commit `fc611fdb`, keeping both getters pending-evidence.

No Painter capture, export, fit or production change was performed in this
offline slice. Runtime still needs the bounded owned-process runner and a
successful capability gate for each state. Export requests are not authorized
by this preparation; item 2.5/R-322 and broader acceptance remain open.

## 20. Owned capability capture and corrected V2 requests

The owned-process runner is committed in `tools/parity/recorder/raw_capability_capture.py`.
It uses the shared canonical lock, PID/start identity and CREATE-bound UUID checks,
closed-state reopen guards and sticky ownership-loss refusal. READY location and
counts are recorded privately before the final ownership check. Runtime fixes
distinguish only the exact known bridge executable from Painter and use the
canonical CLI response envelope and documented `Astra/<session>` owner. No bridge
is imported or executed; a narrowly pinned negative process classifier is the
only provenance exception. Raw capture performs neither exports nor admission.

The first `calibration-float` capability run completed in its own Painter, wrote
two private records and passed the public manifest gate. Cleanup stopped its
process and released the lock. The store admitted the immutable capture, but
capability validation refused it: the sole raised output is first-round setup
`s15/set_color_space`. The authored request passed `Raw`; the recorder's actual
bitmap table accepts `GenericColorSpace.Raw`, so it refused before calling the
Painter API. This is not evidence that Painter lacks Raw. The private capture
report SHA-256 is `0794f01d5db214a03c1dbfa96e94f5a4fe9953e9413d863d20fa8a9a8b2488a8`.
The original request and admitted manifest remain unchanged, and no capability,
transfer, fit, export or production behavior is accepted by this run.

Six new `*-v2.json` requests have distinct golden identities and use the qualified
enum key. Every other authored field and all three bitmap fixtures are unchanged.
The current runner and validator require the exact V2 recipe and refuse historical
requests. Regression coverage now executes the real `member` function and bitmap
enum table against an authored enum, proving that the qualified key reaches the
setter and the old short key refuses first. Sixty-eight affected cases passed;
mypy, Ruff and formatting passed. V2 runtime admission remains a separate gate;
export requests still require successful capability evidence for their state.

The V2 `calibration-float` capability completed in its own Painter, passed the
public manifest gate and admitted two private references. Cleanup stopped the
owned process and released the lock. The capture report SHA-256 is
`61d18c52b03f07bdf10f8fd0286c601702a3b1149b187425f912467c7bcbfede`.
Capability validation refused `authored readback differs`: only round-two
`s30/get_source`, `value.bitmap.resource.context`, differs from the original
import identity. Resource name/version, Raw selection and the remaining fixed
readbacks match. The V2 capture and public manifest remain immutable.

The existing node rebind receipt does not establish a resource-context remap.
The documented `ResourceID.from_project` constructs an identifier without
proving existence; a versioned `Resource.retrieve` can establish its unique
resolution. A corrected request therefore needs independent project-scoped
resource evidence in each round, joined to the original import and the owned
project UUID, before comparing the full bitmap identity. The resource version
is not presumed to be the original file's SHA-256. No comparison is relaxed,
no normalization capture follows this refusal, and exports remain gated.

Six distinct V3 requests add three read-only probes per round: the current UUID
joined to the recorder's own CREATE marker, `ResourceID.from_project` using the
original import's nonempty name/version, and versioned `Resource.retrieve`.
Exactly one retrieved identifier must equal the project-scoped query and the
complete `get_source` bitmap identity. Prior import/query references and special
argument forms are closed and type-checked; existing getter forms stay intact.
The setup, authored fixtures and historical requests are not rewritten.

The real dispatcher branches are tested with authored resource and project
objects, including changed project context after reopen, foreign UUIDs, missing
versions, incorrect references and zero/multiple retrievals. A total of 151
distinct affected cases passed across the initial run and targeted retries;
mypy, Ruff and formatting passed. This validates the V3 software only. Fresh
capability capture/admission remains required before any export collection.

## 21. V3 calibration capability and export collection gate

The owned REV370 calibration FLOAT capture passed manifest validation, private
store admission and capability validation in both rounds. Its capture report
hashes to `0caed6ce43dc1a8c4ba90a68cc78931cfbba79b44793ac2cd32d8380891b4c37`;
the capability validation report hashes to
`a3560baa27c0573c3a48a1ef6427796fe602937087bb8045fe007809dbf1f674`.
The same sequence stopped before launching the normalization FLOAT capture:
the unchanged memory preflight refused insufficient commit headroom. PNG16 did
not start. No Painter or lock remained, and that refusal is preserved. This is
not a Raw capability failure or authorization to lower the memory threshold.

`tools/parity/ocio16_raw_export_gate.py` revalidates all three exact admitted V3
capabilities for each requested export collection, including their environment
joins and a stable current registry. Its private audit binds the export request
and all prerequisite references; an old audit is never accepted as a permit.
Eighteen authored cases passed with real capability validation over authored
in-memory stores; type/lint/format checks and review passed. This gate grants
no numerical identity, cross-format equality or pixel conformity. Actual export
collection still requires a fully gated owned collector.

After a fresh resource preflight recovered, REV372 captured and admitted the two
remaining V3 capabilities without repeating calibration. Both normalization
FLOAT and PNG16 validated in both rounds, with no exports; cleanup left no
Painter and released the lock. Their validation reports hash respectively to
`af7c66c7cddc6ab5f907120cbed7a584e5885daae5e89db8a03506be926e976d` and
`97f836d6869c7ed29ecf6c2e199fde258716365416f8378868cd849b6b51833c`.
All three V3 capabilities now validate. Readout identity, the Color flag and
pixel/production parity remain unestablished; collection and post-export
validation are separate dependencies.

## 22. Gated Raw export collector and post-admission validation

The separate export collector revalidates all three V3 capabilities under its
ownership lock immediately before launch, records a private immutable audit and
rechecks resources and endpoints. The capability command stays capability-only.
READY requires two rounds, one map per round and four exact private references.
Collection does not admit data or establish numerical identity.

The offline post-admission validator joins the complete receipt, environment,
authored setup, resource identity after reopen and exported-map inventory. It
decodes verified EXR blobs directly using the existing OpenEXR binding, requiring
RGB FLOAT32, 256-square dimensions, unit sampling and finite values. Round equality
compares uint32 bits, including signed zero. The producer's linear encoding label
is retained as file metadata; no input/output identity or transform is inferred.

The collector's 45 affected tests plus provenance checks and the validator's 85
tests passed, with mypy, Ruff, formatting, independent review and guard checks.
Authored real EXRs cover equal pixels with different file bytes. No actual export
has run at this checkpoint; input equality, fits, Color flag and production parity
remain separate open requirements.

The subsequent owned REV375 calibration FLOAT export completed with two maps and
four admitted private references. The collector stopped its own Painter and
released its lock. The native FLOAT32 post-admission validation passed both
rounds, including exact uint32 pixel equality. Capture report SHA-256:
`fd11ab768fffdcfa6d25c7de0484770e95a41b10d302e38af6be016a1bb44ae5`;
validation report SHA-256:
`9dcaa65439aeffa142fc091823c3edb4f8b9360d9b9b311c5642f6610dba7cc5`.
Normalization FLOAT and PNG16 exports remain pending. This proves repeated
output stability for calibration only; input identity and production parity
remain unestablished.

REV377 then captured, admitted and validated normalization FLOAT and PNG16,
one owned Painter at a time. Each has two exports and exact native-bit equality
between its rounds; both processes stopped and the lock is free. Their validation
reports hash respectively to
`5475b2cbf569ba73652bb73bf4699dddfd301989ceda04d3fcd9fbe0699f3280` and
`d56cc58e7cad55c0254b25eb20fefdb3bfee6127739c88e228fa0992eba1c9a4`.
All three states now have admitted stable exports. Cross-input transfer and
identity remain separate measurements.

## 23. Fixed-coordinate Raw calibration measurement

`tools/parity/ocio16_raw_identity.py` defines a comparison before inspecting real
oracle pixels: revalidate the admitted calibration export, verify the exact
authored input hash and public formula, decode native FLOAT32 and compare uint32
bits at the same EXR [y,x,R/G/B] indices. Data and display windows must both be
(0,0)-(255,255). No flips, channel permutation, colour conversion, fitting or
tolerance are allowed. A valid difference is a measurement, not an execution
failure or evidence identifying its cause. Equality would apply only to these
finite calibration samples in their recorded context; negative-zero input,
general readout identity, Color flag and production parity remain unestablished.

The command writes a private immutable measurement, or preserves private refusal
diagnostics without overwriting earlier evidence. Forty-eight distinct authored
cases passed across the comparator/post-validator suite and targeted CLI delta;
mypy, Ruff, formatting, independent review and guard checks passed. Tests cover
different encodings of equal pixels, subnormal loss, zero sign, changed values,
orientation, coordinate windows, receipt refusal and write-once diagnostics.
No real calibration pixel was inspected while defining this comparison.

After the method was committed as `1b344be6`, REV378 measured the admitted
calibration: both rounds differ from the authored input in 65,535 of 196,608
samples, with 21,845 differences per RGB channel. Report SHA-256:
`1d75b2eea28d6059a778705c12c180d62b7ddfc53dc2a8e35e96338b7f7d4a0f`.
This refutes joint position/channel/value identity under the fixed comparison;
it does not identify a numerical transform, prove channel invariance or justify
scalar collision claims. No inversion, normalization or production change follows.

## 24. Paired Raw transfer comparison

`tools/parity/ocio16_raw_normalization_compare.py` fixes the FLOAT/PNG16 comparison
before reading their real output pixels. It revalidates both admissions, verifies
authored inputs and formulas at native precision, joins the common recipe,
recorded environment and observed context, and checks an unchanged registry.
Recorder versions are retained separately as provenance, not equated as envelope
fields, following `environment.py`. No code-equivalence or execution-attestation
claim follows from that provenance.

Output comparison uses uint32 bits at the same EXR coordinates and RGB channels,
with identical closed coordinate windows. Equal or different describes only
observable transfer in that context; neither outcome identifies the internal
normalization, establishes readout identity or promotes production support.
Reports and refusal diagnostics remain private and write-once.

Sixty-four distinct authored cases passed across this module and the reused
identity/post-admission modules. The sixteen paired cases passed again after the
provenance-only recorder-version correction; static checks and independent review
passed. Cases cover mismatched contexts/environments, changed registry, receipts,
formulas, windows, native bits and preserved differing recorder provenance.

After commit `b18b5cda` fixed the method, REV381 compared the actual admitted
normalization outputs: FLOAT and PNG16 are bit-equal in both rounds under the
verified common context. Private report SHA-256:
`40c94a11446fef7bbb00d47bd275ff7856cf53a67a3ae6b4590b99ed94c2845e`.
This establishes the measured transfer equality only. Calibration's nonidentity,
internal normalization, Color flag and production support remain unresolved.

## 25. Fixed Raw transfer diagnostics

The separate `ocio16_raw_transfer_diagnostics` method compares the existing
calibration FLOAT and normalization FLOAT experiments after fresh admission,
input hash/formula, native FLOAT32, envelope, context and registry checks. Its
primary metrics remain uint32 equality at identical EXR [y,x,RGB] coordinates,
with per-row, per-column and authored finite-value-class counts. It also checks
the shared authored R input before comparing R outputs at identical coordinates.
A difference there identifies a failed equality under the two RGB contexts,
not its cause.

A separate metric compares the normalization input's same authored code at its
three formula-defined channel/position combinations. Indices are fixed from the
public formula before inspecting real outputs. They never replace the direct
identity result or correct pixels, and they cannot separate channel dependence
from position dependence. No fit, inversion, general identity or production
promotion follows from any result.

Seventy-nine authored tests passed, including fifteen new diagnostic cases and
sixty-four reused admission/comparison cases. Mypy, Ruff, formatting and
independent source review passed. Reports and failure diagnostics are private
and write-once. No actual oracle pixels have been inspected by this new method
at this checkpoint; the method must be committed before that measurement.
