## MODIFIED Requirements

### Requirement: UV projection and filtering
The `UV` projection's `BilinearHQ` and `BilinearSharp` filters SHALL equal the Tier 0 resampling goldens at every scale, including minification, and MUST NOT be accepted on a residual without an owner-approved exception.

#### Scenario: Bilinear near-tie
Given the 64 x 64 pattern UV-projected at scale 1.37 x 2.11 with `BilinearHQ` and `Repeat`
When the fill is evaluated
Then every value equals the `resample-uv` golden, texel (175, 18) included

#### Scenario: Bilinear minification
Given field A UV-projected at scale 3.3 with `BilinearHQ` or `BilinearSharp`
When the fill is evaluated
Then the channel equals the `resample-uv` golden instead of failing with `evaluator:unsupported_source`
