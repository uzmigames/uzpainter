## ADDED Requirements

### Requirement: UV-space raster buffers
The UV raster pass SHALL write position, normal, tangent-frame, island-id and material-id buffers per texture set and UV tile, with texel-centre coverage, from corner buffers with explicit vertex strides.

#### Scenario: Analytic plane
Given a unit plane mapped to the full 0–1 UV square
When it is rasterised at 256×256
Then every texel is covered at its centre and its position equals the analytic interpolation

### Requirement: Conservative coverage by supersampling
The pass MUST produce a conservative coverage mask by supersampling that contains every texel a triangle touches.

#### Scenario: Thin triangle
Given a sliver triangle narrower than one texel
When it is rasterised
Then the conservative mask marks every texel it touches although texel-centre coverage may be empty

### Requirement: Repeatable raster output
Rasterising the same mesh with the same settings and build SHALL produce byte-identical buffers.

#### Scenario: Two runs
Given the bevelled-cube fixture
When it is rasterised twice in separate processes
Then all output buffers are byte-identical
