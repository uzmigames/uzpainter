## ADDED Requirements

### Requirement: Vector Sources Equal to Painter
A fill or fill effect with a `vector` source SHALL rasterise the embedded vector file and evaluate it with output equal to the Tier 0 goldens.

#### Scenario: Vector logo on a sphere
Given a UzmiGames-authored vector file used as a BaseColor source on the sphere fixture
When BaseColor is exported at 16 bit
Then the decoded values equal the private Painter golden exactly

### Requirement: Font Sources Equal to Painter
A fill or fill effect with a `font` source SHALL render the given text with the embedded font and its documented parameters, with output equal to the Tier 0 goldens.

#### Scenario: Text in a mask stack
Given an openly licensed font and a text string used as a source in a layer's mask stack
When the masked channel is exported at 16 bit
Then the decoded values equal the private Painter golden exactly

### Requirement: Vector and Font Sources Persist and Read Back
Vector and font source parameters MUST read back exactly through freshly resolved handles before and after save/reopen, and their files SHALL be stored as content-addressed resources.

#### Scenario: Readback after reopen
Given a font source whose size and text were set through the facade
When the project is saved and reopened
Then the readback returns the same values and the font file is resolved by its SHA-256

### Requirement: Licensed Rasteriser Dependencies
Every library used to rasterise vector or font sources MUST be vendored from upstream with a confirmed Apache-2.0-compatible licence listed in `NOTICE` and `LICENSES/`.

#### Scenario: Inventory check
Given the vendored rasteriser libraries
When the dependency inventory check runs
Then each library has its licence, origin and notice recorded and no entry is "not confirmed"
