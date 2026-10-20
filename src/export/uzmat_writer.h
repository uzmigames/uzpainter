#pragma once

#include <string>
#include <vector>

namespace uzp::exporter {

enum class UzMaterialBlend { Opaque, Masked, Translucent, Additive };

struct UzMaterialSpec {
    std::string name;
    // The .uzmat is at the delivery root, which the consumer mounts as its VFS root.
    std::string materialPath;
    std::string albedo;
    std::string normal;
    std::string orm;
    std::string emissive;
    // Optional exported map; the pinned engine has no verified height binding.
    std::string height;
    UzMaterialBlend blend = UzMaterialBlend::Opaque;
    bool twoSided = false;
};

struct UzMaterialGap {
    std::string binding;
    std::string path;
    std::string reason;
};

struct UzMaterial {
    std::string materialPath;
    std::string bytes;
    // JSON value for a scene entity's components.material block.
    std::string inlineMaterial;
    std::vector<UzMaterialGap> gaps;
};

// Emits the seven PBROutput bindings and their matching inline scene block from
// the approved UzEngine format (U-UZE-RUNTIME, a703c95), without an engine dependency.
// Texture paths are relative to the delivery root and end in .uztexture. The
// material path is a basename ending in .uzmat. Invalid input throws
// std::invalid_argument. This pure writer does not publish files or infer formats.
[[nodiscard]] UzMaterial WriteUzMaterial(const UzMaterialSpec& spec);

}  // namespace uzp::exporter
