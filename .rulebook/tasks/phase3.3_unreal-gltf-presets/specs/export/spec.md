## ADDED Requirements

### Requirement: Unreal And glTF Presets Integration Acceptance
The Unreal and glTF preset work MUST close only when both child tasks are accepted, the UE 5.6 and glTF consumer fixtures load the outputs, and the channel packing of each preset is confirmed.

#### Scenario: Both fixtures load wand v1
Given wand v1 exported with the Unreal Engine (Packed) preset and the glTF PBR Metal Roughness preset
When the UE 5.6 import fixture and the glTF consumer fixture run
Then both import without error and each map is bound with its specified channel packing and colour space

### Requirement: Preset Output Parity Before Shipping
Each shipped Unreal or glTF preset SHALL produce files whose decoded values equal Painter's output for the same preset on the same project, unless an owner-approved exception covers the difference.

#### Scenario: Unapproved difference blocks the preset
Given the tunic v10 ORM map exported by UzPainter differs in one texel from Painter's export of the same preset
When the output-parity comparison runs with no matching entry in `parity/exceptions.json`
Then the preset fails its parity test and is not shipped

### Requirement: Unreal And glTF Consumer Gaps Reported
Each Unreal or glTF export SHALL report every channel the consumer cannot bind, including SpecularWeight, as a consumer gap and MUST NOT compensate for it in the exported maps.

#### Scenario: SpecularWeight in a UE export
Given a texture set with a SpecularWeight channel
When it is exported with the Unreal Engine (Packed) preset
Then `_SpecularWeight` is written as a separate map and the receipt lists it as a consumer gap
