// The viewport scene of a published frame (preview.h `SceneOf`, `MaterialsOf`): shared by the
// preview window's thread and the `painter_viewport` capture (python/capture.h).

#include "evaluator/arith.h"
#include "evaluator/diagnostics.h"
#include "preview/preview.h"
#include "python/display.h"
#include "render/kernel_cache.h"

#include <algorithm>
#include <fstream>
#include <iterator>

#include "uzp_core/manifest/sha256.h"

namespace uzp::preview {

namespace {

/// The first `components` components of a raster with `available` per texel.
std::optional<MaterialMap> Components(uint32_t width, uint32_t height, uint32_t available,
                                      const std::vector<float>& values, uint32_t components) {
    if (width == 0 || height == 0 || available == 0) return std::nullopt;
    MaterialMap map{width, height, components, {}};
    map.values.resize(size_t{width} * height * components);
    for (size_t i = 0; i < size_t{width} * height; ++i) {
        for (uint32_t c = 0; c < components; ++c) {
            map.values[i * components + c] = values[i * available + std::min(c, available - 1)];
        }
    }
    return map;
}

std::optional<MaterialMap> MapOfEvaluated(const EvaluatedMap& evaluated, uint32_t components) {
    if (const auto* channel = std::get_if<std::shared_ptr<const evaluator::ChannelResult>>(&evaluated)) {
        if (!*channel) return std::nullopt;
        const evaluator::DiagnosticMap map = evaluator::MapOf(**channel);
        return Components(map.width, map.height, map.components, map.values, components);
    }
    const auto& normal = std::get<std::shared_ptr<const evaluator::VirtualNormalResult>>(evaluated);
    if (!normal) return std::nullopt;
    return Components(normal->width, normal->height, 3, normal->texels, components);
}

std::expected<std::shared_ptr<const std::string>, std::string> ReadDefaultEnvironment() {
    using Problem = std::expected<std::shared_ptr<const std::string>, std::string>::unexpected_type;
    const std::filesystem::path path =
        render::DefaultDxcompilerPath().parent_path() / "assets" / "environments" / kDefaultEnvironmentFile;
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        return Problem("the installation's default environment " + path.string() +
                       " cannot be read (decision 212: a project that names no environment is lit by it)");
    }
    auto bytes = std::make_shared<const std::string>(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
    if (core::Sha256Hex(*bytes) != kDefaultEnvironmentSha256) {
        return Problem("the installation's default environment " + path.string() + " is not the shipped file (SHA-256 " +
                       std::string(kDefaultEnvironmentSha256) + ", decision 212)");
    }
    return bytes;
}

}  // namespace

std::expected<std::shared_ptr<const std::string>, std::string> DefaultEnvironment() {
    static const std::expected<std::shared_ptr<const std::string>, std::string> shipped = ReadDefaultEnvironment();
    return shipped;
}

std::optional<core::ChannelType> ChannelFor(const core::Stack& stack, MaterialSlot slot) {
    using core::ChannelType;
    const auto has = [&](ChannelType type) { return stack.channels.contains(type); };
    switch (slot) {
        case MaterialSlot::BaseColor:
            if (has(ChannelType::BaseColor)) return ChannelType::BaseColor;
            return std::nullopt;
        case MaterialSlot::Metalness:
            if (has(ChannelType::BaseMetalness)) return ChannelType::BaseMetalness;
            if (has(ChannelType::Metallic)) return ChannelType::Metallic;
            return std::nullopt;
        case MaterialSlot::Roughness:
            if (has(ChannelType::SpecularRoughness)) return ChannelType::SpecularRoughness;
            if (has(ChannelType::Roughness)) return ChannelType::Roughness;
            return std::nullopt;
        case MaterialSlot::Normal: return std::nullopt;  // the combined virtual map, below
    }
    return std::nullopt;
}

std::vector<MaterialInputs> MaterialsOf(const PreviewFrame& frame) {
    std::vector<MaterialInputs> materials;
    if (!frame.project) return materials;
    for (const core::TextureSet& set : frame.project->texture_sets) {
        MaterialInputs inputs;
        const auto find = [&](MaterialSlot slot) -> const EvaluatedMap* {
            const auto it = frame.maps.find({set.id, slot});
            return it == frame.maps.end() ? nullptr : &it->second;
        };
        if (const EvaluatedMap* m = find(MaterialSlot::BaseColor)) inputs.baseColor = MapOfEvaluated(*m, 3);
        if (const EvaluatedMap* m = find(MaterialSlot::Metalness)) inputs.metalness = MapOfEvaluated(*m, 1);
        if (const EvaluatedMap* m = find(MaterialSlot::Roughness)) inputs.roughness = MapOfEvaluated(*m, 1);
        if (const EvaluatedMap* m = find(MaterialSlot::Normal)) inputs.normal = MapOfEvaluated(*m, 3);
        materials.push_back(std::move(inputs));
    }
    return materials;
}

std::expected<ViewportScene, std::string> SceneOf(const PreviewFrame& frame, LightingCache& cache) {
    // Named through `std::expected`: Zig's libc++ also declares the function `Problem()`.
    using Problem = std::expected<ViewportScene, std::string>::unexpected_type;
    if (!frame.project) return Problem(std::string("no project"));
    const core::Project& project = *frame.project;
    ViewportScene next;
    // The display state of the display presets (src/python/display.h, decision 132): its view,
    // its config pin and the active preset's clear colour.
    const core::json::Object preset = python::display::PresetOf(project);
    std::string view(kDefaultSrgbView);
    std::string displayHash;
    if (const auto display = preset.find("display");
        display != preset.end() && display->second.IsObject()) {
        const core::json::Object& d = std::get<core::json::Object>(display->second.data);
        if (const auto it = d.find("view"); it != d.end() && it->second.IsString()) {
            view = std::get<std::string>(it->second.data);
        }
        if (const auto it = d.find("config_sha256"); it != d.end() && it->second.IsString()) {
            displayHash = std::get<std::string>(it->second.data);
        }
    }
    next.display = ConfigurationOf(project, view);
    if (next.display.mode == kOcioMode && next.display.configHash.empty()) next.display.configHash = displayHash;
    if (const auto background = preset.find("background");
        background != preset.end() && background->second.IsObject()) {
        const core::json::Object& b = std::get<core::json::Object>(background->second.data);
        if (const auto it = b.find("srgb8"); it != b.end() && it->second.IsArray() &&
                                             std::get<core::json::Array>(it->second.data).size() == 3) {
            const core::json::Array& rgb = std::get<core::json::Array>(it->second.data);
            for (size_t c = 0; c < 3; ++c) {
                if (rgb[c].IsInt()) {
                    next.background[c] = static_cast<float>(
                        evaluator::arith::SrgbDecode(static_cast<double>(std::get<std::int64_t>(rgb[c].data)) / 255.0));
                }
            }
        }
    }
    if (std::optional<std::string> unsupported = UnsupportedConfiguration(next.display)) {
        return Problem(*unsupported);
    }
    if (!frame.mesh) return Problem(std::string("the evaluation carries no mesh (the project has none)"));
    if (!frame.environmentError.empty()) return Problem(frame.environmentError);
    if (frame.environmentHash.empty()) {
        return Problem(std::string("the project names no environment (RES-03: no substitute)"));
    }
    std::shared_ptr<const EnvironmentLighting>& lighting = cache[frame.environmentHash];
    if (!lighting) {
        std::expected<EnvironmentImage, std::string> image = DecodeEnvironment(*frame.environmentBytes);
        if (!image) {
            cache.erase(frame.environmentHash);
            return Problem(image.error());
        }
        lighting = std::make_shared<const EnvironmentLighting>(PrecomputeLighting(*image));
    }
    next.mesh = frame.mesh;
    next.materials = MaterialsOf(frame);
    next.lighting = lighting;
    next.environmentRotationDegrees = project.display.environment.rotation;
    next.environmentExposure = project.display.environment.exposure;
    return next;
}

}  // namespace uzp::preview
