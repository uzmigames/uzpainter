## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery` (parent input); `phase1.18_export-engine` and `phase0.5_vendor-render-core` delivered

## 2. Implementation
- [ ] 2.1 Vendor etcpak (with bundled bc7enc) from upstream under `thirdparty/etcpak/` with `ORIGIN.md`, licence files, `NOTICE` and dependency-inventory entries (LIC-02)
- [ ] 2.2 BC encoder adapter interface with the etcpak backend: BC1/BC3/BC4/BC5/BC7 and sRGB variants, fixed quality settings, thread-count-independent output
- [ ] 2.3 Mip generation for colour maps: sRGB-aware filtering (decode, filter in linear, re-encode)
- [ ] 2.4 Mip generation for normal maps: per-texel renormalisation at every level
- [ ] 2.5 Mip generation for masked albedo: alpha-coverage preservation per level
- [ ] 2.6 `.uztexture` writer from the vendored `uztexture_format.h` constants and layout, with explicit format, colour space, binding and mip metadata per texture
- [ ] 2.7 Normal guard: detect negative-Z texels before BC5 encoding; export fails or routes the map to an RGB format per the plan option; the choice is recorded in the receipt
- [ ] 2.8 Test-only BC decoder and `.uztexture` reader (UzPainter's own code; the vendored header's read/write declarations stay unimplemented)

## 3. Tests
- [ ] 3.1 Encoder determinism: each BC format encoded twice and at 1, 4 and max worker threads yields identical bytes (hosted CPU lane, `14-parity-testing.md` §7)
- [ ] 3.2 Colour mip test on an authored sRGB ramp: each level equals the linear-space box/declared filter result re-encoded to sRGB
- [ ] 3.3 Normal mip test on an authored hemisphere normal map: every texel of every level is unit length within the storage precision
- [ ] 3.4 Alpha-coverage test on an authored masked-albedo image: coverage above the alpha threshold is preserved per level
- [ ] 3.5 Negative-Z fixture: an authored normal map with one negative-Z texel fails the export or routes to RGB, never writes BC5 silently
- [ ] 3.6 Layout test: written `.uztexture` headers, mip offsets and sizes match the vendored format definition, read back through the test reader
- [ ] 3.7 Lossy-derivative report: decoded BC data vs canonical map gives max/mean/p99 error per map, reported separately from authoring equality (`14-parity-testing.md` §4)

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase3.4_uzengine-preset`: deterministic encoder and mips, layout-correct `.uztexture`, guarded normals, lossy-derivative numbers published

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
