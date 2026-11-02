# 385. Stale Tier 3 references are re-requested under the current envelope: the admitted manifest cloned with the current Painter identity, in the envelope's requests root, scheduled as one OCIO operator series

**Status**: accepted
**Date**: 2026-11-02
**Related Tasks**: phase3.5_path-tracer-materials, phase3.6_path-tracer-tier3-report

## Context

The promotion of `painter-12.2.0+js-api.1.1.20-env-a981b586eae7` left 32 Tier 3 references `stale` (drift report `stale_tier3`: 22 `phase0/iray-references/`, 9 `phase0/iray-stability/`, `tier3/render-procedure/qualification-sphere`). CONTRACT.md §5 and §6.5 bar any whole-product parity claim while one is stale and say they are re-captured "at the next operator session", but nothing said how such a request is staged. Their generator, `tools/parity/render_procedure/references.py`, pinned Painter 12.1.5 and wrote into the superseded envelope's manifest root (inventory `01-inventory.md` §1). The render fits (`tools/parity/render_fits/`) still read those admitted manifests as history.

## Decision

1. **A re-request is the admitted manifest, cloned.** `references.tier3_requests` reads each admitted 12.1.5 manifest (`reference_manifests()` and `stability_manifests()`), replaces `software.painter` with the current envelope's identity from `parity/envelopes/registry.json` and empties `private_records`. Golden ids, inputs, steps, settings and descriptions stay byte-for-byte the same, so the re-capture asks Painter for exactly what was admitted. The test also checks that the generator's own table still produces each request.
2. **Where it goes.** The current envelope's `requests/<golden_id>.json` (the batch compiler's `requests_root`). On admission the store writes the manifest under the current envelope's manifest root at the same relative path. `python -m tools.parity.render_procedure references` now writes these requests and no longer rewrites any superseded envelope's files. The 12.1.5 manifests stay untouched as history, and the fits keep reading them until a re-captured reference is admitted (a fit naming 12.1.5 stays listed for re-check, CONTRACT.md §6.5).
3. **How it is scheduled.** `batch.py` gives the three families the kind `iray-reference`. They form one owned-process session in Painter's substance OCIO configuration (`$env:OCIO` at `<Painter install>\resources\ocio\substance\config.ocio`, decision 038). Each item lists its `iray_conditions`, each with its own command (`recorder iray <request> --condition C [--k 4] --launch --operator ui --operator-id <id>`, plus `--session-file` with the ref_match HDRI for session-environment steps):
   - a reference or the qualification sphere: `separate_session` twice and `k_times_samples` with k 4 once;
   - a stability probe: `separate_session` twice, or `same_session` once for `--same-session`.

   The content de-duplication skips this kind, because a stability repeat has its parent's content on purpose (decision 062).
4. **Panel** (2026-11-02, `cx/gpt-6-astra`, `cx/gpt-6.1-sol`, frozen diff): both marked as a blocker that the first version carried only the first condition's command; fixed (item 3). Both asked for the clone-by-construction of item 1; adopted.

## Alternatives Considered

- **Regenerating from the fixture table with the new build.** Not taken alone: a later edit of the table would silently change a re-capture. The table check stays, as a test.
- **Moving the 12.1.5 manifests into the current envelope.** Rejected: superseded goldens are immutable history (CONTRACT.md §6.5), and the fits read them.

## Consequences

- 32 requests are committed under the current envelope. The batch compiler no longer lists them under `needs_request`.
- Risk: the v2 environment is named by a resource URL whose `version` hash was read under 12.1.5 (`iray_probe.STUDIO_WHITE_SOFT`). If Painter 12.2.0 ships another version of Studio White Soft, those steps fail at record time; nothing offline can tell.
- Operator time is not estimated by the recorder. 23 references take three fresh-Painter renders each and 9 probes take two, about 87 Iray renders at 256 samples or more.
