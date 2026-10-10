## ADDED Requirements

### Requirement: SpecularWeight Channel Storage Format
The SpecularWeight channel SHALL use the storage format measured in Tier 0 for its template and MUST evaluate and export values equal to the Tier 0 goldens.

#### Scenario: Uniform fill exported
Given a texture set with a SpecularWeight channel and a uniform fill of a swept value
When SpecularWeight is exported at the template's format
Then the decoded values equal the private Tier 0 golden

### Requirement: Hat v8 Export Preset
The hat v8 variant of the Assets3D inline preset SHALL export the five pipeline maps plus SpecularWeight and 16-bit AO, with SpecularWeight as 8-bit with the weight in RGB and A, and MUST ship with a provenance record naming its pipeline script.

#### Scenario: Dry run of the hat v8 preset
Given hat v8 rebuilt in UzPainter
When `list_project_textures` runs with the hat v8 preset
Then the plan lists the seven delivered files, SpecularWeight as 8-bit RGBA and AO as 16-bit

### Requirement: SpecularWeight Consumer Gap Never Compensated
Every export whose consumer cannot bind SpecularWeight SHALL list it as a consumer gap in the receipt, and the export MUST NOT apply any consumer-side mapping such as `Specular = 0.5 × SpecularWeight`.

#### Scenario: Other maps unaffected
Given the same project exported with the UzEngine preset with and without a SpecularWeight channel
When the two generations are compared
Then every map other than `<set>_specularweight` is byte-identical and the receipt with the channel lists the gap
