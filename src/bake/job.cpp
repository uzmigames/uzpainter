#include "bake/job.h"

#include <atomic>
#include <exception>

#include "uzp_core/types/errors.h"

namespace uzp::bake {

const char* StopPointName(StopPoint point) {
    switch (point) {
        case StopPoint::None: return "null";
        case StopPoint::BeforePublication: return "before_publication";
        case StopPoint::AfterPublication: return "after_publication";
    }
    return "unknown";
}

const char* BakerOutcomeName(BakerOutcome outcome) {
    switch (outcome) {
        case BakerOutcome::Published: return "published";
        case BakerOutcome::Failed: return "failed";
        case BakerOutcome::Refused: return "refused";
        case BakerOutcome::NotPublished: return "not_published";
        case BakerOutcome::Cancelled: return "cancelled";
    }
    return "unknown";
}

namespace {

std::atomic<std::uint64_t> g_next_bake_job{1};

/// The class of the error `error`, by the names the Python API raises.
std::string ErrorType(const std::exception_ptr& error) {
    try {
        std::rethrow_exception(error);
    } catch (const core::NotYetSupported&) {
        return "NotYetSupported";
    } catch (const core::ValueError&) {
        return "ValueError";
    } catch (const CapabilityError&) {
        return "CapabilityError";
    } catch (...) {
        return "RuntimeError";
    }
}

std::string ErrorMessage(const std::exception_ptr& error) {
    try {
        std::rethrow_exception(error);
    } catch (const std::exception& e) {
        return e.what();
    } catch (...) {
        return "unknown error";
    }
}

/// Every baker of `sets` with `outcome` (and `error` for each).
std::vector<BakerDetail> Every(const std::vector<SetBake>& sets, BakerOutcome outcome, const std::string& type = {},
                               const std::string& error = {}) {
    std::vector<BakerDetail> out;
    for (const SetBake& set : sets) {
        for (MeshMapUsage usage : set.request.usages) out.push_back({set.request.texture_set, usage, outcome, type, error});
    }
    return out;
}

/// `details` with the bakers `marked` names replaced by their entry in `marked`.
void Mark(std::vector<BakerDetail>& details, const std::vector<BakerDetail>& marked) {
    for (const BakerDetail& m : marked) {
        for (BakerDetail& d : details) {
            if (d.texture_set == m.texture_set && d.usage == m.usage) d = m;
        }
    }
}

}  // namespace

core::json::Object ReportJson(const BakeJobReport& report) {
    using core::json::Value;
    core::json::Array bakers;
    for (const BakerDetail& d : report.bakers) {
        core::json::Object entry{{"texture_set", d.texture_set},
                                 {"usage", UsageName(d.usage)},
                                 {"outcome", BakerOutcomeName(d.outcome)}};
        if (!d.error.empty()) {
            entry["error_type"] = d.error_type;
            entry["error"] = d.error;
        }
        bakers.push_back(std::move(entry));
    }
    core::json::Array receipts;
    if (report.publication) {
        for (const PublishedSet& set : report.publication->sets) {
            receipts.push_back(core::json::Object{{"texture_set", set.receipt.texture_set},
                                                  {"input_revision", set.receipt.input_revision},
                                                  {"receipt_sha256", set.receipt_sha256}});
        }
    }
    core::json::Object out{{"job_id", Value(report.job_id)},
                           {"status", JobStatusName(report.status)},
                           {"stopped", report.stopped == StopPoint::None ? Value(nullptr) : Value(StopPointName(report.stopped))},
                           {"cancel_requested", report.cancel_requested},
                           {"bakers", std::move(bakers)},
                           {"committed_revision", report.publication ? Value(report.publication->revision) : Value(nullptr)},
                           {"receipts", std::move(receipts)}};
    out["error"] = report.error.empty() ? Value(nullptr)
                                        : Value(core::json::Object{{"type", report.error_type}, {"message", report.error}});
    return out;
}

std::shared_ptr<BakeJob> BakeJob::Start(IBaker& baker, std::vector<SetBake> sets, Publisher publish,
                                        BakeJobOptions options) {
    if (sets.empty()) throw core::ValueError("a bake job needs at least one texture set");
    std::shared_ptr<BakeJob> job(new BakeJob());
    job->id_ = g_next_bake_job.fetch_add(1);
    job->sets_ = std::move(sets);
    job->publish_ = std::move(publish);
    job->options_ = std::move(options);
    job->report_.job_id = job->id_;
    // Every refusal before any work: a set already started is cancelled when `job` goes away.
    for (const SetBake& set : job->sets_) job->jobs_.push_back(baker.bake(set.request));
    BakeJob* raw = job.get();
    job->thread_ = std::thread([raw] { raw->Run(); });
    return job;
}

BakeJob::~BakeJob() {
    cancel();
    if (thread_.joinable()) thread_.join();
}

JobStatus BakeJob::status() const {
    const std::lock_guard<std::mutex> lock(mutex_);
    return status_;
}

double BakeJob::progress() const {
    if (status() == JobStatus::Success) return 1.0;
    double sum = 0.0;
    for (const JobHandle& job : jobs_) {
        const JobProgress p = job.progress();
        if (p.total_tiles > 0) sum += static_cast<double>(p.done_tiles) / static_cast<double>(p.total_tiles);
    }
    return jobs_.empty() ? 0.0 : sum / static_cast<double>(jobs_.size());
}

bool BakeJob::cancel() {
    const std::lock_guard<std::mutex> lock(mutex_);
    if (status_ != JobStatus::Running) return false;
    stop_ = true;
    for (JobHandle& job : jobs_) job.cancel();
    return true;
}

JobStatus BakeJob::wait() const {
    std::unique_lock<std::mutex> lock(mutex_);
    ended_.wait(lock, [&] { return status_ != JobStatus::Running; });
    return status_;
}

bool BakeJob::wait_for(std::chrono::milliseconds timeout) const {
    std::unique_lock<std::mutex> lock(mutex_);
    return ended_.wait_for(lock, timeout, [&] { return status_ != JobStatus::Running; });
}

BakeJobReport BakeJob::report() const {
    const std::lock_guard<std::mutex> lock(mutex_);
    return report_;
}

void BakeJob::End(BakeJobReport report) {
    {
        const std::lock_guard<std::mutex> lock(mutex_);
        report.job_id = id_;
        report.cancel_requested = stop_;
        status_ = report.status;
        report_ = std::move(report);
    }
    ended_.notify_all();
}

void BakeJob::Run() {
    BakeJobReport report;
    report.bakers = Every(sets_, BakerOutcome::NotPublished);
    const auto stopped = [&] {
        const std::lock_guard<std::mutex> lock(mutex_);
        return stop_;
    };
    const auto cancelled = [&] {
        report.status = JobStatus::Cancel;
        report.stopped = StopPoint::BeforePublication;
        report.bakers = Every(sets_, BakerOutcome::Cancelled);
        End(std::move(report));
    };
    // Every set's cast; the first that failed fails the job, unless a stop was asked first.
    std::vector<BakedSet> baked;
    for (std::size_t i = 0; i < jobs_.size(); ++i) {
        const JobStatus status = jobs_[i].wait();
        if (status == JobStatus::Success) {
            baked.push_back({&sets_[i].request, &jobs_[i].result()});
            continue;
        }
        for (JobHandle& job : jobs_) job.cancel();
        if (status == JobStatus::Cancel || stopped()) return cancelled();
        std::exception_ptr error;
        try {
            (void)jobs_[i].result();
        } catch (...) {
            error = std::current_exception();
        }
        report.status = JobStatus::Fail;
        report.stopped = StopPoint::BeforePublication;
        report.error_type = ErrorType(error);
        report.error = "texture set '" + sets_[i].request.texture_set + "': " + ErrorMessage(error);
        SetBake failed = sets_[i];
        Mark(report.bakers, Every({failed}, BakerOutcome::Failed, report.error_type, ErrorMessage(error)));
        return End(std::move(report));
    }
    if (options_.fail_usage) {
        const auto& [set, usage] = *options_.fail_usage;
        for (const SetBake& s : sets_) {
            if (s.request.texture_set != set) continue;
            for (MeshMapUsage u : s.request.usages) {
                if (u != usage) continue;
                report.status = JobStatus::Fail;
                report.stopped = StopPoint::BeforePublication;
                report.error_type = "RuntimeError";
                report.error = std::string("the ") + UsageName(usage) + " baker of texture set '" + set +
                               "' failed (injected fault): nothing is published";
                Mark(report.bakers, {{set, usage, BakerOutcome::Failed, report.error_type, report.error}});
                return End(std::move(report));
            }
        }
    }
    // The commit point.
    if (stopped()) return cancelled();
    try {
        Publication publication = publish_(baked, id_);
        report.publication = std::move(publication);
        report.bakers = Every(sets_, BakerOutcome::Published);
        const bool stop_after = stopped();
        report.status = stop_after ? JobStatus::Cancel : JobStatus::Success;
        report.stopped = stop_after ? StopPoint::AfterPublication : StopPoint::None;
        return End(std::move(report));
    } catch (const PublicationRefused& refused) {
        if (stopped()) return cancelled();
        report.status = JobStatus::Fail;
        report.stopped = StopPoint::BeforePublication;
        report.error_type = refused.refused().empty() ? "RuntimeError" : refused.refused().front().error_type;
        report.error = refused.what();
        Mark(report.bakers, refused.refused());
        return End(std::move(report));
    } catch (...) {
        if (stopped()) return cancelled();
        const std::exception_ptr error = std::current_exception();
        report.status = JobStatus::Fail;
        report.stopped = StopPoint::BeforePublication;
        report.error_type = ErrorType(error);
        report.error = "the publication failed: " + ErrorMessage(error);
        report.bakers = Every(sets_, BakerOutcome::NotPublished, report.error_type, report.error);
        return End(std::move(report));
    }
}

}  // namespace uzp::bake
