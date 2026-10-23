## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase4.6_gate-g4, phase3.7_path-tracer, phase5.1_performance-budgets; frozen release build hash and dependency lock recorded

## 2. Implementation
- [ ] 2.1 Local comparison command, run on the owner's machine (decision 028; the local run report is the evidence), that runs every tier on DX12 and on Vulkan against the frozen build and fetches oracle blobs through `uzpainter parity fetch`/`verify`
- [ ] 2.2 Tier 0 run over the 14 §3 corpus, including the Phase 4 node kinds and the UDIM fixture
  - Current-envelope reload remains divergent (2026-10-23, decision 109 investigation addendum): Painter 12.2.0 first recording has post-success model-change events, engine disable/enable and `No active stack`; its reopened recording does not. Four bounded private controls (20-second sampling, exact sequence, mesh-map-update prefix, levels-params plus mesh-map-update prefix; two fresh sessions each) did not reproduce it. No golden replacement, exclusion or product change; further probing requires a supported causal hypothesis.
- [ ] 2.3 Tier 1 run for wand v1, belt v5, tunic v10, bracer r9, hat v8, body v6b and every other Tier 1 fixture of 14 §3: every exported map per set, save/reopen, dump-and-rebuild
- [ ] 2.4 Tier 2a per certified procedural asset and Tier 2b for the ten bakers (evidence first, then maps)
- [ ] 2.5 Tier 3: `painter_iray` versus converged Iray references per fixture and material region next to the noise floor (07 §4), and the DXR-versus-Vulkan cross-backend report (07 §3.5)
- [ ] 2.6 Vulkan-versus-DX12 byte comparison of every Tier 0–2 output
- [ ] 2.7 Report generator: oracle stability, repeatability and equality reported separately; 14 §4 diagnostics; hardware, driver, backend, build hash, resource hashes and exception entries per result; written to `parity/reports/phase5/tiers.json` with numbers and hashes only
- [ ] 2.8 Exception register `parity/exceptions.json` published: each entry versioned, linked to its owner decision under `.rulebook/decisions/`, with domain, metric, bound and evidence hashes
- [ ] 2.9 Per-gate fixture status, reporting any `not_migratable` fixture without an owner scope decision as a gate failure
- [ ] 2.10 (decision 117, from phase1.24_python-api-facade item 3.1) `tier0/api-probes/phase1-reload-resources` recording 2, s9 and s12: Painter reports reloads of bytes the project already holds (decision 110 §6; unstable r1 vs r2 in `parity/reports/phase0/tier0-stability.md`). After phase1.15_compositor-colour-fits item 2.1 (decision 130; formerly phase1.14_compositor-core item 2.9) makes recording 1 s9 and s12 exact, either explain recording 2 from a Painter recording that settles it, or enter it in `parity/exceptions.json` as a decision-032 r2 divergence (`api_readback`, the events of s9 and s12). Recording 2 is not claimed exact until a recording shows the rule

## 3. Tests
- [ ] 3.1 Repeatability lane: the frozen build run twice on the same inputs produces identical exported bytes on each backend
- [ ] 3.2 Every exception entry's defect-detection test re-run on the frozen build (sparse seams, alpha defects, one wrong texel region; for renders a missing channel, a wrong lobe, a roughness offset, a wrong environment rotation) and each still fails the injected defect
- [ ] 3.3 Tier 3 structural check: a wrong material binding, a missing map and a wrong camera/environment fail regardless of any exception entry
- [ ] 3.4 A missing oracle blob fails its comparison as `oracle_unavailable`, never as a pass
- [ ] 3.5 Repository guard over `parity/reports/phase5/` and `parity/exceptions.json`: no file whose hash is in the private store index; both validate against their public schemas on the local CPU lane (decision 200)

## 4. Acceptance
- [ ] 4.1 Tiers 0–2 green or covered by approved exceptions on DX12 and Vulkan; Tier 3 passed only through approved exceptions (otherwise blocked); register published; report hash and lock attached to `phase5.4_parity-report`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
