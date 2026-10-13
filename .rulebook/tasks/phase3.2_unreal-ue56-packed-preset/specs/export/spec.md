## ADDED Requirements

### Requirement: Unreal Engine Packed Layout
The Unreal Engine (Packed) preset SHALL write BaseColor with opacity in alpha, OcclusionRoughnessMetallic with R = `AO_Mixed`, G = roughness and B = metallic in linear encoding, Normal as `Normal_DirectX`, and Emissive, and SHALL ship only once its provenance record confirms this layout.

#### Scenario: ORM channels packed as specified
Given wand v1 with AO, roughness and metallic content
When it is exported with the Unreal Engine (Packed) preset
Then `_OcclusionRoughnessMetallic` holds `AO_Mixed` in R, roughness in G and metallic in B, linear, and equals Painter's export of the same preset in decoded values

### Requirement: Unreal Encodings
The preset MUST encode PNG or TGA 8-bit by default and SHALL offer a DDS variant with BC7 for BaseColor, ORM and Emissive and BC5 for Normal.

#### Scenario: DDS variant imports in UE 5.6
Given wand v1 exported with the DDS variant
When the UE 5.6 import fixture imports the published generation
Then all four maps import with BaseColor and Emissive as sRGB, ORM as linear and Normal as a DirectX normal map

### Requirement: Unreal Preset Provenance Without Adobe Content
The preset MUST be authored by hand from documented semantics with a provenance record, and MUST NOT be generated from a serialised Painter readback or contain Adobe preset files or text.

#### Scenario: Provenance names sources and private hashes only
Given the shipped preset
When the reviewer and the local CPU-lane schema check (decision 200) inspect `unreal-engine-packed.provenance.json`
Then it lists public sources and SHA-256 values of private observations, and no readback content is present in the repository

### Requirement: UE 5.6 Fixed-Name Consumption Is Atomic
The UE 5.6 fixture SHALL consume one complete published generation through the generation-pinning delivery adapter or the publication lock.

#### Scenario: Interrupted fixed-name copy
Given a fixed-name copy interrupted after the first file
When the UE 5.6 import is invoked immediately through its adapter
Then it imports one complete generation or fails before consuming any file
