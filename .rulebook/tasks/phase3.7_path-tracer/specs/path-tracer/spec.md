# Path tracer — P3-PATHTRACER integration

## ADDED Requirements

### Requirement: Path Tracer Parent Closure
The P3-PATHTRACER work package SHALL close only when `phase3.4_path-tracer-transport`, `phase3.5_path-tracer-materials` and `phase3.6_path-tracer-tier3-report` have each passed their own acceptance.

#### Scenario: Report child open
Given transport and materials are accepted and the Tier 3 report child is not
When the parent acceptance is evaluated
Then `phase3.7_path-tracer` MUST stay open and name `phase3.6_path-tracer-tier3-report`

### Requirement: Tier 3 Passes Only Through Approved Exceptions
A Tier 3 comparison and any DXR-versus-Vulkan bound MUST pass only through an owner-approved, versioned entry in `parity/exceptions.json`; without one the comparison SHALL be reported `blocked`, never passed.

#### Scenario: No approved entry
Given a Tier 3 comparison whose statistics fall inside a proposed bound that the owner has not approved
When the Tier 3 report is produced
Then the comparison MUST be reported `blocked` and the proposal MUST be listed for owner approval

### Requirement: Painter Iray Capability Scope
The capability manifest MUST report `painter_iray` as supported only for the fixture classes and project configurations covered by approved register entries, and MUST list every other configuration as a gap.

#### Scenario: Unapproved configuration
Given an OCIO project configuration that no approved entry covers
When the capability manifest is regenerated
Then `painter_iray` for that configuration MUST appear as a gap
