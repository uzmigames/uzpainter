# 310. Vulkan device qualification lands as a slice of phase3.1: a qualified Vulkan device for the selftest and the native tests only, explicit criteria judged before any work, bounded waits with abandon-on-failure teardown, and no parity claim

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase3.1_vulkan-compute-parity, phase3.3_vulkan-backend-ray-tracing, phase1.4_render-core-layer, phase0.7_toolchain-probes

## Context

Decision 221 §3 lets phase3.1's device qualification (items 2.1, 2.2, 2.6, 2.8, 3.1, 3.4, 3.8) start before Tunic. It is deferred G3 work: it accepts no task and ranks behind the Wand. Before this slice:

- `render::CreateDevice` refused Vulkan (`gpu_backend_unavailable {backend: vulkan}`). Every product path depends on that refusal: `run --gpu-backend vulkan`, the MCP worker (`gpu_status: unavailable`), the preview and export.
- The vendored `uz::VulkanDevice::Init` does instance creation, physical-device selection and `vkCreateDevice` in one call. Its rules:
  - it orders devices discrete, integrated, virtual, cpu, other, keeps enumeration order within a type, and takes `adapterIndex` in that order;
  - it runs everything on the first queue family that has `GRAPHICS`;
  - it always enables 4 device extensions and 14 features;
  - its descriptor set layout is all update-after-bind (16 sampled images, 16 samplers, 16 uniform buffers, 16 storage images), with 128 bytes of push constants;
  - its instance asks for Vulkan 1.2, and falls back to an older loader version.
- The fence wait was already bounded (UZP-MOD-003). The supervisor's audit (SUP-044, SUP-051, SUP-052) and the model panel found these defects:
  - `vkQueueSubmit` failures were only logged;
  - `vkDeviceWaitIdle` at destruction has no timeout;
  - the copy path had no host barrier, and readback memory was not invalidated;
  - readback row pitches were not whole texels for 12-byte texels;
  - the backend called core 1.3 commands (`vkCmdPipelineBarrier2`, `vkCmdBeginRendering`) under a 1.2 instance;
  - an R16f storage image needs `shaderStorageImageExtendedFormats`, which the device never enabled.

The panel ran one round. Its dossier and answers are in `tmp/scratch/vk-qual/panel/` (untracked).

| Claim | GPT (cx/gpt-6-astra) | Kimi (kimi-k3) | Grok (grok-4.5) |
|---|---|---|---|
| C1 product paths keep refusing; a separate entry point | AGREE | AGREE | AGREE |
| C2 vendored order at the requested index, no fallback; verify UUID and family after creation | PARTLY (verify, do not re-derive) | AGREE | AGREE |
| C3 criteria are exactly what the backend and the kernels use | PARTLY (R16f needs extended formats; audit everything) | PARTLY (same) | PARTLY (enumerate verbatim, UAB pool limits) |
| C4 Vulkan slice not mandatory, reported apart | AGREE | AGREE | AGREE |
| C5 bounded drain, then destroy; abandon on failure | DISAGREE (`vkDeviceWaitIdle` is not bounded by the drain) | PARTLY (full abandon, no VMA teardown) | AGREE |
| C6 host barrier after each list, invalidate before reading | PARTLY | AGREE | PARTLY |
| C7 three bit-exact kernels; formats declared; no parity claim | PARTLY (check the emitted SPIR-V) | PARTLY (extended formats) | AGREE |

## Decision

1. **Reach.** `render::CreateDevice(Vulkan)` keeps refusing; only its message changes, to cite this decision. The qualified device `render::VulkanDevice` (`src/render/vulkan_backend.h`) comes from three steps:
   - `SurveyVulkan`: the capability record of every physical device, from a pre-check 1.2 instance; no logical device is created;
   - `QualifyVulkan`;
   - `CreateQualifiedVulkanDevice`.

   Only the `selftest` Vulkan slice and `uzp-render-tests` call them. No Painter-visible output runs on Vulkan, and the capability manifest is unchanged: it has no Vulkan entry, and phase3.1 item 2.10 adds them with their tier evidence.
2. **Selection.** The device judged is the one at the requested adapter index (default 0) of the vendored order. It is qualified or refused. No other device is tried, as the no-fallback rule of `02-runtime-topology.md` §1 requires. The queue is the first `GRAPHICS` family, and it must report `COMPUTE`. After creation, the device's UUID and queue family are compared with the ones judged. A mismatch is refused before anything is submitted.
3. **Criteria** (`src/render/vulkan_qualification.{h,cpp}`). Each criterion is a named check with its required and found values. A refusal names every unmet criterion, before any `vkCreateDevice`.
   - Instance:
     - the loader is loaded;
     - the instance version is at least 1.2, so an older loader is refused instead of falling back;
     - `VK_KHR_surface` and `VK_KHR_win32_surface` are present;
     - a 1.2 instance can be created.
   - Device:
     - a discrete or integrated GPU (CPU and virtual devices are refused, as DX12 refuses software adapters);
     - API version at least 1.2;
     - the vendored 4 extensions;
     - the vendored 14 features, plus `shaderStorageImageExtendedFormats`;
     - the queue family of point 2;
     - the update-after-bind per-stage, per-set and all-pools limits of the vendored layout and pool;
     - `maxPushConstantsSize` at least 128;
     - `shaderSignedZeroInfNanPreserveFloat32` (IEEE-strict SPIR-V, UZP-MOD-008, declares `SignedZeroInfNanPreserve`);
     - work-group sizes of 8x8 and 64 invocations;
     - a `HOST_VISIBLE` and a `DEVICE_LOCAL` memory type;
     - `STORAGE_IMAGE|TRANSFER_SRC` optimal-tiling support for R16_SFLOAT, R32_UINT and R32_SFLOAT.

   `VK_EXT_memory_budget` is recorded and optional (the backend enables it when present). After creation, the device-level entry points the backend calls must resolve: Vulkan 1.2 core and the KHR names (`MissingVulkanEntryPoints`).
