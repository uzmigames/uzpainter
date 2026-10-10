## ADDED Requirements

### Requirement: Mono-channel mask stacks
A layer or group mask SHALL start from its background value and apply its effects in order, each with its own mode and opacity; a disabled mask MUST count as 1 and a `Mesh` geometry mask SHALL multiply the result.

#### Scenario: Fill effect then subtraction
Given a white-background mask with a bitmap fill effect and a subtracting fill effect
When the masked layer is evaluated
Then the channel values equal the Tier 0 golden

### Requirement: Ordered content effects
Content effects SHALL run in list order on the layer's own content, with the fill effect blending its source by its own mode and opacity and levels remapping the affected channel as the Tier 0 goldens show.

#### Scenario: Levels after fill effect
Given a fill layer with a fill effect followed by a levels effect
When it is evaluated
Then the result equals the Tier 0 content-effect-order golden

### Requirement: Defined base under complementary masks
Two layers under complementary masks MUST produce the defined base value with no unintended default bleed, equal to the Tier 0 base-value goldens.

#### Scenario: Complementary masks
Given two fills whose masks sum to one everywhere
When the stack is evaluated
Then every texel equals the golden and no template default shows through
