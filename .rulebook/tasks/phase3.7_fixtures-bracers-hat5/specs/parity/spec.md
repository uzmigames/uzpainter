## ADDED Requirements

### Requirement: Bracer r9 Tier 1 Equality Through Certified Procedurals
Bracer r9 rebuilt in UzPainter MUST export maps equal to the private Painter goldens at native depth, with every procedural evaluated by a certified `HlslBackend` family; a difference passes only through an owner-approved exception.

#### Scenario: Equal maps without snapshots
Given bracer r9 rebuilt from its stack JSON and resources with identical external mesh maps and `SnapshotBackend` disabled
When every map is exported and compared with the private goldens
Then all maps are equal, or each difference is covered by an approved entry in `parity/exceptions.json`

### Requirement: Hat v5 Applicable Tiers
Hat v5 rebuilt in UzPainter SHALL pass Tier 1 for its maps and the applicable Tier 2 comparisons for its procedural relief and native-baked mesh maps.

#### Scenario: Procedural relief equal
Given hat v5 rebuilt in both tools
When its Height and Normal exports are compared
Then they are equal at native depth or covered by an approved exception

### Requirement: Stroke-Painted Content Per Corpus Migration Assumption
Stroke-painted content in a fixture SHALL be imported as a bitmap only when the documented export route preserves the required output, and otherwise MUST be recorded `not_migratable` with its reason, keeping the fixture's gate blocked unless an explicit owner scope decision is recorded in the capability manifest and gate report.

#### Scenario: Not migratable without owner decision blocks
Given hat v5 marked `not_migratable` because its paint effect cannot be preserved through the documented export route
When the acceptance item is evaluated with no owner scope decision recorded
Then this task and G3 stay blocked even if bracer r9 passes

### Requirement: Fixture Native-Bake Leg
The fixtures' mesh maps baked by `EmbreeBaker` MUST be compared with Painter's CPU bakes per map under Tier 2b, hit and coverage evidence first.

#### Scenario: Baked AO compared per map
Given the hat v5 low/high pair
When `EmbreeBaker` bakes AO and the result is compared with the private Painter bake
Then the report lists hit/coverage agreement and the map comparison, and a difference fails unless an approved exception covers it

### Requirement: Separate Stability, Repeatability And Equality Reports
Each fixture report SHALL state oracle stability, UzPainter repeatability and equality to Painter separately, with max error and affected-texel counts next to any mean or percentile.

#### Scenario: Report shows all three results
Given a completed bracer r9 run
When the report is written to `parity/reports/phase3/`
Then it lists the oracle stability class, the two-run UzPainter hash comparison and the per-map equality numbers
