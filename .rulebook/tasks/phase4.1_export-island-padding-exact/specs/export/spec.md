# Export — exact padding and Normal on UV islands

## ADDED Requirements

### Requirement: Exact Islanded Padding And Normal
On a texture set whose UV islands do not cover the whole tile, `infinite` padding and the virtual Normal SHALL equal Painter's exported files on every texel of every recorded islanded golden, in both recordings; until they do, a padded islanded file MUST be reported as relying on EXC-013 and a combined virtual Normal on it MUST stay refused before writing.

#### Scenario: A recorded islanded golden
Given an admitted `export-padding*` golden exported with `infinite` padding
When UzPainter's production export writes the same configuration
Then every exported file MUST be byte-identical to Painter's, r1 and r2, and its receipt MUST rely on no exception

#### Scenario: A virtual Normal on islands not yet exact
Given a combined virtual Normal on an islanded texture set
When it is requested through the production export before its island-edge texels are exact
Then it MUST be refused before any file is written, naming this task as the owner
