#pragma once

// The baker interface of `docs/architecture/06-baking.md` §1 and its job model (§6; decision
// 306): `IBaker::bake` refuses an unqualified configuration or an invalid request before any work
// (it throws), otherwise it starts an asynchronous job and returns its `JobHandle`. A job reports
// progress in tiles, can be cancelled, and ends in exactly one terminal status. Its result is
// published only on `Success`, whole: a cancelled or failed job publishes nothing.

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <exception>
#include <functional>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>

#include "bake/bake_request.h"

namespace uzp::bake {

/// Painter's `BakingStatus` members, plus `Running` before the terminal status.
enum class JobStatus { Running, Success, Cancel, Fail };

const char* JobStatusName(JobStatus status);

struct JobProgress {
    std::uint32_t done_tiles = 0;
    std::uint32_t total_tiles = 0;  // 0 until the job has partitioned the texture
};

/// Raised by `JobHandle::result()` on a job that ended in `Cancel`.
class JobCancelled : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

/// What a running job sees of its handle: the stop request and the progress counters.
class JobControl {
public:
    bool stop_requested() const { return stop_.load(std::memory_order_acquire); }
    void set_total_tiles(std::uint32_t total) { total_.store(total, std::memory_order_release); }
    void tile_done() { done_.fetch_add(1, std::memory_order_acq_rel); }

private:
    friend class JobHandle;
    friend struct JobState;
    std::atomic<bool> stop_{false};
    std::atomic<std::uint32_t> done_{0};
    std::atomic<std::uint32_t> total_{0};
};

struct JobState;

/// One bake job. Move-only; destroying the handle of a running job cancels it and waits for it.
class JobHandle {
public:
    JobHandle() = default;
    JobHandle(JobHandle&&) noexcept = default;
    JobHandle& operator=(JobHandle&& other) noexcept;
    JobHandle(const JobHandle&) = delete;
    JobHandle& operator=(const JobHandle&) = delete;
    ~JobHandle();

    /// Runs `work` on a new thread. Throws (and starts nothing) when the thread cannot be made.
    static JobHandle Start(std::function<BakeResult(JobControl&)> work);

    bool valid() const { return state_ != nullptr; }
    std::uint64_t id() const;
    JobStatus status() const;
    JobProgress progress() const;
    /// Requests a stop. True when the job was still running: it then ends in `Cancel` and
    /// publishes nothing. False when it had already ended (a published result stays published).
    bool cancel();
    /// Blocks until the terminal status.
    JobStatus wait() const;
    /// The result of a `Success` job (after `wait`). A `Cancel` job raises `JobCancelled`, a
    /// `Fail` job rethrows its error, a running job raises `std::logic_error`.
    const BakeResult& result() const;
    /// The error of a `Fail` job (empty otherwise).
    std::string error_message() const;

private:
    std::shared_ptr<JobState> state_;
};

/// `docs/architecture/06-baking.md` §1.
class IBaker {
public:
    virtual ~IBaker() = default;
    virtual Capabilities caps() const = 0;
    /// Refusals (`CapabilityError`, `uzp::core::NotYetSupported`, `uzp::core::ValueError`) are
    /// thrown before any work; otherwise the bake runs as a job.
    virtual JobHandle bake(const BakeRequest& request) = 0;
};

/// `baker.bake(request)`, waited for: the result, or the job's error rethrown.
BakeResult BakeAndWait(IBaker& baker, const BakeRequest& request);

}  // namespace uzp::bake
