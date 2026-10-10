#pragma once

// UV-space rasterisation of a texturing mesh (docs/architecture/12-mesh-import.md §5, §6;
// 13-engine-integration.md §4.1): one compute pass per texture set and UV tile that writes, for
// every texel, the mesh's position, normal and tangent frame interpolated at the texel centre,
// the island and material ids of the triangle covering it, the texel-centre coverage and a
// conservative coverage mask. Projections, generators and bakers read these buffers.
//
// Texel convention (the Phase 0 prototype's, which equals Painter's bakes on the
// normal-convention fixture, parity/reports/phase0/normal-convention.md): row 0 of every buffer is
// the top of the tile (v = 1), texel (col, row) of a W x H buffer has its centre at
// u = (col + 1/2) / W, v = 1 - (row + 1/2) / H, both relative to the tile's origin.
//
// - Texel-centre coverage: a texel is covered when its centre lies inside or on the boundary of
//   a non-degenerate UV triangle. Edge functions are evaluated in one canonical vertex order per
//   edge, so two triangles sharing an edge see exactly opposite values: no centre on a shared
//   edge is lost, and when several triangles cover a centre the lowest triangle index wins
//   (independent of execution order).
// - Conservative mask: every texel whose square [col, col+1] x [row, row+1] the interior of a
//   triangle overlaps (the overlap has positive area), plus every texel-centre covered texel. The
//   mask is the limit of supersampling the texel (any sub-sample position, at any density), and is
//   evaluated exactly with a separating-axis test instead of a finite sample grid: a finite grid
//   misses triangles narrower than its sample spacing, which the mask must contain. The vendored
//   RHI has no conservative rasterisation (12 §5), so the pass is a compute pass.
//
// Repeatable: the same mesh, settings and build give byte-identical buffers. Kernels are compiled
// IEEE-strict (`-Gis`, kernel_cache.h); coverage is resolved with an atomic minimum and every
// other value is a pure function of the winning triangle and the texel.

#include "render/backend.h"
#include "render/engine_thread.h"

#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace uzp::render {

/// The id written where no triangle covers a texel centre (triangle, material and island ids).
inline constexpr uint32_t kUvRasterNoId = 0xFFFFFFFFu;

/// The UDIM number of the 0-1 UV square. v1 rasterises this tile only (12 §6); every buffer
/// carries its tile so that the UV-tile workflow needs no change of the data model.
inline constexpr uint32_t kUvTile1001 = 1001;

/// Where one per-corner attribute lives: in `CornerBuffers::buffers[buffer]`, the value of corner
/// `c` starts at byte `offset + c * stride`. Offsets and strides are explicit for every
/// attribute (there is no default stride); both are multiples of 4 and the stride is at least
/// the attribute's size. Attributes may share a buffer (interleaved) or not (separate streams).
struct CornerAttribute {
    uint32_t buffer = 0;
    uint32_t offset = 0;
    uint32_t stride = 0;
};

/// The texturing mesh's corners in a backend-neutral layout (12 §1: `corners[]` and the
/// triangles' corner ids). All values are little-endian 32-bit.
struct CornerBuffers {
    /// The raw bytes the attributes point into; at most `kMaxCornerBuffers`, each below 4 GiB.
    std::vector<std::span<const std::byte>> buffers;
    uint32_t cornerCount = 0;
    CornerAttribute position;    ///< float x, y, z (object space)
    CornerAttribute normal;      ///< float x, y, z (the corner normal, not renormalised)
    CornerAttribute uv0;         ///< float u, v
    CornerAttribute tangent;     ///< float x, y, z, bitangent sign (MikkTSpace, 12 §3)
    CornerAttribute materialId;  ///< uint32
    CornerAttribute islandId;    ///< uint32
    /// Three corner ids per triangle, in triangle order (12 §1: `triangles[] {corner ids}`). A
    /// triangle's material and island ids are those of its first corner.
    std::span<const uint32_t> triangles;
};

inline constexpr size_t kMaxCornerBuffers = 6;

struct UvRasterRequest {
    uint32_t width = 0;   ///< Texels; 1 to 16384.
    uint32_t height = 0;
    uint32_t uvTile = kUvTile1001;
    /// The texture set: only triangles whose material id is listed are rasterised; empty
    /// rasterises every triangle.
    std::vector<uint32_t> materials;
};

/// The raster of one texture set and UV tile, as GPU textures in `Common` state (created with
/// shader-resource, unordered-access and copy-source usage). Owned by the caller: `Destroy`
/// releases them.
struct UvRasterBuffers {
    uint32_t uvTile = kUvTile1001;
    uint32_t width = 0;
    uint32_t height = 0;
    /// RGBA32Float: interpolated position xyz, w = 1 on covered texels.
    uz::RHITextureHandle position = uz::RHITextureHandle::Invalid();
    /// RGBA32Float: interpolated corner normal xyz (unnormalised), w = 0.
    uz::RHITextureHandle normal = uz::RHITextureHandle::Invalid();
    /// RGBA32Float: interpolated tangent xyz (unnormalised), w = interpolated bitangent sign
    /// (`TangentSpace.PerFragment` rebuilds the bitangent with `w < 0 ? -1 : +1`).
    uz::RHITextureHandle tangent = uz::RHITextureHandle::Invalid();
    /// RGBA32Float: interpolated `sign * cross(normal, tangent)` of the corners
    /// (`TangentSpace.PerVertex`), w = 0.
    uz::RHITextureHandle bitangent = uz::RHITextureHandle::Invalid();
    /// R32Uint: island id of the covering triangle, `kUvRasterNoId` elsewhere.
    uz::RHITextureHandle islandId = uz::RHITextureHandle::Invalid();
    /// R32Uint: material id of the covering triangle, `kUvRasterNoId` elsewhere.
    uz::RHITextureHandle materialId = uz::RHITextureHandle::Invalid();
    /// R32Uint, the texel-centre coverage: index of the triangle covering the texel centre (the
    /// lowest one), `kUvRasterNoId` where none does.
    uz::RHITextureHandle triangle = uz::RHITextureHandle::Invalid();
    /// R8Unorm, the conservative coverage mask: 1 on every texel a triangle touches, else 0.
    uz::RHITextureHandle conservative = uz::RHITextureHandle::Invalid();

    /// Every texture, in the order of the members above.
    [[nodiscard]] std::vector<uz::RHITextureHandle> Textures() const;
    /// Destroys every texture and resets the handles.
    void Destroy(IDevice& device);
};

/// Checks the corner layout and the request without touching the GPU: every attribute's buffer
/// index, alignment, stride and extent, every corner id, the size and the UV tile.
Result<void> ValidateUvRaster(const CornerBuffers& corners, const UvRasterRequest& request,
                              Backend backend);

/// Rasterises `corners` into the buffers of `request` inside one engine request: uploads the
/// corners, runs the pass and waits for it (bounded by the request's deadline). On an error
/// nothing stays allocated, except after a `timeout`: the GPU may then still use the pass's
/// resources, so they are kept (the engine fails every later request and keeps its device).
Result<UvRasterBuffers> RasterizeUv(EngineContext& context, const CornerBuffers& corners,
                                    const UvRasterRequest& request);

}  // namespace uzp::render
