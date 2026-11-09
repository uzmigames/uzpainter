# Procedural — SourceSubstance presets, image inputs and outputs

## ADDED Requirements

### Requirement: Recorded Preset And Input Semantics
`SourceSubstance.apply_preset`, `get_source`, `set_source`, `reset_source`, `remove_source`, `output_mapping` and `mask_output` SHALL behave as both admitted recordings of the real application show, and MUST NOT be implemented from documentation alone.

#### Scenario: Apply a recorded preset
Given a source on the recorded starter asset with a recorded preset
When `apply_preset` is called with that preset's name
Then `get_parameters` MUST equal the recorded readback in both recordings

#### Scenario: Unrecorded behaviour
Given a call whose outcome no recording observes
When it is made through either API
Then it MUST refuse before any mutation, and the revision MUST stay unchanged
