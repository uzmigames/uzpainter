# Proposal: phase3.5_path-tracer-materials

## Why
VIS-06 requires `painter_iray` to reproduce Painter's Iray output for the same project state, and Painter's default Iray material is described publicly only as an MDL compatible with PBR Metallic/Roughness plus a few documented parameters; CLR-01 limits sources to public literature, the MDL specification and the BSD-3 MDL SDK, with provenance recorded per formula (`docs/prd.md`, decisions 002 and 018). This child of P3-PATHTRACER (`phase3.7_path-tracer`) implements the material model of `docs/architecture/07-preview-and-render-parity.md` §3.1 and §3.3 (D6).

## What Changes
- Layered BSDF written from the MDL specification's distribution functions and OpenPBR lobes: GGX/Trowbridge-Reitz microfacets with height-correlated Smith masking and visible-normal sampling, Schlick or conductor Fresnel, Lambert or Burley diffuse, coat, sheen, transmission with absorption for Refraction/Scattering/Absorption, emission scaled by Emissive Intensity, opacity (sources: MDL specification and SDK, OpenPBR Surface, glTF 2.0 PBR appendix, Walter 2007, Heitz 2014 and 2018, Schlick 1994, Burley 2012).
- Mapping of the project template's texture-set channels and the default-MDL parameters (Emissive Intensity, Refraction, IOR, Scattering, Absorption, Absorption Color) onto the BSDF; material textures bound bindlessly (descriptor indexing on Vulkan from `phase3.2_vulkan-ray-tracing`, SM 6.6 bindless on DX12).
- Normal mapping in the MikkTSpace frame; height→normal per `docs/architecture/04-layer-stack-and-compositing.md` §6; bump versus displacement per the Phase 0 probe result.
- Variant selection by black-box calibration on the analytic fixtures — constant-parameter spheres sweeping base colour, metallic and roughness; a white-furnace fixture; single-channel perturbations (normal, height, emissive, opacity) — never by inspecting Adobe or Iray code.
- Every formula choice and fitted constant recorded in `parity/semantics/iray.json` with its public source and residual; MDL SDK code keeps its BSD-3 notice and is listed in the dependency inventory and `NOTICE`.

## Dependencies
- Prerequisites: `phase3.4_path-tracer-transport`.
- Parent: `phase3.7_path-tracer`. Unblocks `phase3.6_path-tracer-tier3-report`.

## Acceptance
White-furnace energy conservation and lobe sampling/PDF consistency pass on both backends; calibration fits against the private analytic Iray references are recorded with residuals in `parity/semantics/iray.json`; the same material kernels run on DXR and Vulkan with every output difference reported.

## Impact
- Affected specs: path-tracer
- Affected code: path-tracer BSDF and material-binding kernels, `parity/semantics/iray.json`, dependency inventory and `NOTICE`
- Breaking change: NO
- User benefit: physically based materials whose every formula has a public source and a measured residual
