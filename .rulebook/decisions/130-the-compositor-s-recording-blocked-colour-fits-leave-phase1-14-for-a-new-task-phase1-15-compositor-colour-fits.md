# 130. The compositor's recording-blocked colour fits leave phase1.14 for a new task, phase1.15_compositor-colour-fits

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.14_compositor-core, phase1.15_compositor-colour-fits, phase1.24_python-api-facade, phase5.2_parity-report-tiers, phase1.25_pilot-wand, phase1.26_gate-g1

## Context

Every child of `phase1.14_compositor-core` is archived. Its open work was item 3.1 (the final union run), item 4.1 (acceptance) and item 2.9.

Item 2.9 was added by decision 117, following decision 108 §4. It records P20-A (fill channel defaults) and P20-B (dense sRGB decode). It then fits the facade's `DEFAULT_SOURCES`, `default_bitmap_space`, `available_bitmap_spaces` and float32 sRGB decode to them exactly. Neither recording exists, and both need the shared Painter instance.

Decision 108 §2 also made phase1.14 the owner of more colour work, with no checklist item:
- the sRGB bitmap uses other than a 16-bit colour bitmap sampled 1:1 onto an sRGB8 channel: as a mask source, on another channel format, an 8-bit or grey bitmap, a resampled bitmap;
- the bitmap colour spaces Working and Linear;
- OCIO colour management, which waits for the Session O goldens (decision 101);
- the masked group of R5's Legacy twin (`export-ocio-encode-legacy` s5, unstable in the oracle).

Decision 108 says the sRGB variants are "fitted from `export-ocio-encode-legacy`, which is already recorded". `src/evaluator/sources.h` says the opposite: those uses are not recorded. No fit or golden for them is in the repository.

Today every one of these cases is refused before any mutation. The refusals name `phase1.14_compositor-core` in these places:
- the evaluator: `support.cpp`, `dag.cpp`, `evaluate.cpp`;
- the facade: `colour.py`, `nodes.py`;
- the capability entries `compositor:ocio` and `compositor:srgb-unrecorded`;
- the reports.

The 70/255 decode is a named exclusion. Nothing claims these cases are supported.

The brief's speed rule 4 closes a task with a recorded scope split when an item is blocked only by a recording. Archiving phase1.14 with these pointers in place would leave them naming a closed task with no open checklist item. The capability test would still pass, because it accepts an archived owner.

The model panel (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5) was consulted twice. The first round lacked the decision-108 facts above. In it, the panel accepted moving item 2.9 alone to phase1.25_pilot-wand item 2.8. That was C1 AGREE ×3 and C2 owner PARTLY ×3. Decision 108 had already rejected the pilot as owner of compositor semantics. The second round had the full facts:

| Claim | Verdicts |
|---|---|
| C1 Keeping phase1.14 open (A) is wrong: what remains is blocked by recordings and refused | AGREE ×1, PARTLY ×2 (right, but 3.1 and 4.1 must still pass on their own) |
| C2 Moving only 2.9 to the pilot (C) is wrong: it contradicts decision 108 and leaves the other gaps owned by an archived task | AGREE ×3 |
| C3 One new, later, compositor-scoped task owns everything decision 108 gave phase1.14, with every live pointer renamed together; G1 waits on it | AGREE ×3 |
| C4 Sending the facade tables back to phase1.24 (D) is worse: it reverses 108 §4 and 117 without evidence, and P20-B is the same arithmetic as the native sRGB decode | AGREE ×2, PARTLY ×1 (a superseding decision could do it, but nothing here justifies one) |
| C5 Renaming the owner in the refusals is a message change: the refusal set and the arithmetic stay, and the tests that assert the strings cover it | AGREE ×1, PARTLY ×2 (no golden holds refusal text; keep the refusal conditions untouched) |

## Decision

1. A new task, `phase1.15_compositor-colour-fits` (P1-COMPOSITOR follow-up, prerequisite phase1.14_compositor-core, not its child), owns:
   - **2.1**: item 2.9 of phase1.14, with the same wording and acceptance. It covers P20-A and P20-B, the facade tables, the `readback/get_source/29/BaseColor` exclusion, and `phase1-reload-resources` recording 1 s9 and s12.
   - **2.2**: the sRGB bitmap variants and the Working and Linear spaces. It starts by measuring what `export-ocio-encode-legacy` records, and names the recording when that golden does not determine a variant.
   - **2.3**: OCIO colour management after Session O (`export-ocio-encode`, `export-presets-ocio`).
   - **2.4**: R5 Legacy twin s5.
2. Item 2.9 of phase1.14 is checked as a recorded scope split. Its wording stays. phase1.14 archives when 3.1 and 4.1 are green on their own evidence.
3. In the same change, every live owner pointer names the new task:
   - the evaluator refusal messages;
   - the facade messages;
   - the two capability notes;
   - the native `not-yet-supported` cases;
   - the export test comments;
   - `src/evaluator/EVALUATOR.md`;
   - the report rows of `python-api-facade.md` §3 and `pyapi-facade.md`;
   - phase1.24 item 3.1 and phase5.2 item 2.10.

   Decisions 108 and 117 stay as history. Only the owner changes: the refusal conditions and the arithmetic stay as they are.
4. `phase1.26_gate-g1` waits on the new task through its item 3.4, which requires every Phase 1 task archived, unless a later decision changes G1's scope.

## Alternatives Considered

- **Keep phase1.14 open (A).** Rejected: everything left is blocked by recordings and refused, and the speed rule prefers a split.
- **Item 2.9 alone to `phase1.25_pilot-wand` (C; the first round).** Rejected: decision 108 rejected the pilot as owner of compositor semantics, and the other gaps would be left owned by a closed task.
- **The facade tables back to phase1.24 (D).** Rejected: it reverses 108 §4 and 117 without new evidence, and it separates P20-B from the native sRGB decode that it shares.

## Consequences

- phase1.14 can archive on its union run and acceptance.
- The colour gaps keep explicit refusals and an open owner with checklist items.
- The recordings needed are owner actions: P20-A, P20-B and Session O, plus any sRGB-variant recording that 2.2 names.
- G1 now visibly depends on them.
