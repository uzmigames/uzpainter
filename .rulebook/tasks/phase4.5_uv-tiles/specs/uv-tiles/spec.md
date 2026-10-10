## ADDED Requirements

### Requirement: UV Tiles Integration Acceptance
The UV-tile work package MUST close only when `phase4.3_tiles-workflow`, `phase4.4_tiles-per-tile-resolution` and `phase4.4_tiles-export-filters` are accepted and the UDIM fixture passes Tier 0 and Tier 1.

#### Scenario: A failed child keeps the parent open
Given `phase4.4_tiles-export-filters` is not accepted
When the parent acceptance item is evaluated
Then the parent task stays open whatever the UDIM fixture results are

### Requirement: Tier 0 Tile Semantics Exact on the UDIM Fixture
The Tier 0 tile-semantics goldens recorded on the UDIM fixture (per-tile evaluation, `UVTile` geometry mask, per-tile resolution, export filters and naming) SHALL be reproduced exactly.

#### Scenario: Geometry mask restricted to one tile
Given the UDIM fixture with a fill layer whose `UVTile` geometry mask includes only tile 1002
When both tools export BaseColor for every tile at 16 bit
Then the decoded values of every tile equal the private Painter goldens exactly

### Requirement: Tier 1 Recipe Equality on the UDIM Fixture
Every map exported for every tile of the UDIM fixture recipe MUST equal the private Painter goldens and MUST be byte-stable across two runs of the same build.

#### Scenario: Two runs, equal maps per tile
Given the UDIM fixture recipe rebuilt in UzPainter
When it is exported twice with the same configuration
Then each tile's maps equal the Painter goldens and the two runs have identical SHA-256 per file

### Requirement: UV-Tile Capability Reported With Evidence
The capability manifest SHALL list the UV-tile workflow as `supported` only with Tier 0/1 evidence from the UDIM fixture and SHALL keep any unproven part as an explicit `release-gap`.

#### Scenario: Manifest after acceptance
Given the UDIM fixture passed Tier 0 and Tier 1
When the capability manifest is regenerated
Then the UV-tile workflow entries are `supported` and name the UDIM fixture evidence
