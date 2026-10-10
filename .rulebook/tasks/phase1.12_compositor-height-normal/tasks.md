## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.8_tier0-goldens, phase1.7_mesh-loader, phase1.10_compositor-blend-kernels, phase1.11_compositor-mask-effects

## 2. Implementation
- [ ] 2.1 Implement the signed Height channel in its template storage format
- [ ] 2.2 Fit both height→normal methods (footprint, scaling, edge handling, strength) to the Tier 0 ramps and implement the kernel
- [ ] 2.3 Fit and implement the normal-combination operator and the OpenGL/DirectX conversion
- [ ] 2.4 Expose `Normal_OpenGL`/`Normal_DirectX` sources tagged `combined` with the relief round and the geometry-only pass-through tagged `geometry_only`
- [ ] 2.5 Publish `parity/semantics/height-to-normal.json`

## 3. Tests
- [ ] 3.1 Tier 0 height goldens (`SignedAddition`, `LinearDodge` on Height) exact
- [ ] 3.2 Tier 0 height→normal goldens for both methods across the strength sweep exact
- [ ] 3.3 Tier 0 normal-blend goldens (mesh normal ⊕ channel normal ⊕ height normal, both conventions) exact
- [ ] 3.4 Tagging test: a combined normal carries `combined` and its relief round; the geometry-only pass-through carries `geometry_only` (EXP-09)

## 4. Acceptance
- [ ] 4.1 Tier 0 sets of this child exact on the self-hosted GPU runner (DX12); unit tests green

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
