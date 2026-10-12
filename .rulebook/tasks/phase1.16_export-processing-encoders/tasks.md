## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.14_compositor-core, phase1.15_export-plan-compiler

## 2. Implementation
- [x] 2.1 Vendor libpng, zlib and tinyexr from upstream with licence files and origin records
- [x] 2.2 Implement the five padding algorithms with `dilationDistance` on the render-layer dilation pass, fitted to Tier 0
  - scope split, decision 090: `passthrough` everywhere and `infinite` on complete UV coverage implemented and exact (148/148 files byte-identical to Painter); `color`, `transparent`, `diffusion` (no recording) and `infinite` on islanded sets (partial fit published as a gap) refused before writing, owner phase1.18_export-engine item 6 (recording R-090 P5, P9).
- [x] 2.3 Implement resize (`sizeLog2` scalar and `[w,h]`) with the Tier 0-fitted filter
  - scope split, decision 090: no recording; refused before writing naming R-090 (P4), owner phase1.18_export-engine item 6.
- [x] 2.4 Implement per-map dithering with the Tier 0-fitted algorithm
  - scope split, decision 090: no recording; refused before writing naming R-090 (P3), owner phase1.18_export-engine item 6.
- [x] 2.5 Implement bit-depth and colour encoding (sRGB for colour-managed channels, linear for data, signed normals at authoring precision, mesh maps at native precision)
  - scope split, decision 090: evaluator read-out written with the 16-bit UNORM rule (PNG) or as float32 (OpenEXR, signed values kept), sRGB8 User channels linear, all exact; 8-bit and 16f rules, mesh maps other than normal_base (R-090 P1, P2, P7), sRGB8 material channels (recorded, R-090 P10) and RGB+A (needs the plan's alpha sources, R-091) refused before writing, owner phase1.18_export-engine item 6.
- [x] 2.6 Implement the deterministic PNG 8/16 writer (fixed zlib level and strategy) and the EXR 16f/32f writer
  - scope split, decision 089/090: PNG 8/16 (grey, RGB, RGBA) and OpenEXR 32f writers byte-identical to Painter (1027/1027 PNG, 267/267 OpenEXR re-encoded); OpenEXR 16f has no recording (R-090 P2), owner phase1.18_export-engine item 6.
- [x] 2.7 Publish `parity/semantics/export-processing.json`

## 3. Tests
- [x] 3.1 Tier 0 export goldens: padding algorithms and dilation distances exact on decoded pixels
  - scope split, decision 090: complete-coverage padding exact end to end; dilation modes and islanded `infinite` with R-090, owner phase1.18_export-engine item 6.
- [x] 3.2 Tier 0 export goldens: resize (`sizeLog2` scalar and `[w,h]`) exact
  - scope split, decision 090: no recording (R-090 P4), owner phase1.18_export-engine item 6.
- [x] 3.3 Tier 0 export goldens: dithering on and off exact; infinite padding without dithering (EXP-02) exact
  - scope split, decision 090: dithering off and infinite padding without dithering (EXP-02) exact, 148/148 files; dithering on with R-090 P3, owner phase1.18_export-engine item 6.
- [x] 3.4 Tier 0 export goldens: bit depths 8 and 16 (PNG) and 16f/32f (EXR) exact
  - scope split, decision 090: PNG 16 and OpenEXR 32f exact end to end and all recorded PNG 8/16 and OpenEXR 32f files re-encode byte for byte; PNG 8 values and 16f with R-090 P1, P2, owner phase1.18_export-engine item 6.
- [x] 3.5 Byte determinism: identical files across two runs and two processes for PNG8, PNG16 and EXR
- [x] 3.6 Decode round trip: a PNG16 and an EXR read back equal the encoded values at native depth

## 4. Acceptance
- [x] 4.1 Tier 0 sets of this child exact in a local run on the owner's machine (decision 028; the local run report is the evidence); determinism tests green on the hosted CPU lane and in that local run
  - scope split, decision 090: every Tier 0 set this child supports is exact in the local run (`parity/reports/phase1/export-processing-encoders.md`); determinism tests green on the CPU lane and locally; the R-090 sets belong to phase1.18_export-engine item 6.

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
  - tests/export 36 passed (Tier 0 included, local store); tests/vendoring 185 passed; tests/parity/fit publication 37 passed, tests/parity/test_guard + tests/sources green; `zig build export-tests` and `zig build painter` clean with -Werror; ruff and mypy --strict clean.
