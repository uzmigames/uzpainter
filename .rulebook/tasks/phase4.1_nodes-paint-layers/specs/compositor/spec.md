## ADDED Requirements

### Requirement: Paint Layers Receive Bitmaps
Paint layers and paint effects SHALL receive content only through typed whole-bitmap and projected-bitmap operations, each committed as one transaction that creates a new plane version, and their evaluated output MUST equal the Tier 0 goldens.

#### Scenario: Whole bitmap in a paint layer
Given a paint layer with BaseColor and Roughness active and a 16-bit bitmap resource
When the whole-bitmap operation writes the bitmap to both channels and the channels are exported at 16 bit
Then the decoded values equal the private Painter golden exactly and the project has one new revision

### Requirement: Paint Layers Receive Projections
A projected-bitmap operation SHALL rasterise the bitmap through a supported projection mode into the plane, and MUST raise `NotYetSupported` before mutation for a mode that is still a gap.

#### Scenario: Triplanar projection into a paint layer
Given a paint layer on the bevelled cube and a bitmap projected with `Triplanar`
When the affected channel is exported at 16 bit
Then the decoded values equal the private Painter golden exactly

### Requirement: No Stroke Engine
UzPainter MUST NOT expose any brush-stroke operation in `uzpainter`, the `substance_painter` facade or the MCP tool list.

#### Scenario: Tool list without strokes
Given the supervisor started with every typed family registered
When the MCP tool list and the native API are enumerated
Then no stroke operation is present

### Requirement: Unproducible Goldens Reported as not_migratable
A paint golden that Painter's documented routes cannot produce MUST be recorded `not_migratable` with its reason and SHALL NOT be counted as passed.

#### Scenario: Documented route missing
Given a paint case whose content Painter's documented API cannot create
When the recorder runs
Then the manifest marks it `not_migratable` with the reason and the child report lists it as an open gap needing an owner scope decision

### Requirement: Planes Never Alias
Two paint layers on the same channel and tile MUST keep separate planes through save, reopen, revert and compaction.

#### Scenario: Revert keeps both planes
Given two paint layers on BaseColor in tile 1001, each written with a different bitmap
When the project is saved, reopened, reverted to the earlier revision and compacted
Then each layer resolves its own plane version with its original pixels
