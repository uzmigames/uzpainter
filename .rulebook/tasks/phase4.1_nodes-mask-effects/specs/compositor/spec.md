## ADDED Requirements

### Requirement: Compare Mask Equal to Painter
The `compare_mask` effect SHALL evaluate its documented parameters as a mono-channel mask effect with its own mode and opacity, with output equal to the Tier 0 goldens.

#### Scenario: Compare mask sweep
Given a layer whose mask stack holds a fill effect followed by a compare-mask effect with a recorded parameter set
When the masked channel is exported at 16 bit
Then the decoded values equal the private Painter golden exactly

### Requirement: Colour Selection Equal to Painter
The `color_selection` effect SHALL select from the inputs its documented parameters name with output equal to the Tier 0 goldens, and MUST fail evaluation explicitly when a required mesh-map binding is missing or invalid.

#### Scenario: Selection on an authored ID map
Given an authored ID mesh map bound to the texture set and a colour-selection effect picking two recorded colours
When the masked channel is exported at 16 bit
Then the decoded values equal the private Painter golden exactly

#### Scenario: Missing ID map
Given a texture set with no ID mesh-map binding
When a stack with a colour-selection effect is evaluated
Then evaluation fails with an explicit missing-input error and nothing is exported

### Requirement: Mask-Stack-Only Insertion
Compare-mask and colour-selection effects MUST be insertable only into mask stacks; any other insertion SHALL raise the documented error before mutation.

#### Scenario: Insertion into a content stack
Given a fill layer's content stack
When an agent inserts a compare-mask effect there
Then the call raises the documented error and the project revision is unchanged
