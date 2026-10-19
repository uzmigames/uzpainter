#pragma once

// Geometry masks of type `Mesh` (docs/architecture/04-layer-stack-and-compositing.md §1, §2;
// phase1.11_compositor-mask-effects): a layer's inclusion or exclusion list of the mesh objects
// of its texture set, which multiplies the layer's mask. The evaluator reads the mask as a raster
// of the set (one 16-bit grey channel, 65535 where the layer applies, 0 elsewhere) from an
// `IGeometryMaskProvider`, keyed by the query below; `MeshGeometryMasks` rasterises it from the
// project's texturing mesh with the texel-centre convention of the UV raster
// (`src/render/uv_raster.h`): row 0 is the top of UV tile 1001 (v = 1), texel (col, row) has its
// centre at u = (col + 1/2) / W, v = 1 - (row + 1/2) / H, and a texel is covered when its centre
// lies inside or on the boundary of a non-degenerate triangle of the texture set's material that
// belongs to an included object, each of the triangle's vertices first rounded in texel space
// (u W, (1 - v) H) to the nearest 1/256 texel, ties to even (`CoveredTexels`; decision 281: the
// sub-texel vertex precision of Painter's coverage). A texel that included and excluded triangles
// both cover is covered. `UVTile` geometry masks are a release gap (dag.h fails them explicitly).

#include "evaluator/tile_store.h"

#include <array>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace uzp::mesh {
struct TexturingMesh;
}

namespace uzp::evaluator {

struct GeometryMaskQuery {
    /// The texture set's material (`TextureSet::material_id`, the mesh material name).
    std::string material;
    /// True: only `items` apply; false: every object but `items` applies.
    bool inclusionList = false;
    /// Object names.
    std::vector<std::string> items;
    /// The set resolution.
    uint32_t width = 0;
    uint32_t height = 0;

    friend bool operator==(const GeometryMaskQuery&, const GeometryMaskQuery&) = default;
};

class IGeometryMaskProvider {
public:
    virtual ~IGeometryMaskProvider() = default;
    /// The mask raster of `query` (`query.width` x `query.height`, one channel of 16-bit codes,
    /// rows top first), or null when the provider has no mesh for it.
    [[nodiscard]] virtual std::shared_ptr<const DecodedImage> Coverage(
        const GeometryMaskQuery& query) const = 0;
};

/// The provider over a texturing mesh (`src/mesh/texturing_mesh.h`); rasters are computed once
/// per query and kept.
class MeshGeometryMasks final : public IGeometryMaskProvider {
public:
    explicit MeshGeometryMasks(std::shared_ptr<const mesh::TexturingMesh> mesh);

    [[nodiscard]] std::shared_ptr<const DecodedImage> Coverage(
        const GeometryMaskQuery& query) const override;

private:
    std::shared_ptr<const mesh::TexturingMesh> m_mesh;
    mutable std::mutex m_mutex;
    mutable std::vector<std::pair<GeometryMaskQuery, std::shared_ptr<const DecodedImage>>> m_rasters;
};

/// Calls `cover(col, row)` for each texel of a `width` x `height` tile whose centre the triangle of
/// UVs `uv` (v up) covers (above: its vertices snapped to 1/256 texel, the centre inside or on the
/// boundary, nothing when the snapped triangle is degenerate), rows top first.
void CoveredTexels(const std::array<std::array<float, 2>, 3>& uv, uint32_t width, uint32_t height,
                   const std::function<void(uint32_t col, uint32_t row)>& cover);

/// The texel-centre coverage of `query` over `mesh` (above): one 16-bit code per texel.
[[nodiscard]] std::shared_ptr<const DecodedImage> RasterizeGeometryMask(
    const mesh::TexturingMesh& mesh, const GeometryMaskQuery& query);

}  // namespace uzp::evaluator
