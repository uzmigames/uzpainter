# 07 — Synthesis: where the panel agreed, what it corrected, what was decided

Panel (2026-10-11, through the local 9router proxy): GPT-6 Astra, GPT-5.6 Sol (OpenAI), Kimi K3 (Moonshot), Grok 4.5 (xAI). Claude Fable 5.1 and Grok 4.6 were asked and did not answer (upstream connect timeouts). The two GPT models share a family, so the panel is three families plus the author of the analysis (Claude). Dossier: `01-dossier.md`; reviews: `02`–`05`; decision round: `06`.

## 1. Verdicts on the analysis

| Conclusion | Astra | Sol | Kimi | Grok | Result |
|---|---|---|---|---|---|
| C1 one rounding model behind the 24 near-exact fits | PARTLY | DISAGREE | PARTLY | PARTLY | **Overstated.** The cluster is real, but the 24 entries cross blend kernels, sRGB store, quantisation and height-to-normal; a shared residual size is not a shared cause. Replace "find the model" with discriminating probes per stage (ties, clamps, signed and high-range values, every storage boundary), judged on withheld goldens. |
| C2 move the Iray leg out of G0 | PARTLY | AGREE | AGREE | AGREE | **Adopted** with Astra's condition: keep an explicit feasibility gate before path-tracer investment (decision 033). |
| C3 scope overweighted to research; usable product = G2 + cutover | DISAGREE | PARTLY | PARTLY | PARTLY | **Rejected as stated.** "Usable at G2" changes the owner's acceptance criterion; only valid with a formal scope decision. The 205-item count was also wrong: the DXR GPU baker serves Tier 2b bakes, not Tier 3. No scope change made. |
| C4 decide the evaluator dependency-graph shape before mask effects | PARTLY | PARTLY | AGREE | AGREE | **Upheld, with a test as the criterion:** an anchor-change invalidation test on representative graphs (masks, anchors, channel sampling, resolution changes) decides whether the prefix chain survives. Owned by the compositor tasks. |
| C5 provisional evaluator profile persisted everywhere | PARTLY | AGREE | AGREE | AGREE | **Already resolved** the same day: the profile was settled as `painter-12.1-isolated-linear` (decision 032 context). |
| C6 make `-ffp-contract=off` global | PARTLY | PARTLY | AGREE | AGREE | **Upheld but insufficient alone.** Painter's own blend formula uses fused multiply-add (`parity/semantics/blend-modes.json`), so the rule is contraction off plus explicit `fma` where Painter fuses, as the evaluator already does; also pin the target CPU and record denormal and rounding modes. |
| C7 five code bugs found and fixed | PARTLY | PARTLY | PARTLY | AGREE | **Confirmed.** The panel asked for regression tests; each fix landed with a test that fails without it (commit `a0f94fd` for the store fixes; the tile-cache key fix is in the compositor task). |

## 2. The risk the analysis missed

All four models ranked **oracle self-instability and an undefined reproducibility envelope** first. Painter differs from itself on 6 of 59 Tier 0 goldens across save/reopen, and no golden records the GPU, driver, OS or colour configuration it was made under. Decision 032 already makes the same-session recording the exact target for save/reopen instability; variance across fresh processes and environments was unmeasured. Three of four also flagged that progress so far measures scaffolding, not integration, and asked for an end-to-end slice before trusting forecasts. Single mentions worth keeping in view: oracle identifiability (a model fitted to few goldens may not predict withheld ones — Sol), GPU/driver byte nondeterminism (Kimi), and the legal status of calibrating against Painter output (Kimi; decision 002 permits reproducing behaviour, decision 030 covers documented defaults).

## 3. The acceptance criterion

All four called byte-exact parity with an empty exception register unsound as a universal release predicate, and proposed exact equality only inside a versioned reproducibility envelope where Painter is proven stable, statistical tests for Iray, and an exception register seeded from measurement. Decisions 017 and 032 already route instability and Iray through owner-approved register entries, so the panel kept the criterion and added the missing piece, the envelope (decision 034). Exception approvals stay with the owner.

## 4. Decisions taken

| Decision | Content | Vote |
|---|---|---|
| 033 | P0-FEAS-RENDER leaves G0; stays the sole entry gate of P3-PATHTRACER with a reproducibility probe added to its acceptance | 2 ACCEPT, 2 ACCEPT-WITH-CHANGE (merged) |
| 034 | Oracle environment record on every golden; five-recording Tier 0 stability study; fresh-process instability under 032's rule; canary after environment updates; new work package P0-ORACLE-ENVELOPE (`phase0.9_oracle-envelope`) joining G0 | 4 ACCEPT-WITH-CHANGE (merged) |
| 035 | The Wand v1 pilot is the first schedule checkpoint; re-forecast from its measured slice, pass or fail | 2 ACCEPT, 1 ACCEPT-WITH-CHANGE, 1 ACCEPT with note (merged) |

Applied in `docs/dag.md`, `docs/roadmap.md` and `.rulebook/tasks/phase0.9_oracle-envelope/`. Not delegated and still owner actions: the operator session at Painter's Iray panels, approval of register entries, and starting Painter with `--enable-remote-scripting` for the unattended study.
