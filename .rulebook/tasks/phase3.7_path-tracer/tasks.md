## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.9_render-reference-capture, phase1.4_render-core-layer, phase2.10_pilot-tunic-recovery, phase3.3_vulkan-backend-ray-tracing

## 2. Child tasks (mandatory)
- [ ] 2.1 phase3.4_path-tracer-transport accepted
- [ ] 2.2 phase3.5_path-tracer-materials accepted
- [ ] 2.3 phase3.6_path-tracer-tier3-report accepted

## 3. Integration
- [ ] 3.1 Run `painter_iray` on both backends from one build on the owner's machine over the analytic fixtures and the production-project profiles; confirm the Tier 3 report, the cross-backend report and the exception proposals refer to that build hash
- [ ] 3.2 Confirm every Tier 3 pass and every cross-backend bound in the report cites an owner-approved entry of `parity/exceptions.json` with its decision under `.rulebook/decisions/`; every other comparison is reported `blocked`
- [ ] 3.3 Regenerate the capability manifest: `painter_iray` supported only for the approved fixture classes and configurations; all other configurations listed as gaps

## 4. Acceptance
- [ ] 4.1 Acceptance: Tier 3 report produced; every Tier 3 pass and cross-backend bound is an owner-approved register entry, otherwise Tier 3 is blocked; every mandatory child accepted

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
