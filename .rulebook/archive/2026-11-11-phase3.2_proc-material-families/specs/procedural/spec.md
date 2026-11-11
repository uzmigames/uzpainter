# Procedural — material family

## ADDED Requirements

### Requirement: Material Family Tier 2a
Every output of felt, leather grain, burlap and leather pattern MUST equal its Painter oracle over the Tier 2a certification matrix or be covered by an owner-approved exception; otherwise the material MUST be listed as a release gap.

#### Scenario: Leather grain height output
Given leather grain with the parameter set recorded in the locked bracer recipe
When its height output is evaluated on the bevelled cube at 2048 with the recorded seed
Then the output MUST equal the private Painter oracle or cite an approved exception

### Requirement: Material Physical Size
Materials SHALL evaluate at their physical size through `MaterialPhysicalSize` or `CustomPhysicalSize` under the project unit rule, and the effective units MUST be recorded.

#### Scenario: Unit scale change
Given the same felt material applied to a mesh authored in centimetres and the same mesh in metres
When both are evaluated
Then each output MUST equal its oracle and the recorded effective units MUST differ accordingly
