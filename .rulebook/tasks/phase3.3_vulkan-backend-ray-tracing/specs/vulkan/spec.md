# Vulkan — backend and ray tracing (P3-VULKAN acceptance)

## ADDED Requirements

### Requirement: Vulkan Acceptance Closes Only With All Children
The P3-VULKAN parent SHALL close only when `phase3.1_vulkan-compute-parity` and `phase3.2_vulkan-ray-tracing` are both accepted and the qualification report is published under `parity/reports/phase3/`.

#### Scenario: Ray tracing child open
Given `phase3.1_vulkan-compute-parity` accepted and `phase3.2_vulkan-ray-tracing` still open
When acceptance of P3-VULKAN is evaluated
Then the parent MUST remain open

### Requirement: Vulkan Acceptance Qualification Report
The qualification report SHALL record, from one build, the `selftest` results on both backends, the DX12-vs-Vulkan comparison of the Tier 0 subset and of every exported map of Wand v1, Belt v5 and Tunic v10, and every per-ray difference of the ray-cast fixtures between DXR and Vulkan, with the build hash, adapter, driver and every exception relied on.

#### Scenario: Report contents
Given both children accepted
When the report is generated on the owner's machine
Then it MUST contain numbers and hashes only, name the build hash, adapter and driver, and list each exception entry it relies on

### Requirement: Vulkan Acceptance Divergence Only Through Exceptions
Any non-zero difference between Vulkan and DX12 texture outputs, or between Vulkan and DXR ray-cast records, MUST fail acceptance unless an owner-approved entry in `parity/exceptions.json` covers it; reporting a difference alone MUST NOT pass it.

#### Scenario: Unapproved divergence
Given one pilot map differing between DX12 and Vulkan
When no approved exception names that map and backend pair
Then P3-VULKAN MUST NOT be accepted

### Requirement: Vulkan Acceptance No Silent Fallback
Backend selection SHALL stay explicit: a process uses the backend chosen by `--gpu-backend` for its lifetime, and an unavailable Vulkan device or ray-query feature MUST be reported as unavailable, never replaced by DX12 or a software path.

#### Scenario: Vulkan requested on a machine without Vulkan
Given a supervisor started with `--gpu-backend vulkan` on a machine without a usable Vulkan device
When a GPU operation is requested
Then it MUST fail with `gpu_backend_unavailable {backend: vulkan, reason}` before mutating anything and DX12 MUST NOT be used
