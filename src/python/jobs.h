#pragma once

// Worker jobs of the `uzpainter` module (`uzpainter.jobs`, docs/architecture/10-python-api.md §7;
// task phase1.19_pyapi-native-module item 2.8).
//
// A job is work that runs off the Python command thread: one worker thread runs the queued jobs in
// submission order, one at a time, and never touches Python. A job reads the revision it was
// submitted on (a snapshot), so mutations go on while it runs; closing or saving the project while
// it is queued or running raises `BusyError(job_id)`. `Job::Wait` blocks the caller until the job
// ends (the bindings release the GIL around it, so other Python threads run meanwhile), then
// returns its result or rethrows the error that failed it. `Cancel` drops a queued job at once and
// asks a running one to stop at its next checkpoint; a cancelled job's wait raises.
//
// Statuses: `queued`, `running`, `succeeded`, `failed`, `cancelled`. `progress` is 0 until the job
// reports otherwise and 1 when it succeeded.

#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <exception>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include "uzp_core/manifest/json.h"

namespace uzp::python {

enum class JobStatus { queued, running, succeeded, failed, cancelled };

std::string_view JobStatusName(JobStatus status);

class Job;

/// What a job's body sees: its progress and the cancellation request.
class JobContext {
public:
    explicit JobContext(Job& job) : job_(job) {}
    /// Reports progress in [0, 1].
    void SetProgress(double progress);
    /// Throws the cancellation when the job was asked to stop (a checkpoint).
    void Checkpoint() const;

private:
    Job& job_;
};

using JobBody = std::function<core::json::Object(JobContext&)>;

class Job {
public:
    Job(std::string id, std::string kind, JobBody body);

    const std::string& id() const { return id_; }
    const std::string& kind() const { return kind_; }
    JobStatus status() const;
    double progress() const;

    /// Waits for the end (no limit, or at most `timeout`); true when the job has ended.
    bool Wait(std::optional<std::chrono::milliseconds> timeout);
    /// The result of a succeeded job; rethrows the error of a failed one; raises for a cancelled
    /// or unfinished one.
    core::json::Object Result() const;
    /// Drops a queued job; asks a running one to stop at its next checkpoint. False when it has
    /// already ended.
    bool Cancel();

private:
    friend class JobEngine;
    friend class JobContext;
    void Run();

    const std::string id_;
    const std::string kind_;
    JobBody body_;
    mutable std::mutex mutex_;
    std::condition_variable ended_;
    JobStatus status_ = JobStatus::queued;
    double progress_ = 0.0;
    bool cancel_requested_ = false;
    core::json::Object result_;
    std::exception_ptr error_;
};

class JobEngine {
public:
    static JobEngine& Get();

    /// Queues `body` as a job of `kind` (`export`, ...) and returns it.
    std::shared_ptr<Job> Start(std::string kind, JobBody body);
    /// Every job of this process, in submission order.
    std::vector<std::shared_ptr<Job>> List() const;
    /// A job that is queued or running, if any.
    std::optional<std::string> Busy() const;

private:
    JobEngine() = default;
    void Work();

    mutable std::mutex mutex_;
    std::condition_variable queued_;
    std::deque<std::shared_ptr<Job>> queue_;
    std::vector<std::shared_ptr<Job>> jobs_;
    std::uint64_t next_ = 1;
    bool started_ = false;
};

}  // namespace uzp::python
