## ADDED Requirements

### Requirement: External UzEngine Consumer Only
The UzEngine consumer fixture SHALL run UzEngine's own executable as an external process, and UzPainter MUST NOT link, load or call UzEngine code to validate the preset.

#### Scenario: No engine code in UzPainter
Given the UzPainter build used for the fixture run
When its link map and include paths are inspected
Then no UzEngine library, DLL or checkout path appears, and the engine runs only as a separate process launched by the fixture

### Requirement: UzEngine Fixture Loads And Renders The Preset
The fixture MUST load the published `.uzmat` and `.uztexture` files of a pinned generation in a test scene, render it, and verify every slot binding of the UzEngine preset table.

#### Scenario: Wand v1 row 9 passes
Given wand v1 exported with the UzEngine preset into a published generation
When the fixture runs on the self-hosted GPU runner
Then the scene renders and the albedo, normal, ORM, emissive and height bindings match the preset table

#### Scenario: Mis-bound material is caught
Given a `.uzmat` that binds the ORM texture to the albedo pin
When the fixture runs
Then the binding check fails and names the pin

### Requirement: UzEngine Lossy-Derivative Comparison
The fixture SHALL compare decoded `.uztexture` data with the canonical maps under the lossy-derivative contract and report it separately from authoring equality.

#### Scenario: Compression error reported per map
Given the published canonical maps and their `.uztexture` derivatives
When the comparison runs
Then the report lists decoded max, mean and p99 error per map and mip level under the lossy-derivative heading

### Requirement: UzEngine Gaps And Mesh Route Reported
The fixture SHALL publish a gap report listing every output the engine cannot bind and the mesh route used to load the test mesh.

#### Scenario: SpecularWeight gap and mesh route listed
Given a fixture run on a set with a SpecularWeight channel
When the report is written to `parity/reports/phase3/`
Then it lists SpecularWeight as a consumer gap and names the qualified mesh route, which is not the glTF cook path

### Requirement: Unavailable Consumer Never Passes
The fixture MUST fail explicitly when the UzEngine executable or its scene is unavailable.

#### Scenario: Executable missing
Given the runner has no UzEngine executable at the recorded identity
When the fixture runs
Then it fails with an unavailable status and the row is not counted as passed
