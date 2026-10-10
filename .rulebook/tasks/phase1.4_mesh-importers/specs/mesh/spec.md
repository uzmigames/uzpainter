## ADDED Requirements

### Requirement: Corner-preserving import
Importing an already-triangulated mesh SHALL keep corners, winding, corner normals, UVs and materials exactly; the mesh MUST NOT be re-triangulated, welded, re-normalled or repacked.

#### Scenario: Triangulated OBJ
Given a triangulated low-poly OBJ with `usemtl` materials
When it is imported
Then the corner hashes equal those computed from the source file and one texture set exists per material in file order

### Requirement: Explicit identities and units
Material identity SHALL be kept separate from object identity, duplicate material names MUST fail import unless `allow_duplicate_material_names` merges them explicitly, and the effective unit scale SHALL be recorded.

#### Scenario: Duplicate material names
Given a mesh with two materials of the same name
When it is imported without `allow_duplicate_material_names`
Then import fails with an error naming the duplicates and nothing is created

### Requirement: Unsupported inputs refused explicitly
UVs outside 0–1 MUST fail import with the list of tiles, unsupported formats SHALL raise a release-gap error, and `AutoUnwrapSettings` SHALL raise `NotYetSupported`.

#### Scenario: UV outside the 0–1 tile
Given a mesh with UVs in tile 1002
When it is imported
Then import fails listing tile 1002 and no texture set is created
