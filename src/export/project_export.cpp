#include "export/project_export.h"

#include "evaluator/evaluator.h"
#include "evaluator/geometry_mask.h"
#include "evaluator/sources.h"
#include "evaluator/templates.h"
#include "export/plan.h"
#include "mesh/reload.h"
#include "procedural/snapshot_source.h"
#include "store/project_store.h"
#include "uzp_core/types/errors.h"

#include <windows.h>

#include <limits>
#include <memory>
#include <optional>

namespace uzp::exporter {

namespace {

/// The CPU store's bound: the machine's physical memory; the CPU store has no descriptor limit.
evaluator::AdmissionLimits HostLimits() {
    MEMORYSTATUSEX status{};
    status.dwLength = sizeof(status);
    const uint64_t bytes = GlobalMemoryStatusEx(&status) ? status.ullTotalPhys : 0;
    return {bytes, std::numeric_limits<uint64_t>::max()};
}

}  // namespace

render::Result<Publication> ExportProject(const ProjectExportRequest& request) {
    store::ProjectStore::Opened opened = store::ProjectStore::Open(request.project);
    if (!opened.report.ok()) {
        throw core::ValueError("export: the project " + Utf8String(request.project) +
                               " does not verify: " + core::json::WriteCanonical(opened.report.ToJson()));
    }
    store::ProjectStore& projectStore = *opened.store;
    const core::Project& project = opened.state.project;
    const std::int64_t revision = opened.state.revision;

    PlanContext context;
    context.projectPath = Utf8String(request.project);
    const ExportPlan plan = CompilePlan(project, request.config, context);
    CheckExportable(plan);

    auto templates = std::make_shared<const evaluator::TemplateLibrary>(evaluator::TemplateLibrary::Load(
        request.templates.empty() ? evaluator::TemplateLibrary::DefaultDirectory() : request.templates));
    evaluator::CpuEvaluator cpu(templates, HostLimits());
    SourceInputs inputs;
    inputs.procedurals = std::make_shared<procedural::SnapshotSourceProvider>(projectStore, project);
    inputs.templateId = project.settings.template_id;  // the base values the project records
    // A resource the file cannot give (absent, corrupt) is missing to the evaluator, which fails the
    // export with `evaluator:missing_resource` before anything is written.
    inputs.resources = std::make_shared<evaluator::DecodingResourceProvider>(
        [&projectStore](std::string_view sha) -> std::optional<std::string> {
            try {
                return projectStore.ReadResource(sha);
            } catch (const store::StoreError&) {
                return std::nullopt;
            }
        });
    if (project.mesh) {
        mesh::ImportResult imported = mesh::RederiveMesh(
            project, [&projectStore](const std::string& sha) { return projectStore.ReadResource(sha); });
        inputs.geometry = std::make_shared<evaluator::MeshGeometryMasks>(
            std::make_shared<const mesh::TexturingMesh>(std::move(imported.mesh)));
    }
    PublishRequest publish;
    publish.identity = request.identity;
    publish.projectPath = context.projectPath;
    return PublishExport(project, revision, plan, inputs, *templates, cpu.store(), cpu.cache(), publish);
}

}  // namespace uzp::exporter
