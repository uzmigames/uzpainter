## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store, phase0.8_toolchain-slice

## 2. Implementation
- [x] 2.1 Author the hemisphere low/high fixture with its analytic normal field and the manifest `parity/manifests/phase0/normal-convention.json`
- [x] 2.2 Vendor `mikktspace.c` from Mikkelsen's upstream into `thirdparty/mikktspace/` with its licence and `ORIGIN.md`
- [x] 2.3 Record the Painter bake of the hemisphere normal (documented baking API, Normal baker, OpenGL convention) twice and admit it to the store
- [x] 2.4 Prototype in the UzPainter build: MikkTSpace frames per corner; the hemisphere normal expressed in the `PerVertex` and the `PerFragment` frame
- [x] 2.5 Compare both prototype maps with the Painter oracle in tangent space at native depth; record residuals
- [x] 2.6 Shade the map in UzEngine's own executable as an external consumer fixture and record its green-channel convention
- [x] 2.7 Write the verdicts to `parity/semantics/tangent-frame.json` and the numbers to `parity/reports/phase0/normal-convention.md`

## 3. Tests
- [x] 3.1 Analytic check: the prototype reproduces the analytic hemisphere normal field on the authored fixture
- [x] 3.2 Comparison run on the owner's machine: `PerVertex` and `PerFragment` maps against both oracle recordings; the selected frame equals Painter or the residual is reported
- [x] 3.3 Directional check: a +Y-tilted region reads as +Y in the OpenGL map and flips in the DirectX conversion

## 4. Acceptance
- [x] 4.1 Acceptance gate (P0-NORMAL): convention and per-fragment frame settled with evidence

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
