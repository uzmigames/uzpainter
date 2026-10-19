// `uzpainter.export` and `uzpainter.jobs`: the export over the export engine of `src/export/` as a
// worker job, its dry run, and the job handles (jobs.h).
//
// `export.plan(config)` compiles Painter's `json_config` against the current revision and returns
// the typed plan (`uzpainter/export-plan/1`, decision 085), `export.list_project_textures(config)`
// is the dry run in Painter's `{(texture set, stack): [files]}` shape (decision 091). `export.start`
// queues the export of the current revision as a job: the plan is compiled and checked, every
// file is evaluated on the CPU evaluator (the evaluator the export tests compare with Painter's
// goldens; the revision's kept evaluation, evaluation.h, so the tiles an earlier export, capture or
// diagnostic of the same revision computed are not computed again), encoded, and published as a
// new generation under the configuration's `exportPath`
// with its receipt (`PublishExport`, decision 097); `fixed_names` folders then receive the
// generation's files under their fixed names (`CopyFixedNames`; `exportPath` itself gives Painter's
// flat layout). `export.export_project_textures` is the synchronous convenience: start, then wait
// with the GIL released. A refusal (`ValueError`, `NotYetSupported`) happens before anything is
// written; an evaluation failure raises the class of decision 082. The job's result names the
// project file and the imported mesh the export was started from (`project_path`, `mesh_path`),
// absolute, as resolved when the call that named each one ran (None when there is none), so a
// later switch of project or of working directory does not move its sources.
//
// The export job checks for cancellation at every tile the CPU evaluator allocates and before
// every file it evaluates (nothing is written then), and before every fixed-name folder; its commit
// point is the publication of the generation (`JobContext::Commit {generation, revision}`), so a
// cancel during the fixed-name copies reports `stopped: after_commit` (jobs.h, decision 140).

#include <memory>

#include "evaluator/error.h"
#include "evaluator/evaluator.h"
#include "evaluator/templates.h"
#include "export/fixed_names.h"
#include "export/plan.h"
#include "export/publish.h"
#include "export/receipt.h"
#include "python/bindings.h"
#include "python/errors.h"
#include "python/evaluation.h"
#include "python/jobs.h"
#include "python/run.h"

#ifndef UZP_BUILD_MODE
#error "UZP_BUILD_MODE is defined by build.zig"
#endif

namespace uzp::python {

namespace {

std::string ConfigText(const py::object& config) {
    if (py::isinstance<py::str>(config)) return config.cast<std::string>();
    return core::json::WriteCanonical(ToJson(config));
}

std::string ProjectPath() {
    const std::optional<std::filesystem::path> path = Session::Get().FilePath();
    return path ? exporter::Utf8String(*path) : std::string();
}

[[noreturn]] void RaiseRender(const render::Error& error) {
    if (const std::optional<evaluator::EvalErrorKind> kind = evaluator::EvalErrorKindOf(error)) {
        throw ApiError(std::string(evaluator::ErrorClassName(*kind)), error.reason);
    }
    throw ApiError("RuntimeError", error.reason);
}

core::json::Object WrittenJson(const exporter::WrittenFile& file) {
    return {{"path", file.path},
            {"relative_path", file.relativePath},
            {"root_path", file.rootPath},
            {"sha256", file.sha256},
            {"size", static_cast<std::int64_t>(file.size)}};
}

/// The CPU evaluator's tile store, refusing the next tile once the job was asked to stop: the
/// evaluation then fails, and the job ends cancelled before anything is written (a tile checkpoint).
class StoppableTileStore final : public evaluator::ITileStore {
public:
    StoppableTileStore(evaluator::ITileStore& inner, const JobContext& context) : inner_(inner), context_(context) {}

    /// Whether a tile was refused.
    bool stopped() const { return stopped_; }

