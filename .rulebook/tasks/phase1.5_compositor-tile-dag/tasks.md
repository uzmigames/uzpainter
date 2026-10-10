## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.4_render-core-layer, phase1.3_document-model, phase0.8_tier0-goldens

## 2. Implementation
- [ ] 2.1 Implement the `(stack, channel, tile)` DAG with 1024×1024 tiles and the `(node uid, subtree hash, evaluator_profile, tile)` cache
- [ ] 2.2 Implement invalidation by subtree hash on every revision and evaluation on revision snapshots through the engine thread
- [ ] 2.3 Implement memory admission from the VRAM budget with dependency-order evaluation and LRU eviction; refuse texture-set creation above the budget explicitly
- [ ] 2.4 Implement the evaluation order: base value, root layers bottom-up, groups from a transparent start, `PassThrough`, `Disable`
- [ ] 2.5 Implement generated-kernel emission per (node kind, blend mode, channel format) through the kernel cache, with `precise` arithmetic
- [ ] 2.6 Author `assets/templates/*.json` (channel sets, formats, base values) with a provenance record per entry

## 3. Tests
- [ ] 3.1 Tier 0 base-value goldens: an empty project per template exports values equal to the private captures (LAY-10)
- [ ] 3.2 Tier 0 template goldens: channel sets and storage formats per template equal the private captures; template JSON checked against them on the self-hosted runner
- [ ] 3.3 Tier 0 order goldens: asymmetric blends on stacked uniform fills confirm bottom-up evaluation
- [ ] 3.4 Tier 0 group goldens without masks: `Normal` and `PassThrough` groups equal the goldens; `Disable` skips the node per channel
- [ ] 3.5 Cache/invalidation unit test: editing one layer re-evaluates only tiles whose subtree hash changed
- [ ] 3.6 Admission unit test: under a small artificial budget three 4096² sets evaluate in sequence with LRU eviction; a set above the budget is refused at creation

## 4. Acceptance
- [ ] 4.1 Tier 0 sets of this child exact on the self-hosted GPU runner (DX12); unit tests green

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
