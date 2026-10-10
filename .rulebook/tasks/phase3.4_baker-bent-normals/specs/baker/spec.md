# Baker — BentNormals usage

## ADDED Requirements

### Requirement: Bent Normals Tier 2b Equality
Bent-normal maps MUST equal the Painter CPU goldens on the analytic fixtures and the wand and hat pairs, comparing hit/coverage evidence first; a difference MUST pass only through an owner-approved exception.

#### Scenario: Bevelled cube with highs
Given the bevelled cube with highs and its private `BentNormals` golden
When the Tier 2b comparison runs on the owner's machine
Then the map MUST equal the golden or cite an approved exception, with angular max/mean reported

### Requirement: Bent Normals Repeatability
The `BentNormals` baker MUST produce identical bytes for one build and configuration regardless of thread count.

#### Scenario: Two thread counts
Given the sphere fixture
When it is baked at 1 thread and at all hardware threads
Then both bent-normal maps MUST be byte-identical