    render::Result<evaluator::TileHandle> Allocate(const evaluator::TileFormat& format, uint32_t width,
                                                   uint32_t height) override {
        if (context_.CancelRequested()) {
            stopped_ = true;
            return render::Fail(render::ErrorCode::RequestFailed, std::nullopt, "export: cancelled at a tile");
        }
        return inner_.Allocate(format, width, height);
    }
    void Release(evaluator::TileHandle tile) override { inner_.Release(tile); }
    render::Result<void> Upload(evaluator::TileHandle tile, const evaluator::DecodedImage& image, uint32_t x0,
                                uint32_t y0) override {
        return inner_.Upload(tile, image, x0, y0);
    }
    render::Result<void> Project(const evaluator::ProjectOp& op) override { return inner_.Project(op); }
    render::Result<void> Blend(const evaluator::BlendOp& op) override { return inner_.Blend(op); }
    render::Result<void> Levels(const evaluator::LevelsOp& op) override { return inner_.Levels(op); }
    render::Result<void> VirtualNormal(const evaluator::VirtualNormalOp& op) override { return inner_.VirtualNormal(op); }
    render::Result<void> Flush() override { return inner_.Flush(); }
    render::Result<evaluator::TileImage> Read(evaluator::TileHandle tile) override { return inner_.Read(tile); }
    uint64_t AllocatedBytes() const override { return inner_.AllocatedBytes(); }

private:
    evaluator::ITileStore& inner_;
    const JobContext& context_;
    bool stopped_ = false;
};

/// The export job of `snapshot` (see above).
JobBody ExportBody(std::shared_ptr<OpenProject> project, core::Snapshot snapshot, std::string config,
                   std::string project_path, std::string project_source, std::vector<std::string> fixed_names,
                   bool diagnostic) {
    // The export's own sources, absolute, read when it is queued: the mesh from the exported
    // revision itself. A project written before the mesh source was recorded has none (None).
    std::string mesh_source = snapshot.project->mesh ? snapshot.project->mesh->source : std::string();
    return [project = std::move(project), snapshot = std::move(snapshot), config = std::move(config),
            project_path = std::move(project_path), project_source = std::move(project_source),
            mesh_source = std::move(mesh_source), fixed_names = std::move(fixed_names), diagnostic](JobContext& context) {
        const core::Project& p = *snapshot.project;
        const exporter::ExportPlan plan = exporter::CompilePlan(p, config, exporter::PlanContext{project_path});
        exporter::CheckExportable(plan);
        context.SetProgress(0.1, "plan compiled");
        context.Checkpoint();

        // The revision's evaluation: the one an earlier call on this revision kept, tiles included.
        EvaluationLease evaluation = LeaseEvaluation(project, snapshot);
        exporter::SourceInputs inputs = evaluation->inputs;
        context.SetProgress(0.2, "sources ready");
        context.Checkpoint();

        bool stopped_at_file = false;
        inputs.beforeFile = [&](size_t file, size_t files) {
            if (context.CancelRequested()) {
                stopped_at_file = true;
                return false;
            }
            context.SetProgress(0.2 + 0.7 * static_cast<double>(file) / static_cast<double>(files),
                                "evaluating " + plan.files[file].relativePath);
            return true;
        };
        StoppableTileStore tiles(evaluation->cpu.store(), context);
        exporter::PublishRequest request;
        request.identity = exporter::BuildIdentity{kAppVersion, std::string("uzpainter-") + UZP_BUILD_MODE};
        request.projectPath = project_path;
        // `UzPainter.exe run --diagnostic-measure-export` only (run.h): not conformant (decision 286).
        if (diagnostic) request.diagnostic = exporter::DiagnosticMeasure{evaluation->mesh};
        render::Result<exporter::Publication> published = exporter::PublishExport(
            p, snapshot.revision, plan, inputs, *evaluation->templates, tiles, evaluation->cpu.cache(), request);
        if (!published) {
            if (stopped_at_file || tiles.stopped()) context.Checkpoint();  // nothing was written
            RaiseRender(published.error());
        }
        evaluation.Keep();
        context.Commit({{"generation", published->generation},
                        {"directory", exporter::Utf8String(published->directory)},
                        {"revision", snapshot.revision}});
        context.SetProgress(0.9, "published generation " + published->generation);

        core::json::Array files;
        for (const exporter::WrittenFile& file : published->files) files.push_back(WrittenJson(file));
        core::json::Array copies;
        for (const std::string& folder : fixed_names) {
            context.Checkpoint();
            render::Result<exporter::Delivery> delivery =
                exporter::CopyFixedNames(exporter::Utf8Path(plan.exportPath), exporter::Utf8Path(folder));
            if (!delivery) RaiseRender(delivery.error());
            copies.push_back(core::json::Object{{"directory", exporter::Utf8String(delivery->directory)},
                                                {"generation", delivery->generation}});
        }
        core::json::Object result{{"directory", exporter::Utf8String(published->directory)},
                                  {"files", std::move(files)},
                                  {"fixed_names", std::move(copies)},
                                  {"generation", published->generation},
                                  {"mesh_path", mesh_source.empty() ? core::json::Value(nullptr)
                                                                    : core::json::Value(mesh_source)},
                                  {"plan_hash", plan.hash},
                                  {"project_path", project_source.empty() ? core::json::Value(nullptr)
                                                                          : core::json::Value(project_source)},
                                  {"receipt", exporter::Utf8String(published->receipt)},
                                  {"receipt_sha256", published->receiptSha256},
                                  {"revision", snapshot.revision}};
        if (diagnostic) result["non_conformant"] = std::string(exporter::kDiagnosticMeasureMode);
        return result;
    };
}

struct JobHandle {
    std::shared_ptr<Job> job;
};

py::object WaitFor(const JobHandle& handle, std::optional<double> timeout) {
    bool ended = false;
    {
        py::gil_scoped_release release;
        std::optional<std::chrono::milliseconds> limit;
        if (timeout) limit = std::chrono::milliseconds(static_cast<std::int64_t>(*timeout * 1000.0));
        ended = handle.job->Wait(limit);
    }
    if (!ended) throw py::value_error("timeout");
    return FromJson(handle.job->Result());
}

JobHandle StartExport(const py::object& config, const std::vector<std::string>& fixed_names) {
    return {JobEngine::Get().Start("export", ExportJob(ConfigText(config), fixed_names))};
}

}  // namespace

JobBody ExportJob(std::string config, std::vector<std::string> fixed_names) {
    if (Session::Get().TransactionOpen()) {
        throw ApiError("RuntimeError", "an export reads a committed revision: commit the open Transaction first");
    }
    const std::shared_ptr<OpenProject> project = Session::Get().Current();
    core::Snapshot snapshot = project->document->snapshot();
    std::string source = project->untitled_dir.empty() ? exporter::Utf8String(project->project_source) : std::string();
    return ExportBody(project, std::move(snapshot), std::move(config), ProjectPath(), std::move(source),
                      std::move(fixed_names), DiagnosticMeasureExport());
}

void BindExport(py::module_& m, py::module_& jobs) {
    Session::Get().running_job = [] { return JobEngine::Get().Busy(); };

    py::class_<JobHandle> job(jobs, "Job",
                              "A worker job: id, kind, status, progress, message, wait(timeout=None), cancel(), "
                              "receipt().");
    job.def_property_readonly("id", [](const JobHandle& j) { return j.job->id(); })
        .def_property_readonly("kind", [](const JobHandle& j) { return j.job->kind(); })
        .def_property_readonly("status", [](const JobHandle& j) { return std::string(JobStatusName(j.job->status())); })
        .def_property_readonly("progress", [](const JobHandle& j) { return j.job->progress(); })
        .def_property_readonly("message", [](const JobHandle& j) { return j.job->message(); })
        .def("receipt", [](const JobHandle& j) { return FromJson(j.job->Receipt()); },
             "{id, kind, status, progress, message, committed, stopped, cancel_requested, no_op}: what the job "
             "committed and, once it ended, whether it stopped before or after its commit point.")
        .def("wait", &WaitFor, py::arg("timeout") = py::none(),
             "Blocks (the GIL released) until the job ends, then returns its result or raises its error; "
             "ValueError('timeout') when `timeout` seconds pass first.")
        .def("cancel", [](const JobHandle& j) { return j.job->Cancel(); })
        .def("__repr__", [](const JobHandle& j) {
            return "Job(" + j.job->id() + ", " + j.job->kind() + ", " + std::string(JobStatusName(j.job->status())) + ")";
        });
    SealClass(job);
    jobs.def(
        "busy", []() -> py::object {
            const std::optional<std::string> job = JobEngine::Get().Busy();
            return job ? py::object(py::str(*job)) : py::none();
        },
        "The id of a job that is queued (deferred included) or running, else None.");
    jobs.def("list", [] {
        std::vector<JobHandle> handles;
        for (auto& j : JobEngine::Get().List()) handles.push_back({j});
        return handles;
    });

    m.def(
        "plan",
        [](const py::object& config) {
            const auto project = Read();
            return FromJson(exporter::PlanJson(
                exporter::CompilePlan(*project, ConfigText(config), exporter::PlanContext{ProjectPath()})));
        },
        py::arg("json_config"), "The typed plan of `json_config` on the current revision (a dry run; nothing is written).");
    m.def(
        "list_project_textures",
        [](const py::object& config) {
            const auto project = Read();
            py::dict out;
            for (const exporter::StackFiles& entry :
                 exporter::ListProjectTextures(*project, ConfigText(config), exporter::PlanContext{ProjectPath()})) {
                out[py::make_tuple(entry.textureSet, entry.stack)] = entry.files;
            }
            return out;
        },
        py::arg("json_config"));
    m.def("start", &StartExport, py::arg("json_config"), py::arg("fixed_names") = std::vector<std::string>{},
          "Queues the export of the current revision; returns its jobs.Job.");
    m.def(
        "export_project_textures",
        [](const py::object& config, const std::vector<std::string>& fixed_names) {
            return WaitFor(StartExport(config, fixed_names), std::nullopt);
        },
        py::arg("json_config"), py::arg("fixed_names") = std::vector<std::string>{},
        "Exports and waits (the GIL released): {generation, directory, receipt, receipt_sha256, plan_hash, "
        "revision, files, fixed_names}.");
}

}  // namespace uzp::python
