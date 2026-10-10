## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.8_toolchain-slice, phase1.1_core-device-kernels

## 2. Implementation
- [ ] 2.1 Implement `TextureReadback` request objects owning their staging buffer, with the 256-byte aligned row pitch of `CopyTextureToBuffer`
- [ ] 2.2 Link each map to the copy's fence and map only after the fence wait returns `signaled`; return the wait error otherwise
- [ ] 2.3 Implement drain: complete or fail every outstanding request and release every staging buffer
- [ ] 2.4 Support the native formats used by channels and mesh maps (8-bit, 16-bit unorm, 16/32-bit float; one to four channels) without conversion

## 3. Tests
- [ ] 3.1 Drain test: many concurrent readback requests drained in submission order; no staging buffer remains allocated afterwards
- [ ] 3.2 Pitch test: widths whose row size is not a multiple of 256 bytes (1, 3, 1023, 4097 texels) read back with correct rows
- [ ] 3.3 Exactness test: uploaded known values read back bit-identical for every supported format
- [ ] 3.4 Failure test: a readback after injected device removal returns an error and never returns previous data

## 4. Acceptance
- [ ] 4.1 Readback drain tests green on the DX12 hardware adapter (P1-CORE gate item)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
