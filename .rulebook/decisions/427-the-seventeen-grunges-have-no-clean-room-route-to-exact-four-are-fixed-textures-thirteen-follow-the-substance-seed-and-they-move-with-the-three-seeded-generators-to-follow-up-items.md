# 427. The seventeen grunges have no clean-room route to exact: four are fixed textures, thirteen follow the Substance seed; they move with the three seeded generators to follow-up items

**Status**: accepted (coordinator scope split under the owner's throughput rule, 2026-11-10). No candidate exception is proposed: there is no candidate. The route for these assets is the owner's to choose.
**Date**: 2026-11-10
**Related Tasks**: phase3.2_proc-grunge-families, phase3.3_procedural-families

## Context

`phase3.2_proc-grunge-families` certifies the seventeen grunges the recipes use (decision 331) and, since decision 425, the Dirt, Metal Edge Wear and Mask Builder - Legacy generators that read Painter's seeded grunge. Each must be exact, or covered by an owner-approved exception; otherwise it is a release gap.

Painter 12.2.0 was recorded on 2026-11-10 (Legacy, Painter lock seq 2372 to 2373):

- eleven diagnostic goldens on the authored plane, each grunge as a mask source at seeds 1 and 2 at 1024 and seed 1 at 2048, or at its defaults where it has no seed;
- every case's readback of the grunge source through the documented `Property` API.

Two first goldens were refused because `grunge/dirt-large` has no `$randomseed`. Their requests are kept. Numbers: `docs/analysis/proc-grunge-families/03-diagnostic-evidence-2026-11-10.md`. Parameters: `02-parameter-discovery.md`. r1 equals r2 on every texel of every case.

## Decision

1. **Four grunges are fixed textures.**
   - `grunge/rock`, `grunge/stone-details` and `grunge/scratches` list a seed, but seeds 0, 1 and 2 give identical outputs.
   - `grunge/dirt-large` has no seed. Its 1024 output is the 2 x 2 mean of its 2048 output within 7.7e-6, with 1 016 distinct values.
   - Exact equality with a fixed texture reproduces its content. That is Adobe asset content, which the clean room never copies or ships (`docs/licensing-and-clean-room.md` §1 items 1 and 3).

2. **Thirteen grunges follow the Substance seed.**
   - The seed changes 30 % to 100 % of the texels, by up to 1.0. The best cyclic translation leaves about as many different.
   - The output is a function of the seed through the Substance engine's random number generator and each graph. No public source describes either, and recovering them from outputs would reverse-engineer Adobe's engine.
   - This extends to each asset the feasibility study's finding for the grunge inside Metal Edge Wear (`parity/reports/phase0/procedural-feasibility.md` §1).

3. **No fitting was run, and no exception is proposed.** The ~2 h time box per family cannot change §1 or §2: no UzPainter pattern kind (decision 331 §3) has a parameter that turns it into an Adobe texture or Adobe's random sequence. With no candidate there is no residual to offer as a candidate exception.

4. **The three seeded generators inherit §2.** Dirt, Metal Edge Wear and Mask Builder - Legacy change with the seed at their defaults (decision 423 §4). They read the blocked grunge, so their item 2.7 cannot start.

5. **Moved items.** Each asset stays a release gap: refused with `family not certified`, its `@1` record `unavailable`, no alias. Existing approved states stay served by project snapshots (decision 327), which certify no editing.
   - `phase3.3_procedural-families` item 2.13 takes the seventeen grunges. They need an owner route decision before any engineering. Possible routes:
     - snapshot-only (no editing);
     - an owner-approved art change to independently designed UzPainter grunges (`05-procedural-content.md` §5), certified as UzPainter assets rather than as Painter parity;
     - another route the owner names.
   - Item 2.14 takes Dirt, Metal Edge Wear and Mask Builder - Legacy, after item 2.13. It reuses decision 423's requests, batch builder and coverage mask.

6. **Narrowed acceptance.** `phase3.2_proc-grunge-families` is accepted when:
   - items 2.1, 2.3, 3.2 and 3.4 stay met;
   - item 2.2's discovery is published;
   - each domain is declared (item 2.6, first half);
   - the seventeen grunges and three generators are listed as release gaps with the evidence above and their new items.

   Nothing is relaxed. Each moved asset still needs to be exact, or covered by an owner-approved exception.

## Alternatives Considered

- **Fitting each pattern kind for 2 h anyway.** Rejected. §1 and §2 hold for any kernel, and time spent fitting would not change them.
- **Reverse-engineering the Substance random sequence from recordings.** Rejected. It would reproduce Adobe's engine, not behaviour derived from public literature (`docs/licensing-and-clean-room.md` §1 item 2).
- **Keeping the task open.** Rejected under the owner's throughput rule. The blocker is a route decision, not work inside this task.

## Consequences

- `phase3.2_proc-grunge-families` is archived on 2026-11-10, and parent item 2.4 is met.
- The capability manifest keeps the twenty assets as release gaps until items 2.13 and 2.14 close.
- The `@1` records' `parity.reason` text still names this task's items. A later records edit can point it at items 2.13 and 2.14; their status is unchanged.
