# Compositor — Height magnification at 4096 px

## ADDED Requirements

### Requirement: Exact Height Magnification Above 2048 Texels
A bitmap magnified by a bilinear filter on the Height channel of a texture set wider or taller than 2048 texels SHALL give Painter's Height on every texel of every recorded golden, in both recordings, and MUST stay refused before evaluation wherever it is not yet exact.

#### Scenario: The recorded 4096 px golden
Given `tier0/semantics/height-normal-resolution-4096`
When the evaluator evaluates s0 to s3
Then the Height channel and both virtual normal maps MUST equal r1 on every texel

#### Scenario: An unfitted magnification
Given a Height bitmap magnified onto a 4096 px set that no recording fits
When it is evaluated
Then it MUST fail with `evaluator:unsupported_source`, naming decision 400 and this task
