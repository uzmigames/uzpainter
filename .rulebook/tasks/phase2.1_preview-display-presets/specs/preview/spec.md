## ADDED Requirements

### Requirement: Serialisable Display Presets
A display preset SHALL be serialisable data holding environment identity and parameters, background, ground, display configuration, cameras, samples and seed, and MUST round-trip without loss.

#### Scenario: ref_match round trip
Given the `ref_match` preset
When it is serialised, loaded into a new project and serialised again
Then both serialisations are identical and match the pipeline standard's values

### Requirement: Environments Identified By Content
Environments SHALL be stored as bytes plus SHA-256, and a preset naming a missing environment MUST fail explicitly without substitution.

#### Scenario: Missing environment
Given a preset naming an environment hash absent from the project
When the preset is applied
Then the call fails with an explicit missing-resource error and the display state is unchanged

### Requirement: Cameras Convert To The Blender Convention
Cameras SHALL be importable and exportable in the Blender convention defined by the pipeline's coordinate contract.

#### Scenario: Camera round trip
Given a camera exported in the Blender convention
When it is imported and exported again
Then position, rotation and lens values are unchanged
