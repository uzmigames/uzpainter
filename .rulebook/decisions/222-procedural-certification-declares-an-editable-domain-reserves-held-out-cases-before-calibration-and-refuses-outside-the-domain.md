# 222. Procedural certification declares an editable domain, reserves held-out cases before calibration and refuses outside the domain

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase3.1_proc-backend-seam, phase3.2_proc-generator-families, phase3.2_proc-grunge-families, phase3.2_proc-filter-families, phase3.2_proc-material-families, phase3.2_proc-snapshot-backend, phase3.3_procedural-families

## Context

This is the Codex plan review's F-003 (`docs/analysis/plan-purpose-review/02-delivery-risks.md`), checked on main `b44760c`.

- `docs/architecture/05-procedural-content.md` §6 certifies each procedural asset on one matrix: 3 meshes × 3 resolutions × {defaults, recipe sets, two boundary sets} × 2 seeds.
- The phase3.2 family tasks calibrate against private oracles (generator 2.5, grunge 2.4, filter 2.5, material 2.5), then run Tier 2a (3.1) on the same matrix. No case is held out.
- §7 exposes `SourceSubstance.get/set_parameters` over the documented ranges, and no document says which parameters, seeds or geometry are certified.

A fit can therefore match its calibration fixtures and still differ from Painter on the first edit. Frozen snapshots (§4) are exact-signature only and already refuse extrapolation.

The model panel ran one round, together with decision 221:

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| The plan does not separate fitting from generalisation, and exposes editing without a certified domain | AGREE | AGREE | AGREE |
| A declared domain, a held-out set fixed before fitting and a loud refusal outside the domain is the right repair, and is planning-only now | PARTLY (finite samples do not prove a continuous range; keep "exact" honest) | AGREE | AGREE |
| Held-out cases fit the existing recording workflow, and snapshots cannot satisfy them | AGREE | AGREE | AGREE |

Amendments taken from the panel and from the coordinator's Codex constraints:

- Fix the held-out membership before calibration.
- A held-out case used for tuning is replaced, and kept as a regression case.
- The refusal names the field, the value and the certified range.
- The domain covers parameters, seeds and geometry.
- The report states what the cases sample and does not claim proof over continuous ranges.

## Decision

1. **Certified editable domain per asset.** It is declared before calibration and recorded in the provenance record, in `uzpainter assets list --parity` and in the capability manifest. It covers:
   - parameter ranges or sets, with joint constraints;
   - the seed policy;
   - geometry, as checkable image-input properties (mesh-map usages, their resolution, format and colour space, a single UV tile) and the mesh classes the held-out meshes stand for;
   - output resolutions, formats and colour spaces.
2. **Held-out set reserved before calibration.** It is recorded in the same batch as the calibration set, and its hash list is committed before fitting starts. It holds at least:
   - one mesh outside the calibration set;
   - interior parameter points inside each range;
   - other seeds;
   - one resolution.

   An asset is `exact` only if both sets are exact. A held-out case that was looked at to change a fit moves to the calibration set as a regression case, and a new held-out set must be recorded. A held-out failure is a failure, or a candidate owner exception. It is never a reason to refit on the same cases.
3. **Loud refusal outside the domain.** `HlslBackend.canEvaluate` is false outside the domain. Unless a project snapshot matches the request's exact signature, the request raises `UnsupportedProcedural{asset, reason: "outside certified domain", field, value, certified range}` before mutation. Nothing is clamped, nothing is replaced by the nearest point, and no similar asset is substituted. The uncovered part of each documented range is a release gap.
4. **Snapshots stay migration data.** They are exact-signature-only. They never count as calibration or held-out evidence and never widen an editable domain.
5. Planning edits only, made in these places:
   - `05-procedural-content.md` §2, §3, §4, §6 and §7;
   - the seam task (2.1, 2.7, 3.5, new 3.6, 4.1);
   - the four family tasks (a new "declare domain and reserve held-out set" item, ordered before calibration; 3.1 on both sets; a new domain-refusal test; 4.1);
   - the snapshot task (2.2);
   - the parent `phase3.3_procedural-families` (3.1-3.3, 4.1).

## Alternatives Considered

- **Certify only the recorded recipe points.** Rejected: it would make every edit `unsupported` and defeat editable replacement, which is the purpose.
- **Clamp out-of-domain values to the nearest certified value.** Rejected: that is a silent substitution and an art change (§5).
- **Rely on the boundary sets as validation.** Rejected: they are fitted against, so they are calibration evidence.

## Consequences

- Recording batches for Phase 3 families need extra held-out cases, recorded on the owner's machine with the calibration set.
- A certified asset's status means "exact on the declared calibration and held-out cases, inside the declared domain". The Tier 2a report publishes the domain and both result sets.
