// The diagnostic views of the open project (diagnostics.h).

#include "python/diagnostics.h"

#include <algorithm>
#include <utility>

#include "evaluator/error.h"
#include "evaluator/geometry_mask.h"
#include "evaluator/sources.h"
#include "export/write.h"
#include "mesh/reload.h"
#include "python/errors.h"
#include "store/container.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/types/errors.h"

#ifndef UZP_BUILD_MODE
#error "UZP_BUILD_MODE is defined by build.zig"
#endif

namespace uzp::python {

namespace {

namespace json = core::json;

[[noreturn]] void RaiseRender(const render::Error& error) {
    if (const std::optional<evaluator::EvalErrorKind> kind = evaluator::EvalErrorKindOf(error)) {
        throw ApiError(std::string(evaluator::ErrorClassName(*kind)), error.reason);
    }
    throw ApiError("RuntimeError", error.reason);
}

template <typename T>
T Take(render::Result<T> result) {
    if (!result) RaiseRender(result.error());
    return std::move(*result);
}

exporter::PlannedSource Planned(const evaluator::DiagnosticSource& source) {
    exporter::PlannedSource planned;
    planned.type = exporter::SourceType::diagnosticMap;
    planned.name = evaluator::SourceName(source);
    planned.diagnostic = source;
    return planned;
}

/// The export configuration writing `sources` of the stack `rootPath` under `exportPath`, the
/// sources of `components[i]` == 3 as R+G+B, the others as L.
std::string ExportConfig(const std::string& exportPath, const std::string& rootPath,
                         const std::vector<evaluator::DiagnosticSource>& sources, const std::vector<uint32_t>& components) {
    json::Array maps;
    for (size_t i = 0; i < sources.size(); ++i) {
        const std::string name = evaluator::SourceName(sources[i]);
        std::string file = "$textureSet_" + name;
        std::replace(file.begin(), file.end(), '/', '_');
        json::Array channels;
        const auto channel = [&](const char* letter) {
            channels.push_back(json::Object{{"destChannel", letter},
                                            {"srcChannel", letter},
                                            {"srcMapType", std::string(evaluator::kDiagnosticMapType)},
                                            {"srcMapName", name}});
        };
        if (components[i] == 3) {
            for (const char* letter : {"R", "G", "B"}) channel(letter);
        } else {
            channel("L");
        }
        maps.push_back(json::Object{{"fileName", file}, {"channels", std::move(channels)}});
    }
    const json::Object config{
        {"exportPath", exportPath},
        {"exportShaderParams", false},
        {"defaultExportPreset", "uzpainter-diagnostics"},
        {"exportPresets", json::Array{json::Object{{"name", "uzpainter-diagnostics"}, {"maps", std::move(maps)}}}},
        {"exportList", json::Array{json::Object{{"rootPath", rootPath}}}},
        {"exportParameters",
         json::Array{json::Object{{"parameters", json::Object{{"fileFormat", "exr"},
                                                              {"bitDepth", "32f"},
                                                              {"dithering", false},
                                                              {"paddingAlgorithm", "passthrough"}}}}}}};
    return json::WriteCanonical(config);
}

}  // namespace

DiagnosticRun::DiagnosticRun() {
    if (Session::Get().TransactionOpen()) {
        throw ApiError("RuntimeError", "a diagnostic reads a committed revision: commit the open Transaction first");
    }
    m_open = Session::Get().Current();
    m_snapshot = m_open->document->snapshot();
    const core::Project& project = *m_snapshot.project;
    m_templates = std::make_shared<const evaluator::TemplateLibrary>(
        evaluator::TemplateLibrary::Load(evaluator::TemplateLibrary::DefaultDirectory()));
    store::ProjectStore* store = m_open->store.get();
    m_inputs.templateId = project.settings.template_id;
    m_inputs.resources = std::make_shared<evaluator::DecodingResourceProvider>(
        [store](std::string_view sha256) -> std::optional<std::string> {
            try {
                return store->ReadResource(sha256);
            } catch (const store::StoreError& error) {
                if (error.code() == store::StoreError::Code::missing_resource) return std::nullopt;
                throw;
            }
        });
    if (project.mesh) {
        mesh::ImportResult mesh =
            mesh::RederiveMesh(project, [store](const std::string& sha256) { return store->ReadResource(sha256); });
        m_inputs.geometry = std::make_shared<evaluator::MeshGeometryMasks>(
            std::make_shared<const mesh::TexturingMesh>(std::move(mesh.mesh)));
    }
    m_cpu = std::make_unique<evaluator::CpuEvaluator>(m_templates, evaluator::AdmissionLimits{64ull << 30, 1 << 20});
}

evaluator::DiagnosticRequest DiagnosticRun::RequestFor(core::Id node) const {
    evaluator::DiagnosticRequest request{core::kNoId, core::kNoId, m_inputs.templateId, m_inputs.resources,
                                         m_inputs.geometry};
    core::ForEachNode(*m_snapshot.project, [&](const core::NodeVisit& visit) {
        if ((visit.layer ? visit.layer->uid : visit.effect->uid) == node) {
            request.textureSet = visit.texture_set;
            request.stack = visit.stack;
        }
    });
    if (request.stack == core::kNoId) {
        throw ApiError("ValueError", "node " + std::to_string(node) + " is in no stack of revision " +
                                         std::to_string(m_snapshot.revision));
    }
    return request;
}

void DiagnosticRun::RequireExact(const evaluator::DiagnosticRequest& request,
                                 const evaluator::DiagnosticSource& source) const {
    const core::Project& project = *m_snapshot.project;
    const exporter::PlannedSource planned = Planned(source);
    render::Result<void> identified = exporter::RequireIdentifiedBase(project, request.textureSet, request.stack,
                                                                      planned, request.templateId, *m_templates);
    if (!identified) RaiseRender(identified.error());
    if (!exporter::ReadsCombinedNormal(planned)) return;
    for (const core::TextureSet& set : project.texture_sets) {
        if (set.id != request.textureSet) continue;
        // Without a texturing mesh there are no UV islands.
        const std::optional<exporter::Coverage> coverage = exporter::CoverageOf(set, m_inputs);
        if (coverage && !coverage->Complete()) {
            throw ApiError("NotYetSupported", "diagnostics: " + exporter::IslandNormalRefusal(planned));
        }
    }
}

evaluator::IsolationResult DiagnosticRun::Isolate(core::Id node, const evaluator::DiagnosticMapId& map) {
    const evaluator::DiagnosticRequest request = RequestFor(node);
    RequireExact(request, {evaluator::DiagnosticSource::Kind::Isolated, map, {}, node});
    return Take(evaluator::IsolateOn(*m_snapshot.project, m_snapshot.revision, map, node, request, *m_templates,
                                     m_cpu->store(), m_cpu->cache()));
}

evaluator::ContributionResult DiagnosticRun::Contribution(core::Id node, const evaluator::DiagnosticMapId& map) {
    const evaluator::DiagnosticRequest request = RequestFor(node);
    RequireExact(request, {evaluator::DiagnosticSource::Kind::Contribution, map, {}, node});
    return Take(evaluator::ContributionOn(*m_snapshot.project, m_snapshot.revision, map, node, request, *m_templates,
                                          m_cpu->store(), m_cpu->cache()));
}

DiagnosticMaterialViews DiagnosticRun::MaterialViews(core::Id material) {
    const evaluator::DiagnosticRequest request = RequestFor(material);
    DiagnosticMaterialViews out;
    out.views = Take(evaluator::MaterialViewsOn(*m_snapshot.project, m_snapshot.revision, material, request,
                                                *m_templates, m_cpu->store(), m_cpu->cache()));
    std::erase_if(out.views.views, [&](const evaluator::MaterialView& view) {
        // A view refused for its values is refused for its leaks too: both read the channel.
        render::Result<void> identified = exporter::RequireIdentifiedBase(
            *m_snapshot.project, request.textureSet, request.stack,
            Planned({evaluator::DiagnosticSource::Kind::MaterialView, {}, view.view, material}), request.templateId,
            *m_templates);
        if (identified) return false;
        out.refused[std::string(evaluator::MaterialViewName(view.view))] = identified.error().reason;
        return true;
    });
    return out;
}

evaluator::RegionStats DiagnosticRun::RegionStats(const evaluator::DiagnosticMapId& map, core::Id material) {
    const evaluator::DiagnosticRequest request = RequestFor(material);
    const evaluator::DiagnosticSource source{evaluator::DiagnosticSource::Kind::RegionStats, map, {}, material};
    RequireExact(request, source);
    evaluator::DiagnosticOutput output = Take(evaluator::EvaluateDiagnosticOn(
        *m_snapshot.project, m_snapshot.revision, source, request, *m_templates, m_cpu->store(), m_cpu->cache()));
    return std::move(*output.stats);
}

exporter::Publication DiagnosticRun::Export(core::Id node, const std::vector<evaluator::DiagnosticSource>& sources,
                                            const std::filesystem::path& exportPath) {
    const evaluator::DiagnosticRequest request = RequestFor(node);
    const core::Project& project = *m_snapshot.project;
    const core::TextureSet* set = nullptr;
    for (const core::TextureSet& candidate : project.texture_sets) {
        if (candidate.id == request.textureSet) set = &candidate;
    }
    const core::Stack& stack = *core::FindStack(project, request.textureSet, request.stack);
    const std::string path = exporter::Utf8String(exportPath);
    const std::string rootPath = exporter::RootPathOf(*set, stack);
    const std::optional<std::filesystem::path> file = Session::Get().FilePath();
    const exporter::PlanContext context{file ? exporter::Utf8String(*file) : std::string()};
    try {
        // The export resolves each source's components; a first plan of grey maps reads them, so
        // a colour source is written R+G+B and never as its luma.
        const exporter::ExportPlan probe = exporter::CompilePlan(
            project, ExportConfig(path, rootPath, sources, std::vector<uint32_t>(sources.size(), 1)), context);
        std::vector<uint32_t> components;
        for (const exporter::PlannedFile& planned : probe.files) components.push_back(planned.channels[0].source.components);
        if (components.size() != sources.size()) {
            throw ApiError("ValueError", "the export of the diagnostic sources skips one of them");
        }
        const exporter::ExportPlan plan = exporter::CompilePlan(project, ExportConfig(path, rootPath, sources, components), context);
        exporter::CheckExportable(plan);
        exporter::PublishRequest publish;
        publish.identity = exporter::BuildIdentity{kAppVersion, std::string("uzpainter-") + UZP_BUILD_MODE};
        publish.projectPath = context.projectPath;
        return Take(exporter::PublishExport(project, m_snapshot.revision, plan, m_inputs, *m_templates, m_cpu->store(),
                                            m_cpu->cache(), publish));
    } catch (const core::ValueError& error) {
        throw ApiError("ValueError", error.what());
    } catch (const core::NotYetSupported& error) {
        throw ApiError("NotYetSupported", error.what());
    }
}

}  // namespace uzp::python
