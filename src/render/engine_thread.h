#pragma once

// The engine thread: sole owner of the GPU device of the selected backend
// (docs/architecture/02-runtime-topology.md §4). Other threads submit requests against immutable
// revision snapshots and receive the results through futures; requests run one at a time, in
// submission order, on the engine thread. Every GPU wait of a request is bounded by the request's
// deadline (default 60 s, configurable), and the failure model of 02 §5 applies:
//
// - no device of the requested backend: every request fails with `gpu_backend_unavailable
//   {backend, reason}` before its work runs (nothing is mutated, no other backend is tried);
// - a removed or lost device, or a wait that passes its deadline: the request fails with
//   `device_removed {backend, reason}` or `timeout`, and so does every later request (the worker
//   is expected to exit and be relaunched).

#include "render/backend.h"
#include "render/capabilities.h"
#include "render/device.h"
#include "render/kernel_cache.h"

#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <thread>
#include <type_traits>
#include <unordered_map>
#include <utility>

namespace uzp::render {

struct EngineOptions {
    DeviceOptions device;
    /// Bound of every GPU wait of one request, counted from the start of the request.
    std::chrono::milliseconds requestDeadline{60'000};
    /// Kernel cache folder; empty: `DefaultKernelCacheRoot()`.
    std::filesystem::path kernelCacheRoot;
    /// `dxcompiler.dll`; empty: `DefaultDxcompilerPath()`.
    std::filesystem::path dxcompiler;
    AdmissionPolicy admission;
};

class Engine;

/// What a request's work sees on the engine thread. Valid only during that request.
class EngineContext {
public:
    [[nodiscard]] IDevice& Device() { return m_device; }
    /// The point in time every wait of this request is bounded by.
    [[nodiscard]] Deadline RequestDeadline() const { return m_deadline; }

    /// Submits one command list (see `IQueue::Submit`).
    Result<uint64_t> Submit(const RecordFn& record);
    /// Waits for a submission until the request's deadline; `timeout` or `device_removed`
    /// otherwise.
    Result<void> Wait(uint64_t value);
    Result<void> SubmitAndWait(const RecordFn& record);

    /// The kernel compiled through the cache for this device's bytecode format and created on
    /// the device; created once per cache key and kept until the engine stops.
    Result<ComputeKernel> Kernel(const KernelSource& source);

private:
    friend class Engine;
    EngineContext(IDevice& device, Engine& engine, Deadline deadline)
        : m_device(device), m_engine(engine), m_deadline(deadline) {}

    IDevice& m_device;
    Engine& m_engine;
    Deadline m_deadline;
};

class Engine {
public:
    /// Starts the engine thread, which creates the device, queries its capabilities and loads
    /// DXC; returns once that is done.
    explicit Engine(EngineOptions options);
    /// `Stop()`.
    ~Engine();
    Engine(const Engine&) = delete;
    Engine& operator=(const Engine&) = delete;

    /// Empty when the device is ready; `gpu_backend_unavailable {backend, reason}` otherwise.
    [[nodiscard]] const std::optional<Error>& DeviceError() const { return m_deviceError; }
    /// The capability report of the device, with the derived admission budget.
    [[nodiscard]] Result<CapabilityReport> Capabilities() const;
    [[nodiscard]] std::thread::id ThreadId() const { return m_thread.get_id(); }
    [[nodiscard]] const EngineOptions& Options() const { return m_options; }

    /// Queues `work(context, *snapshot)` for the engine thread. `work` returns `Result<T>`; the
    /// snapshot is kept alive until the request has run.
    template <class Snapshot, class Work>
    auto Submit(std::shared_ptr<const Snapshot> snapshot, Work work)
        -> std::future<std::invoke_result_t<Work&, EngineContext&, const Snapshot&>>;

    /// Fails the requests still queued with `engine_stopped`, waits for the running one, then
    /// releases the GPU objects on the engine thread and joins it. When the GPU did not drain
    /// before the deadline the device is deliberately not destroyed (destroying resources the GPU
    /// may still use is unsafe); the process is expected to exit.
    void Stop();

private:
    friend class EngineContext;

    struct Job {
        std::function<void(EngineContext&)> run;
        std::function<void(const Error&)> fail;
    };

    void Enqueue(Job job);
    void ThreadMain(std::promise<void> started);
    void RunJob(Job& job);
    void Teardown();
    Result<void> WaitFor(uint64_t value, Deadline deadline);
    /// What a failed request reports (02 §5): the fatal fault it already hit (a wait's `timeout`
    /// or `device_removed`), else the removal of the device, else `error` itself.
    Error RequestError(Error error) const;
    Result<ComputeKernel> KernelFor(const KernelSource& source);

    EngineOptions m_options;
    std::thread m_thread;

    // Engine-thread state.
    std::unique_ptr<IDevice> m_device;
    std::optional<Error> m_deviceError;
    std::optional<Error> m_fatal;
    std::optional<CapabilityReport> m_capabilities;
    std::optional<Error> m_capabilityError;
    std::unique_ptr<DxcKernelCompiler> m_compiler;
    std::optional<Error> m_compilerError;
    std::unique_ptr<KernelCache> m_kernelCache;
    std::unordered_map<uint64_t, ComputeKernel> m_kernels;

    // Shared with submitting threads.
    std::mutex m_mutex;
    std::condition_variable m_wake;
    std::deque<Job> m_jobs;
    bool m_stopping = false;
};

template <class Snapshot, class Work>
auto Engine::Submit(std::shared_ptr<const Snapshot> snapshot, Work work)
    -> std::future<std::invoke_result_t<Work&, EngineContext&, const Snapshot&>> {
    using R = std::invoke_result_t<Work&, EngineContext&, const Snapshot&>;
    static_assert(std::is_same_v<R, Result<typename R::value_type>>,
                  "engine work must return uzp::render::Result<T>");
    auto promise = std::make_shared<std::promise<R>>();
    std::future<R> future = promise->get_future();
    if (!snapshot) {
        promise->set_value(Fail(ErrorCode::RequestFailed, m_options.device.backend,
                                "request submitted without a revision snapshot"));
        return future;
    }
    Job job;
    job.run = [this, promise, snapshot = std::move(snapshot),
               work = std::move(work)](EngineContext& context) mutable {
        R result = work(context, *snapshot);
        // A creation or map call on a removed device fails with its own code: the request
        // reports the device fault instead, so the caller sees the cause, not its symptom.
        if (!result) result = Unexpected(RequestError(std::move(result.error())));
        promise->set_value(std::move(result));
    };
    job.fail = [promise](const Error& error) { promise->set_value(Unexpected(error)); };
    Enqueue(std::move(job));
    return future;
}

}  // namespace uzp::render
