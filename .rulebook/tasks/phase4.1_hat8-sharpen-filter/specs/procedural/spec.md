## ADDED Requirements

### Requirement: Sharpen Filter Effect In Mask Stacks
UzPainter SHALL evaluate the certified Sharpen family as a mono-channel filter effect in mask stacks, in effect-list order, blended with its own mode and opacity, and MUST reject a channel argument for mask-stack blending with `ValueError` as documented.

#### Scenario: Sharpen over a levels mask
Given a mask stack with a white background, a bitmap fill effect, a levels effect and a sharpen filter on top
When the mask is evaluated
Then sharpen reads the value produced by the levels effect and the exported mask equals the private Tier 0 golden

#### Scenario: Channel argument rejected in mask context
Given a sharpen filter effect in a mask stack
When its blending mode is set with a channel argument
Then the call raises `ValueError` and the stack is unchanged

### Requirement: Sharpen Tier 0 Mask Goldens
The Tier 0 corpus SHALL include sharpen mask goldens over a parameter, mode and opacity sweep on the synthetic meshes, and UzPainter MUST reproduce them exactly or through an owner-approved exception.

#### Scenario: Sweep exact
Given the recorded sharpen mask goldens
When UzPainter evaluates the same fixtures
Then every decoded mask equals its golden at native depth

### Requirement: Hat v8 Sharpen Instances Equal
Every Sharpen instance in the hat v8 recipe SHALL evaluate equal to Painter with its recorded parameters, in content and mask contexts.

#### Scenario: Recorded parameter set
Given a hat v8 Sharpen instance with its recorded parameters
When it is evaluated on the hat v8 mesh maps and content
Then its output equals the private golden for that instance
