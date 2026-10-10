## ADDED Requirements

### Requirement: Height to normal reproduced
The height→normal conversion SHALL reproduce both Painter methods and the strength scaling exactly as fitted from the Tier 0 height ramps.

#### Scenario: Strength sweep
Given a height ramp evaluated at several strength values with each method
When the derived normal is computed
Then every case equals its Tier 0 golden

### Requirement: Relief applied exactly once
Combined normals SHALL be tagged `combined` with their relief round and the geometry-only pass-through SHALL be tagged `geometry_only`, so that relief MUST never be applied twice downstream.

#### Scenario: Combined normal export source
Given a stack with Height content and an imported mesh normal map
When the `Normal_OpenGL` source is evaluated
Then it equals the Tier 0 golden and carries the tag `combined` with the relief round
