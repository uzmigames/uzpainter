## ADDED Requirements

### Requirement: Serialisable Display Presets
A display preset SHALL be serialisable data holding environment identity and parameters, background, ground, display configuration, cameras, samples and seed, and MUST round-trip without loss.

#### Scenario: ref_match round trip
Given the `ref_match` preset
When it is serialised, loaded into a new project and serialised again
Then both serialisations are identical and match the pipeline standard's values

### Requirement: Display State Limited To The Fixed Pipeline
Display state SHALL support only the fixed render pipeline of decision 038: the display configuration MUST be OCIO with Painter's substance config and the view `Default - sRGB`, the colour LUT MUST be none, shader parameters MUST be those of the default `open-pbr` instance, and a value outside the pipeline MUST fail with an explicit unsupported-value error naming decision 038, never be stored or ignored silently. The documented `substance_painter.display` symbols SHALL remain available (decision 042).

#### Scenario: Tone mapping on a colour-managed project
Given a project created with OCIO colour management
When `substance_painter.display.set_tone_mapping` is called
Then it raises `RuntimeError` as Painter documents and the display state is unchanged

#### Scenario: Value outside the fixed pipeline
Given a project under the common comparison standard
When a script sets the environment exposure to 1.0 or a colour LUT resource
Then the call fails with an unsupported-value error naming the setting, the accepted values and decision 038, and the display state is unchanged

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
