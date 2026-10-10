## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.9_render-reference-capture, phase1.4_render-core-layer, phase2.10_pilot-tunic-recovery, phase3.3_vulkan-backend-ray-tracing

## 2. Implementation
- [ ] 2.1 Confirm Kajiya 1986, Veach 1997, PBRT 4th ed. and Burley 2020 are entries of the approved-source index; cite the entry for each transport formula in code comments and in `parity/semantics/iray.json`
- [ ] 2.2 Implement the path-tracer host: feature detection at startup and in `selftest`, `PathTracerUnavailable{backend, missing}` before any work, no fallback to `painter_viewport` or a software path
- [ ] 2.3 Build scene acceleration structures through the backend-neutral builder: one BLAS per texture-set mesh rebuilt only on geometry change, one TLAS per scene
- [ ] 2.4 Implement Owen-scrambled Sobol sampling indexed by (pixel, sample, dimension) under a fixed seed
- [ ] 2.5 Implement the camera from Painter's documented model (position, Euler rotation, projection type, field of view, focal length, orthographic height, focus distance, aperture) in Y-up scene space with the VIS-05 coordinate conversions
- [ ] 2.6 Implement environment lighting from the display preset (environment by SHA-256, exposure, rotation, dome) with importance sampling from a piecewise-constant 2D distribution; a missing environment is an explicit error
- [ ] 2.7 Implement the transport kernel (inline ray queries, one HLSL for DXIL and SPIR-V): next-event estimation, MIS between BSDF and environment sampling, Russian roulette after a fixed minimum depth, maximum depth from the Phase 0 fit, RGB fp32, per-pixel fixed-order accumulation without floating-point atomics
- [ ] 2.8 Implement the Lambert transport-verification lobe behind the BSDF interface the layered material model will implement
- [ ] 2.9 Implement the display transform: Legacy `Linear` (IEC 61966-2-1, values above 1 clamped) and `ACES` (public Academy transforms), OCIO through OpenColorIO with the pinned config and recorded view; unsupported configurations (incl. ACE mode until qualified) fail before rendering
- [ ] 2.10 Implement `display.capture(mode=painter_iray, …)`: wait for the current revision and uploads, offscreen RGBA32F accumulation of exactly `samples` samples, display transform, `TextureReadback`, PNG plus linear EXR, full receipt
- [ ] 2.11 Record transport parameters (minimum depth, maximum depth, sampler, seed handling) with their public sources in `parity/semantics/iray.json`
- [ ] 2.12 Update the capability manifest: `painter_iray` per backend from the feature detection, replacing the Phase 2 unavailable entry

## 3. Tests
- [ ] 3.1 White-furnace fixture with the Lambert lobe under a constant environment: mean signed error against the analytic value consistent with zero given its standard error, at two sample counts, on both backends
- [ ] 3.2 Environment importance-sampling fixture (single bright patch): MIS estimate unbiased against the analytic irradiance; sampling PDF matches the distribution
- [ ] 3.3 Sobol/Owen sampler tests against independently authored expectations (stratification per dimension, seed changes the sequence, same seed reproduces it)
- [ ] 3.4 Repeatability: same build, adapter, driver, seed and sample count rendered twice on each backend; bytes compared and the result reported, not assumed
- [ ] 3.5 Cross-backend run of the transport fixtures on DXR and Vulkan; every difference recorded for the cross-backend report
- [ ] 3.6 `PathTracerUnavailable` test with a missing ray-query feature: error before any work, no capture written, no fallback
- [ ] 3.7 Capture tests: headless with no window, exactly `samples` samples, receipt fields complete, missing environment fails, unsupported display configuration fails before rendering
- [ ] 3.8 Camera tests: documented camera parameters set and read back produce the expected silhouette of the analytic sphere and bevelled cube

## 4. Acceptance
- [ ] 4.1 Acceptance: `painter_iray` captures on DX12 and Vulkan with identical kernels; transport fixtures unbiased; repeatability measured; cross-backend differences reported; unavailable features reported before work

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
