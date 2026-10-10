## ADDED Requirements

### Requirement: Tile/channel DAG with subtree-hash cache
The evaluator SHALL evaluate each `(stack, channel, tile)` from revision snapshots, MUST cache node outputs by `(node uid, subtree hash, evaluator_profile, tile)` and SHALL re-evaluate only tiles whose subtree hash changed.

#### Scenario: One-layer edit
Given an evaluated stack of ten layers
When the opacity of one layer changes in a new revision
Then only tiles whose subtree hash changed are re-evaluated and the others are served from the cache

### Requirement: Memory admission
Live tiles MUST stay within the VRAM budget derived from the capability query, and creating a texture set that cannot fit SHALL fail explicitly at creation.

#### Scenario: Body-sized project
Given three 4096² texture sets and a budget that holds one set's live tiles
When all channels are evaluated
Then evaluation completes set by set with LRU eviction and never exceeds the budget

### Requirement: Painter evaluation order and base values
Each channel SHALL start from its template base value and composite root layers bottom-up, with groups composited from a transparent start, `PassThrough` composited directly and `Disable` skipped, exactly matching the Tier 0 goldens.

#### Scenario: Asymmetric stack
Given two uniform fills with a non-commutative blend mode
When the stack is evaluated
Then the result equals the Tier 0 golden for bottom-up order
