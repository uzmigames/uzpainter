## ADDED Requirements

### Requirement: Reload keeps the stack and invalidates dependents
`reload_mesh` SHALL keep stacks and resources, match texture sets by material identity, classify texels per set, and MUST mark dependent mesh maps, geometry masks, procedural caches and receipts `invalid` without deleting them.

#### Scenario: Moved vertices
Given a project with an imported AO map bound to a set
When the mesh is reloaded with moved vertices in that set
Then the stack is unchanged, the affected texels are classified `moved` and the AO binding is kept and marked `invalid`

### Requirement: No silent attach on changed materials
A reload whose materials were renamed, split or merged MUST fail with an explicit error carrying a mapping proposal and SHALL leave the project unchanged.

#### Scenario: Renamed material
Given a project whose mesh material `cloth` becomes `cloth_v2`
When the mesh is reloaded
Then the reload fails proposing `cloth → cloth_v2` and the old mesh and bindings remain
