## ADDED Requirements

### Requirement: Resolution Per UV Tile
Each UV tile SHALL have an effective resolution that is its own power-of-two value between 128 and 8192 when set, or the texture set's resolution otherwise, readable through the API and persisted in the project.

#### Scenario: Override and reset
Given a UVTile project whose set resolution is 2048
When tile 1002 is set to 1024, the project is saved and reopened, and the override is then reset
Then tile 1002 reads 1024 after reopen and 2048 after the reset, while tile 1001 reads 2048 throughout

### Requirement: Mixed-Resolution Evaluation Equal to Painter
The compositor MUST evaluate each tile at its effective resolution and SHALL reproduce the Tier 0 per-tile resolution goldens exactly, including a resolution change after a bitmap was written to a paint layer.

#### Scenario: Two tiles, two resolutions
Given a set with tile 1001 at 2048 and tile 1002 at 1024 and the Tier 0 recipe
When every channel is exported at 16 bit for both tiles
Then each tile's decoded values equal the private Painter goldens exactly

### Requirement: Per-Tile Admission
A tile resolution whose evaluation would exceed the VRAM admission budget MUST be refused explicitly before any mutation.

#### Scenario: Over-budget tile refused
Given a worker started with a reduced synthetic VRAM budget
When a tile resolution above that budget is requested
Then the call fails with an explicit admission error and the project revision is unchanged
