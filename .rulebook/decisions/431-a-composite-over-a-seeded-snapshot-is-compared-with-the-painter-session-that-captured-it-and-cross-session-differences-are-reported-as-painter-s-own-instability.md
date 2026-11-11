# 431. A composite over a seeded snapshot is compared with the Painter session that captured it, and cross-session differences are reported as Painter's own instability

**Status**: accepted (owner decision, 2026-11-11, choice "Mesma sessão")
**Date**: 2026-11-11
**Related Tasks**: phase3.3_procedural-families

## Context

Item 2.15 of `phase3.3_procedural-families` composites project-private snapshots (decision 429) inside mask stacks. Its first recordings (`docs/analysis/proc-grunge-families/04-snapshot-in-mask-2026-11-10.md`) found that Painter does not reproduce its own seeded sources across sessions:

- In a fresh Painter session, `grunge/dirt-a` (seeds 1 and 2), Dirt at its default seed and Mask Builder - Legacy differ from the 2.13/2.14 capture on 4 to 10 of 65 536 texels, by up to 23 16-bit codes.
- Which texels differ changes from session to session. Within one session, r1 equals r2 (after save and reopen) on every texel.

A snapshot is byte-equal to the session that captured it, so no snapshot predicts every texel of another session. Exact parity against an independent recording therefore needed a comparison rule. The analysis named two options: a same-session reference, or an exception, which only the owner may approve. The owner chose the same-session reference.

## Decision

1. **The reference is the capturing session.** For a composite over a snapshot of a seeded source (`grunge/dirt-a`, Dirt, Mask Builder - Legacy, and any other seeded snapshot), the exact reference is a Painter recording made in the Painter session that captured the snapshot.
   - The probe does both in one session: `tests/python/capture_snapshot_in_mask_session.py` captures the destination project's snapshots with `UzPainter.exe assets snapshot`, then records the Tier 0 composites (`tier0/semantics/snapshot-in-mask-session`) before Painter stops.
   - The comparison is byte-equal on every texel of every exported map, against r1 and r2. No tolerance is introduced.
   - The rule is the owner's for seeded snapshots. An unseeded snapshot (`grunge/rock`, `grunge/dirt-large`) has been equal to its capture in every recorded session, so a recording of any session is its reference, as for any other golden.
2. **Cross-session differences are reported, not compared.** A recording from another Painter session is Painter's own instability for these sources, as EXC-001, EXC-002 and EXC-006 record Painter's instability across save and reopen.
   - The counts (differing texels, largest difference in codes) are published in the analysis. They gate nothing.
   - No exception entry, bound or tolerance is created, because no comparison is made against the other session.
3. **Nothing else changes.**
   - UzPainter still serves only the snapshot stored in the user's own project, at its exact signature (decision 429 §2, §5). Its output is a function of that snapshot, never of another session.
   - A snapshot still certifies nothing (decision 222) and makes no parameter editable.
   - Every other golden keeps its own reference rule (decisions 032 and 034).

## Alternatives Considered

- **An exception over the cross-session texels.** Not chosen by the owner. It would bound a difference that UzPainter cannot reproduce from the user's snapshot.
- **Comparing with the 2026-11-10 goldens.** Rejected. They were recorded in sessions other than the capture's, so their seeded texels are not the snapshot's.

## Consequences

- Item 2.15 is measured on one session: the destination project of that session (store record `snapshot-in-mask-session-project`) and its goldens `snapshot-in-mask-session` and `snapshot-in-mask-read`.
- The 2026-11-10 goldens `snapshot-in-mask` and `snapshot-in-mask-sources` stay admitted. They are the cross-session evidence the analysis reports.
- **Measured on 2026-11-11 (Painter lock seq 2378 to 2379): the same session is not enough for seeded sources.** Evidence: `docs/analysis/proc-grunge-families/05-snapshot-in-mask-session-2026-11-11.md`.
  - The composites over `grunge/dirt-a` (both seeds), Dirt at its default seed and Mask Builder - Legacy still differ from the model over that session's own captures, on 1 to 10 of 65 536 texels by up to 21 codes. r1 equals r2.
  - So each Painter instance of a seeded source can differ from another one on a few texels, within one session too. The capture's instance does not predict the mask stack's instance.
  - Under this decision these composites are not exact. Seeded grunge snapshots and generator effects therefore stay refused in a mask stack.
  - The fixed grunges `grunge/rock` and `grunge/dirt-large` equal every recording of them in a mask. They are served as a mask fill source.
