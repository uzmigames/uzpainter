## MODIFIED Requirements

### Requirement: Component and normal-map blend modes
The evaluator SHALL reproduce `Tint`, `Saturation`, `Color` and `Value` on colour channels, and `NormalMapCombine`, `NormalMapDetail` and `NormalMapInverseDetail` at every opacity, equal to their Tier 0 goldens at native decoded values. A mode not yet exact MUST stay `release-gap` and MUST NOT be accepted on a residual without an owner-approved exception.

#### Scenario: Saturation over a nearly grey hue source
Given field B over field A in `Saturation` on an RGB16 channel at opacity 1
When the channel is evaluated
Then every value equals the `blend-component` s1 golden

#### Scenario: Normal-map mode below opacity 1
Given field B over field A in `NormalMapDetail` on an RGB16 channel at opacity 0.5
When the channel is evaluated
Then every value equals the `blend-component` s5 golden

### Requirement: PassThrough groups
A `PassThrough` group SHALL composite as Painter does, evidenced by a Tier 0 golden recorded through Painter's documented API, or be recorded `not_migratable` by an owner scope decision.

#### Scenario: PassThrough group
Given a group in `PassThrough` holding two layers over a backdrop
When the stack is evaluated
Then the result equals its golden, or the mode is reported `release-gap`
