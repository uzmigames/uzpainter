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
//
// Commit point and receipt (task phase2.3_supervisor-jobs, decision 140). A job that makes a
// durable change records it with `JobContext::Commit` the moment it is durable (an export's
// publication, a mutation's revision); a success that changed nothing says so with `NoOp`.
// `Receipt` reports the job in the same terms as the supervisor's job ledger:
// `{id, kind, status, progress, message, committed, stopped, cancel_requested, no_op}`, where
// `committed` is what the job committed (or null) and `stopped` is null for a success no cancel was
// asked of, otherwise `before_commit` or `after_commit`. A job is `succeeded` only when its body ran
// to its end: one that committed and then failed or was cancelled reports `failed` or `cancelled`
// with what it committed, never a success. A cancel that arrives after the body's last checkpoint
// leaves the job `succeeded`, with `cancel_requested` and `stopped: after_commit`.
//
// Engine computations (`application.enable_engine_computations`, phase1.21): while they are
// disabled ordinary queued jobs are deferred, not dropped, and `Busy` keeps naming them. Explicit
// synchronous exports opt into running while paused (observed R10); they skip deferred jobs without
// enabling computations. Enabling computations releases the remaining backlog in submission order.

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
#include "render/backend.h"

namespace uzp::render {
class Engine;
class EngineContext;
}

namespace uzp::python {

enum class JobStatus { queued, running, succeeded, failed, cancelled };

std::string_view JobStatusName(JobStatus status);

class Job;

/// What a job's body sees: its progress and the cancellation request.
class JobContext {
public:
    explicit JobContext(Job& job) : job_(job) {}
    /// Reports progress in [0, 1], with a message when given.
    void SetProgress(double progress, std::string message = {});
    /// Throws the cancellation when the job was asked to stop (a checkpoint).
    void Checkpoint() const;
    /// Whether the job was asked to stop (for work that stops itself, then calls `Checkpoint`).
    bool CancelRequested() const;
    /// Records the job's commit point: what it made durable (`{revision}`, `{generation, ...}`).
    void Commit(core::json::Object committed);
    /// Marks a success that changed nothing.
    void NoOp();

private:
    Job& job_;
};

using JobBody = std::function<core::json::Object(JobContext&)>;
/// Called on the job's thread after each change of its progress or its commit point.
using JobObserver = std::function<void(const Job&)>;

class Job {
public:
    Job(std::string id, std::string kind, JobBody body, JobObserver observer = {}, bool run_when_paused = false);

    const std::string& id() const { return id_; }
    const std::string& kind() const { return kind_; }
    JobStatus status() const;
    double progress() const;
    std::string message() const;
    /// What the job committed, if it reached its commit point.
    std::optional<core::json::Object> committed() const;
    /// The receipt (see above).
    core::json::Object Receipt() const;

    /// Waits for the end (no limit, or at most `timeout`); true when the job has ended.
    bool Wait(std::optional<std::chrono::milliseconds> timeout);
    /// The result of a succeeded job; rethrows the error of a failed one; raises for a cancelled
    /// or unfinished one.
    core::json::Object Result() const;
    /// Drops a queued job; asks a running one to stop at its next checkpoint. False when it has
    /// already ended.
    bool Cancel();
    /// Drops a queued job atomically; never requests cancellation of a running job.
    bool CancelQueued();

private:
    friend class JobEngine;
    friend class JobContext;
    bool Cancel(bool queued_only);
    void Run();

    const std::string id_;
    const std::string kind_;
    JobBody body_;
    const JobObserver observer_;
    const bool run_when_paused_;
    mutable std::mutex mutex_;
    std::condition_variable ended_;
    JobStatus status_ = JobStatus::queued;
    double progress_ = 0.0;
    std::string message_;
    bool cancel_requested_ = false;
    std::optional<core::json::Object> committed_;
    bool no_op_ = false;
    core::json::Object result_;
    std::exception_ptr error_;
};

class JobEngine {
public:
    static JobEngine& Get();

    /// Queues `body` as a job of `kind` (`export`, ...); `observer` sees its progress.
    /// `run_when_paused` opts explicit synchronous work into bypassing the computations pause.
    std::shared_ptr<Job> Start(std::string kind, JobBody body, JobObserver observer = {},
                               bool run_when_paused = false);
    /// Every job of this process, in submission order.
    std::vector<std::shared_ptr<Job>> List() const;
    /// A job that is queued or running, if any, other than the one whose body runs on the calling
    /// thread: a job is not busy with itself.
    std::optional<std::string> Busy() const;
    /// Engine computations: while paused, ordinary queued jobs wait (see above).
    void SetPaused(bool paused);
    bool Paused() const;

private:
    JobEngine() = default;
    void Work();

    mutable std::mutex mutex_;
    std::condition_variable queued_;
    std::deque<std::shared_ptr<Job>> queue_;
    std::vector<std::shared_ptr<Job>> jobs_;
    std::uint64_t next_ = 1;
    bool started_ = false;
    bool paused_ = false;
};

/// The export of the current revision as a job body (bind_export.cpp): `config` is Painter's
/// `json_config` as JSON text, `fixed_names` the folders that receive the generation's files under
/// their fixed names. It checks at every tile and every file, and its commit point is the
/// publication of the generation. Raises `RuntimeError` while a native `Transaction` is open.
JobBody ExportJob(std::string config, std::vector<std::string> fixed_names);

/// A host's operational engine for exports, or null for the CPU path. Set before submitting
/// jobs; the engine and callback must outlive them. The worker supplies its Debug fault hook.
void SetExportGpu(render::Engine* engine,
                  std::function<render::Result<void>(render::EngineContext&)> beforeGpu = {},
                  std::function<void(const render::Error&)> failed = {});

/// Lazy CLI engine factory, copied into each queued export; the job owns the returned engine
/// until all submitted work and tile-store cleanup finish. Plan/source refusals do not call it.
void SetExportGpuFactory(std::function<std::shared_ptr<render::Engine>()> createEngine);

}  // namespace uzp::python
