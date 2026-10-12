#include "export/virtual_maps.h"

#include "evaluator/error.h"
#include "evaluator/evaluator.h"

namespace uzp::exporter {

namespace {

using evaluator::EvalErrorKind;
using evaluator::EvalFail;

constexpr std::array<std::string_view, kVirtualMapCount> kNames{
    "Normal_OpenGL", "Normal_DirectX", "AO_Mixed",   "Diffuse", "Specular", "Glossiness", "Unity4Diff",
    "Unity4Gloss",   "reflection",     "1/ior",      "Glossiness2", "f0",   "View_2D",
};

/// The owner of the virtual maps without a Tier 0 golden: a recording and a fit (decision 086).
constexpr std::string_view kVirtualGapOwner =
    "phase1.18_export-engine: Tier 0 recording R-086 and its fit (decision 086)";

}  // namespace

std::string_view VirtualMapName(VirtualMap map) { return kNames[static_cast<size_t>(map)]; }

std::optional<VirtualMap> ParseVirtualMap(std::string_view name) {
    for (size_t i = 0; i < kNames.size(); ++i) {
        if (kNames[i] == name) return static_cast<VirtualMap>(i);
    }
    return std::nullopt;
}

std::vector<std::string> VirtualMapNames() { return {kNames.begin(), kNames.end()}; }

VirtualMapSupport Support(VirtualMap map) {
    switch (map) {
        case VirtualMap::Normal_OpenGL:
        case VirtualMap::Normal_DirectX:
            return {true, 3,
                    "tier0/semantics/height-normal-plane-amplitudes, height-normal-sphere, height-normal-bevelled-cube, "
                    "blend-normal-channel and the semantics-ui height-normal goldens (phase1.12, decisions 064, 065)"};
        case VirtualMap::AO_Mixed:
            // The calibrated operator of parity/semantics/ao-mixed.json misses the opacity-0.5 set
            // of tier0/semantics/ao-mixed, where Painter's two recordings also disagree.
            return {false, 1, std::string(kVirtualGapOwner)};
        case VirtualMap::Diffuse:
        case VirtualMap::Specular:
        case VirtualMap::reflection:
        case VirtualMap::f0:
        case VirtualMap::Unity4Diff:
        case VirtualMap::View_2D: return {false, 3, std::string(kVirtualGapOwner)};
        case VirtualMap::Glossiness:
        case VirtualMap::Glossiness2:
        case VirtualMap::Unity4Gloss:
        case VirtualMap::OneOverIor: return {false, 1, std::string(kVirtualGapOwner)};
    }
    return {};
}

render::Result<VirtualMapResult> EvaluateVirtualMapOn(const core::Project& project, std::int64_t revision,
                                                      VirtualMap map, const VirtualMapRequest& request,
                                                      const evaluator::TemplateLibrary& templates,
                                                      evaluator::ITileStore& store, evaluator::TileCache& cache) {
    if (!Support(map).supported) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "the virtual map " + std::string(VirtualMapName(map)) + " is a release gap (" +
                            Support(map).evidenceOrOwner + ")");
    }
    // The supported maps are the combined normals.
    evaluator::VirtualNormalRequest normal;
    normal.textureSet = request.textureSet;
    normal.stack = request.stack;
    normal.kind = evaluator::NormalSourceKind::Combined;
    normal.convention = map == VirtualMap::Normal_OpenGL ? core::NormalMapFormat::OpenGL : core::NormalMapFormat::DirectX;
    normal.templateId = request.templateId;
    normal.resources = request.resources;
    normal.geometry = request.geometry;
    render::Result<evaluator::VirtualNormalResult> evaluated =
        evaluator::EvaluateVirtualNormalOn(project, revision, normal, templates, store, cache);
    if (!evaluated) return render::Unexpected(evaluated.error());
    VirtualMapResult result;
    result.values = {evaluated->width, evaluated->height, 3, std::move(evaluated->texels)};
    result.tag = evaluated->tag;
    return result;
}

render::Result<VirtualMapResult> EvaluateMeshMapOn(const core::Project& project, std::int64_t revision,
                                                   core::MeshMapUsage usage, const VirtualMapRequest& request,
                                                   const evaluator::TemplateLibrary& templates,
                                                   evaluator::ITileStore& store, evaluator::TileCache& cache) {
    if (usage != core::MeshMapUsage::Normal) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "exporting the " + std::string(core::ToString(usage)) +
                            " mesh map at its native precision is a release gap (phase1.16_export-processing-encoders)");
    }
    evaluator::VirtualNormalRequest normal;
    normal.textureSet = request.textureSet;
    normal.stack = request.stack;
    normal.kind = evaluator::NormalSourceKind::GeometryOnly;
    normal.convention = project.settings.normal_map_format;
    normal.templateId = request.templateId;
    normal.resources = request.resources;
    normal.geometry = request.geometry;
    render::Result<evaluator::VirtualNormalResult> evaluated =
        evaluator::EvaluateVirtualNormalOn(project, revision, normal, templates, store, cache);
    if (!evaluated) return render::Unexpected(evaluated.error());
    VirtualMapResult result;
    result.values = {evaluated->width, evaluated->height, 3, std::move(evaluated->texels)};
    result.tag = evaluated->tag;
    return result;
}

}  // namespace uzp::exporter
