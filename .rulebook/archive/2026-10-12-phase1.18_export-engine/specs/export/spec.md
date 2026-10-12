## ADDED Requirements

### Requirement: Export engine accepted
The export engine SHALL pass the Tier 0 export goldens exactly, produce identical bytes for the same build, project and configuration, and pass every publication interruption test before P1-PYAPI builds on it.

#### Scenario: Acceptance run
Given all four export children are accepted
When the Tier 0 export set, the determinism lane and the interruption suite run
Then every golden is equal, both determinism runs are byte-identical and every interruption leaves one complete generation visible

### Requirement: Nothing reported that was not written
An export result and its receipt MUST list exactly the files written and verified; a failed export SHALL leave the previously published generation selected.

#### Scenario: Encoder failure
Given an export whose third file fails to encode
When the export runs
Then it fails, reports no file as delivered, and `current.json` still selects the previous generation
