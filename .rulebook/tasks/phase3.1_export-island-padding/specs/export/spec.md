# Export — islanded padding under the owner's exception

## ADDED Requirements

### Requirement: Islanded Infinite Padding Under An Owner Exception
On a texture set whose UV islands do not cover the whole tile, the production export SHALL write `infinite` padding with every covered texel equal to the evaluation and SHALL report each file it pads as relying on EXC-013 (decision 414); a combined virtual Normal on such a set MUST stay refused before writing.

#### Scenario: An islanded `infinite` export
Given a texture set whose UV islands leave texels uncovered
When the production export writes its maps with `infinite` padding
Then every covered texel MUST keep its evaluated value, and the receipt MUST list EXC-013 version 1 with every padded file in `exceptions_relied_on`, with no `non_conformant` block

#### Scenario: A virtual Normal on islands
Given a combined virtual Normal on an islanded texture set
When it is requested through the production export
Then it MUST be refused before any file is written, naming `phase4.1_export-island-padding-exact` as the owner
