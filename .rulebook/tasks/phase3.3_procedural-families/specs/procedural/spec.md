# Procedural — P3-PROC integration

## ADDED Requirements

### Requirement: Procedural Parent Closure
The P3-PROC work package SHALL close only when every mandatory child task (`phase3.1_proc-backend-seam`, `phase3.2_proc-snapshot-backend`, `phase3.2_proc-generator-families`, `phase3.2_proc-grunge-families`, `phase3.2_proc-filter-families`, `phase3.2_proc-material-families`) has passed its own acceptance.

#### Scenario: Family still uncertified
Given every procedural child is accepted except `phase3.2_proc-material-families`
When the parent acceptance is evaluated
Then `phase3.3_procedural-families` MUST stay open and name the missing child

### Requirement: Tier 2a Report Published
The system MUST publish a Tier 2a report for every certified asset over the certification matrix of `05-procedural-content.md` §6, with numbers and hashes only, and an asset MUST pass only with zero residual or an owner-approved exception.

#### Scenario: Calibrated asset without exception
Given a certified asset whose p99 |Δ| is non-zero and no exception covers it
When the Tier 2a report is produced
Then the asset MUST be reported as failed with its max/mean/p99 |Δ| and affected-texel count, and the parent MUST NOT pass

### Requirement: Procedural Gaps Visible
The capability manifest MUST list every uncertified Painter procedural and arbitrary `.sbsar` execution as release gaps, and `uzpainter assets list --parity` MUST agree with the published report.

#### Scenario: Manifest consistency
Given the Tier 2a report and the regenerated capability manifest
When `uzpainter assets list --parity` runs
Then each asset's status MUST match the report and every uncertified asset MUST appear as a gap
