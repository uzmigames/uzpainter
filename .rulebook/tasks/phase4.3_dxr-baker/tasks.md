## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase3.5_embree-bakers`, `phase3.3_vulkan-backend-ray-tracing`

## 2. Children (mandatory for this optional parent)
- [ ] 2.1 Child accepted: `phase4.1_dxr-gpu-baker-core`
- [ ] 2.2 Child accepted: `phase4.2_dxr-dx12-rt`
- [ ] 2.3 Child accepted: `phase4.2_dxr-vulkan-rt`

## 3. Integration
- [ ] 3.1 Backend selection through the bake request and `caps()`; `embree` stays the default and the reference
- [ ] 3.2 Capability-manifest entries per backend: `supported` only for a qualified backend, otherwise an explicit gap naming the missing feature or failed qualification
- [ ] 3.3 One qualification report per backend in `parity/reports/phase4/` (Embree comparison, Painter-golden comparison, exceptions relied on)

## 4. Tests
- [ ] 4.1 The same `BakeRequest` on `embree`, `dx12_rt` and `vulkan_rt` produces receipts with identical settings hashes and backend fields that name each backend
- [ ] 4.2 Importing mesh maps and every stack operation work with no GPU baker available

## 5. Acceptance
- [ ] 5.1 DAG gate P4-DXR met: each backend qualified separately against Embree outputs and Painter goldens — same outputs or approved exceptions

## 6. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 6.1 Update or create documentation covering the implementation
- [ ] 6.2 Write tests covering the new behavior
- [ ] 6.3 Run tests and confirm they pass
