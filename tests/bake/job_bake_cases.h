// The bake job (phase3.3_baker-evidence-publication items 2.5 and 3.3; decision 355). Included inside
// the native driver's namespace after the receipt cases: their publication fixtures
// (`receipt_cases::Published`, `PublicationProject`) are the document the job publishes into.

namespace job_cases {

/// A publisher into `p.document`: every set in one transaction (`PublishInto`), as the session's.
Publisher Into(receipt_cases::Published& p, const Capabilities& caps, std::function<void()> after = {}) {
    return [&p, caps, after](const std::vector<BakedSet>& sets, std::uint64_t job_id) {
        PublicationContext context;
        context.job_id = job_id;
        context.build_hash = "test-build";
        context.published_at = "2026-10-22T00:00:00Z";
        Publication publication;
        const std::string key = "bake-job-" + std::to_string(job_id);
        const uzp::core::RequestOutcome outcome = uzp::core::Execute(
            p.document, {"bake_start", uzp::core::json::Object{{"key", key}}, key, p.document.revision()},
            [&](uzp::core::Edit& edit) {
                for (const BakedSet& set : sets) {
                    publication.sets.push_back(
                        PublishInto(edit, p.document.revision(), *set.request, *set.result, caps, context, p.stage));
                }
            });
        if (!outcome.result || outcome.result->status != uzp::core::ResultStatus::committed) {
            throw std::runtime_error("publication failed: " + (outcome.result ? outcome.result->error : std::string("not executed")));
        }
        publication.revision = outcome.result->revision;
        if (after) after();
        return publication;
    };
}

BakeRequest JobRequest(const BakeMesh& low, const BakeMesh& high) {
    BakeRequest request = receipt_cases::OffsetPlaneRequest(low, high, {MeshMapUsage::AO, MeshMapUsage::Normal});
    request.output_size_log2[0] = request.output_size_log2[1] = 7;
    request.input_revision = "0";
    return request;
}

const BakerDetail& Detail(const BakeJobReport& report, MeshMapUsage usage) {
    for (const BakerDetail& d : report.bakers) {
        if (d.usage == usage) return d;
    }
    throw Failure(std::string("no baker detail for ") + UsageName(usage));
}

}  // namespace job_cases

/// 2.5: a job bakes, reports progress, publishes at its one commit point and ends in `Success`,
/// with every baker `published`; its id is unique and a late cancel is refused.
void CaseBakeJobSuccess() {
    using namespace job_cases;
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeMesh high = NormalHigh({0, 0, 1});
    receipt_cases::Published p(receipt_cases::PublicationProject(128));
    const std::shared_ptr<BakeJob> job =
        BakeJob::Start(baker, {{JobRequest(low, high), nullptr}}, Into(p, baker.caps()));
    const std::shared_ptr<BakeJob> other =
        BakeJob::Start(baker, {{JobRequest(low, high), nullptr}}, [](const std::vector<BakedSet>&, std::uint64_t) -> Publication {
            throw std::runtime_error("unused");
        });
    CHECK(job->id() != other->id());
    double before = 0.0;
    while (!job->wait_for(std::chrono::milliseconds(1))) {
        const double now = job->progress();
        CHECK(now >= before && now <= 1.0);
        before = now;
    }
    CHECK(job->wait() == JobStatus::Success && job->progress() == 1.0);
    CHECK(!job->cancel());  // ended: a published bake stays published
    const BakeJobReport report = job->report();
    CHECK(report.stopped == StopPoint::None && !report.cancel_requested && report.error.empty());
    CHECK_EQ(report.bakers.size(), 2u);
    for (const BakerDetail& d : report.bakers) CHECK(d.outcome == BakerOutcome::Published && d.texture_set == "fixture");
    CHECK(report.publication && report.publication->revision == 1 && p.document.revision() == 1);
    CHECK_EQ(p.Set().mesh_maps.size(), 2u);
    const uzp::core::json::Object json = ReportJson(report);
    CHECK(json.at("status") == uzp::core::json::Value("Success") && json.at("stopped").IsNull());
    CHECK(json.at("committed_revision") == uzp::core::json::Value(std::int64_t{1}));
    other->wait();
}

/// 2.5, 3.3: a cancel during the cast is acknowledged at once and stops at a tile boundary:
/// `Cancel`, `before_publication`, every baker `cancelled`, nothing bound, the revision intact.
void CaseBakeJobCancelBeforePublication() {
    using namespace job_cases;
    std::atomic<BakeJob*> target{nullptr};
    std::atomic<int> acknowledged{-1};
    BakerConfig config;
    config.on_tile_done = [&](std::uint32_t) {
        BakeJob* job = target.load();
        if (job && acknowledged.load() < 0) acknowledged = job->cancel() ? 1 : 0;
    };
    EmbreeBaker baker(config);
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeMesh high = NormalHigh({0, 0, 1});
    BakeRequest request = JobRequest(low, high);
    request.output_size_log2[0] = request.output_size_log2[1] = 9;  // 1024 tiles
    request.threads = 1;
    receipt_cases::Published p(receipt_cases::PublicationProject(512));
    bool published = false;
    const std::shared_ptr<BakeJob> job = BakeJob::Start(baker, {{request, nullptr}}, [&](const std::vector<BakedSet>&, std::uint64_t) -> Publication {
        published = true;
        return {};
    });
    target = job.get();
    CHECK(job->wait() == JobStatus::Cancel);
    CHECK_EQ(acknowledged.load(), 1);
    CHECK(job->progress() < 1.0);
    const BakeJobReport report = job->report();
    CHECK(report.stopped == StopPoint::BeforePublication && report.cancel_requested && !report.publication);
    for (const BakerDetail& d : report.bakers) CHECK(d.outcome == BakerOutcome::Cancelled);
    CHECK(!published && p.document.revision() == 0 && p.Set().mesh_maps.empty());
    CHECK(!job->cancel());
    CHECK(ReportJson(report).at("stopped") == uzp::core::json::Value("before_publication"));
}

