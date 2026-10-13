# Smart presets — smart-material recipes

## ADDED Requirements

### Requirement: Smart Material Expansion
`insert_smart_material` SHALL expand a smart-material recipe into an editable group carrying `preset_ref {asset@version}` for provenance only, built detached and attached in one transaction, and MUST reject insertion where Painter's documented insertion rules forbid a smart material.

#### Scenario: Insert into the hierarchy
Given an open project and a shipped UzmiGames smart material
When `insert_smart_material` is called at a root position
Then one revision MUST add an editable group whose layers and effects match the recipe and whose `preset_ref` names the recipe version

#### Scenario: Edit after insertion
Given a project where a smart material was inserted
When a script changes one parameter of a fill inside the inserted group
Then the change MUST commit as a normal edit and `preset_ref` MUST remain unchanged

#### Scenario: Failure attaches nothing
Given a recipe that references a family with no backend able to serve it
When the insertion runs
Then it MUST fail with `UnsupportedProcedural`, attach nothing and leave the revision unchanged

### Requirement: Smart Material Tier 2a Parity
Every shipped smart-material recipe SHALL pass Tier 2a: the same recipe rebuilt in Painter through the documented API MUST produce equal outputs for every exported channel over the certification matrix, and a non-zero residual MUST pass only through an owner-approved exception.

#### Scenario: Boundary parameter set
Given a shipped recipe, the bevelled cube at 2048 and a boundary parameter set
When the Tier 2a comparison runs against the Painter rebuild
Then every channel output MUST be equal at native precision or cite an approved exception

### Requirement: Smart Material Portable Folders
`smart_export {uid, kind: material, path}` SHALL write a portable folder containing the group's recipe, its resources by content hash and the provenance records, and inserting that folder into another project MUST reproduce identical parameters, resources and outputs.

#### Scenario: Round trip between projects
Given a smart-material group exported to a folder from project A
When the folder is inserted into project B with the same mesh and settings
Then parameters and resource hashes MUST be identical and the exported maps MUST be byte-equal to project A's

### Requirement: Smart Material Aliases Never Substitute
A Painter smart-material name SHALL resolve through the internal alias table only to the private observed structure on the owner's machine; where that structure is unavailable the call MUST raise `UnsupportedProcedural{asset, reason: "private preset unavailable"}` and MUST NOT insert a UzmiGames recipe instead.

#### Scenario: Machine without the private store
Given a machine without the private store
When a script inserts Leather Damaged by its Painter name
Then the call MUST raise `private preset unavailable` before any mutation and no UzmiGames recipe MUST be inserted

### Requirement: Smart Material Apply Recipe Tool
The MCP `apply_smart {config_json, texture_set}` tool SHALL apply a smart configuration with the `painter_layer_stack.py smart` semantics without requiring Python.

#### Scenario: Python disabled
Given a supervisor started without `--allow-python`
When a client calls `apply_smart` with a valid configuration
Then the configured smart materials MUST be inserted in one transaction and the result MUST list the created node uids
