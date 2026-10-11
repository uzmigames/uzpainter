# Proposal: phase3.5_path-tracer-materials

## Why
VIS-06 requires `painter_iray` to reproduce Painter's Iray output for the same project state under the fixed render pipeline (decision 038). Painter 12.1.5's default shader instance of a new project is `open-pbr` ("Main shader", MDL parameters), not the older default MDL whose help page lists Emissive Intensity, Refraction, Scattering and Absorption (phase0.6 probe panel image `probe:panel/defaults/shader-settings`, SHA-256 `9e934960aaf7b568c4163c6f97245ec7cd6af15e099ca32f11ad3c9b1288a534`; decision 042). Decision 038 pins its parameters at Painter's defaults. CLR-01 limits sources to public literature, the MDL specification and the BSD-3 MDL SDK, with provenance recorded per formula (`docs/prd.md`, decisions 002 and 018). This child of P3-PATHTRACER (`phase3.7_path-tracer`) implements the material model of `docs/architecture/07-preview-and-render-parity.md` §3.1 and §3.3 (D6).

## What Changes
- BSDF of the `open-pbr` default instance written from the MDL specification's distribution functions and the OpenPBR Surface specification: GGX/Trowbridge-Reitz microfacets with height-correlated Smith masking and visible-normal sampling, Schlick or conductor Fresnel at the default IOR 1.5, the base diffuse lobe with diffuse roughness off, emission from the emissive channel scaled by the default Emission Luminance, opacity at the default instance's alpha mode (sources: MDL specification and SDK, OpenPBR Surface, glTF 2.0 PBR appendix, Walter 2007, Heitz 2014 and 2018, Schlick 1994, Burley 2012). Calibration chooses the lobe equations; parameter names do not fix them.
- Coat, fuzz (sheen), transmission, subsurface, thin-film, specular colour, anisotropy and diffuse roughness are disabled in the default instance and pinned off by decision 038. They are not implemented, and a project whose shader enables one fails before rendering with an unsupported-configuration error (decision 042).
- Mapping of the project template's texture-set channels and the `open-pbr` default instance's parameters onto the BSDF; material textures bound bindlessly (descriptor indexing on Vulkan from `phase3.2_vulkan-ray-tracing`, SM 6.6 bindless on DX12). The old default-MDL parameters (Emissive Intensity, Refraction, Scattering, Absorption, Absorption Color) are not in 12.1.5's default shader; the open-pbr parameters replace them at their defaults (IOR 1.5, Emission Luminance 0, every optional feature disabled). Any non-default shader parameter fails before rendering.
- The defaults are read back from Painter's Shader Settings on an OCIO project as hashed private evidence before calibration. The phase0.6 image covers the base, specular, emission and optional-feature sections. It does not show Geometry/Opacity or Displacement & Tessellation, which so far come only from an unhashed Legacy-project dump.
- Normal mapping in the MikkTSpace frame; height→normal per `docs/architecture/04-layer-stack-and-compositing.md` §6; height applied as bump, as the Phase 0 probe measured with the shader at its defaults (`parity/reports/phase0/iray-capture-procedure.md`, row `height`: shading changed, 0 outline pixels changed); displacement pinned to the default instance's value by decision 038, not a variable.
- Variant selection by black-box calibration on the analytic fixtures — constant-parameter spheres sweeping base colour, metallic and roughness; a white-furnace fixture; single-channel perturbations (normal, height, emissive, opacity) with the shader at its defaults — never by inspecting Adobe or Iray code.
- Tunic v10's shader parameter "Double sided" (set by the pipeline, `docs/analysis/assets3d-pipeline/02-painter-usage.md`, hypothesis grade) is an owner scope point (decision 042). The read-back verifies whether it differs from the `open-pbr` default. If it does, `painter_iray` refuses that state, and the Tunic v10 production render stays out of Tier 3 acceptance until the owner amends decision 038 or the fixture.
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
