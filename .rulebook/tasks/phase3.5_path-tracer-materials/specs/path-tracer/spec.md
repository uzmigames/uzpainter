# Path tracer — material model

## ADDED Requirements

### Requirement: Layered BSDF From Public Sources
The path tracer SHALL implement the BSDF of Painter's default `open-pbr` shader instance at its default parameters (GGX with height-correlated Smith masking and visible-normal sampling, Schlick or conductor Fresnel at IOR 1.5, the base diffuse lobe with diffuse roughness off, emission, opacity) written only from the MDL specification, the BSD-3 MDL SDK, OpenPBR, the glTF 2.0 PBR appendix and the cited BRDF papers, and MUST NOT use Iray, the Iray SDK or Painter's shipped material files.

#### Scenario: Provenance of a fitted constant
Given a fitted roughness remapping constant in the material kernels
When `parity/semantics/iray.json` is inspected
Then the constant MUST appear with its public source and its residual

### Requirement: Shader State Limited To The Default Instance
The supported shader state SHALL be the `open-pbr` default instance at Painter's defaults (decision 038). The features that instance disables (coat, fuzz, transmission, subsurface, thin-film, specular colour, anisotropy, diffuse roughness) are pinned off. A project whose shader enables one, or sets any other non-default parameter, MUST fail before rendering with an explicit unsupported-configuration error.

#### Scenario: Coat enabled
Given a project whose shader instance has Coat enabled
When a `painter_iray` capture is requested
Then it MUST fail with an unsupported-configuration error naming decision 038 before any rendering work

### Requirement: Energy Conservation
The BSDF MUST NOT create energy: under a uniform white environment a white, non-emissive material SHALL return at most the incident radiance for every lobe combination.

#### Scenario: White furnace
Given the white-furnace fixture with base colour 1, metallic 0 and roughness swept from 0 to 1
When it is rendered on DX12 and on Vulkan
Then no pixel MUST exceed the environment radiance beyond the measured Monte-Carlo error of the render

### Requirement: Material Fits Recorded
Material variants SHALL be chosen by black-box calibration on the analytic fixtures, and every choice MUST be recorded in `parity/semantics/iray.json` with its residual against the private Iray references.

#### Scenario: Roughness sweep fit
Given the constant-parameter sphere references for a roughness sweep in the private store
When calibration runs on the owner's machine
Then the selected lobe variant and its per-fixture residuals MUST be written to `parity/semantics/iray.json` and no reference pixel MUST be committed
