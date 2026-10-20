#include "render/engine_thread.h"

#include <cstdio>
#include <exception>
#include <string>

namespace uzp::render {

// ── EngineContext ────────────────────────────────────────────────────────────

Result<uint64_t> EngineContext::Submit(const RecordFn& record) {
    if (m_engine.m_fatal) return Unexpected(*m_engine.m_fatal);
    return m_device.Queue().Submit(record);
}

Result<void> EngineContext::Wait(uint64_t value) { return m_engine.WaitFor(value, m_deadline); }

Result<void> EngineContext::SubmitAndWait(const RecordFn& record) {
    Result<uint64_t> value = Submit(record);
    if (!value) return Unexpected(std::move(value.error()));
    return Wait(*value);
}

Result<ComputeKernel> EngineContext::Kernel(const KernelSource& source) {
    return m_engine.KernelFor(source);
}

// ── Engine ───────────────────────────────────────────────────────────────────

Engine::Engine(EngineOptions options) : m_options(std::move(options)) {
    std::promise<void> started;
    std::future<void> ready = started.get_future();
    m_thread = std::thread(&Engine::ThreadMain, this, std::move(started));
    ready.wait();
}

Engine::~Engine() { Stop(); }

Result<CapabilityReport> Engine::Capabilities() const {
    if (m_capabilities) return *m_capabilities;
    if (m_deviceError) return Unexpected(*m_deviceError);
    return Unexpected(*m_capabilityError);
}

void Engine::Enqueue(Job job) {
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (!m_stopping) {
            m_jobs.push_back(std::move(job));
            m_wake.notify_one();
            return;
        }
    }
    job.fail(Error{ErrorCode::EngineStopped, m_options.device.backend,
                   "the engine thread has stopped"});
}

void Engine::Stop() {
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_stopping = true;
    }
    m_wake.notify_all();
    if (m_thread.joinable()) m_thread.join();
}

void Engine::ThreadMain(std::promise<void> started) {
    Result<std::unique_ptr<IDevice>> device =
        m_options.createDevice ? m_options.createDevice() : CreateDevice(m_options.device);
    if (device) {
        m_device = std::move(*device);
    } else {
        m_deviceError = std::move(device.error());
    }
    if (m_device) {
        Result<CapabilityReport> capabilities = QueryCapabilities(*m_device, m_options.admission);
        if (capabilities) {
            m_capabilities = std::move(*capabilities);
        } else {
            m_capabilityError = std::move(capabilities.error());
        }
        const std::filesystem::path dxc =
            m_options.dxcompiler.empty() ? DefaultDxcompilerPath() : m_options.dxcompiler;
        const std::filesystem::path root = m_options.kernelCacheRoot.empty()
                                               ? DefaultKernelCacheRoot()
                                               : m_options.kernelCacheRoot;
        Result<std::unique_ptr<DxcKernelCompiler>> compiler = DxcKernelCompiler::Load(dxc);
        if (!compiler) {
            m_compilerError = std::move(compiler.error());
        } else if (root.empty()) {
            m_compilerError = Error{ErrorCode::KernelCompileFailed, std::nullopt,
                                    "the local app-data folder for the kernel cache is unknown"};
        } else {
            m_compiler = std::move(*compiler);
            m_kernelCache = std::make_unique<KernelCache>(*m_compiler, root);
        }
    }
    started.set_value();

    for (;;) {
        Job job;
        {
            std::unique_lock<std::mutex> lock(m_mutex);
            m_wake.wait(lock, [this] { return m_stopping || !m_jobs.empty(); });
            if (m_stopping) {
                std::deque<Job> pending = std::move(m_jobs);
                m_jobs.clear();
                lock.unlock();
                for (Job& queued : pending) {
                    queued.fail(Error{ErrorCode::EngineStopped, m_options.device.backend,
                                      "the engine thread stopped before the request ran"});
                }
                break;
            }
            job = std::move(m_jobs.front());
            m_jobs.pop_front();
        }
        RunJob(job);
    }
    Teardown();
}

void Engine::RunJob(Job& job) {
    // Nothing runs without a usable device: the request fails before its work can mutate
    // anything.
    std::optional<Error> blocked = m_deviceError ? m_deviceError : m_fatal;
    if (!blocked) {
        blocked = m_device->CheckRemoved();
        if (blocked) m_fatal = blocked;
    }
    if (blocked) {
        job.fail(*blocked);
        return;
    }

    EngineContext context(*m_device, *this, Clock::now() + m_options.requestDeadline);
    try {
        job.run(context);
    } catch (const std::exception& e) {
        job.fail(RequestError(Error{ErrorCode::RequestFailed, m_device->GetBackend(),
                                    std::string("the request threw: ") + e.what()}));
    } catch (...) {
        job.fail(RequestError(Error{ErrorCode::RequestFailed, m_device->GetBackend(),
                                    "the request threw a non-standard exception"}));
    }
    if (!m_fatal) m_fatal = m_device->CheckRemoved();
}

Error Engine::RequestError(Error error) const {
    if (m_fatal) return *m_fatal;
    if (std::optional<Error> removed = m_device->CheckRemoved()) return std::move(*removed);
    return error;
}

Result<void> Engine::WaitFor(uint64_t value, Deadline deadline) {
    if (m_fatal) return Unexpected(*m_fatal);
    const WaitResult wait = m_device->Queue().Wait(value, deadline);
    if (wait.status == WaitStatus::Signaled) return {};
    Error error = m_device->WaitFailure(wait);
    if (error.code == ErrorCode::Timeout) {
        error.reason += " (request deadline " + std::to_string(m_options.requestDeadline.count()) +
                        " ms)";
    }
    // A stalled or lost GPU ends this engine: later requests fail with the same error.
    m_fatal = error;
    return Unexpected(std::move(error));
}

Result<ComputeKernel> Engine::KernelFor(const KernelSource& source) {
    if (!m_kernelCache) return Unexpected(*m_compilerError);
    const KernelTarget target = m_device->NativeKernelTarget();
    const uint64_t key = KernelKey(source, target, m_kernelCache->CompilerVersion());
    if (const auto found = m_kernels.find(key); found != m_kernels.end()) return found->second;
    Result<CompiledKernel> compiled = m_kernelCache->Get(source, target);
    if (!compiled) return Unexpected(std::move(compiled.error()));
    Result<ComputeKernel> kernel = m_device->CreateComputeKernel(compiled->bytecode, source.name);
    if (!kernel) return kernel;
    m_kernels.emplace(key, *kernel);
    return kernel;
}

void Engine::Teardown() {
    if (!m_device) return;
    IQueue& queue = m_device->Queue();
    bool drained = true;
    if (queue.Completed() < queue.LastSubmitted()) {
        // A lost device runs nothing any more; only a GPU still busy at the deadline blocks
        // destruction.
        const WaitResult wait =
            queue.Wait(queue.LastSubmitted(), Clock::now() + m_options.requestDeadline);
        drained = wait.status != WaitStatus::Timeout;
    }
    if (!drained) {
        std::fprintf(stderr,
                     "uzp render: the GPU did not drain before the deadline; the %s device is "
                     "left undestroyed\n",
                     std::string(BackendName(m_device->GetBackend())).c_str());
        m_kernels.clear();
        static_cast<void>(m_device.release());
    } else {
        for (const auto& [key, kernel] : m_kernels) m_device->DestroyComputeKernel(kernel);
        m_kernels.clear();
        m_device.reset();
    }
    m_kernelCache.reset();
    m_compiler.reset();
}

}  // namespace uzp::render
