## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.4_render-core-layer, phase1.7_mesh-loader, phase1.3_document-model, phase0.8_tier0-goldens, phase1.5_compositor-tile-dag

## 2. Implementation
- [x] 2.1 Implement fill layers and fill effects in `Split` mode with `active_channels`, never resetting values on toggle in the native evaluator
- [x] 2.2 Implement uniform-colour sources with explicit colour-space handling and the IEC 61966-2-1 transfer, adjusted only by the fitted Tier 0 deviation
- [x] 2.3 Implement bitmap sources from resources with the `(hash, format)` decode cache and per-node bindings by content hash plus alias
- [x] 2.4 Implement the `Fill` and `UV` projections with in-kernel `BilinearHQ`, `BilinearSharp`, `Nearest` filtering, four wrap modes and the UV transform
- [x] 2.5 Connect the texturing mesh to the UV raster pass and record the island-edge rule
- [x] 2.6 Publish `parity/semantics/colour-transfer.json` and `parity/semantics/uv-sampling.json` (fitted formula, public source, residual)

## 3. Tests
- [x] 3.1 Tier 0 uniform colour-space goldens: sRGB and Raw uniform values per channel exact
- [x] 3.2 Tier 0 sRGB ramp goldens: encode/decode exact after the fitted deviation
- [x] 3.3 Tier 0 UV filter/wrap/transform goldens and `BilinearHQ` resampling goldens exact — split (q1, 2026-10-11): exact for Nearest, RepeatNone and every Repeat value but one; the Bilinear+Repeat near-tie (s0/s1 User2, one code) and bilinear minification (User6) moved to `phase1.9_compositor-resample-gaps`, not accepted here
- [x] 3.4 Tier 0 island-edge goldens on the sphere and bevelled-cube fixtures exact
- [x] 3.5 1:1 bitmap fill copies the source texels exactly; two nodes binding different hashes under the same alias evaluate to their own bytes (LAY-13)

## 4. Acceptance
- [x] 4.1 Tier 0 sets of this child exact in a local DX12 run on the owner's machine (decision 028; the local run report is the evidence); unit tests green — split (q1): the two resample-uv differences are owned by `phase1.9_compositor-resample-gaps`; report `parity/reports/phase1/compositor-sources-projection.md`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
