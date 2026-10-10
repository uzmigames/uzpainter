## ADDED Requirements

### Requirement: Oracle stability classified
Every Tier 0 golden's recordings MUST be compared at native decoded depth, and each channel type, classified by measured storage format, SHALL be reported as `stable` or `unstable` with max |Δ|, mean |Δ| and differing-texel count; an unstable golden MUST NOT be admitted as an exact golden.

#### Scenario: Painter reproduces itself
Given two recordings of a blend-sweep golden that are byte-identical
When the stability comparison runs
Then the golden is classified `stable` and admitted

#### Scenario: Painter does not reproduce itself
Given two recordings of a golden that differ in some texels
When the stability comparison runs
Then the golden is classified `unstable` with its statistics, is not admitted as exact, and its statistics are kept as exception evidence

### Requirement: Clean-room fits with residuals
Each published fit in `parity/semantics/` MUST name its formula, parameters, colour space, clamping, public source, the golden hashes used and its residual at storage precision; it SHALL NOT contain recorded Painter values.

#### Scenario: Blend-mode fit published
Given the `Multiply` sweep goldens and the W3C Compositing and Blending Level 1 candidate
When the fit runs
Then `blend-modes.json` holds the fitted formula with its source and its max |Δ|, mean |Δ| and differing-texel count

#### Scenario: Guard rejects a recorded value
Given a fits file into which a recorded readback was pasted
When the repository guard runs
Then the file is rejected

### Requirement: Evaluator profile settled
The quantisation points and the blending space of sRGB8 channels MUST be settled by the three-1/3-opacity-fills experiment and recorded as an evaluator profile with id `painter-12.1-<profile-id>`.

#### Scenario: Quantisation model chosen by evidence
Given the exact and per-layer-quantised models of the three-fill stack
When both are compared with the golden
Then the model that reproduces the golden is recorded in `evaluator-profile.json` with its residual

### Requirement: Settlement of the Tier 0 list
The stability report SHALL list every item of `04-layer-stack-and-compositing.md` §9 as settled or not settled with the golden hashes and residual that decide it; a fit with a non-zero residual MUST be reported as an open item, not as settled.

#### Scenario: Unsettled item reported
Given a height→normal fit with a non-zero residual
When the report is written
Then the item is listed as not settled with its residual
