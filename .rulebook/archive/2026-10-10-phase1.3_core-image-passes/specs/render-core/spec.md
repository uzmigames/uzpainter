## ADDED Requirements

### Requirement: Jump-flood dilation
Dilation SHALL fill uncovered texels from the nearest covered texel within the requested distance, equal to the CPU reference with the same tie-breaking rule.

#### Scenario: Two islands
Given a coverage mask with two islands and a dilation distance of 8 texels
When the dilation pass runs
Then every texel within 8 texels of an island equals the CPU reference and texels farther away are unchanged

### Requirement: Resampling and mip generation
Resampling and mip generation MUST equal their CPU references; sRGB data SHALL be filtered in linear space, normals SHALL be renormalised and alpha coverage SHALL be preserved in the respective modes.

#### Scenario: sRGB mip chain
Given an sRGB8 colour image
When its mip chain is generated in sRGB-aware mode
Then every level equals the CPU decode–filter–encode reference

### Requirement: Repeatable image passes
Each image pass SHALL produce byte-identical output for identical inputs and build.

#### Scenario: Repeat run
Given the same input and parameters
When a pass runs twice
Then both outputs are byte-identical
