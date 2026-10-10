## ADDED Requirements

### Requirement: Wand v1 maps equal to Painter
Every map UzPainter exports for Wand v1 through the unchanged pipeline scripts SHALL equal the private Painter golden at native decoded values; any non-zero difference MUST fail unless an owner-approved exception covers it.

#### Scenario: Tier 1 comparison
Given Wand v1 goldens recorded twice and admitted, and the UzPainter rebuild through the pipeline adapter on DX12
When every exported map is compared at native depth
Then every map is equal and the report lists max |Δ| = 0 and zero differing texels per map

### Requirement: Wand v1 byte-stable
Two UzPainter runs of the Wand v1 rebuild and export with the same build and inputs SHALL produce byte-identical files.

#### Scenario: Two runs
Given the same build, inputs and export configuration
When the rebuild and export run twice in separate processes
Then every exported file has the same SHA-256 in both runs

### Requirement: Report keeps oracle data private
The Tier 1 report MUST contain numbers and hashes only, and SHALL report oracle stability, UzPainter repeatability and equality to Painter separately.

#### Scenario: Published report
Given a completed Wand v1 comparison
When `parity/reports/phase1/tier1-wand-v1.json` is written
Then it contains the three results and per-map statistics, no pixels, and passes the repository guard
