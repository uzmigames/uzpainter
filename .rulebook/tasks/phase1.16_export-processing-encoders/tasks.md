## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.14_compositor-core, phase1.15_export-plan-compiler

## 2. Implementation
- [ ] 2.1 Vendor libpng, zlib and tinyexr from upstream with licence files and origin records
- [ ] 2.2 Implement the five padding algorithms with `dilationDistance` on the render-layer dilation pass, fitted to Tier 0
- [ ] 2.3 Implement resize (`sizeLog2` scalar and `[w,h]`) with the Tier 0-fitted filter
- [ ] 2.4 Implement per-map dithering with the Tier 0-fitted algorithm
- [ ] 2.5 Implement bit-depth and colour encoding (sRGB for colour-managed channels, linear for data, signed normals at authoring precision, mesh maps at native precision)
- [ ] 2.6 Implement the deterministic PNG 8/16 writer (fixed zlib level and strategy) and the EXR 16f/32f writer
- [ ] 2.7 Publish `parity/semantics/export-processing.json`

## 3. Tests
- [ ] 3.1 Tier 0 export goldens: padding algorithms and dilation distances exact on decoded pixels
- [ ] 3.2 Tier 0 export goldens: resize (`sizeLog2` scalar and `[w,h]`) exact
- [ ] 3.3 Tier 0 export goldens: dithering on and off exact; infinite padding without dithering (EXP-02) exact
- [ ] 3.4 Tier 0 export goldens: bit depths 8 and 16 (PNG) and 16f/32f (EXR) exact
- [ ] 3.5 Byte determinism: identical files across two runs and two processes for PNG8, PNG16 and EXR
- [ ] 3.6 Decode round trip: a PNG16 and an EXR read back equal the encoded values at native depth

## 4. Acceptance
- [ ] 4.1 Tier 0 sets of this child exact on the self-hosted GPU runner; determinism tests green on the hosted CPU lane and the runner

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