/// 2.5, 3.3: a cancel that arrives once the publication committed ends the job in `Cancel`,
/// `after_publication`, with the committed bindings intact.
void CaseBakeJobCancelAfterPublication() {
    using namespace job_cases;
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeMesh high = NormalHigh({0, 0, 1});
    receipt_cases::Published p(receipt_cases::PublicationProject(128));
    std::shared_ptr<BakeJob> job;
    std::mutex started;
    std::unique_lock<std::mutex> hold(started);  // the publisher waits until `job` is set
    bool acknowledged = false;
    job = BakeJob::Start(baker, {{JobRequest(low, high), nullptr}}, Into(p, baker.caps(), [&] {
                             const std::lock_guard<std::mutex> lock(started);
                             acknowledged = job->cancel();
                         }));
    hold.unlock();
    CHECK(job->wait() == JobStatus::Cancel && acknowledged);
    const BakeJobReport report = job->report();
    CHECK(report.stopped == StopPoint::AfterPublication && report.cancel_requested);
    CHECK(report.publication && report.publication->revision == 1);
    for (const BakerDetail& d : report.bakers) CHECK(d.outcome == BakerOutcome::Published);
    CHECK(p.document.revision() == 1 && p.Set().mesh_maps.size() == 2u);
    CHECK(ReportJson(report).at("stopped") == uzp::core::json::Value("after_publication"));
}

/// 2.5, 3.3: a baker failing on one usage fails the job with per-baker detail (that baker
/// `failed`, the other `not_published`); a cast failure fails every baker of its set; a refused
/// publication names the refused baker. Nothing is bound in any of them.
void CaseBakeJobFailures() {
    using namespace job_cases;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeMesh high = NormalHigh({0, 0, 1});
    {
        EmbreeBaker baker;
        receipt_cases::Published p(receipt_cases::PublicationProject(128));
        BakeJobOptions options;
        options.fail_usage = {"fixture", MeshMapUsage::AO};
        const std::shared_ptr<BakeJob> job =
            BakeJob::Start(baker, {{JobRequest(low, high), nullptr}}, Into(p, baker.caps()), options);
        CHECK(job->wait() == JobStatus::Fail);
        const BakeJobReport report = job->report();
        CHECK(report.stopped == StopPoint::BeforePublication && !report.publication);
        CHECK(Detail(report, MeshMapUsage::AO).outcome == BakerOutcome::Failed);
        CHECK(Contains(Detail(report, MeshMapUsage::AO).error, "AO baker"));
        CHECK(Detail(report, MeshMapUsage::Normal).outcome == BakerOutcome::NotPublished);
        CHECK(p.document.revision() == 0 && p.Set().mesh_maps.empty());
    }
    {
        BakerConfig config;
        config.faults.embree_acquisition_failure = 0;
        EmbreeBaker baker(config);
        receipt_cases::Published p(receipt_cases::PublicationProject(128));
        const std::shared_ptr<BakeJob> job =
            BakeJob::Start(baker, {{JobRequest(low, high), nullptr}}, Into(p, baker.caps()));
        CHECK(job->wait() == JobStatus::Fail);
        const BakeJobReport report = job->report();
        CHECK(report.error_type == "CapabilityError" && Contains(report.error, "fixture"));
        for (const BakerDetail& d : report.bakers) CHECK(d.outcome == BakerOutcome::Failed && !d.error.empty());
        CHECK(p.document.revision() == 0 && p.Set().mesh_maps.empty());
    }
    {
        EmbreeBaker baker;
        const std::shared_ptr<BakeJob> job = BakeJob::Start(
            baker, {{JobRequest(low, high), nullptr}}, [](const std::vector<BakedSet>&, std::uint64_t) -> Publication {
                throw PublicationRefused("Normal refused", {{"fixture", MeshMapUsage::Normal, BakerOutcome::Refused,
                                                             "NotYetSupported", "Normal refused"}});
            });
        CHECK(job->wait() == JobStatus::Fail);
        const BakeJobReport report = job->report();
        CHECK(report.error_type == "NotYetSupported" && report.error == "Normal refused");
        CHECK(Detail(report, MeshMapUsage::Normal).outcome == BakerOutcome::Refused);
        CHECK(Detail(report, MeshMapUsage::AO).outcome == BakerOutcome::NotPublished);
    }
    // A refusal is raised by Start, before any work: no job exists.
    EmbreeBaker baker;
    BakeRequest curvature = JobRequest(low, high);
    curvature.usages = {MeshMapUsage::Curvature};
    ExpectThrow<CapabilityError>([&] {
        (void)BakeJob::Start(baker, {{JobRequest(low, high), nullptr}, {curvature, nullptr}},
                             [](const std::vector<BakedSet>&, std::uint64_t) -> Publication { return {}; });
    });
}
