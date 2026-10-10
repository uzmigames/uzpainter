# Smart presets — P3-SMART acceptance

## ADDED Requirements

### Requirement: Smart Presets Parent Closure
The P3-SMART parent SHALL close only when `phase3.4_smart-projections`, `phase3.4_smart-mask-recipes` and `phase3.5_smart-material-recipes` are all accepted and the P3-SMART report is published under `parity/reports/phase3/`.

#### Scenario: Recipes child open
Given the projection and smart-mask children accepted and the smart-material child open
When P3-SMART acceptance is evaluated
Then the parent MUST remain open

### Requirement: Smart Presets Report
The P3-SMART report SHALL contain, from one build, the Tier 0 projection results and the Tier 2a result of every shipped recipe, as numbers and hashes only, and SHALL list every exception it relies on.

#### Scenario: Calibrated recipe without exception
Given a shipped smart material whose Tier 2a comparison shows a non-zero residual
When no owner-approved exception covers it
Then the report MUST mark it failed and P3-SMART MUST NOT be accepted

### Requirement: Smart Presets Publication Rule
Every shipped smart preset SHALL be an independently designed UzmiGames recipe with a provenance record for itself and every family and resource it uses; observed Adobe preset trees, parameter collections and readbacks MUST NOT appear in the repository or the distribution.

#### Scenario: Release content check
Given the release candidate's `assets/` folder and repository tree
When the publication check runs
Then every smart preset MUST have a provenance record and no file MUST match a private oracle hash in the store index
