# 04 — Review by Kimi K3 (`kimi/kimi-k3`)

Answer to the dossier of `01-dossier.md`, unedited.

---

## 1. Verdicts

**C1: PARTLY.** 24 entries span blend kernels, quantisation store, height-to-normal — different code paths, unlikely one rounding model. Half-up vs half-even at 8/16-bit store boundary could flip many, yes, but "single discovery" claim unproven. Changes my mind: apply one rounding fix, show >10 entries flip to exact.

**C2: AGREE.** Node with no downstream phase-1/2 dependency blocking G0 is pure critical-path drag, and it needs owner at UI panels — violates "100% AI agents" anyway. Move it.

**C3: AGREE on Tier-3 cut, PARTLY on "37%".** 11% of items serving a tier that passes only by exception is waste; cut it. But "usable product at 37%" assumes Tier-1 parity achievable — unproven while worst-case residuals sit at 257–65k codes.

**C4: AGREE.** Masks/effects/projection are the next 65% of compositor; building them on linear-list cache guarantees rewrite. Graph shape decision now is cheap, later is not.

**C5: AGREE.** Persisting "provisional" ids into goldens poisons every recorded oracle. Version profile-scoped goldens immediately; retro-fixing hashes later is worse.

**C6: AGREE.** 0 FMAs at baseline but 146 at `x86_64_v3` proves hazard is one flag away, and Zig makes target-CPU switches easy to do accidentally. Global flag costs nothing. Note: fixes host determinism only; GPU byte-parity untouched.

**C7: PARTLY.** Cannot verify repo. Fixes are plausible and correctly scoped, but "found and fixed" needs regression tests per bug — evidence given shows none. Lock-file race especially: needs adversarial concurrency test, not just code change.

## 2. Missed risks, ranked

1. **Oracle self-instability.** Painter differs from itself on 6/59 goldens (257 codes). Byte-exact parity against a nondeterministic oracle is definitionally impossible; acceptance criterion already broken at Tier 0/1, not just Iray. Cheap test: record each Tier-0 golden 5× across save/reopen, diff; publish self-variance as the parity floor.
2. **GPU/driver byte-nondeterminism.** FloatEnv fixed on CPU, but DX12 execution order, driver shader JIT, and hardware scheduling vary across GPU/driver combos. Byte-exact textures may hold only on one machine. Cheap test: run identical instruction sequence on two GPUs (or two driver versions), byte-diff outputs.
3. **Clean-room contamination via calibration.** Fitting residuals to 61 measured behaviors goes beyond the documented API into behavioral reverse engineering; Adobe EULA/anti-reverse-engineering risk, and "calibrated" constants are arguably derived from Adobe output. Cheap test: legal review of probing methodology + written contamination policy before more calibration.

## 3. Acceptance criterion sound?

No. Byte-exact parity with a closed-source, partly stochastic, self-unstable GPU app, with an empty exception register, is not an engineering target — it is a veto on shipping. Owner's own data refutes it: the oracle fails byte-equality against itself. Change it: parity bound = Painter's measured self-variance per tier. Tier 1 deterministic paths: bit-exact, hard requirement. Tier 2 GPU paths: equality within measured oracle noise floor, per-map, in 16-bit codes. Tier 3 Iray: statistical (SSIM/histogram + seed-matched variance bound). Exception register becomes the specification, seeded from measurement — not an admission of failure.

## 4. Top-5 next actions

1. Run oracle reproducibility study (risk 1); write self-variance numbers into contract.
2. Renegotiate acceptance criterion per section 3; owner sign-off before more parity work.
3. Freeze evaluator profile; re-version existing goldens profile-scoped (C5).
4. Move `-ffp-contract=off` global, pin target CPU, add CI byte-diff lane (C6).
5. Decide anchor dependency-graph shape; only then start masks/effects (C4).
