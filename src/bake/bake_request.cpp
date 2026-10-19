#include "bake/bake_request.h"

namespace uzp::bake {

const char* UsageName(MeshMapUsage usage) {
    switch (usage) {
        case MeshMapUsage::Normal: return "Normal";
        case MeshMapUsage::WorldSpaceNormal: return "WorldSpaceNormal";
        case MeshMapUsage::ID: return "ID";
        case MeshMapUsage::AO: return "AO";
        case MeshMapUsage::Curvature: return "Curvature";
        case MeshMapUsage::Position: return "Position";
        case MeshMapUsage::Thickness: return "Thickness";
        case MeshMapUsage::Height: return "Height";
        case MeshMapUsage::BentNormals: return "BentNormals";
        case MeshMapUsage::Opacity: return "Opacity";
    }
    return "unknown";
}

namespace {

void PutLe(std::string& out, std::uint64_t value, int bytes) {
    for (int i = 0; i < bytes; ++i) out.push_back(static_cast<char>((value >> (8 * i)) & 0xFFu));
}

}  // namespace

std::string SerializeResult(const BakeResult& result) {
    std::string out = "UZPBAKE1";
    PutLe(out, result.width, 4);
    PutLe(out, result.height, 4);
    PutLe(out, result.tile_size, 4);
    PutLe(out, result.rays_per_texel, 4);
    for (std::uint16_t v : result.ao_raw) PutLe(out, v, 2);
    for (std::uint8_t v : result.texel_class) PutLe(out, v, 1);
    for (std::uint16_t v : result.back_face_rays) PutLe(out, v, 2);
    for (std::uint16_t v : result.self_hit_rays) PutLe(out, v, 2);
    const TexelClassCounts& t = result.texels;
    for (std::uint64_t v : {t.uncovered, t.straight_hit, t.back_face_hit, t.centre_miss}) PutLe(out, v, 8);
    const RayClassCounts& r = result.rays;
    for (std::uint64_t v : {r.escaped, r.front_hit, r.back_face_hit, r.self_hit}) PutLe(out, v, 8);
    return out;
}

}  // namespace uzp::bake
