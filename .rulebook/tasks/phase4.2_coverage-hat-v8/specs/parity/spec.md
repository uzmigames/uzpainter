## ADDED Requirements

### Requirement: Hat v8 Tier 1 Equality
Hat v8 rebuilt in UzPainter from the same stack JSON and resources with identical external mesh maps MUST export its seven delivered maps equal to the private Painter goldens at native depth; a difference passes only through an owner-approved exception.

#### Scenario: 43-layer stack equal
Given hat v8 rebuilt with its 43-layer stack
When the seven maps are exported and compared with the private goldens
Then every map is equal, or each difference is covered by an approved entry in `parity/exceptions.json`

### Requirement: Hat v8 Single Corrected AO Per Set
The hat v8 fixture SHALL bind one corrected AO per set that feeds generators, delivery and albedo layers, and SHALL export it for the glTF occlusion slot.

#### Scenario: AO in the occlusion slot
Given the hat v8 delivery
When consumer-matrix row 2 builds the GLB
Then the 16-bit AO is in the glTF occlusion slot and is the same AO the generators read

### Requirement: Hat v8 Consumers Unchanged
The hat consumers of rows 2, 3, 5 and 7 SHALL run unchanged on the UzPainter delivery with bindings and outputs identical to those on the Painter delivery, and rows 8 and 9 SHALL pass on their expected bindings.

#### Scenario: Specular augmentation unchanged
Given the GLB of row 2 built from the UzPainter delivery
When `glb_add_specular.py` (row 3) runs unchanged
Then `KHR_materials_specular` is written with the same values as on the Painter delivery

### Requirement: Hat v8 Migration Limits Block The Gate
Stroke-painted hat v8 content MUST be imported as bitmaps only when the documented export route preserves the required output; otherwise the fixture SHALL be recorded `not_migratable` and acceptance stays blocked until an owner scope decision is recorded.

#### Scenario: Unpreservable paint content
Given a hat v8 paint layer whose content cannot be preserved through the documented export route
When the acceptance item is evaluated without an owner scope decision
Then P4-HAT8 and G4 stay blocked
