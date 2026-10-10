## ADDED Requirements

### Requirement: Thirty-two documented blend modes
The evaluator SHALL implement all 32 documented `BlendingMode` members per channel with per-channel opacity, each equal to its Tier 0 goldens at native decoded values.

#### Scenario: Overlay sweep
Given two uniform fills swept over values and opacities with `Overlay`
When each case is evaluated and compared with its 16-bit golden
Then every case is equal

### Requirement: No accepted mode without exact evidence
A blend mode whose fit does not reproduce its goldens exactly MUST remain `release-gap` in the capability manifest, and SHALL pass only through an owner-approved exception with evidence.

#### Scenario: Inexact fit
Given a mode whose fitted kernel differs from one golden case
When the capability manifest is generated
Then the mode is listed as `release-gap` and is not reported `supported`
