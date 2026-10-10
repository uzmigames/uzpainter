## ADDED Requirements

### Requirement: UzEngine Preset Integration Acceptance
The UzEngine preset MUST close only when its three child tasks are accepted and the external UzEngine consumer fixture loads and renders the wand v1 preset output with the bindings of the UzEngine preset table in `08-export.md` §4.

#### Scenario: Wand v1 renders in the external fixture
Given the wand v1 project rebuilt in UzPainter and exported with the UzEngine preset
When the external UzEngine fixture loads the published `.uzmat` and `.uztexture` files in its test scene
Then the scene renders with albedo, normal, ORM, emissive and height bound to their slots and the fixture reports success

#### Scenario: A failed child keeps the parent open
Given `phase3.3_uze-consumer-fixture` is not accepted
When the parent acceptance item is evaluated
Then the parent task stays open whatever the integration results are

### Requirement: UzEngine Consumer Gaps Listed
Every UzEngine preset run SHALL list each output the engine cannot bind as a consumer gap in the export receipt and in the consolidated gap report, and SHALL NOT compensate for it inside the export.

#### Scenario: SpecularWeight reported, not executed
Given a texture set with a SpecularWeight channel
When it is exported with the UzEngine preset
Then `<set>_specularweight` is written and the receipt lists it as a consumer gap with no engine slot

### Requirement: UzEngine Preset Determinism
The UzEngine preset MUST produce byte-identical `.uzmat`, `.uztexture` and canonical map files for the same build, project and configuration.

#### Scenario: Two runs, same bytes
Given the same build, the same tunic v10 project and the same export configuration
When the UzEngine preset is exported twice into two generations
Then every file of the two generations has the same SHA-256
