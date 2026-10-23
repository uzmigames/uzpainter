# 357. CLI Python exports use the selected GPU lazily and drain jobs before reporting

**Status**: accepted
**Date**: 2026-10-23
**Related Tasks**: phase3.1_vulkan-compute-parity

## Context

Decisions 111 and 148 retained CPU export in the single-process run host while its GPU backend selection applied to viewport capture. The worker now exports on its operational GPU, and Vulkan product activation requires the run host to honor the same explicit backend selection. This changes only those earlier decisions' CPU-only run-export provision.

## Decision

UzPainter.exe run uses DX12 by default or the explicit --gpu-backend dx12|vulkan. Each export job creates and owns its selected render Engine after export-plan validation and source preflight, retaining it until submitted work and tile-store cleanup finish. Device creation and GPU evaluation failures are reported without CPU fallback. No device is created at process start, on rejected preflight, or for a paused queued job cancelled at shutdown. The explicit --test-gpu-unavailable Debug fixture keeps export on the CPU path and still refuses GPU capture; Release builds reject that fixture. After the script returns, the run host waits for jobs and drains dispatcher callbacks while stdout/stderr remain captured, cancels queued jobs when computations are paused, and only then finalizes its one JSON report and closes the project. Worker RunSource callers retain their existing lifecycle through the optional completion callback's empty default. The separate UzPainter.exe export command remains CPU.

## Alternatives Considered

- Keep run exports CPU despite --gpu-backend: rejected because backend selection would misrepresent the export execution path.
- Create the engine at process startup: rejected because invalid plans and CPU-only scripts must not require a GPU.
- Fall back to CPU after a selected GPU failure: rejected because receipts and failure behavior must expose actual backend availability.

## Consequences

Receipts identify the tile store actually used: backend plus adapter and driver for GPU, cpu plus null identities for the explicit CPU fixture. CLI export no longer uses the retained CPU tile cache; decoded inputs may still be reused. Unawaited asynchronous jobs are joined; their failures remain available through job results and do not independently change an otherwise successful script result. Validation: 26 CLI CPU tests and four real hardware tests pass; DX12/Vulkan synchronous and asynchronous masked-height PNG16 exports equal CPU bytes on the same revision, with truthful receipts and strict output framing. A controlled pause-after-wait regression times out on the previous binary and completes after bounded host waits recheck the pause. Queued-only cancellation checks and updates status under the job mutex, so a running job receives no cancellation request. The native runner fixture explicitly selects CPU with --test-gpu-unavailable. Debug, ReleaseSafe, ReleaseFast and ReleaseSmall painter/pyapi-tests builds pass.
