## ADDED Requirements

### Requirement: Painter-equal export processing
Padding, resize, dithering and bit-depth/colour encoding SHALL reproduce the Tier 0 export goldens exactly on decoded pixels at native depth.

#### Scenario: Infinite padding at 16 bit
Given a channel with islands exported as PNG 16-bit with infinite padding and no dithering
When the export runs
Then the decoded pixels equal the Tier 0 golden

### Requirement: Byte-deterministic encoders
The same build, project and configuration MUST produce byte-identical PNG and EXR files.

#### Scenario: Two exports
Given one project and one configuration
When the export runs twice in separate processes
Then every file is byte-identical
