# 63. P0-FEAS-RENDER stays open until the qualification sphere has its term (c) and the owner signs the path-tracer entry gate record

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase0.9_render-reference-capture, phase3.7_path-tracer

## Context

Task `phase0.9_render-reference-capture` is P0-FEAS-RENDER, the sole entry gate of P3-PATHTRACER (decision 033). Its three children are archived: the procedure `iray-capture/1` is qualified (phase0.6, decisions 038, 039), 23 reference goldens are admitted with 69 references (phase0.7, decision 046), and the noise floor, first lobe fits and GPU probes are published (phase0.8, decisions 050-052). Measured by this task:

- All 69 admitted references name `iray-capture/1` in their sheet, carry the settings sheet's SHA-256 on every reference output of their private record, and list `random_seed` as `uncontrolled` (item 3.1).
- Decision 052's capture request and decision 033's reproducibility probe are recorded and published (decision 062, `iray-noise-floor.md` §9).
- The noise-floor report gives (a), (b) and the prototype's (c) for the 22 fixtures of decision 046. The qualification sphere has (a) and (b) (`iray-references.md` §4) but no (c): its material is the template default of an OCIO project, which has never been read back, so the prototype has no scene for it. Decision 046 counts the sphere in the reference set ("22 goldens plus the qualification sphere"; "the qualification sphere completes as the default-material fixture"), and phase0.6 item 3.1 calls it an analytic fixture.
- Signing gate records is an owner-only action.

Model panel under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5, 2026-10-11):

| Claim | Verdicts |
|---|---|
| R6 Item 3.2 is met with the sphere's (c) stated as missing | PARTLY x3: met only if decision 046 excludes the sphere from the analytic fixtures; it does not, so compute (c) or hold 3.2 open (two of three); one would close with an explicit exclusion |
| R7 Archive the task now, signature pending | PARTLY x2, DISAGREE x1: the signature is the gate act; keep the task open as "ready for gate" and archive on signature |

## Decision

1. Item 3.2 stays open until the qualification sphere has its term (c): read back the template-default material of an OCIO project (empty-stack BaseColor, BaseMetalness and SpecularRoughness) as a hashed private record, then measure the prototype's (c) on the sphere as the noise-floor report's §3 does. Owner: this task, with the next Painter session.
2. The gate record `parity/reports/phase0/gate-p3-pathtracer-entry.md` is written now with result "held open": every other clause of P0-FEAS-RENDER is evidenced (procedure, admitted references with item 3.1 checked, noise floor, fixture content proposed, reproducibility probe), and it lists the owner's signature and item 3.2 as what remains.
3. The task is not archived until both close. P3-PATHTRACER does not start before then; it also needs P1-CORE, P2-TUNIC and P3-VULKAN.
4. Ratification of the fixture content is not a closing condition (task item 3.3 and the render-parity spec: the profile stays labelled proposed until the owner answers).

## Alternatives Considered

- Close item 3.2 by excluding the sphere from the analytic fixtures (rejected: decision 046 and phase0.6 count it in).
- Archive before the signature (rejected by the panel: the signature is the gate act).

## Consequences

The task stays in `.rulebook/tasks/` with items 3.2 and 4.1 open; the owner's actions are the signature and, optionally, the ratification of the fixture content.
