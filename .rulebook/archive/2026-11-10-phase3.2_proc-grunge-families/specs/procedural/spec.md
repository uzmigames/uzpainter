# Procedural — grunge and noise family

## ADDED Requirements

### Requirement: Grunge Family Tier 2a
Each inventoried grunge or noise asset referenced by the body and hat recipes, and `fabric_linen`, MUST equal its Painter oracle over the Tier 2a certification matrix or be covered by an owner-approved exception; otherwise it MUST be listed as a release gap.

#### Scenario: Recorded body-recipe grunge
Given a grunge asset with the parameter set recorded in the body recipe
When it is evaluated on the bevelled cube at 4096 with the recorded seed
Then the output MUST equal the private Painter oracle or cite an approved exception

### Requirement: Seeded And Tiled Evaluation
Grunge and noise assets SHALL take tiling, seed and parameters as documented, and the same request MUST produce byte-identical output on repeated evaluation.

#### Scenario: Repeat evaluation
Given one asset, seed and parameter set
When it is evaluated twice on DX12
Then both rasters MUST be byte-identical
