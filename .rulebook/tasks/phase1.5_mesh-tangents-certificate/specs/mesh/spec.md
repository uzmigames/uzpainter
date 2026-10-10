## ADDED Requirements

### Requirement: MikkTSpace tangent frames
Tangent frames SHALL be computed per corner with MikkTSpace, in `PerFragment` mode by default and `PerVertex` on request, using the convention settled by the P0-NORMAL fixture.

#### Scenario: Hemisphere fixture
Given the P0-NORMAL hemisphere fixture
When UzPainter computes its tangent-space normal with the production frames
Then the result reproduces the settled verdict against the private Painter bake

### Requirement: Certificate flags and never repairs
Import SHALL compute the certificate of `docs/architecture/12-mesh-import.md` §4 and MUST NOT modify the mesh to fix any flagged defect.

#### Scenario: Coincident opposite faces
Given a mesh with two coincident faces of opposite winding
When it is imported and certified
Then `faces.coincident_opposite` counts them, `status` is not `pass`, and the mesh corners are unchanged
