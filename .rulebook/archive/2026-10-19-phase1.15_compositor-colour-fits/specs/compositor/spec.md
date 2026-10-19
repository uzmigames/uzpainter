## MODIFIED Requirements

### Requirement: Colour of bitmap sources and colour management
Bitmap sources in every colour space and use, the fill channel defaults, and OCIO colour management SHALL equal their Tier 0 goldens. A use without an exact fit MUST be refused before any mutation with `NotYetSupported` or `evaluator:unsupported_source` naming `phase1.15_compositor-colour-fits`.

#### Scenario: Dense sRGB decode
Given a fill on BaseColor set to `Color(c/255, c/255, c/255, sRGB)` for each of the 256 codes
When `get_source(BaseColor).get_color().working` is read back
Then each value equals the P20-B golden in both recordings

#### Scenario: Unrecorded sRGB bitmap use
Given a 16-bit colour bitmap in the sRGB space bound to a fill on an RGB16 channel, a use no golden records
When the fill is inserted
Then the call raises `NotYetSupported` naming `phase1.15_compositor-colour-fits`, and the document is unchanged
