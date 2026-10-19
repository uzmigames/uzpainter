#include "bake/baker.h"

#include <utility>

namespace uzp::bake {

const char* JobStatusName(JobStatus status) {
    switch (status) {
        case JobStatus::Running: return "Running";
        case JobStatus::Success: return "Success";
        case JobStatus::Cancel: return "Cancel";
        case JobStatus::Fail: return "Fail";
    }
    return "unknown";
}

struct JobState {
    std::uint64_t id = 0;
    JobControl control;
    mutable std::mutex mutex;
    mutable std::condition_variable ended;
    JobStatus status = JobStatus::Running;
    BakeResult result;
    std::exception_ptr error;
    std::thread thread;

    /// Publication: `Success` with the whole result, unless a stop was requested first.
    void Publish(BakeResult&& value) {
        {
            const std::lock_guard<std::mutex> lock(mutex);
            if (control.stop_requested()) {
                status = JobStatus::Cancel;
            } else {
                result = std::move(value);
                status = JobStatus::Success;
            }
        }
        ended.notify_all();
    }

    /// A requested stop wins over a later failure: `cancel()` returned true, so the job ends in
    /// `Cancel`.
    void Failed(std::exception_ptr failure) {
        {
            const std::lock_guard<std::mutex> lock(mutex);
            if (control.stop_requested()) {
                status = JobStatus::Cancel;
            } else {
                error = std::move(failure);
                status = JobStatus::Fail;
            }
        }
        ended.notify_all();
    }
};

namespace {

std::atomic<std::uint64_t> g_next_job_id{1};

}  // namespace

JobHandle JobHandle::Start(std::function<BakeResult(JobControl&)> work) {
    JobHandle handle;
    handle.state_ = std::make_shared<JobState>();
    handle.state_->id = g_next_job_id.fetch_add(1);
    JobState* state = handle.state_.get();
    // The handle joins the thread before the state goes away, so the raw pointer stays valid.
    state->thread = std::thread([state, work = std::move(work)] {
        try {
            state->Publish(work(state->control));
        } catch (...) {
            state->Failed(std::current_exception());
        }
    });
    return handle;
}

JobHandle& JobHandle::operator=(JobHandle&& other) noexcept {
    if (this != &other) {
        JobHandle discarded(std::move(*this));
        state_ = std::move(other.state_);
    }
    return *this;
}

JobHandle::~JobHandle() {
    if (!state_) return;
    cancel();
    if (state_->thread.joinable()) state_->thread.join();
}

std::uint64_t JobHandle::id() const { return state_ ? state_->id : 0; }

JobStatus JobHandle::status() const {
    if (!state_) throw std::logic_error("an empty JobHandle has no status");
    const std::lock_guard<std::mutex> lock(state_->mutex);
    return state_->status;
}

JobProgress JobHandle::progress() const {
    if (!state_) return {};
    return {state_->control.done_.load(std::memory_order_acquire),
            state_->control.total_.load(std::memory_order_acquire)};
}

bool JobHandle::cancel() {
    if (!state_) return false;
    const std::lock_guard<std::mutex> lock(state_->mutex);
    if (state_->status != JobStatus::Running) return false;
    state_->control.stop_.store(true, std::memory_order_release);
    return true;
}

JobStatus JobHandle::wait() const {
    if (!state_) throw std::logic_error("an empty JobHandle cannot be waited for");
    std::unique_lock<std::mutex> lock(state_->mutex);
    state_->ended.wait(lock, [&] { return state_->status != JobStatus::Running; });
    return state_->status;
}

const BakeResult& JobHandle::result() const {
    if (!state_) throw std::logic_error("an empty JobHandle has no result");
    const std::lock_guard<std::mutex> lock(state_->mutex);
    switch (state_->status) {
        case JobStatus::Success: return state_->result;
        case JobStatus::Cancel:
            throw JobCancelled("bake job " + std::to_string(state_->id) +
                               " was cancelled: nothing was published");
        case JobStatus::Fail: std::rethrow_exception(state_->error);
        case JobStatus::Running: break;
    }
    throw std::logic_error("bake job " + std::to_string(state_->id) + " is still running");
}

std::string JobHandle::error_message() const {
    if (!state_) return {};
    const std::lock_guard<std::mutex> lock(state_->mutex);
    if (!state_->error) return {};
    try {
        std::rethrow_exception(state_->error);
    } catch (const std::exception& error) {
        return error.what();
    } catch (...) {
        return "unknown error";
    }
}

BakeResult BakeAndWait(IBaker& baker, const BakeRequest& request) {
    const JobHandle job = baker.bake(request);
    job.wait();
    return job.result();
}

}  // namespace uzp::bake
