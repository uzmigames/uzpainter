## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.4_path-tracer-transport

## 2. Implementation
- [ ] 2.1 Implement the GGX/Trowbridge-Reitz specular lobe with height-correlated Smith masking, visible-normal sampling and Schlick/conductor Fresnel
- [ ] 2.2 Implement Lambert and Burley diffuse, coat and sheen lobes and their layering per the MDL specification and OpenPBR
- [ ] 2.3 Implement transmission with absorption (Refraction, IOR, Scattering, Absorption, Absorption Color), emission scaled by Emissive Intensity, and opacity
- [ ] 2.4 Map the template's texture-set channels and default-MDL parameters onto the BSDF with bindless material textures on both backends
- [ ] 2.5 Implement normal mapping in the MikkTSpace frame and height→normal per `04-layer-stack-and-compositing.md` §6, applying height as bump or displacement per the Phase 0 probe
- [ ] 2.6 Calibrate variants black-box on the analytic fixtures; write every formula choice, fitted constant, public source and residual to `parity/semantics/iray.json`
- [ ] 2.7 Record MDL SDK code with its BSD-3 notice in the dependency inventory and `NOTICE`

## 3. Tests
- [ ] 3.1 White-furnace fixture: energy conservation per lobe and for the layered BSDF on DX12 and Vulkan
- [ ] 3.2 Lobe sampling tests: sampled-direction histograms match the evaluated PDF (chi-square) and BSDF reciprocity holds
- [ ] 3.3 Calibration on the owner's machine: constant-parameter spheres (base colour, metallic, roughness sweeps) and single-channel perturbations (normal, height, emissive, opacity) against private Iray references; residuals recorded
- [ ] 3.4 Cross-backend: the same material fixtures on DXR and Vulkan, every difference reported

## 4. Acceptance
- [ ] 4.1 Acceptance: furnace and sampling tests pass on both backends; fits and residuals recorded in `parity/semantics/iray.json` with public sources

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
