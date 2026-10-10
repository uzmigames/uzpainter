# P0-TIER0 acceptance — owner's machine run

Task `phase0.8_tier0-goldens`, the integration and acceptance task of P0-TIER0 (`docs/dag.md`; D3, D5, D9, D13). Decision 028: oracle checks run locally on the owner's machine and this report is their evidence. Run on 2026-10-10 on the tree of commit `c656753` with the working-tree changes of that moment (none under `parity/manifests/tier0/`, `parity/semantics/` or `tools/parity/`, apart from another task's new `tools/parity/normal_convention/`). Numbers and hashes only; every recorded output stays in the private store. The children's evidence: `parity/TIER0-SEMANTICS.md`, `parity/RECORDER.md`, `parity/FITS.md`, `tier0-stability.md` (this folder) and the archived children's `tasks.md`.

**Result: P0-TIER0 accepted.** All 59 Tier 0 goldens are recorded at least twice and verify in the store; each is classified (53 stable, 6 unstable); six `parity/semantics/*.json` files are published, every fit with its public source and residuals; the guard blocks nothing.

## Gate

| Gate item (`docs/dag.md`) | Evidence of this run | Verdict |
|---|---|---|
| Each golden recorded ≥ 2× | 59 manifests under `parity/manifests/tier0/` (api-probes 9, defaults-templates 2, recorder-sample 1, semantics 47). Every private record resolves in the store, passes the private-record schema and its cross-field rules, and holds both `same_session` and `after_save_reopen` recordings: 57 records with 2 recordings, `baking-defaults` with 3, `lifecycle-events` with 4 | met |
| Stability classified | `tier0-stability.md` §2 classifies every measured storage format (five export formats and JSON readbacks and captures) and §3 every golden: 53 stable (exact goldens), 6 unstable (`insert-positions`, `mask-stack`, `textureset-project-readback`, `ao-mixed`, `blend-inputs`, `quantisation-thirds`), not admitted as exact goldens; their statistics are the exception evidence of §4; no exception is proposed and `parity/exceptions.json` is unchanged | met |
| Fits published | `ao-mixed.json` (2 entries), `blend-modes.json` (34), `evaluator-profile.json` (4), `height-to-normal.json` (4), `resampling.json` (4), `srgb-transfer.json` (3): 51 entries, each naming its public sources. The 49 fits (6 exact, 43 calibrated) carry residuals against both recordings, as numbers; the 2 `gap` entries (`blend-passthrough`, `height-normal-second-method-and-strength`) carry no fit and no residual, because their cases moved to `phase0.7_tier0-semantics-ui-cases`. `python -m tools.parity.fit check` re-ran every fit against the store and reproduced the published residuals | met |

## Integration checks (tasks.md §3)

| Check | Command | Result |
|---|---|---|
| Whole-store integrity | `python -m tools.parity.store verify` | exit 0, `store C:\Users\Bolado\AppData\Local\UzPainter\parity-store: ok` |
| Every manifest hash (`uzpainter parity verify`) | `python -m tools.parity.store verify parity/manifests` | exit 0; 76 manifests, 2587 listed blobs, all `available` (the Tier 0 subset: 59 manifests, 2523 blobs) |
| Fits reproduce | `python -m tools.parity.fit check` | exit 0, `reproduced: blend, profile, srgb, normal, resample, ao` |
| Guard on the repository | `python -m tools.parity.guard` | exit 0; store-hash rule against the store index (722 hashes); 1932 files checked, 0 blocked |
| Gate tests | `python -m pytest tests/parity/test_tier0_gate.py` | 64 passed with the store; 61 passed and 3 skipped ("no private oracle store on this machine") without it |

## Prerequisites and children

Prerequisites `phase0.3_painter-oracle-recorder` and `phase0.5_private-oracle-store`, and the four children `phase0.6_tier0-semantics-goldens`, `phase0.6_tier0-defaults-templates`, `phase0.6_tier0-api-probes`, `phase0.7_tier0-stability-fits`, are archived. `phase0.7_tier0-semantics-ui-cases` (the `PassThrough` group with masks, the second height-to-normal method and the strength sweep) is not a prerequisite of this task or of G0 (owner answer, 2026-10-10); until it closes, those cases are release gaps.

## What the gate does not claim

None of the eleven `04-layer-stack-and-compositing.md` §9 items is settled yet (`tier0-stability.md` §6): settlement needs exact fits over stable goldens and belongs to the Phase 1 compositor tasks, which name the Tier 0 tests they own (`docs/dag.md`, P1-COMPOSITOR "Tier 0 semantics exact for the implemented subset"). The six unstable goldens stay out of exact comparison until they are re-recorded stable or an exception is proposed and accepted (`14-parity-testing.md` §5).

## Reproduce

```
python -m tools.parity.store verify
python -m tools.parity.store verify parity/manifests
python -m tools.parity.fit check
python -m tools.parity.guard
python -m pytest tests/parity/test_tier0_gate.py
```
