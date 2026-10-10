## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: none (DAG inputs of P0-OWNER are empty)

## 2. Decision records
- [x] 2.1 Decision 017 (Q1 exact equality, owner-approved exception register, no preset tolerances) exists, status accepted, text matches `docs/open-questions.md` Q1
- [x] 2.2 Decision 018 (Q2 Painter's Iray as render target, clean-room path tracer on DXR and Vulkan RT) exists, status accepted, matches Q2; decision 008 marked superseded by 018
- [x] 2.3 Decision 019 (Q5 capability manifest, brush strokes out of scope) exists, status accepted, matches Q5; decision 004 marked superseded by 019
- [x] 2.4 Decision 020 (Q6 rebuild through the documented API, no `.spp` reader) exists, status accepted, matches Q6
- [x] 2.5 Decision 021 (Q8 zero UzEngine dependency, vendored render core, own build) exists, status accepted, matches Q8; decision 014 marked superseded by 021
- [x] 2.6 Decision 022 (Q9/Q9b Windows 10/11 x64, DX12 + Vulkan, owner's machine as GPU runner and oracle store) exists, status accepted, matches Q9
- [x] 2.7 Decision 023 (Q10 UE 5.6 PNG/TGA + optional DDS BC7/BC5, `.uzmat` + compressed `.uztexture`, SpecularWeight consumer gap) exists, status accepted, matches Q10
- [x] 2.8 Decision 024 (Q11 self-contained `.uzp`, 10 % candidate budget, checkpoint and 50-revision retention) exists, status accepted, matches Q11
- [x] 2.9 Decision 025 (Q12 `run_python` behind `--allow-python`, typed MCP tools cover every required operation) exists, status accepted, matches Q12
- [x] 2.10 Decision 026 (Q13 Assets3D rule amended after Tunic v10 passes G2) exists, status accepted, matches Q13; its sentence naming the cutover node `P5-CUTOVER` predates the dag rename to `P3-CUTOVER` (`phase3_assets3d-cutover`) and was reported to the orchestrator, decision text left unchanged
- [x] 2.11 Decision 027 (clean repository history recreated before the repository is made public) exists, status accepted, matches the repository-history row
- [x] 2.12 Questions answered by earlier records confirmed accepted: Q3 and Q4 on decision 002, Q7 and Q14 on decision 016
- [x] 2.13 `docs/open-questions.md` lists every question closed with its decision id and no open question remains

## 3. Acceptance
- [x] 3.1 Acceptance gate (P0-OWNER): decisions recorded without re-asking decided points; work consistent with a recorded decision proceeds; only an operation that would change a decision waits for the owner

## 4. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 4.1 Update or create documentation covering the implementation
- [ ] 4.2 Write tests covering the new behavior
- [ ] 4.3 Run tests and confirm they pass

<!-- tail-waiver: governance record only; decisions 017-027 already recorded and verified, no code -->
