#include "export/virtual_maps.h"

#include "evaluator/arith.h"
#include "evaluator/cpu_store.h"
#include "evaluator/error.h"
#include "evaluator/evaluator.h"
#include "evaluator/formats.h"
#include "export/padding.h"

#include <algorithm>
#include <cstdlib>
#include <exception>
#include <filesystem>
#include <fstream>

namespace uzp::exporter {

namespace {

using evaluator::EvalErrorKind;
using evaluator::EvalFail;

/// The combined virtual normal on UV islands as Painter computes it (virtual_maps.h, decision
/// 308): the diagnostic measure export only. `normal` is the whole-tile request.
render::Result<VirtualMapResult> IslandNormalOn(const core::Project& project, std::int64_t revision,
                                                const evaluator::VirtualNormalRequest& normal,
                                                const Coverage& coverage,
                                                const evaluator::TemplateLibrary& templates,
                                                evaluator::ITileStore& store, evaluator::TileCache& cache) {
    const core::TextureSet* set = nullptr;
    for (const core::TextureSet& candidate : project.texture_sets) {
        if (candidate.id == normal.textureSet) set = &candidate;
    }
    if (set == nullptr) return EvalFail(EvalErrorKind::NotFound, "the texture set of the island normal is not in the project");
    // The Height's stored format: the operands its padding reads (encode.h, decision 274).
    std::optional<core::ChannelFormat> heightFormat;
    for (const core::Stack& stack : set->stacks) {
        if (stack.id != normal.stack) continue;
        if (const auto it = stack.channels.find(core::ChannelType::Height); it != stack.channels.end()) {
            heightFormat = it->second.format;
        }
    }
    const size_t texels = coverage.covered.size();
    // 1. The Height the stencil reads: the read-out where covered, else the padding of the stored
    // operands without the 1 - (1 - m) step (decisions 263, 288 (a)).
    // A measurement may ask for the float32 Height the stencil reads, before and after the padding
    // (raw float32, rows top first): `UZP_DIAGNOSTIC_NORMAL_DUMP` names a directory. Only this
    // diagnostic path reads it.
    const char* dump = std::getenv("UZP_DIAGNOSTIC_NORMAL_DUMP");
    const auto write = [&](const std::string& name, const std::vector<float>& data) {
        if (dump == nullptr || *dump == '\0') return;
        std::ofstream(std::filesystem::path(dump) / (set->name + "-" + name + ".f32"), std::ios::binary)
            .write(reinterpret_cast<const char*>(data.data()), static_cast<std::streamsize>(data.size() * sizeof(float)));
    };
    evaluator::VirtualNormalRequest padded = normal;
    padded.heightPadding = [&coverage, heightFormat, texels, &write](std::vector<float>& heights) {
        write("height-readout", heights);
        std::vector<float> operands(heights);
        if (heightFormat) {
            const evaluator::TileFormat tile = evaluator::TileFormatOf(*heightFormat);
            for (float& v : operands) v = evaluator::OperandOf(evaluator::StoreValue(v, tile, 0), tile, 0);
        }
        PadIslandHeight(coverage, operands);
        for (size_t t = 0; t < texels; ++t) {
            if (coverage.covered[t] == 0) heights[t] = operands[t];
        }
        write("height-padded", heights);
    };
    const bool mesh = set->mesh_maps.contains(core::MeshMapUsage::Normal);
    try {
        // 2. The covered texels.
        render::Result<evaluator::VirtualNormalResult> combined =
            evaluator::EvaluateVirtualNormalOn(project, revision, padded, templates, store, cache);
        if (!combined) return render::Unexpected(combined.error());
        // 3. Pad unit Hn/C separately with a mesh map; otherwise copy the encoded normal.
        std::vector<float> free;
        std::vector<float> heightNormals, channelNormals;
        if (mesh) {
            evaluator::VirtualNormalRequest request = padded;
            request.withoutMesh = true;
            request.component = evaluator::VirtualNormalComponent::Height;
            render::Result<evaluator::VirtualNormalResult> heightPart =
                evaluator::EvaluateVirtualNormalOn(project, revision, request, templates, store, cache);
            if (!heightPart) return render::Unexpected(heightPart.error());
            heightNormals = std::move(heightPart->texels);
            request.component = evaluator::VirtualNormalComponent::Channel;
            render::Result<evaluator::VirtualNormalResult> channelPart =
                evaluator::EvaluateVirtualNormalOn(project, revision, request, templates, store, cache);
            if (!channelPart) return render::Unexpected(channelPart.error());
            channelNormals = std::move(channelPart->texels);
        } else {
            free = combined->texels;
        }
        if (mesh) {
            // Across-border-only ring texels retain flat Hn and their own C (decision 287).
            // Other ring texels copy a covered pair before the common clamped flood.
            for (size_t t = 0; t < texels; ++t) {
                if (coverage.covered[t] == 0) {
                    heightNormals[t * 3] = 0.0f;
                    heightNormals[t * 3 + 1] = 0.0f;
                    heightNormals[t * 3 + 2] = 1.0f;
                }
            }
            PadIslandNormal(coverage, heightNormals);
            PadIslandNormal(coverage, channelNormals);
        } else if (NormalRingAcrossBorder(coverage)) {
            // A flat height normal combined with the Normal channel (decision 287 §4).
            evaluator::VirtualNormalRequest request = normal;
            request.withoutMesh = true;
            request.heightPadding = [](std::vector<float>& heights) { std::fill(heights.begin(), heights.end(), 0.0f); };
            render::Result<evaluator::VirtualNormalResult> flat =
                evaluator::EvaluateVirtualNormalOn(project, revision, request, templates, store, cache);
            if (!flat) return render::Unexpected(flat.error());
            for (size_t t = 0; t < texels; ++t) {
                if (coverage.covered[t] == 0) std::copy_n(flat->texels.begin() + static_cast<std::ptrdiff_t>(t * 3), 3,
                                                          free.begin() + static_cast<std::ptrdiff_t>(t * 3));
            }
        }
        if (!mesh) PadIslandNormal(coverage, free);
        // 4. The uncovered texels: the padded normal, under the mesh map at the texel when one is bound.
        std::shared_ptr<const evaluator::DecodedImage> meshImage;
        if (mesh && normal.resources) {
            meshImage = normal.resources->Fetch(set->mesh_maps.at(core::MeshMapUsage::Normal).resource);
        }
        if (mesh && !meshImage) {
            return EvalFail(EvalErrorKind::MissingResource, "the Normal mesh map of the island normal is not available");
        }
        // EvaluateVirtualNormalOn refused a mesh map in another convention than the project's.
        const bool meshDirectX = project.settings.normal_map_format == core::NormalMapFormat::DirectX;
        VirtualMapResult result;
        result.values = {combined->width, combined->height, 3, std::move(combined->texels)};
        result.tag = combined->tag;
        result.padded = true;
        std::vector<float>& out = result.values.values;
        for (size_t t = 0; t < texels; ++t) {
            if (coverage.covered[t] != 0) continue;
            std::array<float, 3> e{};
            if (mesh) {
                const auto x = static_cast<uint32_t>(t % coverage.width);
                const auto y = static_cast<uint32_t>(t / coverage.width);
                std::array<float, 3> f{};
                for (uint32_t c = 0; c < 3; ++c) f[c] = evaluator::arith::UnormOperand(meshImage->At(x, y, c) & 0xFFFFu, 16);
                const std::array<float, 3> h{heightNormals[t * 3], heightNormals[t * 3 + 1], heightNormals[t * 3 + 2]};
                const std::array<float, 3> c{channelNormals[t * 3], channelNormals[t * 3 + 1], channelNormals[t * 3 + 2]};
                e = evaluator::MeshOnPaddedNormal(f, meshDirectX, h, c, normal.convention);
                // Preserve the diagnostic marker until the Height-ring and border evidence closes.
                ++result.undecided;
            } else {
                e = {free[t * 3], free[t * 3 + 1], free[t * 3 + 2]};
            }
            std::copy(e.begin(), e.end(), out.begin() + static_cast<std::ptrdiff_t>(t * 3));
        }
        return result;
    } catch (const std::exception& e) {
        return EvalFail(EvalErrorKind::Internal, std::string("the island normal (decision 308): ") + e.what());
    }
}

constexpr std::array<std::string_view, kVirtualMapCount> kNames{
    "Normal_OpenGL", "Normal_DirectX", "AO_Mixed",   "Diffuse", "Specular", "Glossiness", "Unity4Diff",
    "Unity4Gloss",   "reflection",     "1/ior",      "Glossiness2", "f0",   "View_2D",
};

/// The owners of the virtual maps not reproduced exactly (decision 092).
constexpr std::string_view kAoMixedOwner =
    "phase3.2_unreal-ue56-packed-preset item 2.10, decision 131: Painter's AO_Mixed arithmetic is not identified "
    "(the best model misses r1 at 31 values); Tier 0 recording R-092 and its fit (decision 092)";
constexpr std::string_view kConvertedOwner =
    "phase1.18_export-engine: fitted, but it needs each channel's per-texel coverage from the evaluator "
    "and the uncovered constants of Tier 0 recording R-092 (decision 092)";
constexpr std::string_view kView2dOwner =
    "a reproduction of Painter's 2D view render, which no task owns yet (decision 092)";

}  // namespace

std::optional<uint32_t> PassThroughComponents(core::MeshMapUsage usage) {
    switch (usage) {
        case core::MeshMapUsage::AO:
        case core::MeshMapUsage::Curvature: return 1;
        case core::MeshMapUsage::Position: return 3;
        default: return std::nullopt;
    }
}

render::Result<VirtualMapResult> PassThroughMeshMap(const core::Project& project, core::MeshMapUsage usage,
                                                    const VirtualMapRequest& request) {
    const std::string name(core::ToString(usage));
    const std::optional<uint32_t> components = PassThroughComponents(usage);
    if (!components) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "exporting the " + name +
                            " mesh map is not recorded (recording R-090 P7 shows AO, Curvature and Position; decision 103)");
    }
    const core::TextureSet* set = nullptr;
    for (const core::TextureSet& candidate : project.texture_sets) {
        if (candidate.id == request.textureSet) set = &candidate;
    }
    if (set == nullptr) return EvalFail(EvalErrorKind::Internal, "the texture set of the mesh map is not in the project");
    const auto binding = set->mesh_maps.find(usage);
    if (binding == set->mesh_maps.end()) {
        return EvalFail(EvalErrorKind::MissingResource, "texture set " + set->name + " has no " + name + " mesh map");
    }
    const std::shared_ptr<const evaluator::DecodedImage> image =
        request.resources ? request.resources->Fetch(binding->second.resource) : nullptr;
    if (!image) {
        return EvalFail(EvalErrorKind::MissingResource,
                        "the " + name + " mesh map's image " + binding->second.resource + " is not available");
    }
    const bool unorm = image->encoding == render::TexelEncoding::Unorm16 ||
                       image->encoding == render::TexelEncoding::Unorm8;
    if (!unorm || image->channels != *components || image->width != static_cast<uint32_t>(set->resolution.width) ||
        image->height != static_cast<uint32_t>(set->resolution.height)) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "the " + name + " mesh map is recorded as an 8- or 16-bit " +
                            (*components == 1 ? "grey" : "RGB") +
                            " image at the set resolution only (a pass-through does not resample; decision 103)");
    }
    const uint32_t bits = image->encoding == render::TexelEncoding::Unorm16 ? 16u : 8u;
    const uint32_t max = (1u << bits) - 1u;
    VirtualMapResult result;
    result.values.width = image->width;
    result.values.height = image->height;
    result.values.components = *components;
    result.values.values.reserve(image->values.size());
    for (const uint32_t code : image->values) result.values.values.push_back(evaluator::arith::UnormOperand(code & max, bits));
    return result;
}

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
    normal.procedurals = request.procedurals;
    normal.geometry = request.geometry;
    if (request.islandNormal != nullptr && !request.islandNormal->Complete()) {
        return IslandNormalOn(project, revision, normal, *request.islandNormal, templates, store, cache);
    }
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
    if (usage != core::MeshMapUsage::Normal) return PassThroughMeshMap(project, usage, request);
    evaluator::VirtualNormalRequest normal;
    normal.textureSet = request.textureSet;
    normal.stack = request.stack;
    normal.kind = evaluator::NormalSourceKind::GeometryOnly;
    normal.convention = project.settings.normal_map_format;
    normal.templateId = request.templateId;
    normal.resources = request.resources;
    normal.procedurals = request.procedurals;
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
