# Baker — WorldSpaceNormal usage

## ADDED Requirements

### Requirement: World-Space Normal Tier 2b Equality
World-space normal maps MUST equal the Painter CPU goldens on the analytic fixtures and the wand and hat low/high/cage pairs, comparing hit/coverage evidence first; a difference MUST pass only through an owner-approved exception.

#### Scenario: Sphere fixture
Given the sphere fixture and its private `WorldSpaceNormal` golden
When the Tier 2b comparison runs on the owner's machine
Then the decoded map MUST equal the golden at native precision or cite an approved exception

### Requirement: World-Space Normal Repeatability
The `WorldSpaceNormal` baker MUST produce identical bytes for one build and configuration regardless of thread count.

#### Scenario: Two thread counts
Given the bevelled cube with highs
When it is baked at 1 thread and at all hardware threads
Then both maps MUST be byte-identical
