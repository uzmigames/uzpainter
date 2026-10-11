# 02 — Review by GPT-6 Astra (`cx/gpt-6-astra`)

Answer to the dossier of `01-dossier.md`, unedited.

---

## 1. Verdict per conclusion C1–C7

**C1 — PARTLY.** Shared rounding is worth probing; “single model,” “half become exact,” and “halve exceptions” lack evidence. FMA, intermediate precision, color conversion, clamping, and operation order can produce similar residuals; controlled boundary-value probes showing one correction generalizes to held-out cases would support this claim.

**C2 — PARTLY.** Scheduling dependency and feasibility gate serve different purposes: Iray capture may intentionally prevent investment before acceptance feasibility is known. Allow independent implementation work, but remove capture from G0 only if another explicit gate retains that feasibility check; supplied evidence cannot establish DAG intent.

**C3 — DISAGREE.** G2 may deliver useful intermediate capability, but cannot satisfy owner’s stated acceptance criterion. DXR baking also serves texture parity, not inherently Tier 3; task-level dependency evidence and owner-approved scope reduction would change this assessment.

**C4 — PARTLY.** Anchor dependencies need explicit invalidation, cycle rules, and channel/subresource semantics before effects proliferate. But measured state already says “tile DAG”; no evidence establishes whether linear prefix hashing is merely one component or an architectural dead end—an anchor-change invalidation test would settle more than terminology.

**C5 — PARTLY.** Persisting provisional profile IDs is sensible provenance, not inherently wrong order. Problem exists if profile meaning can mutate or incompatible artifacts compare as equivalent; immutable, content-addressed profile definitions and strict comparison rules would remove concern.

**C6 — PARTLY.** CPU-dependent FMA generation demonstrates portability exposure, not proven parity failure; globally disabling contraction may even conflict with Painter’s arithmetic. Test output differences across baseline/v3 first, then define deterministic compilation per numerical domain, including shader arithmetic, reductions, SIMD dispatch, and libraries.

**C7 — PARTLY.** Reported defects are credible and serious, but neither causes nor fixes are independently verifiable here. Concurrent-owner stress tests, resolution-change cache tests, replay tests, malicious-ID containment tests, and Windows collision tests would support closure; green aggregate counts cannot.

## 2. Three biggest missed risks

**1. Oracle lacks stable experimental identity.** Six unstable goldens undermine claims that residuals measure implementation error; 257 suggests an 8-bit code step represented in 16-bit, not necessarily random noise. Cheap test: repeat capture before save, after reopen, and after restart with identical asset, profile, settings, and environment hashes; compare native buffers separately from exported files.

**2. Render feasibility remains unmeasured, not merely unfinished.** Unknown sampling sequence, integrator, materials, denoiser, stopping rules, and hidden state matter beyond seed exposure. “Impossible” is too absolute, but noise-floor measurement cannot authorize an exception. Cheap test: capture one trivial Iray scene repeatedly, using documented automation only; record pixel equality, settings observability, and reproducibility. Failure establishes immediate contract risk before tracer investment.

**3. No demonstrated end-to-end instruction equivalence.** Hundreds of missing API symbols, near-empty Python integration, and paper-only export threaten semantic coverage more than kernel completion percentages reveal. Cheap test: run one minimal agent-authored script in Painter and UzPainter covering import, layer creation, parameter change, save/reopen, and export; compare intermediate state and final bytes. Record unsupported steps explicitly.

## 3. Acceptance criterion

**Sound as a contractual aspiration; unsound as a committed delivery target without demonstrated reproducibility and scope.** Keep current criterion binding until owner explicitly changes it. Proposed replacement: enumerate supported operations, assets, versions, hardware/backend profiles, and comparison representations; require byte equality for canonical texture outputs in qualified deterministic cases. Separately specify encoded-file equality if required. For Iray, require reproducible capture first, then owner-approved numerical and statistical limits established from both repeated references and meaningful image differences—not noise floor alone. Every deviation needs a narrow, versioned exception with evidence; until approved, divergent result remains failure, not calibrated success.

## 4. Top-five next actions

1. **Resolve acceptance feasibility:** obtain owner decision on Iray reproducibility failures and UI-dependent capture.
2. **Stabilize oracle:** freeze environment, immutable profiles, capture settings, and comparison formats.
3. **Build one end-to-end parity slice:** agent instructions through export and reopen.
4. **Run discriminating numerical probes:** rounding boundaries, precision, FMA, color conversion, and resampling.
5. **Replan from measured blockers:** retain explicit feasibility gates; validate anchor invalidation and reported fixes before expanding features.
