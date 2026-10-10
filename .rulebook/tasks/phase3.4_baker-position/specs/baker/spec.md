# Baker — Position usage

## ADDED Requirements

### Requirement: Position Tier 2b Equality
Position maps MUST equal the Painter CPU goldens on the analytic fixtures and the wand and hat pairs for each exercised `Mode`, `Axis` and `Normalization`, comparing hit/coverage evidence first; a difference MUST pass only through an owner-approved exception.

#### Scenario: Single-axis mode
Given the bevelled cube with highs and a private golden baked with a single-axis `Mode`
When the Tier 2b comparison runs on the owner's machine
Then the map MUST equal the golden or cite an approved exception

### Requirement: Position Normalisation Recorded
The `Position` baker SHALL record the effective normalisation it applied in `baked.effective_normalization` and in the receipt.

#### Scenario: Receipt carries normalisation
Given a `Position` bake with `NormalizationScale` set
When the bake publishes
Then the receipt and the binding MUST both carry the effective bounds and scale used
