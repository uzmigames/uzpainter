# 06 — Decision round on D033–D035

After the reviews, the owner delegated decisions to the panel ("você tem vários modelos pra contrapor você, não precisa ficar me perguntando nada"). The proposed decisions below were put to the same four models for blocking flaws and a vote; the accepted texts, with the changes merged, are decisions 033, 034 and 035 in `.rulebook/decisions/`. Synthesis: `07-synthesis.md`.

## Prompt

You are one member of a decision panel (other members: other model families). The project owner has delegated decisions to the panel. Your job: find BLOCKING flaws in the proposed decisions below, then vote. Be terse and concrete. No restating.

# Context (facts)
UzPainter: clean-room reimplementation of Substance Painter 12.1.0, acceptance = byte-exact output parity with Painter, exceptions only via an owner-approved register. Painter is driven as an oracle via its documented remote-scripting API (localhost HTTP), unattended for texture goldens; Iray render references need a human operator at Painter's UI panels.
Already in force (do not contradict):
- Decision 017: exact equality, no preset tolerances; exceptions need owner approval.
- Decision 032 (owner, today): when Painter is unstable for a golden (same-session recording r1 != after-save/reopen r2), r1 is the exact target; UzPainter must match r1 exactly; r1-vs-r2 and UzPainter-vs-r2 residuals are published; each such golden gets a register entry naming 032.
- The evaluator quantisation profile was settled today ("painter-12.1-isolated-linear", matches r1 exactly).
- Every golden is recorded at least twice (same session; after save/reopen).
Plan: gates G0..G5. G0 currently joins, among others, P0-FEAS-RENDER (qualify the Iray capture procedure + capture references; 10/14 settings rows need the owner at the panels). G0 -> G1. No Phase-1/2 work node depends on P0-FEAS-RENDER; P0-FEAS-RENDER -> P3-PATHTRACER is an existing edge.
A prior 4-model review agreed (3 AGREE, 1 PARTLY) to move Iray out of G0, the PARTLY asking to keep an explicit feasibility gate before path-tracer investment; all 4 named oracle self-instability / undefined reproducibility envelope as the top missed risk; 3/4 asked for an end-to-end vertical slice before trusting velocity-based forecasts.

# Proposed decisions
D033 — Iray leaves G0. Remove the edge P0-FEAS-RENDER -> G0. P0-FEAS-RENDER stays a Phase-0 work package and remains the sole entry gate of P3-PATHTRACER: no path-tracer implementation task may start until P0-FEAS-RENDER is accepted, and its acceptance must include a reproducibility probe (one trivial Iray scene captured repeatedly; report pixel equality and which settings are observable). G0's other joins are unchanged.

D034 — Oracle reproducibility envelope (extends 032). (a) Every admitted golden carries an environment record: Painter build string, GPU model, driver version, OS build, colour-configuration hash, recorder version. A comparison is valid only against goldens whose envelope matches the current oracle environment; a mismatch is reported as oracle_unavailable-like ("out_of_envelope"), never pass or fail. (b) A one-off stability study re-records the full Tier-0 corpus 5 times per golden (2 same-session, 2 after save/reopen, 1 in a freshly started Painter process) and publishes per-golden self-variance; goldens that vary across fresh processes but not within a session are classified separately from 032's save/reopen instability. (c) Run (b) before any further calibration of "calibrated" fits; after a GPU/driver/Painter update, re-record a 10-golden canary subset and diff before reusing the corpus.

D035 — Vertical slice before forecasting. Keep the plan's order, but the Phase-1 pilot (Wand v1: instructions -> project -> evaluation -> PNG16 export -> comparison against Painter goldens) is the first schedule checkpoint: after it passes, re-forecast every remaining phase from measured wall-clock and exception counts of that slice, and record the re-forecast in the roadmap. No change to scope now.

# Answer format (max 250 words total)
For each of D033, D034, D035: ACCEPT / ACCEPT-WITH-CHANGE / REJECT, then at most 2 sentences; for ACCEPT-WITH-CHANGE give the exact change. Then one line: any decision that is MISSING and should be taken now.

