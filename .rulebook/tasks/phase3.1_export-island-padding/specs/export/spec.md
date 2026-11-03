# Export — exact padding and Normal on UV islands

## ADDED Requirements

### Requirement: Exact Islanded Padding And Normal
On a texture set whose UV islands do not cover the whole tile, `infinite` padding and the virtual Normal SHALL equal Painter's exported files on every texel of every recorded islanded golden, in both recordings, and MUST stay refused before writing wherever they are not yet exact.

#### Scenario: A recorded islanded golden
Given an admitted `export-padding*` golden exported with `infinite` padding
When UzPainter's production export writes the same configuration
Then every exported file MUST be byte-identical to Painter's, r1 and r2

#### Scenario: An unfitted case
Given an islanded export that no recording fits
When it is requested through the production export
Then it MUST be refused before any file is written, naming this task as the owner