4. **Vendored changes.**
   - UZP-MOD-011: `VulkanCommandList::LastSubmitResult` and `VulkanFence::LastSignalResult` expose each `vkQueueSubmit` result.
   - UZP-MOD-012:
     - barriers and dynamic rendering go through `vkCmdPipelineBarrier2KHR`, `vkCmdBeginRenderingKHR` and `vkCmdEndRenderingKHR`, the extensions the device enables;
     - `shaderStorageImageExtendedFormats` is enabled when supported.

   Qualification stays at Vulkan 1.2 plus those extensions; it does not narrow to 1.3.
5. **Submissions and waits.** A submission is the command list, a pre-recorded host-visibility barrier, then the fence signal.
   - A refused command list fails `Submit` at once, and nothing reached the GPU. The error is `device_removed` for `VK_ERROR_DEVICE_LOST`, `request_failed` otherwise.
   - A refusal after it (barrier or signal) is a **partial submission**. The work may still run, so the device is failed for good: `Destroy*` keep their objects, and `Create*` and `Submit` fail.
   - A refused signal fails every wait on its value at once, never by a timeout.
   - Every wait is the bounded UZP-MOD-003 wait.
   - Readback buffers are invalidated (`vmaInvalidateAllocation`) before the host reads them.
6. **Teardown.** `Shutdown(deadline)` first waits for the last submission.
   - If that wait signals and nothing failed, the device is destroyed. The vendored destructor then calls `vkDeviceWaitIdle`. **That call is not bounded by the deadline**; it is only reached after every submission on the device's one queue has completed.
   - On a timeout, a device loss or a failed submission, the device is abandoned: nothing of it is destroyed or waited on again, and its memory lasts until the process ends.
   - A process-level bound for a hung driver is the supervisor's worker relaunch, which is item 3.4 and still `pending`.
7. **Descriptors and admission in Vulkan's terms.** No descriptor lives with a texture. Each dispatch binds one snapshot of the 64-binding set from one device-wide pool. So:
   - per dispatch, at most 16 bindings of each type, or less where the device's limit is lower;
   - the pool holds 128 snapshots at once, bounded by its 2048 samplers;
   - live tiles are not bounded by descriptors.

   The admission bytes are `DeriveAdmissionBudget` over the device-local heaps. With `VK_EXT_memory_budget` they use its budget and usage. Without it, they use the heap size with usage unknown, under the policy's reserve and share.
8. **Readback pitch** (`ReadbackRowPitch(rowBytes, texel)`). The pitch is a multiple of both 256 and the texel size, so a row is a whole number of texels on Vulkan. For RGB32F that is 768-byte steps; power-of-two texels are unchanged, and DX12 accepts the larger pitch. On the owner's RTX 4090 (driver 617.14), `R32G32B32_SFLOAT` has no optimal-tiling features at all, so Vulkan cannot create an RGB32F texture there. The Vulkan `TextureReadback` (item 2.4) must refuse that format by name rather than read it.
9. **Selftest.** `vulkan-device`, `vulkan-compute-readback` and `vulkan-png16` run after the probes and report `vulkan_hardware_slice`, apart from the DX12 slice and the `vulkan-availability` probe. They are not mandatory, so they never change the exit code; phase3.1's acceptance makes them a gate.
   - The kernels are pattern16 (R16_SFLOAT, the DX12 slice's pattern), hash32 (R32_UINT) and ieee32 (R32_SFLOAT, IEEE-strict). They are checked bit for bit against CPU references, at the slice size and at an odd width.
   - Their SPIR-V must declare its image format and may use only the capabilities the criteria cover: `Shader`, `StorageImageExtendedFormats` (exactly for R16f) and `SignedZeroInfNanPreserve` (exactly for the IEEE-strict kernel); no `...WithoutFormat` capability.
   - The R16 result is also compared with the DX12 readback. That comparison is recorded as a fact, not as parity evidence.

## Alternatives Considered

- **Let `--gpu-backend vulkan` reach the new device now.** Rejected by all three models: it would produce Painter-visible output on a backend whose outputs nobody has compared.
- **Pick the first qualified device.** Rejected: it silently changes which GPU produces outputs.
- **Bound `vkDeviceWaitIdle` by a fence deadline.** Rejected: Vulkan offers no bounded device-idle wait, and claiming one would be untrue (GPT, SUP-044). Process isolation is the bound (item 3.4).
- **Refuse API < 1.3 and keep the core 1.3 names.** Rejected: the instance asks for 1.2, so the core 1.3 names stay outside the effective API version even on a 1.3 device.
- **A kernel format that needs no extended-format capability.** Rejected: the R16 pattern is the DX12 slice's, and keeping it lets the slice compare the two readbacks.
- **Mandatory Vulkan stages now.** Rejected: G0 was accepted on DX12, and no gate requires Vulkan yet.

## Consequences

- phase3.1 items 2.1, 2.2, 2.6, 2.8, 3.1 and 3.4 are implemented in part (see the task's notes). No item is checked, and the Vulkan entries of `supervisor-settling.json` and `preview-settling.json` stay `pending`.
- Supervisor and pyapi tests still use `--gpu-backend vulkan` as their GPU-free backend (decision 221). They stay correct while `CreateDevice(Vulkan)` refuses. Before phase3.1 lifts that refusal, they need a deterministic unavailable-device fixture of their own.
- `uzp-render-tests vulkan-qualify` is that fixture for the render layer. It refuses an unqualified device before the loader is even loaded, and it needs no GPU.
