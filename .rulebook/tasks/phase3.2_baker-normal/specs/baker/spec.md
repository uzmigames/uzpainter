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

### Requirement: Native Normal Request Boundary
The native CPU Normal calculation SHALL retain MikkTSpace tangents per corner before material partitioning, use the existing inverse-frame transform, and encode RGB16 with the Phase 0 float32 operation order. DirectX SHALL complement the encoded OpenGL green code. Native requests with Normal SHALL currently refuse subsampling other than 1, nonzero dilation and imported low objects with nonidentity transforms before starting a job; these are explicit unresolved domains, not parity acceptance.

#### Scenario: Material partition preserves the frame
Given a source object whose shared corners receive contributions from faces with different materials
When `LowParts` selects one material
Then its retained corner tangents MUST equal the complete object's MikkTSpace results
And the Normal baker MUST NOT recalculate those tangents on the material subset

#### Scenario: Independent usages and failure publication
Given a native request containing Normal without AO
When AO settings contain values outside the AO domain
Then they MUST NOT affect Normal validation or computation, no secondary rays SHALL be cast, and AO maps SHALL remain empty
And a singular or non-finite interpolated tangent frame MUST fail the job without publishing any result

#### Scenario: DirectX code conversion
Given an OpenGL Normal hit whose encoded green code is 32768
When the same request selects DirectX
Then its green code MUST be 32767 and its red and blue codes MUST remain unchanged
And non-hit texels MUST retain zero codes and their separate classifications

#### Scenario: Canonical bytes and qualification
Given an AO-only request and a request that also contains Normal
When their results are serialized
Then the AO-only representation MUST remain `UZPBAKE3`, and the Normal result MUST use `UZPBAKE4` with usage and configuration metadata
And both usages MUST remain `pending-evidence` with their individual owner tasks until Tier 2b acceptance

### Requirement: Painter's Texel Samples And Ray Directions
The native baker SHALL place each texel sample by decision 408's rasterisation of the low UV triangles (float32 device coordinates, 1/256-texel vertices, the top-left edge rule) and interpolate with the snapped triangle's barycentric weights. With `SmoothNormals` on, the distance-based primary ray SHALL run along the interpolated averaged normal: at each low vertex the normalised sum of the distinct normals of the part's vertices at that position.

#### Scenario: Hard-edged low faces
Given the bevelled cube's hard-edged low faces and its chamfered high, baked with Painter's default `SmoothNormals`
When the Tier 2b comparison runs
Then the native hit texels MUST equal Painter's and every hit texel's code MUST equal Painter's

#### Scenario: Shared UV edges
Given a texel centre on an edge shared by two low UV triangles
When the baker samples it
Then the sample MUST belong to the triangle for which that edge is a top-left edge

### Requirement: Low Z Is An Inspection Signal
The normal baker MUST NOT replace any texel because of a low or negative normal Z; such texels SHALL be counted and reported.

#### Scenario: Buried face
Given a part whose high-poly normal yields Z < 0 texels
When the bake completes
Then the texels MUST keep their baked values and the count MUST appear in the report

#### Scenario: Comparison inspection at native depth
Given a candidate normal map with finite vectors whose decoded Z is negative, zero or positive, and non-finite vectors
When the comparison tool produces the map's normal diagnostics
Then `negative_z_count` MUST count only wholly finite candidate vectors with Z < 0 across the whole map, using n = 2c/max - 1 for integer channels and the stored values for float channels
And zero-Z and non-finite vectors MUST NOT contribute to that count; non-finite vectors remain in `non_finite_count`
And the diagnostic MUST NOT change any sample, encoded file, equality verdict or exception metric
And historical comparison reports without the new field MUST remain valid
