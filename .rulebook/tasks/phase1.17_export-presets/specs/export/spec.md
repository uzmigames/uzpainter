## ADDED Requirements

### Requirement: Clean-room presets with provenance
Every shipped export preset SHALL be hand-written from documented export semantics and observed behaviour, MUST carry a complete provenance record, and SHALL NOT be generated from a readback or an Adobe preset file.

#### Scenario: Preset without provenance
Given a preset JSON in `assets/export-presets/` without its `.provenance.json`
When the preset tests run
Then the build fails naming the preset

### Requirement: Preset output parity
A preset MUST pass its output-parity test against the private oracle records before it ships.

#### Scenario: Blender preset
Given the UzmiGames fixture project and Painter's recorded output for `Blender (Principled BSDF)`
When UzPainter exports the same project with the shipped preset
Then every file name and decoded map equals the recorded output
