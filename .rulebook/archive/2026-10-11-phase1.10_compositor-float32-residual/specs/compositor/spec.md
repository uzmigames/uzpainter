## MODIFIED Requirements

### Requirement: 32-bit float quantisation of partly covered stacks
The evaluator SHALL reproduce Painter's same-session recording r1 exactly on RGB32F and L32F channels of a partly covered root stack, and a residual against r1 MUST NOT be counted as a pass (decision 032).

#### Scenario: Three one-third fills on 32-bit float channels
Given three uniform fills at opacity 1/3 in `Normal` on an RGB32F and an L32F channel (`quantisation-thirds` s0-s3)
When the stack is evaluated under the current profile
Then every value equals r1 on the CPU and on the GPU

#### Scenario: Earlier profile unchanged
Given a project stamped `painter-12.1-isolated-linear`
When it is evaluated after the new profile is registered
Then its results are unchanged bit for bit
