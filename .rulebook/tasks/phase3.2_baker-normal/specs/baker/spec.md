# Baker — Normal usage

## ADDED Requirements

### Requirement: Tangent-Space Normal Bake
The `Normal` baker SHALL express the high-poly normal in the texturing mesh's MikkTSpace frame under the project's `TangentSpace` mode and encode it per `NormalMapFormat`, using the convention settled by the normal-convention fixture.

#### Scenario: Hemisphere convention fixture
Given the hemisphere fixture and its Painter-baked normal map in the private store
When UzPainter bakes the same fixture with `NormalMapFormat` OpenGL
Then the decoded map MUST equal the Painter map at native precision

### Requirement: Normal Tier 2b Equality
Normal maps MUST equal the Painter CPU goldens on the analytic fixtures and the wand and hat low/high/cage pairs, comparing hit/coverage evidence first; a difference MUST pass only through an owner-approved exception.

#### Scenario: Bevelled cube with highs
Given the bevelled cube low/high pair and its private golden
When the Tier 2b comparison runs on the owner's machine
Then the hit and coverage evidence MUST match first, and the normal map MUST be equal or cite an approved exception

### Requirement: Low Z Is An Inspection Signal
The normal baker MUST NOT replace any texel because of a low or negative normal Z; such texels SHALL be counted and reported.

#### Scenario: Buried face
Given a part whose high-poly normal yields Z < 0 texels
When the bake completes
Then the texels MUST keep their baked values and the count MUST appear in the report
