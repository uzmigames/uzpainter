# Baker — Opacity usage

## ADDED Requirements

### Requirement: Opacity Tier 2b Equality
Opacity maps MUST equal the Painter CPU goldens on the analytic fixtures and the wand and hat pairs with exact alpha equality and matching edge coverage, comparing hit/coverage evidence first; a difference MUST pass only through an owner-approved exception.

#### Scenario: Plane fixture
Given the plane fixture with a high-poly mesh and its private `Opacity` golden
When the Tier 2b comparison runs on the owner's machine
Then every alpha value MUST equal the golden or the map MUST cite an approved exception

### Requirement: Opacity Repeatability
The `Opacity` baker MUST produce identical bytes for one build and configuration regardless of thread count.

#### Scenario: Two thread counts
Given the bevelled cube with highs
When it is baked at 1 thread and at all hardware threads
Then both opacity maps MUST be byte-identical
