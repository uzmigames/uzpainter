# Procedural — mesh-map generator family

## ADDED Requirements

### Requirement: Mesh-Map Generator Tier 2a
Each certified mesh-map generator (Mask Builder (Legacy), Mask Editor, Metal Edge Wear, Dirt, Curvature, Position, World Space Normals, Ambient Occlusion) MUST equal its Painter oracle over the Tier 2a certification matrix, or be covered by an owner-approved exception; otherwise it MUST be listed as a release gap.

#### Scenario: Metal Edge Wear on hat v6 low
Given hat v6 low with its mesh maps and the recorded recipe parameters
When Metal Edge Wear is evaluated at 2048 with the recorded seed
Then the output MUST equal the private Painter oracle or cite an approved exception

### Requirement: Generator Provenance Records
Every generator family SHALL ship a provenance record naming its public sources, author, calibration corpus id and residuals, and MUST NOT cite any Adobe shipped file as a source.

#### Scenario: Provenance audit
Given the generator family record
When the asset-library inventory is checked
Then each generator MUST have public sources, an author, a corpus id and residuals, and no off-limits source

### Requirement: Generators Bind Mesh Maps By Usage
Generators SHALL read mesh maps by usage and MUST fail evaluation loudly when a required map is missing or invalid.

#### Scenario: Invalid curvature binding
Given a texture set whose curvature binding is marked invalid after a mesh reload
When a Dirt generator is evaluated
Then evaluation MUST fail with an error naming the invalid mesh map
