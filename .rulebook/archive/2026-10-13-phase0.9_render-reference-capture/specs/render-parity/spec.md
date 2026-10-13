## ADDED Requirements

### Requirement: Qualified Iray reference capture
No Iray reference MUST be admitted before the capture procedure of `07-preview-and-render-parity.md` §2.2 is qualified, and every admitted reference MUST name the procedure version, its settings sheet and every setting recorded as `uncontrolled`.

#### Scenario: Reference before qualification is refused
Given an Iray render saved before the procedure is qualified
When admission is attempted
Then the reference is not admitted

### Requirement: Noise floor measured per analytic fixture
For every analytic fixture with an admitted reference, the render package MUST publish the Iray run-to-run difference, Iray's Monte-Carlo error at S and UzPainter's error at S as numbers only.

#### Scenario: Noise floor reported
Given two session-separated references and one k·S reference for a fixture
When the noise-floor report is produced
Then it lists the run-to-run difference and both Monte-Carlo error terms for that fixture

### Requirement: Fixture values proposed for ratification
The analytic fixture profile values MUST be proposed to the owner for ratification and MUST NOT be treated as ratified until the owner answers.

#### Scenario: Unratified profile stays proposed
Given the proposed analytic fixture profile
When the owner has not answered
Then the profile is labelled proposed in every report that uses it
