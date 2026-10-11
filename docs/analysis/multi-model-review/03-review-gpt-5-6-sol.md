# 03 — Review by GPT-5.6 Sol (`cx/gpt-5.6-sol`)

Answer to the dossier of `01-dossier.md`, unedited.

---

1. Verdict per conclusion C1-C7

**C1 — DISAGREE.** Evidence does not support “single” rounding model or “half” flipping exact: entries span blend math, quantisation, normals, and storage, each potentially diverging at different stages. Run differential probes around ties, signed values, clamp boundaries, subnormals, and every intermediate storage boundary; shared residual signatures would change verdict.

**C2 — AGREE.** If Iray capture has no dependency before Phase 3, placing it in G0 creates pure schedule blockage, especially because owner UI work is required. Keep only capture-procedure validation in G0 if later oracle availability cannot otherwise be guaranteed.

**C3 — PARTLY.** Tier-3 investment is badly aligned with known impossibility, but calling G2 a “usable product” changes stated acceptance criterion and understates missing masks, effects, projections, procedurals, export, and 807 API symbols. Agree only if owner formally defines G2 as separate deliverable with narrower parity contract.

**C4 — PARTLY.** Cross-layer/channel dependencies make linear prefix caching suspicious, but evidence does not prove rewrite: dependency-aware invalidation could sit above immutable per-channel chains. Require representative graphs covering masks, anchor cycles, channel sampling, effects, and resolution changes before choosing architecture.

**C5 — AGREE.** Persisted provisional semantics can silently make projects and goldens mutually incomparable. Profile ID needs immutable definition, schema/version, evaluator build identity, and migration policy; evidence of those controls would weaken criticism.

**C6 — PARTLY.** Global `-ffp-contract=off` is necessary for controlled CPU results, but insufficient: ISA selection, SIMD width, reassociation, denormals, rounding mode, math library, GPU shader compiler, and shader precision also matter. Exact parity requires recorded toolchain and execution profile, not one flag.

**C7 — PARTLY.** Listed defects are credible and material, especially ownership race and recursive deletion validation, but “fixed” cannot be established from summary. Need regression tests including concurrent processes, crash recovery, resolution churn, replay beyond horizon, malicious IDs, and Windows case-folding behavior.

2. The 3 biggest risks the reviewer MISSED

**1. Oracle identifiability and coverage.** Output-only probes may not uniquely identify Painter’s hidden color spaces, precision boundaries, mip generation, kernels, or hardware-specific paths; many models can fit small goldens then diverge. Cheap test: generate discriminating micro-cases using adversarial values, odd dimensions, alpha edges, negative/high-range inputs, all mip levels, and operation permutations; verify one model predicts withheld goldens exactly.

**2. Reproducibility envelope is undefined.** “Painter 12.1.0” is not enough: GPU model, driver, OS build, color management, plugin state, locale, thread scheduling, and Adobe updates may alter output. Existing 6/59 unstable goldens already show oracle nondeterminism. Cheap test: repeat identical captures across fresh processes, save/reopen, two machines, two drivers, and 100 runs; hash every artifact and record environment metadata.

**3. Apparent velocity may measure scaffolding, not integration.** Forty-one commits and 68k lines in two days, while core compositor features, Vulkan, export, bakers, path tracer, MCP, and 807 API symbols remain absent, gives little evidence for 30–39 weeks. Cheap test: build one vertical slice from Painter API instruction through project persistence, mask/anchor/projection evaluation, export, reopen, and oracle comparison on one real asset; count failures and manual interventions.

3. Is the acceptance criterion itself sound?

No. Byte-exact texture parity can be valid only for explicitly enumerated operations under a frozen Painter build, OS, GPU/driver, color configuration, input domain, and capture procedure. Pixel-identical Iray parity is unsound when oracle output is stochastic and seed/control state is unavailable; empty exception register contradicts known instability before implementation starts. Replace criterion with: deterministic texture stages require exact equality inside a versioned reproducibility envelope; nondeterministic or hardware-dependent stages use preregistered statistical tests over repeated captures, including confidence bounds and perceptual/energy metrics; every unsupported or unstable behavior gets a mandatory scoped exception before gate passage. Keep exact equality as goal, not universal release predicate.

4. Own top-5 next actions

1. Freeze and document oracle environment; measure repeatability across 100 runs, reopen cycles, machines, and drivers.
2. Define versioned parity profiles and acceptance rules before producing more goldens.
3. Build one end-to-end vertical slice including mask, anchor, projection, persistence, API control, and export.
4. Run discriminating numeric probes; locate precision, color-space, quantisation, and resampling boundaries instead of assuming one rounding rule.
5. Replan gates around evidence: remove Iray from G0, isolate Tier 3, and estimate remaining work from completed vertical slices rather than checklist throughput.
