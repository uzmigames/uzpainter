#include "evaluator/geometry_mask.h"

#include <algorithm>
#include <cmath>
#include <set>

#include "mesh/texturing_mesh.h"

namespace uzp::evaluator {

namespace {

struct Point {
    double u = 0.0;
    double v = 0.0;
};

double Cross(const Point& a, const Point& b, const Point& p) {
    return (b.u - a.u) * (p.v - a.v) - (b.v - a.v) * (p.u - a.u);
}

}  // namespace

std::shared_ptr<const DecodedImage> RasterizeGeometryMask(const mesh::TexturingMesh& mesh,
                                                          const GeometryMaskQuery& query) {
    auto image = std::make_shared<DecodedImage>();
    image->width = query.width;
    image->height = query.height;
    image->channels = 1;
    image->encoding = render::TexelEncoding::Unorm16;
    image->values.assign(size_t{query.width} * query.height, 0u);
    uint32_t material = UINT32_MAX;
    for (const mesh::Material& candidate : mesh.materials) {
        if (candidate.name == query.material) material = candidate.index;
    }
    if (material == UINT32_MAX || query.width == 0 || query.height == 0) return image;
    const std::set<std::string> items(query.items.begin(), query.items.end());
    const double width = query.width;
    const double height = query.height;
    for (const mesh::Object& object : mesh.objects) {
        if (items.contains(object.name) != query.inclusionList) continue;
        for (const mesh::Triangle& triangle : object.triangles) {
            if (mesh.corners[triangle.corners[0]].material != material) continue;
            Point p[3];
            for (int k = 0; k < 3; ++k) {
                const mesh::Float2 uv = mesh.corners[triangle.corners[static_cast<size_t>(k)]].uv0;
                p[k] = {static_cast<double>(uv.u), static_cast<double>(uv.v)};
            }
            const double area = Cross(p[0], p[1], p[2]);
            if (area == 0.0) continue;
            const double uMin = std::min({p[0].u, p[1].u, p[2].u});
            const double uMax = std::max({p[0].u, p[1].u, p[2].u});
            const double vMin = std::min({p[0].v, p[1].v, p[2].v});
            const double vMax = std::max({p[0].v, p[1].v, p[2].v});
            // Texel centres u = (col + 1/2) / W and v = 1 - (row + 1/2) / H inside the bounds.
            const double colLo = std::max(0.0, std::floor(uMin * width - 0.5));
            const double colHi = std::min(width - 1.0, std::ceil(uMax * width - 0.5));
            const double rowLo = std::max(0.0, std::floor((1.0 - vMax) * height - 0.5));
            const double rowHi = std::min(height - 1.0, std::ceil((1.0 - vMin) * height - 0.5));
            for (double row = rowLo; row <= rowHi; row += 1.0) {
                for (double col = colLo; col <= colHi; col += 1.0) {
                    const Point centre{(col + 0.5) / width, 1.0 - (row + 0.5) / height};
                    const double w0 = Cross(p[0], p[1], centre);
                    const double w1 = Cross(p[1], p[2], centre);
                    const double w2 = Cross(p[2], p[0], centre);
                    const bool inside = area > 0.0 ? (w0 >= 0.0 && w1 >= 0.0 && w2 >= 0.0)
                                                   : (w0 <= 0.0 && w1 <= 0.0 && w2 <= 0.0);
                    if (inside) {
                        image->values[static_cast<size_t>(row) * query.width + static_cast<size_t>(col)] = 0xFFFFu;
                    }
                }
            }
        }
    }
    return image;
}

MeshGeometryMasks::MeshGeometryMasks(std::shared_ptr<const mesh::TexturingMesh> mesh)
    : m_mesh(std::move(mesh)) {}

std::shared_ptr<const DecodedImage> MeshGeometryMasks::Coverage(const GeometryMaskQuery& query) const {
    if (!m_mesh) return nullptr;
    std::lock_guard<std::mutex> lock(m_mutex);
    for (const auto& [cached, raster] : m_rasters) {
        if (cached == query) return raster;
    }
    std::shared_ptr<const DecodedImage> raster = RasterizeGeometryMask(*m_mesh, query);
    m_rasters.emplace_back(query, raster);
    return raster;
}

}  // namespace uzp::evaluator
