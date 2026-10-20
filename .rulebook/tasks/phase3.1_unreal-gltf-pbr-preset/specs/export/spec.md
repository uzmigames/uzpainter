## ADDED Requirements

### Requirement: glTF Metallic-Roughness Packing
The glTF PBR Metal Roughness preset SHALL pack and encode its outputs as the glTF 2.0 metallic-roughness material specifies, and each packing decision MUST cite that specification in the provenance record.

#### Scenario: Packing confirmed by the consumer
Given wand v1 exported with the glTF PBR Metal Roughness preset
When the glTF consumer fixture assembles and loads the test asset
Then base colour, metallic-roughness, normal, occlusion and emissive textures bind to their glTF slots with the specified channels and colour spaces

### Requirement: glTF Preset Output Parity
The preset's files SHALL equal Painter's export of its `glTF PBR Metal Roughness` preset on the same project in decoded values, unless an owner-approved exception covers the difference.

#### Scenario: Equal to the private observation
Given belt v5 rebuilt in both tools
When both export with the glTF preset and the decoded files are compared at native depth
Then every file is equal, or the comparison fails and the preset is not shipped

### Requirement: Recorded glTF Consumer
The glTF consumer fixture MUST record the consumer it uses (validator and loader identities and versions) in its manifest.

#### Scenario: Consumer identity in the manifest
Given the fixture manifest `parity/manifests/consumers/gltf/wand-v1.json`
When the fixture runs
Then the report names the consumer identities and versions taken from the manifest

### Requirement: Pinned Consumer Input and Independent Packing Check
The fixture runner SHALL read one publication pointer and verify the receipt and all
published file hashes and sizes before consuming that generation. It SHALL copy the
five selected PNGs without changing their bytes and use the recorded fastgltf loader
and structural validator. The runner MUST compare metallic-roughness G/B at native
depth against independently pinned roughness and metallic PNG references.

#### Scenario: Swapped channels with consistent publication hashes
Given a published metallic-roughness PNG whose G/B channels have been swapped and whose
receipt and pointer have been updated to match those bytes
When the consumer fixture compares the PNG with the independent references
Then it fails the packing check and produces no passing report

#### Scenario: Authored fixture is not pilot acceptance
Given an authored CPU fixture that validates and loads through fastgltf
When its successful report is written
Then the report describes structural validation and bindings only, and the Wand
manifest remains pending until the real pilot and R-314 comparisons pass
