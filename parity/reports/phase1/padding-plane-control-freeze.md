# Fresh endpoint-plane control: pre-capture predictions

Date: 2026-10-23. Status: authored, CPU-scored, not recorded or admitted.
Task: phase1.25_pilot-wand item 2.7. No production policy change.

`tools/parity/tier0_semantics/padding_plane_control.py` defines 32 copies of a
2-by-2 control: one versus two internal tau hinges, and regular versus slender
triangle aspect. A single 12-degree corner is truncated symmetrically to form
two 6-degree hinges. The initial and final supporting planes are identical
between the two constructions; the final endpoint positions and UVs coincide.
The intermediate facet replaces part of the corner, so local surface geometry
does change. This is not a claim of identical intermediate distances.

Widths 4 and 16 cm change aspect at fixed UVs. Both quad diagonals, a translated
duplicate, a 90-degree rigid duplicate and an oblique rigid duplicate exercise
conditioning and box-normalized arithmetic. Existing packing anchors fix the
mesh box at [-256,256] x [-64,64] x [-256,256] cm. The normal gate sees a single
12-degree hinge versus two 6-degree hinges. Their combined endpoint-plane
relation to the far chart is shared, separating physical-hinge development
from the generic direct-plane hypothesis.

## Frozen predictions

All three CPU policies predict 1,280 ring texels using the standard eight RGB32F
kernel-source maps and recomputed tap ordering. No Painter pixels were read.

| Comparison | Differing texels | Two-tap | Four-tap |
| --- | ---: | ---: | ---: |
| Baseline versus generic J/tau | 80 | 16 | 64 |
| Baseline versus conservative J/tau | 0 | 0 | 0 |
| Generic versus conservative J/tau | 80 | 16 | 64 |

Differences occur in all sixteen one-hinge copies: six per regular copy, four
per slender copy. All sixteen two-hinge copies are negative controls with
identical predictions across policies. Thus this probe discriminates generic
J/tau from the count-restricted candidate on fresh geometry; it cannot by itself
prove a general two-hinge cutoff or explain every earlier slender-triangle miss.

The first 12 source components provide support/centroid information; the last
12 verify predicted mixtures. These are the existing one-hot/ramp and code
maps, including affine/superposition controls, not 24 statistically independent
channels. Verification must retain float32 bits, report support/order changes,
score every ring texel and both aspect groups, and check repeated infinite
exports plus save/reopen. All covered texels must reproduce authored inputs.
Uncovered passthrough stability is separate from infinite-policy scoring.
Do not change predicates after observing the capture; a changed hypothesis
requires separately identified predictions and new verification evidence.

Nine authored tests pass, covering endpoint planes, nonzero 6-degree hinges,
deterministic geometry, rigid duplicates, fixed-box containment and the export request.
Ruff and mypy pass for the fixture module and its test. No GPU/Painter used.
After registry integration, all 162 control, recording-request and Tier 0
semantics tests pass; the generated fixture/request catalog is current.

## Hash commitments

| Artifact | SHA-256 |
| --- | --- |
| Authored OBJ bytes | `3e406f3fae528e122b62e93ecb1db63214455d0dc9951d73a1b74d890201b7bb` |
| Frozen complete CPU predictions | `5b98e22a8d9c288a7b14e8dbe08c3216b7fb90b18fed2950d022bb5a5339224e` |
| Fixture module | `fd3adddbc66eda64e15674647499ced45366b2a971361c3d1a9e21bba4dc8255` |
| Scratch freeze script | `5db2d8e38cf4a43f62c29dcea82c28eeec7010757c42da845eb92b9c2ba0094c` |
| Generic J/tau scratch source | `28119f768f1d880d0593f568739c9942fb0a4204b5878856b539bc6e809d4e34` |
| Conservative J/tau scratch source | `4b9eff71a82cdf76ea06809f54b569eb82171d23b7b2f41cbf2beb8057998e4b` |
| Baseline reference | `c36795882a04c6ee6ff956f4280e4e58a5e605451039dc4f3b0df732e82e546a` |

Predictions and the suggested registry integration patch are local scratch
artifacts under `scripts/tmp/plane-control-freeze/`; only aggregates and hashes
are published here. The fixture and material are registered in the request
catalog; the generated current-envelope request is pending capture. No admission
is claimed. Painter remains closed while the full suite owns the GPU.

## Bounded capture batch

The next batch starts only after the full suite releases the GPU. Its hypothesis
and three predictions remain exactly those committed above: the 80 differing
one-hinge texels distinguish the generic policy; the two-hinge copies are negative
controls. The batch shares at most 60 minutes of live recording with the authored
AO and R-322 controls, followed by at most 30 minutes of initial CPU scoring.
The private run ledger records start/end times and elapsed time; waiting for the
suite is excluded. Stop on timeout, identity change, failed state precondition or
completion of the declared repeats/reopen. Preserve every residual, record the
outcome and select a separately documented next hypothesis before another batch.
Neither timeout nor agreement on this control changes the production refusal.

CPU verifier: `python -m tools.parity.fit.padding_plane_control --manifest <admitted-manifest> --predictions scripts/tmp/plane-control-freeze/predictions.json`.
It checks the raw record identity before indexing, frozen inputs/protocol,
effective RGB32F state, covered inputs and every infinite repeat/reopen. Scores
cover all 1,280 ring texels by policy, hinge count and aspect group. Uncovered
passthrough changes are separate. The freeze does not contain ordered tap lists,
so the report explicitly declines to certify tap order. Its 21 authored tests,
Ruff and mypy pass; this is verification tooling, not a new observation.
