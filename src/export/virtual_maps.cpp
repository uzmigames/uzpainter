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

/// The owners of the virtual maps not reproduced exactly (decision 092).
constexpr std::string_view kAoMixedOwner =
    "phase1.18_export-engine: Painter's AO_Mixed arithmetic is not identified (the best model misses r1 "
    "at 31 values); Tier 0 recording R-092 and its fit (decision 092)";
constexpr std::string_view kConvertedOwner =
    "phase1.18_export-engine: fitted, but it needs each channel's per-texel coverage from the evaluator "
    "and the uncovered constants of Tier 0 recording R-092 (decision 092)";
constexpr std::string_view kView2dOwner =
    "a reproduction of Painter's 2D view render, which no task owns yet (decision 092)";

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
        case VirtualMap::AO_Mixed: return {false, 1, std::string(kAoMixedOwner)};
        case VirtualMap::Diffuse:
        case VirtualMap::Specular:
        case VirtualMap::reflection:
        case VirtualMap::f0:
        case VirtualMap::Unity4Diff: return {false, 3, std::string(kConvertedOwner)};
        case VirtualMap::View_2D: return {false, 3, std::string(kView2dOwner)};
        case VirtualMap::Glossiness:
        case VirtualMap::Glossiness2:
        case VirtualMap::Unity4Gloss:
        case VirtualMap::OneOverIor: return {false, 1, std::string(kConvertedOwner)};
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
