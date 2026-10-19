#include "evaluator/geometry_mask.h"

#include <algorithm>
#include <cmath>
#include <set>

#include "mesh/texturing_mesh.h"

namespace uzp::evaluator {

namespace {

/// A texel-space point (x = u W, y = (1 - v) H).
struct Point {
    double x = 0.0;
    double y = 0.0;
};

double Cross(const Point& a, const Point& b, const Point& p) {
    return (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x);
}

// The coverage's vertex precision: 1/256 texel (decision 281).
constexpr double kSubTexel = 256.0;

}  // namespace

void CoveredTexels(const std::array<std::array<float, 2>, 3>& uv, uint32_t width, uint32_t height,
                   const std::function<void(uint32_t col, uint32_t row)>& cover) {
    const double w = width;
    const double h = height;
    // Each vertex rounded to the nearest 1/256 texel (ties to even); the products and the edge
    // functions below are exact in double for float32 UVs on tiles up to 2^16 texels.
    std::array<Point, 3> p{};
    for (size_t k = 0; k < 3; ++k) {
        p[k] = {std::nearbyint(static_cast<double>(uv[k][0]) * w * kSubTexel) / kSubTexel,
                std::nearbyint((1.0 - static_cast<double>(uv[k][1])) * h * kSubTexel) / kSubTexel};
    }
    const double area = Cross(p[0], p[1], p[2]);
    if (area == 0.0) return;
    // Texel centres (col + 1/2, row + 1/2) inside the bounds.
    const double colLo = std::max(0.0, std::floor(std::min({p[0].x, p[1].x, p[2].x}) - 0.5));
    const double colHi = std::min(w - 1.0, std::ceil(std::max({p[0].x, p[1].x, p[2].x}) - 0.5));
    const double rowLo = std::max(0.0, std::floor(std::min({p[0].y, p[1].y, p[2].y}) - 0.5));
    const double rowHi = std::min(h - 1.0, std::ceil(std::max({p[0].y, p[1].y, p[2].y}) - 0.5));
    for (double row = rowLo; row <= rowHi; row += 1.0) {
        for (double col = colLo; col <= colHi; col += 1.0) {
            const Point centre{col + 0.5, row + 0.5};
            const double w0 = Cross(p[0], p[1], centre);
            const double w1 = Cross(p[1], p[2], centre);
            const double w2 = Cross(p[2], p[0], centre);
            const bool inside =
                area > 0.0 ? (w0 >= 0.0 && w1 >= 0.0 && w2 >= 0.0) : (w0 <= 0.0 && w1 <= 0.0 && w2 <= 0.0);
            if (inside) cover(static_cast<uint32_t>(col), static_cast<uint32_t>(row));
        }
    }
}

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
    for (const mesh::Object& object : mesh.objects) {
        if (items.contains(object.name) != query.inclusionList) continue;
        for (const mesh::Triangle& triangle : object.triangles) {
            if (mesh.corners[triangle.corners[0]].material != material) continue;
            std::array<std::array<float, 2>, 3> uv{};
            for (size_t k = 0; k < 3; ++k) {
                const mesh::Float2 corner = mesh.corners[triangle.corners[k]].uv0;
                uv[k] = {corner.u, corner.v};
            }
            CoveredTexels(uv, query.width, query.height, [&](uint32_t col, uint32_t row) {
                image->values[size_t{row} * query.width + col] = 0xFFFFu;
            });
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
