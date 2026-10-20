#include "bake/id_baker.h"

#include <limits>
#include <string>

#include "uzp_core/types/errors.h"

namespace uzp::bake {

namespace {

const char* SourceLabel(IdColorSource source) {
    switch (source) {
        case IdColorSource::VertexColor: return "Vertex color";
        case IdColorSource::MaterialColor: return "Material color";
        case IdColorSource::FileId: return "File ID";
        case IdColorSource::MeshId: return "Mesh ID / Polygroup";
        case IdColorSource::Submesh: return "Submesh";
    }
    return "unknown";
}

const char* GeneratorLabel(IdColorGenerator generator) {
    switch (generator) {
        case IdColorGenerator::Random: return "Random";
        case IdColorGenerator::HueShift: return "Hue shift";
        case IdColorGenerator::Grayscale: return "Grayscale";
    }
    return "unknown";
}

}  // namespace

void ValidateId(const BakeRequest& request) {
    const std::string owner = UsageOwnerTask(MeshMapUsage::ID) + ", decision 337";
    const IdColorSource source = request.id.source;
    if (source == IdColorSource::VertexColor || source == IdColorSource::MaterialColor ||
        source == IdColorSource::FileId) {
        throw core::NotYetSupported(std::string("ID ColorSource '") + SourceLabel(source) +
                                    "': the bake mesh carries no such input (vertex colours, the material's colour, "
                                    "an ID file) and its use is not recorded (" + owner + ")");
    }
    if (source == IdColorSource::Submesh) {
        throw core::NotYetSupported("ID ColorSource 'Submesh': what Painter groups by is not recorded (" + owner + ")");
    }
    if (source != IdColorSource::MeshId) throw core::ValueError("invalid ID ColorSource");
    if (request.id.generator) {
        const IdColorGenerator generator = *request.id.generator;
        if (generator != IdColorGenerator::Random && generator != IdColorGenerator::HueShift &&
            generator != IdColorGenerator::Grayscale) {
            throw core::ValueError("invalid ID ColorGenerator");
        }
        throw core::NotYetSupported(std::string("ID ColorGenerator '") + GeneratorLabel(generator) +
                                    "': the colour Painter gives each label is not recorded; an ID golden settles "
                                    "it (" + owner + ")");
    }
    if (request.detail.subsampling != 1) {
        throw core::NotYetSupported("ID SubSampling > 1 has no established resolve rule (" + owner + ")");
    }
    if (request.common.dilation_width != 0) {
        throw core::NotYetSupported("ID DilationWidth > 0 has no established padding rule (" + owner + ")");
    }
    const std::size_t meshes = request.detail.low_as_high ? request.low.size() : request.high.size();
    if (meshes > std::numeric_limits<std::uint16_t>::max() - 1u) {
        throw core::ValueError("ID labels are uint16: at most 65534 meshes");
    }
}

void PrepareId(const std::vector<const BakeMesh*>& high, BakeResult& result) {
    result.id_labels.assign(static_cast<std::size_t>(result.width) * result.height, 0);
    result.id_label_meshes.clear();
    for (const BakeMesh* mesh : high) result.id_label_meshes.push_back(mesh->name);
}

void WriteId(BakeResult& result, std::size_t texel, unsigned mesh) {
    result.id_labels[texel] = static_cast<std::uint16_t>(mesh + 1u);
}

}  // namespace uzp::bake
