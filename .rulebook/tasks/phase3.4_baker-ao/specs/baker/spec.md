# Baker — AO usage

## ADDED Requirements

### Requirement: AO Tier 2b Equality
AO maps MUST equal the Painter CPU AO goldens on the analytic fixtures and the wand and hat low/high/cage pairs for the documented AO parameters, comparing hit/coverage evidence first; a difference MUST pass only through an owner-approved exception.

#### Scenario: Ground plane enabled
Given the sphere fixture with `GroundPlane` enabled and its private golden
When the Tier 2b comparison runs on the owner's machine
Then the AO map MUST be equal or cite an approved exception

### Requirement: AO Miss Evidence
The AO baker SHALL report misses from hit evidence, distinct from real holes, hidden surfaces and low AO, and an optional wider second pass MUST change only missed texels.

#### Scenario: Second pass scope
Given a bake with misses and the second pass enabled
When the bake completes
Then only texels classified as `miss` in the first pass MUST differ from a bake without the second pass, and the receipt MUST record that the pass ran
