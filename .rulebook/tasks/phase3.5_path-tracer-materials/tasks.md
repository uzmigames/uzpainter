## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.4_path-tracer-transport

## 2. Implementation
- [ ] 2.1 Implement the GGX/Trowbridge-Reitz specular lobe with height-correlated Smith masking, visible-normal sampling and Schlick/conductor Fresnel
- [ ] 2.2 Implement the `open-pbr` base diffuse lobe with diffuse roughness off (Lambert or Burley chosen by calibration) and its layering under the specular lobe per the MDL specification and OpenPBR; coat and fuzz (sheen) pinned off by decision 038, and a shader enabling them fails before rendering
- [ ] 2.3 Transmission, subsurface and thin-film pinned off by decision 038 (each disabled in the `open-pbr` default instance; a shader enabling one fails before rendering); IOR pinned to 1.5; implement emission from the emissive channel scaled by Emission Luminance at its default, and opacity at the default instance's alpha mode
- [ ] 2.4 Read back the `open-pbr` default instance's parameters on an OCIO project as hashed private evidence (including Geometry/Opacity and Displacement & Tessellation, which the phase0.6 image lacks) and Tunic v10's "Double sided" value; map the template's texture-set channels and those parameters onto the BSDF with bindless material textures on both backends; any non-default parameter fails before rendering (decision 042)
- [ ] 2.5 Implement normal mapping in the MikkTSpace frame and height→normal per `04-layer-stack-and-compositing.md` §6, applying height as bump per the Phase 0 probe (row `height`); displacement pinned to the default instance's value by decision 038
- [ ] 2.6 Calibrate variants black-box on the analytic fixtures; write every formula choice, fitted constant, public source and residual to `parity/semantics/iray.json`
- [ ] 2.7 Record MDL SDK code with its BSD-3 notice in the dependency inventory and `NOTICE`

## 3. Tests
- [ ] 3.1 White-furnace fixture: energy conservation per lobe and for the layered BSDF on DX12 and Vulkan
- [ ] 3.2 Lobe sampling tests: sampled-direction histograms match the evaluated PDF (chi-square) and BSDF reciprocity holds
- [ ] 3.3 Calibration on the owner's machine: constant-parameter spheres (base colour, metallic, roughness sweeps) and single-channel perturbations (normal, height, emissive, opacity) against private Iray references under the fixed pipeline with the shader at its `open-pbr` defaults; residuals recorded
- [ ] 3.4 Cross-backend: the same material fixtures on DXR and Vulkan, every difference reported
- [ ] 3.5 Unsupported shader state: a project whose shader enables coat, fuzz, transmission, subsurface, thin-film, specular colour, anisotropy or diffuse roughness, or sets any other non-default parameter, fails before rendering with an error naming decision 038

## 4. Acceptance
- [ ] 4.1 Acceptance: furnace and sampling tests pass on both backends; fits and residuals recorded in `parity/semantics/iray.json` with public sources

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
