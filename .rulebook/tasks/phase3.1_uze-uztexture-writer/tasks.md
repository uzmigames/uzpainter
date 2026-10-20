## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery` (parent input); `phase1.18_export-engine` and `phase0.5_vendor-render-core` delivered

## 2. Implementation
- [x] 2.1 Vendor etcpak (with bundled bc7enc) from upstream under `thirdparty/etcpak/` with `ORIGIN.md`, licence files, `NOTICE` and dependency-inventory entries (LIC-02)
- [x] 2.2 BC encoder adapter interface with the etcpak backend: BC1/BC3/BC4/BC5/BC7 and sRGB variants, fixed quality settings, thread-count-independent output
- [x] 2.3 Mip generation for colour maps: sRGB-aware filtering (decode, filter in linear, re-encode)
- [x] 2.4 Mip generation for normal maps: per-texel renormalisation at every level
- [x] 2.5 Mip generation for masked albedo: alpha-coverage preservation per level
- [x] 2.6 `.uztexture` writer from the vendored `uztexture_format.h` constants and layout, with explicit format, colour space, binding and mip metadata per texture
- [ ] 2.7 Normal guard: detect negative-Z texels before BC5 encoding; export fails or routes the map to an RGB format per the plan option; the choice is recorded in the receipt
- [x] 2.8 Test-only BC decoder and `.uztexture` reader (UzPainter's own code; the vendored header's read/write declarations stay unimplemented) — BC1/3/4/5 and all eight BC7 modes; attributed format constants, independent oracle and numerical contract in `docs/BC-DECODER.md`

## 3. Tests
- [x] 3.1 Encoder determinism: each BC format encoded twice and at 1, 4 and max worker threads yields identical bytes (local CPU lane, decision 200, `14-parity-testing.md` §7)
- [x] 3.2 Colour mip test on an authored sRGB ramp: each level equals the linear-space box/declared filter result re-encoded to sRGB
- [x] 3.3 Normal mip test on an authored hemisphere normal map: every texel of every level is unit length within the storage precision
- [x] 3.4 Alpha-coverage test on an authored masked-albedo image: coverage above the alpha threshold is preserved per level
- [ ] 3.5 Negative-Z fixture: an authored normal map with one negative-Z texel fails the export or routes to RGB, never writes BC5 silently
- [x] 3.6 Layout test: written `.uztexture` headers, mip offsets and sizes match the vendored format definition, read back through the test reader
- [x] 3.7 Lossy-derivative report: decoded BC data vs canonical map gives max/mean/p99 error per map, reported separately from authoring equality (`14-parity-testing.md` §4)

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase3.4_uzengine-preset`: deterministic encoder and mips, layout-correct `.uztexture`, guarded normals, lossy-derivative numbers published

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Item 2.8 validation (2026-10-20)
- Authored decoder, reader and size-validation regressions: all 11 `tests/export/test_uze_texture.py` tests passed on Debug; all 10 native cases passed separately on ReleaseSafe, ReleaseFast and ReleaseSmall. The source audit passed 57 tests. Run evidence: `tmp/scratch/bc-decoder/`.
- The all-mode corpus exposed an uninitialised alpha read in the bcdec oracle. The recorded, archive-reproducible initialisation fix retains sanitizers. Vendoring checks: two passed initially; the remaining check's obsolete single-patched-library expectation was updated and its rerun passed. No skipped tests counted as evidence.
- Reader and writer reject overflowing dimensions/offsets and malformed image buffers before access or publication. BC7 format constants retain their upstream MIT notice; bcdec is called only by the differential test, never by `DecodeBc` or the lossy report.
- Items 2.7 and 3.5 still require the real export plan, receipt and publication integration. Their library guard tests do not close those obligations. Prerequisite and final acceptance remain open.
