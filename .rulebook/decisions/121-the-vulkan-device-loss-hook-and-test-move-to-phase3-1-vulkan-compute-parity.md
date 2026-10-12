# 121. The Vulkan device-loss hook and test move to phase3.1_vulkan-compute-parity

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.1_supervisor-ipc-worker, phase3.1_vulkan-compute-parity, phase2.4_supervisor-worker

## Context

phase2.1 items 2.11 and 3.3 ask for a Vulkan device-loss hook and a Vulkan variant of the device-fault test. `render::CreateDevice` implements DX12 only, and a Vulkan request is reported `gpu_backend_unavailable`, never served by DX12. phase3.1_vulkan-compute-parity already owns:

- the Vulkan device wrapper (item 2.1);
- its deadline wait, with `VK_ERROR_DEVICE_LOST` mapped to `device_removed {backend, reason}` (item 2.2);
- "device-loss and stall injection on Vulkan" (item 3.4).

The model panel (one round, with decision 120) agreed ×3 that the hook cannot exist before a Vulkan device does. GPT asked that phase3.1's test run through the supervisor.

## Decision

1. **phase3.1_vulkan-compute-parity items 2.2 and 3.4** own the Vulkan device-loss hook and the Vulkan device-fault test. The test runs through the supervisor: `device_removed` is reported, the worker exits, and the supervisor relaunches it on Vulkan at the last committed revision. The hook joins `src/supervisor/fault_hooks.h` (`remove_device` on a Vulkan device), under the same Debug-only rule as decision 120.
2. **Until then, `--gpu-backend vulkan` runs without a device.** The worker starts with `gpu_status: unavailable`. The CPU-lane tests use this to exercise the unavailable-backend rule (GPU calls refused before mutating, GPU-free calls served) without creating any device.
3. phase2.1 items 2.11 and 3.3 are checked for their DX12 part, with this split recorded. Nothing in them claims a Vulkan result.

## Alternatives Considered

- **Keeping phase2.1 open until Vulkan exists.** Rejected: the blocker is a later phase's deliverable (the decision-069 pattern).
- **A simulated Vulkan device loss without a device.** Rejected: it would test nothing real.

## Consequences

- phase3.1 item 3.4 names the supervisor path.
- phase2.4's acceptance (both backends) still needs that item.
