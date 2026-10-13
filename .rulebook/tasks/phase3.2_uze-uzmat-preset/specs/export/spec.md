## ADDED Requirements

### Requirement: UzEngine Material File
UzPainter SHALL write `<set>.uzmat` with its own code, binding `TextureSample → PBROutput` pins 0..6 to the preset's textures and writing the inline scene-material block.

#### Scenario: Pins reference the exported textures
Given wand v1 exported with the UzEngine preset
When `<set>.uzmat` is parsed
Then pins 0..6 reference the albedo, normal, ORM, emissive and height textures of the same generation as stated in the preset table

### Requirement: UzEngine Preset Outputs With Explicit Metadata
The UzEngine preset MUST compile into a typed plan whose outputs, formats, colour spaces and bindings equal the UzEngine preset table of `08-export.md` §4, and MUST NOT infer any of them from file names.

#### Scenario: Dry run lists the table
Given a texture set with all preset source channels
When `list_project_textures` runs with the UzEngine preset
Then the plan lists `<set>_albedo`, `<set>_normal`, `<set>_orm`, `<set>_emissive`, `<set>_height`, `<set>_specularweight` and `<set>.uzmat` with their formats and bindings

### Requirement: Canonical Maps Beside Derivatives
Every cooked `.uztexture` derivative SHALL be accompanied by its canonical 16-bit or float map in the same generation.

#### Scenario: Canonical ORM next to its BC7 derivative
Given an export with the UzEngine preset
When the generation is published
Then `<set>_orm` exists both as a canonical map and as a BC7 `.uztexture`, and the receipt links the two

### Requirement: UzEngine Opacity And SpecularWeight Gaps
The UzEngine preset SHALL carry opacity in albedo alpha, SHALL report the SM5 route as unsupported for opacity, and SHALL report SpecularWeight as a consumer gap with no engine slot.

#### Scenario: Gaps in the receipt
Given an authored fixture texture set with opacity and SpecularWeight channels
When it is exported with the UzEngine preset
Then the receipt lists the SM5 opacity route and SpecularWeight as consumer gaps and the export does not alter other maps to compensate

### Requirement: UzEngine Preset Provenance
The shipped UzEngine preset MUST have a provenance record with the fields of `08-export.md` §4 and SHALL NOT ship without it.

#### Scenario: Missing record fails CI
Given `assets/export-presets/uzengine.json` without `uzengine.provenance.json`
When the provenance check runs on the local CPU lane (decision 200)
Then the check fails and names the preset
