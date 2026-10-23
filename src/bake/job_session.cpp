#include "bake/job_session.h"

#include <chrono>
#include <memory>
#include <stdexcept>
#include <utility>

#include "bake/bake_publication.h"
#include "bake/bake_receipt.h"
#include "bake/embree_baker.h"
#include "bake/job_inputs.h"
#include "python/errors.h"
#include "python/session.h"
#include "store/container.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

#ifndef UZP_BUILD_MODE
#error "UZP_BUILD_MODE is defined by build.zig"
#endif

namespace uzp::bake {

namespace {

/// The CPU baker of the process (Embree is loaded once).
EmbreeBaker& Baker() {
    static EmbreeBaker* baker = new EmbreeBaker();  // its jobs may outlive static destructors
    return *baker;
}

std::string BuildHash() { return std::string("uzpainter-") + UZP_BUILD_MODE; }

std::string OwnerOf(const Capabilities& caps, MeshMapUsage usage) {
    const auto owner = caps.parity_owner_tasks.find(usage);
    return owner != caps.parity_owner_tasks.end() ? owner->second : UsageOwnerTask(usage);
}

}  // namespace

python::JobBody StartSessionBake(const std::vector<std::string>& texture_sets, const std::vector<MeshMapUsage>& usages,
                                 SessionSubmit submit, BakeJobOptions options) {
    python::Session& session = python::Session::Get();
    if (session.TransactionOpen()) {
        throw python::ApiError("RuntimeError", "a bake reads a committed revision: commit the open Transaction first");
    }
    const std::shared_ptr<python::OpenProject> open = session.Current();
    const core::Snapshot snapshot = open->document->snapshot();
    const core::Project& project = *snapshot.project;
    PreparedBakes prepared = PrepareBakes(
        project, snapshot.revision, [&open](const std::string& sha256) { return open->store->ReadResource(sha256); },
        texture_sets, usages);
    core::ResultRecordHeader header;
    header.revision = snapshot.revision;
    header.evaluator_profile = project.versions.evaluator_profile;
    header.compat_profile = project.versions.compat_profile;
    header.app_version = project.versions.app_version;
    header.resource_hashes = prepared.input_resources;
    EmbreeBaker& baker = Baker();
    const Capabilities caps = baker.caps();

    Publisher publish = [open, header, caps, submit = std::move(submit), inputs = prepared.input_resources](
                            const std::vector<BakedSet>& sets, std::uint64_t job_id) -> Publication {
        // Decision 001: a usage whose receipt does not say `supported` is never bound.
        std::vector<BakerDetail> refused;
        std::string message;
        for (const BakedSet& set : sets) {
            const BakeReceipt receipt =
                BuildReceipt(*set.request, *set.result, caps, ReceiptContext{job_id, header, BuildHash()});
            if (receipt.parity_status == "supported") continue;
            const std::string sha = core::Sha256Hex(ReceiptBytes(receipt));
            for (MeshMapUsage usage : set.request->usages) {
                const std::string why = std::string("publishing ") + UsageName(usage) + " of texture set '" +
                                        set.request->texture_set + "': its parity with Painter is " +
                                        receipt.parity_status + " (decision 001); the bake ran (receipt " + sha +
                                        ") and nothing is bound (owner " + OwnerOf(caps, usage) + ")";
                refused.push_back({set.request->texture_set, usage, BakerOutcome::Refused, "NotYetSupported", why});
                message += (message.empty() ? "" : "; ") + why;
            }
        }
        if (!refused.empty()) throw PublicationRefused(message, std::move(refused));
        PublicationContext context;
        context.job_id = job_id;
        context.build_hash = BuildHash();
        context.input_resources = inputs;
        context.published_at = store::UtcNow();
        Publication publication;
        const StageResource stage = [&open](std::string bytes, std::string mime) {
            return open->store->StageResource(std::move(bytes), std::move(mime));
        };
        publication.revision = submit([&](core::Edit& edit) {
            publication.sets.clear();
            const std::int64_t revision = open->document->revision();
            for (const BakedSet& set : sets) {
                publication.sets.push_back(PublishInto(edit, revision, *set.request, *set.result, caps, context, stage));
            }
            core::json::Array bakes;
            for (const PublishedSet& p : publication.sets) {
                bakes.push_back(core::json::Object{{"texture_set", p.receipt.texture_set},
                                                   {"input_revision", p.receipt.input_revision},
                                                   {"receipt", p.receipt_sha256}});
            }
            edit.returned()["bake"] = std::move(bakes);
        });
        return publication;
    };
    std::shared_ptr<BakeJob> job = BakeJob::Start(baker, std::move(prepared.sets), std::move(publish), std::move(options));

    return [job](python::JobContext& context) -> core::json::Object {
        context.SetProgress(0.0, "baking (job " + std::to_string(job->id()) + ")");
        while (!job->wait_for(std::chrono::milliseconds(20))) {
            if (context.CancelRequested()) job->cancel();
            context.SetProgress(job->progress(), "baking (job " + std::to_string(job->id()) + ")");
        }
        const BakeJobReport report = job->report();
        if (report.publication) context.Commit({{"revision", report.publication->revision}});
        switch (report.status) {
            case JobStatus::Success: return ReportJson(report);
            case JobStatus::Cancel:
                context.Checkpoint();  // the pool's cancellation: the bake stopped because it was asked to
                throw std::logic_error("a bake job ended in Cancel without a cancel request");
            case JobStatus::Fail: break;
            case JobStatus::Running: throw std::logic_error("a bake job ended Running");
        }
        const std::string detail = report.error + " (report: " + core::json::WriteCanonical(ReportJson(report)) + ")";
        if (report.error_type == "NotYetSupported") throw core::NotYetSupported(detail);
        if (report.error_type == "ValueError") throw core::ValueError(detail);
        throw std::runtime_error(detail);
    };
}

}  // namespace uzp::bake
