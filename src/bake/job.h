#pragma once

// The bake job (phase3.3_baker-evidence-publication item 2.5, `docs/architecture/06-baking.md` §6;
// decision 355): one job bakes one or more texture sets, each a request on the baker's own job
// (`IBaker::bake`, `JobHandle`), and publishes them all at one commit point.
//
// - `Start` asks the baker for every set's job at once, so every refusal (`CapabilityError`,
//   `uzp::core::NotYetSupported`, `uzp::core::ValueError`) is raised by `Start`, before any work and
//   before the job exists; a set already started is cancelled.
// - Progress is the tiles done over the tiles of every set (0 until each set has partitioned its
//   texture); cancellation is checked at tile boundaries by the baker.
// - `cancel()` is acknowledged at once: it returns true while the job runs and asks every set's
//   job to stop. A stop before the commit point ends the job in `Cancel`, `before_publication`,
//   with nothing published. A stop asked while the publication runs, or after it committed but
//   before the job ended, ends it in `Cancel`, `after_publication`, with the publication intact.
// - The publisher runs once, after every set baked: it binds them all in one transaction, or
//   nothing. It refuses usages by throwing `PublicationRefused`, whose per-baker detail the report
//   keeps; any other throw fails every baker of the job as `not_published`.
// - Terminal status: `Success` (published), `Cancel` or `Fail`, with one `BakerDetail` per
//   (texture set, usage) saying what became of that baker.

#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "bake/bake_publication.h"
#include "bake/baker.h"
#include "uzp_core/manifest/json.h"

namespace uzp::bake {

/// One texture set to bake: its request, and what keeps the request's meshes alive.
struct SetBake {
    BakeRequest request;
    std::shared_ptr<const void> meshes;
};

/// Where a job stopped with respect to its single commit point.
enum class StopPoint { None, BeforePublication, AfterPublication };
/// `null`, `before_publication`, `after_publication`.
const char* StopPointName(StopPoint point);

/// What became of one baker of a job.
enum class BakerOutcome { Published, Failed, Refused, NotPublished, Cancelled };
/// `published`, `failed`, `refused`, `not_published`, `cancelled`.
const char* BakerOutcomeName(BakerOutcome outcome);

struct BakerDetail {
    std::string texture_set;
    MeshMapUsage usage = MeshMapUsage::AO;
    BakerOutcome outcome = BakerOutcome::NotPublished;
    /// The error's class (`NotYetSupported`, `ValueError`, `CapabilityError`, `RuntimeError`) and
    /// message; empty for a published or cancelled baker.
    std::string error_type;
    std::string error;
};

/// A set that baked, as the publisher sees it.
struct BakedSet {
    const BakeRequest* request = nullptr;
    const BakeResult* result = nullptr;
};

/// What a committed publication made: its revision and each set's receipt, in set order.
struct Publication {
    std::int64_t revision = 0;
    std::vector<PublishedSet> sets;
};

/// Thrown by a publisher that refuses usages before any change: the detail of each refused baker.
class PublicationRefused : public std::runtime_error {
public:
    PublicationRefused(const std::string& message, std::vector<BakerDetail> refused)
        : std::runtime_error(message), refused_(std::move(refused)) {}
    const std::vector<BakerDetail>& refused() const { return refused_; }

private:
    std::vector<BakerDetail> refused_;
};

/// Publishes every set of a job (job id given) in one transaction, or throws and publishes nothing.
using Publisher = std::function<Publication(const std::vector<BakedSet>& sets, std::uint64_t job_id)>;

struct BakeJobReport {
    std::uint64_t job_id = 0;
    JobStatus status = JobStatus::Running;
    StopPoint stopped = StopPoint::None;
    bool cancel_requested = false;
    std::vector<BakerDetail> bakers;
    /// Set when the publication committed.
    std::optional<Publication> publication;
    /// The job's error (a failure), or empty.
    std::string error_type;
    std::string error;
};

/// `{job_id, status, stopped, cancel_requested, bakers[], committed_revision, receipts[], error}`.
core::json::Object ReportJson(const BakeJobReport& report);

struct BakeJobOptions {
    /// Test seam (never set in production): the baker of this (texture set, usage) fails after its
    /// set's cast, before the publication, as a baker failing on one usage would.
    std::optional<std::pair<std::string, MeshMapUsage>> fail_usage;
};

class BakeJob {
public:
    /// Starts the job: raises the baker's refusals before any work (see above).
    static std::shared_ptr<BakeJob> Start(IBaker& baker, std::vector<SetBake> sets, Publisher publish,
                                          BakeJobOptions options = {});
    /// Cancels a running job and waits for its end.
    ~BakeJob();
    BakeJob(const BakeJob&) = delete;
    BakeJob& operator=(const BakeJob&) = delete;

    std::uint64_t id() const { return id_; }
    JobStatus status() const;
    /// Tiles done over the tiles of every set, in [0, 1]; 1 once the job succeeded.
    double progress() const;
    /// Asks the job to stop; true when it was still running (acknowledged at once).
    bool cancel();
    /// Blocks until the terminal status.
    JobStatus wait() const;
    /// Waits at most `timeout`; true when the job has ended.
    bool wait_for(std::chrono::milliseconds timeout) const;
    /// The report (final once the job has ended).
    BakeJobReport report() const;

private:
    BakeJob() = default;
    void Run();
    void End(BakeJobReport report);

    std::uint64_t id_ = 0;
    std::vector<SetBake> sets_;
    std::vector<JobHandle> jobs_;
    Publisher publish_;
    BakeJobOptions options_;
    mutable std::mutex mutex_;
    mutable std::condition_variable ended_;
    JobStatus status_ = JobStatus::Running;
    bool stop_ = false;
    std::optional<Publication> published_;
    BakeJobReport report_;
    std::thread thread_;
};

}  // namespace uzp::bake
