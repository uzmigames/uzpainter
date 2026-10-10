## ADDED Requirements

### Requirement: Uniform and bitmap sources
Fill layers SHALL evaluate uniform-colour and bitmap sources per active channel with explicit colour-space handling, and MUST bind bitmaps by content hash so that same-named resources can differ per node.

#### Scenario: Same alias, different bytes
Given two fill layers binding different mask bytes under the alias `M_piping`
When the stack is evaluated
Then each layer uses its own bound bytes

### Requirement: UV projection and filtering
The `Fill` and `UV` projections SHALL implement the documented filters, wrap modes and transform with in-kernel filtering equal to the Tier 0 resampling goldens, and a 1:1 bitmap MUST be copied exactly.

#### Scenario: BilinearHQ at scale 1
Given a 16-bit sRGB BaseColor bitmap in final-UV space with scale 1, no repeat and `BilinearHQ`
When the fill is evaluated
Then the BaseColor channel equals the Tier 0 golden