# Votes (unedited)

## GPT-6 Astra

**D033 — ACCEPT-WITH-CHANGE.** Add: “P0-FEAS-RENDER acceptance requires qualified capture procedure and required references for all 14 settings rows, plus documented disposition of probe results; unresolved capture or exact-parity feasibility blockers prevent acceptance unless covered by owner-approved exceptions.” Probe reporting alone must not unlock path-tracer investment.

**D034 — ACCEPT-WITH-CHANGE.** Replace “current oracle environment” with “explicitly selected reference envelope; offline comparisons require no live oracle, and UzPainter’s execution environment need not match Painter’s recording environment.” Add: “Canary success does not migrate existing goldens into a new envelope; retain comparisons against their original envelope or re-record affected goldens under the new envelope, preserving original r1 targets and 032 records.”

**D035 — ACCEPT.** No blocking flaw; re-forecast must distinguish measured slice costs from unmeasured later-phase estimates, not treat slice throughput as validated path-tracer throughput.

**MISSING — Owner decision on fresh-process-only instability:** designate exact target and register treatment before admitting affected goldens; preserve 032’s r1 rule wherever 032 applies, with no averaging, tolerances, or silent target replacement.

## GPT-5.6 Sol

D033 — ACCEPT. Removes unrelated human-dependent work from G0 while preserving hard feasibility gate before path-tracer investment.

D034 — ACCEPT-WITH-CHANGE. Replace “comparison is valid only against goldens whose envelope matches current oracle environment” with: “Oracle re-recording and oracle-to-golden comparisons require matching envelopes; UzPainter-to-recorded-golden comparisons remain valid against golden’s recorded envelope.” Also define canonical target for fresh-process variance; classification alone leaves exact target ambiguous.

D035 — ACCEPT-WITH-CHANGE. Trigger re-forecast when vertical slice completes, whether pass or fail; record failure causes, wall-clock, and exception counts.

MISSING — Owner decision defining canonical target and exception-register treatment for fresh-process oracle instability not covered by D032.

## Kimi K3

**D033 — ACCEPT-WITH-CHANGE.** Change: probe acceptance must not demand exact pixel equality — 032 established oracle self-instability, so hard equality may be unreachable and blocks P3 forever. Probe accepts when pixel equality holds OR variance is bounded, quantified, and published per setting row, with explicit pass thresholds named in the acceptance criteria.

**D034 — ACCEPT-WITH-CHANGE.** Change: canary diff lacks a verdict rule. Specify: canary diff non-zero → full corpus re-record and re-baseline before reuse; define which diff magnitude triggers that (suggest: any nonzero diff in any canary golden, consistent with 017). Also: envelope mismatch counting as "out_of_envelope" can silently shrink valid corpus to zero after a driver update — roadmap must treat envelope re-validation as a gating task, not passive reporting.

**D035 — ACCEPT.** Pilot-first checkpoint and re-forecast from measured data addresses 3/4 reviewers. Non-blocking note: define "passes" for pilot now (exception counts? which goldens?) or checkpoint dispute returns later.

**MISSING:** Decision on P0-FEAS-RENDER acceptance criteria and owner-operator scheduling — 10/14 settings rows need owner at Painter UI panels; without committed owner time and explicit accept thresholds, P3-PATHTRACER gate is unschedulable regardless of D033.

## Grok 4.5

D033: ACCEPT. No Phase-1/2 node waits on Iray. Probe stay sole P3 entry; G0 unblocked.

D034: ACCEPT-WITH-CHANGE. Fresh-process variance class lacks target rule under 017 exact-match. Change: same-session r1 is gold (align 032); register entry names 034; publish residuals; bind (a)+(b) as P0-ORACLE-ENVELOPE joined to G0 exit; canary set owner-pinned.

D035: ACCEPT. Pilot wall-clock + exception counts drive re-forecast. Scope freeze hold.

MISSING: owner sign-off protocol for human-panel Iray captures (dual-run attest, operator ID in envelope) before P0-FEAS-RENDER accept.

