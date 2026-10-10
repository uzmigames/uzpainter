# Baker — Height usage

## ADDED Requirements

### Requirement: Height Tier 2b Equality
Height maps MUST equal the Painter CPU goldens on the analytic fixtures and the wand and hat pairs for the exercised `MaximizeRange` and `Divisor` settings, comparing hit/coverage evidence first; a difference MUST pass only through an owner-approved exception.

#### Scenario: Divisor sweep
Given the bevelled cube with highs and private goldens for two `Divisor` values
When the Tier 2b comparison runs on the owner's machine
Then both maps MUST equal their goldens or cite approved exceptions

### Requirement: Height Range And Units Recorded
The `Height` baker SHALL record the effective range, divisor and distance units in `baked.effective_normalization` and in the receipt.

#### Scenario: Receipt carries range
Given a `Height` bake with `MaximizeRange` enabled
When the bake publishes
Then the receipt and binding MUST carry the effective range, the divisor and the unit
