## ADDED Requirements

### Requirement: Measured quantisation profile
The evaluator SHALL quantise each channel's accumulator at the points and in the colour space selected by the Tier 0 experiment, with fp32 intermediates and no FP16 substitute for 16-bit storage.

#### Scenario: Three 1/3-opacity fills
Given a stack of three uniform fills at 1/3 opacity on an `L16` channel
When it is evaluated
Then the result equals the Tier 0 golden exactly

### Requirement: Versioned evaluator profile
Every project and golden SHALL record its `evaluator_profile`, and a project MUST be evaluated with the profile it records.

#### Scenario: New profile registered
Given a project recorded with profile `painter-12.1-a`
When a profile `painter-12.1-b` is added to the build
Then the project still evaluates with `painter-12.1-a` and its exports are unchanged
