# Smart presets — smart-mask recipes

## ADDED Requirements

### Requirement: Smart Mask Recipes Pass Tier 2a
Every shipped UzmiGames smart-mask recipe MUST produce outputs equal to the same recipe rebuilt in Painter through the documented API, or the difference MUST be covered by an owner-approved exception.

#### Scenario: Edge-wear recipe on hat v6 low
Given the UzmiGames edge-wear smart-mask recipe and its Painter rebuild recorded privately
When the recipe is evaluated in UzPainter on hat v6 low at 2048
Then the mask MUST equal the Painter output or cite an approved exception

### Requirement: Smart Mask Insertion Rules
`insert_smart_mask` SHALL expand a recipe into an effect list only inside a mask stack, attach it in one transaction and record `preset_ref {asset@version}` for provenance only.

#### Scenario: Insertion into a content stack
Given a fill layer's content stack
When `insert_smart_mask` targets it
Then the call MUST raise and the revision MUST NOT advance

### Requirement: Smart Mask Aliases Never Substitute
A Painter smart-mask name SHALL resolve only to the private observed structure on the owner's machine; without one it MUST raise `UnsupportedProcedural` with reason "private preset unavailable" and MUST NOT substitute a UzmiGames recipe.

#### Scenario: Private structure unavailable
Given a machine without the private store
When a script inserts the smart mask by its Painter name
Then `UnsupportedProcedural` MUST be raised with reason "private preset unavailable"

### Requirement: Observed Preset Structures Stay Private
Adobe preset trees, parameter collections and serialized readbacks obtained by observation MUST NOT be committed or shipped, whatever their format or names.

#### Scenario: Recorded readback committed
Given a serialized smart-mask readback recorded into the private store
When a commit adds that file to the repository
Then the repository guard MUST reject it by its hash in the store index

#### Scenario: Recipe without independent provenance
Given a recipe file with no independently authored provenance record
When the asset-library inventory check runs
Then the recipe MUST be refused for shipping
