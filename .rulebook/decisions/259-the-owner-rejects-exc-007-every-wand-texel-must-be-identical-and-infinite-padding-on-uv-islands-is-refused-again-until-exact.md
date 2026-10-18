# 259. The owner rejects EXC-007: every Wand texel must be identical, and `infinite` padding on UV islands is refused again until exact

**Status**: accepted
**Date**: 2026-10-18
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

Decision 223 wrote `infinite` padding on UV-islanded texture sets under exception EXC-007 (version 1). That exception held the texels inside the UV islands exactly equal to Painter's, and let the padding texels outside them differ. The register recorded it as `approved_by: owner`. The owner had not said yes to it: he had answered "n sei oq quer dizer isso, fale com outros modelos disponiveis no 9 router" ("I don't know what this means; talk to the other models"), and decision 223 took that as a delegation to the model panel. The proposal delivery review flagged the record (`docs/analysis/proposal-delivery-review/03-governance-and-guardrails.md`, F-013): the register said the owner had approved a term he had not understood.

**The owner's answer.** On 2026-10-18 the owner (André) was asked, in plain words: "Posso aceitar a margem diferente para fechar a Varinha?" ("Can I accept the different margin to close the Wand?"). The margin means the padding texels outside the UV islands, which would differ from Painter's while every texel inside the islands stays identical. He answered himself, verbatim:

> "Não, tudo idêntico" (no, everything identical)

## Decision

1. **EXC-007 is withdrawn** by version 2 of the entry (`parity/exceptions.json`).
   - Version 2 is marked `withdrawn: true`. It repeats version 1's terms to record what is withdrawn and names this decision.
   - Version 1 stays in the register as history, so the reports that relied on it can still be traced.
   - Only the highest version of an id is in force (CONTRACT §5). A withdrawing version leaves nothing of its id in force (`tools/parity/verdict.py` `in_force`).
   - The id is not reused. The next exception is EXC-008.
   - The schema gains the optional `withdrawn` property (`parity/schema/exceptions.json`). `register_problems` checks that a withdrawing version has a lower version to withdraw.
2. **The verdict fails any padding difference on the Wand.** With the published register, a Wand v1 Tier 1 comparison that differs on one padding texel, or on all of them, is `fail` and relies on no entry. Covered-texel defects fail as before. The test is `tests/parity/test_verdict.py::test_withdrawn_exc007_fails_every_padding_difference`.
3. **Decision 223 is superseded in this part**, which covers its §1, §2, §3, §6, §7 (the lift) and §8. Its measurements stand. Its coverage-only rule (§4) is kept as a measured candidate only (item 4 below). The coverage mask, the `covered` bound scope and the `padding` block of the Tier 1 report stay. The report keeps publishing the covered and uncovered statistics of each map, which is what the exact hunt reads.
4. **`infinite` padding on a UV-islanded set is refused again before writing** (R-090).
   - `CheckPadding` (`src/export/padding.cpp`) refuses it with `NotYetSupported` in step 1 of `EncodeExport`, before anything is evaluated or written.
   - The message names the cause (Painter's ring across UV seams, at seam corners and at poles is not identified, and the best-known rule misses its padding texels by up to 59,150 PNG 16 codes, decision 220). It also names the owner (`phase1.25_pilot-wand` item 2.7), recording R-090 and this decision.
   - No case is lifted: no recording shows the rule exact on any islanded set, not even on straight edges alone. The refusal is lifted only when item 2.7 makes the rule exact.
   - The writer stays behind the refusal. `ApplyPadding` and `EncodeFile` write it only when a caller asks for `InexactPadding::measure`. Only the `uzp-export-tests process` cases of the exact hunt ask for it. The export never does, and nothing inexact is written silently.
   - Decision 245 §1's "without the Normal under `infinite` (EXC-007)" no longer holds. On the Wand, any `infinite` export is refused, with or without the Normal. Its document maps export with `passthrough` only.
5. **G1 needs both exact rules**:
   - exact `infinite` padding on UV islands (`phase1.25_pilot-wand` item 2.7);
   - the exact island-edge Normal (decision 245: Painter's Height outside the islands).
   
   The Wand's Tier 1 test still ends as an expected failure (decision 255). It now accepts either decided refusal: decision 245's, or this decision's. Any other refusal fails it.
6. **Owner approval means the owner's own yes.**
   - No exception is recorded `approved_by: owner` unless the owner says yes to its terms himself.
   - A delegation to the model panel does not count, nor a reading of his silence or of an answer to another question. The memory note *decide with a model panel* already excludes signing exception records from what it delegates.
   - An entry prepared without that yes stays a prepared entry. Its comparisons stay `blocked` or `fail`.

## Alternatives Considered

- **Delete the EXC-007 entry.** Rejected. Deleting it would lose the record of what reports relied on. `next_exception_number` would also hand out EXC-007 again, for different terms.
- **Keep EXC-007 and set `approved_by` to the delegation**, as F-013 suggested before the owner answered. Rejected: the owner answered no.
- **Delete the coverage-only writer.** Rejected. It is the exact hunt's measured baseline: it is exact on the covered texels, and its padding residuals are published. With the refusal in front of it, keeping it writes nothing inexact.

## Consequences

- The Wand cannot pass Tier 1 until item 2.7 is exact and decision 245's island-edge Normal is solved. G1 waits on both.
- No `infinite` export of an islanded set is written. `passthrough` keeps its own rules (decision 090).
- `parity/reports/phase1/tier1-wand-v1.json` is still decision 223's run, which relied on EXC-007 version 1. Its verdict was `fail`, and no current claim rests on it. A local run with `UZP_TIER1_REPORT` set rewrites it as the refusal.
- `parity/semantics/export-processing.json` keeps `padding-islands` as a gap. Its formula again says it is refused before writing.
