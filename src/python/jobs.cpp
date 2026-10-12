// Worker jobs (jobs.h).

#include "python/jobs.h"

#include <algorithm>

#include "python/errors.h"

namespace uzp::python {

namespace {

/// Thrown by `JobContext::Checkpoint` when the job was asked to stop.
struct Cancelled {};

}  // namespace

std::string_view JobStatusName(JobStatus status) {
    switch (status) {
        case JobStatus::queued: return "queued";
        case JobStatus::running: return "running";
        case JobStatus::succeeded: return "succeeded";
        case JobStatus::failed: return "failed";
        case JobStatus::cancelled: return "cancelled";
    }
    return "failed";
}

void JobContext::SetProgress(double progress) {
    std::lock_guard lock(job_.mutex_);
    job_.progress_ = std::clamp(progress, 0.0, 1.0);
}

void JobContext::Checkpoint() const {
    std::lock_guard lock(job_.mutex_);
    if (job_.cancel_requested_) throw Cancelled{};
}

Job::Job(std::string id, std::string kind, JobBody body)
    : id_(std::move(id)), kind_(std::move(kind)), body_(std::move(body)) {}

JobStatus Job::status() const {
    std::lock_guard lock(mutex_);
    return status_;
}

double Job::progress() const {
    std::lock_guard lock(mutex_);
    return progress_;
}

bool Job::Wait(std::optional<std::chrono::milliseconds> timeout) {
    std::unique_lock lock(mutex_);
    const auto ended = [this] {
        return status_ == JobStatus::succeeded || status_ == JobStatus::failed || status_ == JobStatus::cancelled;
    };
    if (timeout) return ended_.wait_for(lock, *timeout, ended);
    ended_.wait(lock, ended);
    return true;
}

core::json::Object Job::Result() const {
    std::lock_guard lock(mutex_);
    switch (status_) {
        case JobStatus::succeeded: return result_;
        case JobStatus::failed: std::rethrow_exception(error_);
        case JobStatus::cancelled: throw ApiError("RuntimeError", "job " + id_ + " was cancelled");
        default: throw ApiError("RuntimeError", "job " + id_ + " has not ended");
    }
}

bool Job::Cancel() {
    std::lock_guard lock(mutex_);
    if (status_ == JobStatus::queued) {
        status_ = JobStatus::cancelled;
        body_ = nullptr;
        ended_.notify_all();
        return true;
    }
    if (status_ == JobStatus::running) {
        cancel_requested_ = true;
        return true;
    }
    return false;
}

void Job::Run() {
    JobBody body;
    {
        std::lock_guard lock(mutex_);
        if (status_ != JobStatus::queued) return;  // cancelled while queued
        status_ = JobStatus::running;
        body = std::move(body_);
    }
    JobContext context(*this);
    JobStatus status = JobStatus::succeeded;
    core::json::Object result;
    std::exception_ptr error;
    try {
        result = body(context);
    } catch (const Cancelled&) {
        status = JobStatus::cancelled;
    } catch (...) {
        status = JobStatus::failed;
        error = std::current_exception();
    }
    std::lock_guard lock(mutex_);
    status_ = status;
    if (status == JobStatus::succeeded) progress_ = 1.0;
    result_ = std::move(result);
    error_ = error;
    ended_.notify_all();
}

JobEngine& JobEngine::Get() {
    static JobEngine* engine = new JobEngine();  // its worker outlives every static destructor
    return *engine;
}

std::shared_ptr<Job> JobEngine::Start(std::string kind, JobBody body) {
    std::lock_guard lock(mutex_);
    auto job = std::make_shared<Job>("job-" + std::to_string(next_++), std::move(kind), std::move(body));
    jobs_.push_back(job);
    queue_.push_back(job);
    if (!started_) {
        started_ = true;
        std::thread([this] { Work(); }).detach();
    }
    queued_.notify_one();
    return job;
}

std::vector<std::shared_ptr<Job>> JobEngine::List() const {
    std::lock_guard lock(mutex_);
    return jobs_;
}

std::optional<std::string> JobEngine::Busy() const {
    std::lock_guard lock(mutex_);
    for (const auto& job : jobs_) {
        const JobStatus status = job->status();
        if (status == JobStatus::queued || status == JobStatus::running) return job->id();
    }
    return std::nullopt;
}

void JobEngine::SetPaused(bool paused) {
    std::lock_guard lock(mutex_);
    paused_ = paused;
    if (!paused) queued_.notify_all();
}

bool JobEngine::Paused() const {
    std::lock_guard lock(mutex_);
    return paused_;
}

void JobEngine::Work() {
    for (;;) {
        std::shared_ptr<Job> job;
        {
            std::unique_lock lock(mutex_);
            queued_.wait(lock, [this] { return !queue_.empty() && !paused_; });
            job = std::move(queue_.front());
            queue_.pop_front();
        }
        job->Run();
    }
}

}  // namespace uzp::python
