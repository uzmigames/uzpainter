## 1. Prerequisites
- [ ] 1.1 Prerequisite accepted: phase1.10_compositor-blend-kernels

## 2. Implementation
- [ ] 2.1 Fit the HSV hue/saturation arithmetic of Tint, Saturation, Color and Value on colour channels (near-grey hue sources); record a finer Tier 0 sweep if the existing golden does not determine it
- [ ] 2.2 Fit the opacity rotation of NormalMapCombine, NormalMapDetail and NormalMapInverseDetail below opacity 1; record an opacity sweep if needed
- [ ] 2.3 Record PassThrough through Painter's documented API and fit it, or record it `not_migratable` with the reason and ask the owner
- [ ] 2.4 Implement the fits in the CPU reference and the blend kernel (GPU = CPU bit for bit)
- [ ] 2.5 Re-derive and publish `parity/semantics/blend-kernels.json`; lift a capability release gap only with its Tier 0 evidence

## 3. Tests
- [ ] 3.1 `blend-component` s0–s6 every channel exact against both recordings on CPU and GPU
- [ ] 3.2 `blend-normal-channel` s1–s3 exact; normal-map modes exact at every recorded opacity
- [ ] 3.3 GPU equals CPU bit for bit for every mode (`kernel-sweep`, `gpu-vs-cpu`)

## 4. Acceptance
- [ ] 4.1 Local DX12 run on the owner's machine exact (decision 028), or an owner-approved exception-register entry for what remains (decision 017)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
