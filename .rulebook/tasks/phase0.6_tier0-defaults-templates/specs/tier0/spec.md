## ADDED Requirements

### Requirement: Baking defaults captured through the documented API
The Tier 0 corpus MUST capture, on a fresh Painter 12.1.0 project, every key of `BakingParameters.common()` and of `baker(usage)` for the ten `MeshMapUsage` bakers with its value, name, short name, label, widget type, enum values, enum value and nested properties, using only the documented Python API.

#### Scenario: Every key captured
Given a fresh Painter 12.1.0 project
When the defaults instruction sequence runs
Then the capture holds an entry for every key returned by `common().keys()` and by `baker(usage).keys()` for all ten usages

#### Scenario: Enum integers not guessed
Given a key whose widget type is an enumeration
When it is captured
Then the capture records the labels from `enum_values()` together with the current `enum_value`

### Requirement: Template channel sets and formats captured
For each project template shipped with Painter 12.1.0 that the documented project-creation API accepts, the corpus MUST capture every stack's channel set and each channel's `ChannelFormat` read back through the documented `textureset` API.

#### Scenario: Template observed
Given a shipped template selectable through the documented API
When a project is created from it on a synthetic mesh
Then the capture lists each channel of each stack with its `ChannelFormat`

### Requirement: Captures private and recorded twice
Each capture SHALL be recorded at least twice and stored only in the private store; the public manifest MUST hold only instruction sequences, template identifiers, the Painter build id and SHA-256 hashes.

#### Scenario: Captured table not published
Given the recorded defaults capture
When it is staged for commit in the repository
Then the repository guard rejects it, and the manifest carries only its hash
