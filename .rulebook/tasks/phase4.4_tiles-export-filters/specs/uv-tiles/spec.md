## ADDED Requirements

### Requirement: UV-Tile Export Filters
The export plan compiler SHALL resolve `filter.uvTiles` in `exportList` entries and `exportParameters` rules exactly as Painter does, producing one planned file per selected set, stack, output map and UV tile, and MUST reject an unknown tile before any GPU work.

#### Scenario: Subset of tiles exported
Given the UDIM fixture with tiles 1001, 1002 and 1011 and an `exportList` entry filtering `uvTiles` to tile 1002
When the configuration is exported
Then only tile 1002 files are planned and written, and the file list and decoded maps equal the private Painter goldens

#### Scenario: Unknown tile rejected
Given an export configuration whose filter names tile 1099, absent from the set
When the plan is compiled
Then compilation fails listing the valid tiles and nothing is written

### Requirement: UV-Tile Naming Wildcards
The exporter SHALL expand `$udim` and `$uvTileName` per tile, remove `( … )` optional groups whose wildcards are empty, and MUST reject naming collisions across tiles at compile time.

#### Scenario: Pattern without a tile wildcard
Given a multi-tile export whose file-name pattern contains no tile wildcard
When the plan is compiled
Then compilation fails with a collision error naming the colliding tiles and no file is written

### Requirement: Deterministic Tile Export
The same build, project and configuration MUST produce byte-identical per-tile files, published through one atomic generation update.

#### Scenario: Two runs, same bytes
Given the UDIM fixture and one export configuration
When it is exported twice into two generations
Then every per-tile file of the two generations has the same SHA-256
