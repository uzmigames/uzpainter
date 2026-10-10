#include "mesh/mesh_builder.h"

#include <algorithm>
#include <numeric>
#include <stdexcept>
#include <vector>

namespace uzp::mesh {

void MeshBuilder::BeginObject(std::string name, const Matrix4& transform) {
    mesh_.objects.push_back(Object{std::move(name), transform, {}});
    has_object_ = true;
}

std::uint32_t MeshBuilder::Material(std::uint64_t key, std::uint64_t file_order, const std::string& name) {
    const auto [it, inserted] = ids_.try_emplace(key, static_cast<std::uint32_t>(sources_.size()));
    if (inserted) sources_.push_back(Source{file_order, name});
    return it->second;
}

void MeshBuilder::AddPolygon(std::span<const Corner> corners) {
    if (!has_object_) throw std::invalid_argument("a face before any object");
    if (corners.size() < 3) {
        throw std::invalid_argument("a face of " + std::to_string(corners.size()) + " corners");
    }
    const auto first = static_cast<std::uint32_t>(mesh_.corners.size());
    mesh_.corners.insert(mesh_.corners.end(), corners.begin(), corners.end());
    Object& object = mesh_.objects.back();
    const auto last = first + static_cast<std::uint32_t>(corners.size()) - 1;
    for (std::uint32_t i = 0; i + 2 < corners.size(); ++i) {
        object.triangles.push_back(Triangle{{first + i, first + i + 1, last}});
    }
    if (corners.size() > 3) ++mesh_.flags.ngons_triangulated;
}

void MeshBuilder::Finish() {
    std::erase_if(mesh_.objects, [](const Object& o) { return o.triangles.empty(); });
    std::vector<bool> used(sources_.size(), false);
    for (const Corner& c : mesh_.corners) used.at(c.material) = true;
    std::vector<std::uint32_t> order(sources_.size());
    std::iota(order.begin(), order.end(), 0u);
    std::stable_sort(order.begin(), order.end(), [&](std::uint32_t a, std::uint32_t b) {
        return sources_[a].file_order < sources_[b].file_order;
    });
    std::vector<std::uint32_t> final_id(sources_.size(), 0);
    mesh_.materials.clear();
    for (std::uint32_t provisional : order) {
        if (!used[provisional]) continue;
        const auto index = static_cast<std::uint32_t>(mesh_.materials.size());
        final_id[provisional] = index;
        mesh_.materials.push_back(mesh::Material{sources_[provisional].name, index});
    }
    for (Corner& c : mesh_.corners) c.material = final_id[c.material];
}

}  // namespace uzp::mesh
