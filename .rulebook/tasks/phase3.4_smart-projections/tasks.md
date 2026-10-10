## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.3_procedural-families

## 2. Implementation
- [ ] 2.1 Extend the fill projection model with `Triplanar`, `Planar`, `Spherical` and `Cylindrical` parameters and symmetry `{enabled, params}` as documented for fill projections; reject `Warp` and `UVSetToUVSet` with a capability error
- [ ] 2.2 Record the Tier 0 projection goldens not already in the corpus through the UzmiGames recorder (each twice; blobs private, hashes in `parity/manifests/`)
- [ ] 2.3 Fit the projection semantics (triplanar blend weights and hardness, `projection_3d.scale` units, culling, crop) from the goldens; record formulas, sources and residuals in `parity/semantics/projections.json`
- [ ] 2.4 Implement the `Triplanar` kernel with normal-weighted blending and hardness from the UV raster's position and normal maps
- [ ] 2.5 Implement the `Planar`, `Spherical` and `Cylindrical` kernels with culling, crop and 3D transform
- [ ] 2.6 Implement mirror and radial symmetry for the 3D projections
- [ ] 2.7 Implement `MaterialPhysicalSize` and `CustomPhysicalSize` with the mesh `units {source, scale_to_internal}` rule; write the effective projection scale into evaluation and export receipts
- [ ] 2.8 Expose projection and symmetry through the facade fill API, the `uzpainter` API and the MCP `fill_set` tool, with set→get readback matching the documented types
- [ ] 2.9 Update the capability manifest: 3D projections and symmetry with their Tier 0 evidence; `Warp` and `UVSetToUVSet` as release gaps

## 3. Tests
- [ ] 3.1 Tier 0 triplanar goldens (hardness and scale sweeps, rotated 3D transforms) on plane, sphere and bevelled cube: exact
- [ ] 3.2 Tier 0 planar, spherical and cylindrical goldens (culling, crop, transforms): exact
- [ ] 3.3 Tier 0 mirror and radial symmetry goldens: exact
- [ ] 3.4 Tier 0 physical-size goldens on meshes with different source units: exact, effective scale present in the receipt
- [ ] 3.5 API probes: projection and symmetry set→get readback exact; `Warp`/`UVSetToUVSet` requests return the capability error without mutation
- [ ] 3.6 Repeatability: each projection kernel produces identical bytes across two runs

## 4. Acceptance
- [ ] 4.1 Acceptance: Tier 0 projection goldens exact or covered by owner-approved exceptions; warp and UV-set projections listed as gaps

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
