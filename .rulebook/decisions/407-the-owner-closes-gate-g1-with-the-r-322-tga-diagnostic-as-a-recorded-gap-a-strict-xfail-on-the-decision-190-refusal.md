# 407. The owner closes gate G1 with the R-322 TGA diagnostic as a recorded gap: a strict xfail on the decision-190 refusal

**Status**: accepted
**Date**: 2026-11-08
**Related Tasks**: phase1.26_gate-g1, phase3.2_unreal-ue56-packed-preset

## Context

After the 2026-11-08 recording batch and decisions 404 to 406, six of the seven known failures of gate G1's second full gate (`parity/reports/phase1/gate-g1.md` §9.1, run on `58f7260b`) pass on re-run. The seventh, `tests/export/test_tga_capture_replay.py::test_r322_tga_capture_diagnostic`, fails for one reason only:

- The native candidate refuses the R-322 setup's OCIO session at `encode_export` with `unsupported_source`: "under OCIO, only an 8-bit colour bitmap on an sRGB8 channel sampled 1:1 is recorded (… decision 190)". The setup's colour bitmap is RGB16.
- Decision 406 refuted the one candidate rule for that route (strict comparison in the sRGB8 store). Painter stores the upper code on every exact threshold. The three 16-bit codes whose OCIO decode equals a threshold (2429, 6548, 14017) still store the lower code. The value the decode hands the store there is not identified (hypothesis: a decode evaluated differently for the sRGB8 and RGB32F channel formats).

The test is a diagnostic of a Phase 3 preset (`phase3.2_unreal-ue56-packed-preset` item 2.5). No G1 clause of `docs/roadmap.md` depends on it.

## Decision

1. **The owner closes G1 with this gap** (owner, 2026-11-08, through the coordinator). The gap is the decision-190 refusal of the RGB16 colour bitmap under OCIO in the R-322 setup, nothing broader.
2. **Strict, narrow xfail.** `test_r322_tga_capture_diagnostic` is `pytest.mark.xfail(strict=True, raises=Ocio16BitmapUnsupported)`. `classify` raises `Ocio16BitmapUnsupported` only for the exact native refusal: `blocked` false, `code` `request_failed`, `error` `Failure`, `eval_class` `NotYetSupported`, `eval_kind` `unsupported_source`, `stage` `encode_export`, the decision-190 message, and no candidate file. The test still saves its private report first. Any other failure (another refusal, a setup error, an unsaved report, a differing comparison) stays a test failure. A passing run is an XPASS, which fails under `strict`.
3. **Who removes it.** `phase3.2_unreal-ue56-packed-preset` removes the mark when item 2.5 lands the RGB16 OCIO route. A note on that item names this decision.

## Alternatives Considered

- **Keeping G1 open until the route exists.** Declined by the owner: the route is Phase 3 work.
- **A bare xfail, or one on `pytest.fail`'s exception.** Rejected: it would swallow unrelated failures of the diagnostic.
- **A parity exception.** Not applicable: no Tier 1 or Tier 0 comparison is excepted. This is a gate test's recorded gap, not a relaxation of an equality rule.

## Consequences

- `test_r322_tga_capture_diagnostic` reports XFAIL (2026-11-08, 1 xfailed in 14.7 s, run alone under the native lock).
- Test: `tests/export/test_tga_capture_replay.py::test_only_the_exact_decision_190_refusal_is_the_recorded_gap` (the refusal raises the gap; another stage, another kind, another message or a written candidate raise a plain `SetupFailure`).
