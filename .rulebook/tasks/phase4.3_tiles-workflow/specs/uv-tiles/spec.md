## ADDED Requirements

### Requirement: Tile Workflows At Project Creation
The project SHALL accept the `UVTile` and `TextureSetPerUVTile` workflows, record the tile list of every texture set in `uv_tiles[]`, and keep the `Default` workflow's rejection of UVs outside 0–1 unchanged.

#### Scenario: UDIM mesh under the UVTile workflow
Given a UzmiGames-authored mesh with UVs on tiles 1001, 1002 and 1011
When a project is created with the `UVTile` workflow
Then the texture set lists exactly the tiles 1001, 1002 and 1011 and the certificate reports per-tile counts

#### Scenario: Default workflow still refuses
Given the same mesh
When a project is created with the `Default` workflow
Then the import fails before mutation and the error lists the tiles outside 0–1

### Requirement: Per-Tile Evaluation Equal to Painter
The compositor MUST evaluate every stack per UV tile and SHALL reproduce the Tier 0 tile goldens exactly, including the `Fill` projection's per-tile matching and triangles spanning two tiles.

#### Scenario: Bitmap fill on two tiles
Given a bitmap BaseColor fill with UV projection on the UDIM mesh
When BaseColor is exported for tiles 1001 and 1002 at 16 bit
Then the decoded values of both tiles equal the private Painter goldens exactly

### Requirement: UVTile Geometry Mask
A `UVTile` geometry mask SHALL restrict a layer or effect to the tiles of its inclusion list.

#### Scenario: Layer limited to one tile
Given a uniform fill whose `UVTile` geometry mask includes only tile 1011
When the stack is evaluated
Then tile 1011 carries the fill and tiles 1001 and 1002 keep the underlying values, equal to the Painter goldens

### Requirement: Tile Identity Persisted
Raster planes and mesh-map bindings MUST carry their UV tile, and two planes on the same channel in different tiles SHALL never alias after save, reopen or compaction.

#### Scenario: Planes per tile survive compaction
Given two paint layers on BaseColor receiving bitmaps in tiles 1001 and 1002
When the project is saved, reopened and compacted
Then each plane keeps its own tile identity and its pixels are unchanged
