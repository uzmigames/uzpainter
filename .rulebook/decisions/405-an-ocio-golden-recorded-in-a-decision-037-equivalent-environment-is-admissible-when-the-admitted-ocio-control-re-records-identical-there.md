# 405. An OCIO golden recorded in a decision-037 equivalent environment is admissible when the admitted OCIO control re-records identical there

**Status**: accepted
**Date**: 2026-11-08
**Related Tasks**: phase0.9_oracle-envelope, phase3.2_unreal-ue56-packed-preset, phase1.26_gate-g1

## Context

On 2026-11-08 the host's AMD integrated GPU driver (32.0.11024.2 -> 32.0.21042.62) and OS build (26200.9457 -> 26200.9711) changed. Decision 037's other-environment branch ran the Legacy canary (10 goldens unchanged, 21 equal pairs) and `03cd9f97` recorded the environment `820cb084…` in `equivalent_envelopes`.

Decision 309 compares an OCIO session's five envelope fields with those of the admitted OCIO goldens (references), all recorded under the previous host. The driver and OS fields are in the five, so every OCIO session on the equivalent host was `other_environment` (exit 3). The OCIO decode-stage control `ocio16-bitmap-srgb-basecolor-rgb32f` (`04a12cb9`) was recorded but not admitted for that reason. Decision 309 item 6 forbids adding an OCIO hash to `equivalent_envelopes`, because the canary is Legacy.

Evidence: the admitted OCIO control `tier0/api-probes/ocio16-bitmap-srgb-basecolor` was re-recorded on the new host under the record prefix `hostcheck-` (inbox run `20261108T201538…`). Against the admitted golden record: same golden id and key; both recordings (r1 `same_session`, r2 `after_save_reopen`) have the same outputs, and the 6 exported maps (PNG8, PNG16, EXR32f, r1 and r2) are equal by hash; only `session_id` and `recorded_at` differ. The environment differs only in the driver, the OS build and the recorder version; the colour configuration hash (`8f384af9…`) and the Painter build are the golden's.

## Decision

1. **Control re-recording.** A re-recording of an admitted golden naming an `OCIO` configuration, under the record prefix `hostcheck-` and admitted beside the golden's own records (`store record --run`), is a control. `tools/parity/envelope/ocio.py` `control_environment` verifies it from the manifest and the store: golden and environment records present on both sides; every `hostcheck-` blob record has the hash of the golden's record of the same id; golden id, key and each recording's id, condition and outputs equal (the outputs name every exported blob by hash); colour configuration and Painter build equal. A verified control's environment joins the references, marked `ocio_control_of` (the golden id); an unverified one is ignored.
2. **Admissible identity.** `ocio_reference_state` takes the references recorded under their own identity (not a control's hash) as before: one envelope hash, recorded on an anchor host. A verified control's hash is admissible too when its host fields are an anchor's (the registry's environment or a decision-037 equivalent one: the anchors decision 309 already reads) and its colour configuration is the identity's. An OCIO session or a recorded OCIO golden on that hash is `ocio_reference`, and goldens recorded there join the references without splitting them. Any other hash still splits the references or is `other_environment`; a session on an equivalent host without a verified control is `other_environment`, naming this decision.
3. **Nothing relabelled.** The registry is read, never written; `equivalent_envelopes` keeps only Legacy-canary environments. Each golden keeps its own environment record. No comparison is loosened: the control must reproduce the golden exactly.
4. **Admitted under this decision (2026-11-08):** the control's `hostcheck-` run into `manifests/tier0/api-probes/ocio16-bitmap-srgb-basecolor.json` (16 private records), then `ocio16-bitmap-srgb-basecolor-rgb32f` (4 records): its recorded environment is `ocio_reference` by item 2, and `envelope check --request` on the running OCIO session exits 0 with the same answer. Both inbox runs were deleted after admission; `store verify` lists every record `available`.
5. **Fit-tool record filters.** `tools/parity/fit/ao_operand_control.py` and `padding_plane_control.py` accepted only the registry's envelope hash; they now accept `equivalent_envelopes` too, as `plane_transform_diagnostic.validate_record` does since `df3b2da3` and as detection does.

## Alternatives Considered

- **Adding the OCIO hash to `equivalent_envelopes`.** Rejected by decision 309 item 6: the canary is Legacy.
- **Re-recording every OCIO golden on the new host.** Rejected: the identical control already shows the OCIO path unchanged there, at the cost of one recording.
- **Accepting any anchor host without a control.** Rejected: the Legacy canary does not exercise the OCIO path; the control does.

## Consequences

- `python -m tools.parity.envelope check --request <OCIO request>` exits 0 on the 2026-11-08 host.
- A later host change needs its own Legacy canary and its own `hostcheck-` control before OCIO recordings there.
- Tests: `tests/parity/test_oracle_envelope.py` (`test_ocio_on_an_equivalent_host_needs_an_identical_control`, `test_control_environment_*`), `tests/parity/test_ao_operand_verifier.py` (the equivalent case of the identity test), `tests/parity/test_padding_plane_control_fit.py::test_record_environment_is_the_current_envelope_or_an_equivalent`.
