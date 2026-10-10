# Baker — Thickness usage

## ADDED Requirements

### Requirement: Thickness Tier 2b Equality
Thickness maps MUST equal the Painter CPU goldens on the analytic fixtures and the wand and hat pairs, comparing hit/coverage evidence first; a difference MUST pass only through an owner-approved exception.

#### Scenario: MaximizeRange enabled
Given the sphere fixture with `MaximizeRange` enabled and its private golden
When the Tier 2b comparison runs on the owner's machine
Then the map MUST equal the golden or cite an approved exception, and the receipt MUST carry the effective range

### Requirement: Thickness Repeatability
The `Thickness` baker MUST produce identical bytes for one build and configuration regardless of thread count.

#### Scenario: Two thread counts
Given the bevelled cube with highs
When it is baked at 1 thread and at all hardware threads
Then both thickness maps MUST be byte-identical
