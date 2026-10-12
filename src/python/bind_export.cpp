// `uzpainter.export` and `uzpainter.jobs`: the export over the export engine of `src/export/` as a
// worker job, its dry run, and the job handles (jobs.h).
//
// `export.plan(config)` compiles Painter's `json_config` against the current revision and returns
// the typed plan (`uzpainter/export-plan/1`, decision 085), `export.list_project_textures(config)`
// is the dry run in Painter's `{(texture set, stack): [files]}` shape (decision 091). `export.start`
// queues the export of the current revision as a job: the plan is compiled and checked, every
// file is evaluated on the CPU evaluator (the evaluator the export tests compare with Painter's
// goldens), encoded, and published as a new generation under the configuration's `exportPath`
// with its receipt (`PublishExport`, decision 097); `fixed_names` folders then receive the
// generation's files under their fixed names (`CopyFixedNames`; `exportPath` itself gives Painter's
// flat layout). `export.export_project_textures` is the synchronous convenience: start, then wait
// with the GIL released. A refusal (`ValueError`, `NotYetSupported`) happens before anything is
// written; an evaluation failure raises the class of decision 082.

#include <memory>

#include "evaluator/error.h"
#include "evaluator/evaluator.h"
#include "evaluator/geometry_mask.h"
#include "evaluator/sources.h"
#include "evaluator/templates.h"
#include "export/fixed_names.h"
#include "export/plan.h"
#include "export/publish.h"
#include "mesh/reload.h"
#include "python/bindings.h"
#include "python/errors.h"
#include "python/jobs.h"
#include "store/container.h"

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

/// The export job of `snapshot` (see above).
JobBody ExportBody(std::shared_ptr<OpenProject> project, core::Snapshot snapshot, std::string config,
                   std::string project_path, std::vector<std::string> fixed_names) {
    return [project = std::move(project), snapshot = std::move(snapshot), config = std::move(config),
            project_path = std::move(project_path), fixed_names = std::move(fixed_names)](JobContext& context) {
        const core::Project& p = *snapshot.project;
        const exporter::ExportPlan plan = exporter::CompilePlan(p, config, exporter::PlanContext{project_path});
        exporter::CheckExportable(plan);
        context.SetProgress(0.1);
        context.Checkpoint();

        store::ProjectStore* store = project->store.get();
        auto templates = std::make_shared<const evaluator::TemplateLibrary>(
            evaluator::TemplateLibrary::Load(evaluator::TemplateLibrary::DefaultDirectory()));
        exporter::SourceInputs inputs;
        inputs.resources = std::make_shared<evaluator::DecodingResourceProvider>(
            [store](std::string_view sha256) -> std::optional<std::string> {
                try {
                    return store->ReadResource(sha256);
                } catch (const store::StoreError& error) {
                    if (error.code() == store::StoreError::Code::missing_resource) return std::nullopt;
                    throw;
                }
            });
        if (p.mesh) {
            mesh::ImportResult mesh =
                mesh::RederiveMesh(p, [store](const std::string& sha256) { return store->ReadResource(sha256); });
            inputs.geometry = std::make_shared<evaluator::MeshGeometryMasks>(
                std::make_shared<const mesh::TexturingMesh>(std::move(mesh.mesh)));
        }
        context.SetProgress(0.2);
        context.Checkpoint();

        evaluator::CpuEvaluator cpu(templates, evaluator::AdmissionLimits{64ull << 30, 1 << 20});
        exporter::PublishRequest request;
        request.identity = exporter::BuildIdentity{kAppVersion, std::string("uzpainter-") + UZP_BUILD_MODE};
        request.projectPath = project_path;
        render::Result<exporter::Publication> published =
            exporter::PublishExport(p, snapshot.revision, plan, inputs, *templates, cpu.store(), cpu.cache(), request);
        if (!published) RaiseRender(published.error());
        context.SetProgress(0.9);

        core::json::Array files;
        for (const exporter::WrittenFile& file : published->files) files.push_back(WrittenJson(file));
        core::json::Array copies;
        for (const std::string& folder : fixed_names) {
            render::Result<exporter::Delivery> delivery =
                exporter::CopyFixedNames(exporter::Utf8Path(plan.exportPath), exporter::Utf8Path(folder));
            if (!delivery) RaiseRender(delivery.error());
            copies.push_back(core::json::Object{{"directory", exporter::Utf8String(delivery->directory)},
                                                {"generation", delivery->generation}});
        }
        return core::json::Object{{"directory", exporter::Utf8String(published->directory)},
                                  {"files", std::move(files)},
                                  {"fixed_names", std::move(copies)},
                                  {"generation", published->generation},
                                  {"plan_hash", plan.hash},
                                  {"receipt", exporter::Utf8String(published->receipt)},
                                  {"receipt_sha256", published->receiptSha256},
                                  {"revision", snapshot.revision}};
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
    if (Session::Get().TransactionOpen()) {
        throw ApiError("RuntimeError", "an export reads a committed revision: commit the open Transaction first");
    }
    const std::shared_ptr<OpenProject> project = Session::Get().Current();
    core::Snapshot snapshot = project->document->snapshot();
    return {JobEngine::Get().Start("export", ExportBody(project, std::move(snapshot), ConfigText(config), ProjectPath(),
                                                        fixed_names))};
}

}  // namespace

void BindExport(py::module_& m, py::module_& jobs) {
    Session::Get().running_job = [] { return JobEngine::Get().Busy(); };

    py::class_<JobHandle> job(jobs, "Job", "A worker job: id, status, progress, wait(timeout=None), cancel().");
    job.def_property_readonly("id", [](const JobHandle& j) { return j.job->id(); })
        .def_property_readonly("kind", [](const JobHandle& j) { return j.job->kind(); })
        .def_property_readonly("status", [](const JobHandle& j) { return std::string(JobStatusName(j.job->status())); })
        .def_property_readonly("progress", [](const JobHandle& j) { return j.job->progress(); })
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
