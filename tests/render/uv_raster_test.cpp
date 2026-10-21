// Native tests of the UV-space raster pass (src/render/uv_raster.*, rulebook task
// phase1.3_core-uv-raster), on synthetic meshes. Part of `uzp-render-tests.exe` (`zig build
// render-tests`), dispatched from render_core_test.cpp's main() and driven by
// tests/render/test_core_uv_raster.py.
//
// Cases (uzp-render-tests <case> <work-dir>):
//   uv-raster-validate  corner-layout and request validation (no GPU)
//   uv-raster-plane     unit plane on the 0-1 square at 256 x 256: analytic coverage and values;
//                       interleaved and separate corner layouts give identical buffers
//   uv-raster-thin      a sliver narrower than a texel: the conservative mask holds every texel
//                       it touches
//   uv-raster-coverage  sphere and bevelled cube: conservative mask against an exact reference
//   uv-raster-ids       two materials, two islands: ids per texel; a texture-set filter
//   uv-raster-repeat    the bevelled cube rasterised twice: byte-identical; prints `HASH` lines
//                       that the Python test compares across processes
//   uv-raster-tier0     the plane, sphere and bevelled cube OBJs of the Tier 0 corpus (copied into
//                       <work-dir>/tier0-meshes/ by tests/render/test_render_core_layer.py)
//   vulkan-uv-raster    the plane, sphere and bevelled cube on DX12 and on the qualified Vulkan
//                       device: every buffer byte for byte equal (phase3.1_vulkan-compute-parity
//                       items 2.5, 3.2; tests/render/test_vulkan_image_passes.py)
//
// The reference is computed on the CPU in double precision. Texels within `kEps` texels of a
// triangle boundary are ambiguous at single precision and are checked only for consistency.

#include "uv_raster_fixtures.h"

#include "render/backend.h"
#include "render/engine_thread.h"
#include "render/texture_readback.h"
#include "render/uv_raster.h"
#include "render/vulkan_backend.h"
#include "render/xxhash64.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <future>
#include <memory>
#include <numbers>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

int RunUvRasterCase(std::string_view mode, const std::filesystem::path& dir);

namespace {

using namespace uzp::render;
namespace fs = std::filesystem;

constexpr int kExitSkip = 77;
constexpr double kEps = 1e-3;  // texels
int g_failures = 0;

void Check(bool ok, std::string_view name, const std::string& detail = {}) {
    if (ok) {
        std::printf("PASS %.*s\n", static_cast<int>(name.size()), name.data());
    } else {
        std::printf("FAIL %.*s: %s\n", static_cast<int>(name.size()), name.data(), detail.c_str());
        ++g_failures;
    }
    std::fflush(stdout);
}

void Info(const std::string& text) {
    std::printf("INFO %s\n", text.c_str());
    std::fflush(stdout);
}

int Finish() { return g_failures == 0 ? 0 : 1; }

template <class T>
std::string Describe(const Result<T>& result) {
    return result ? std::string("success") : result.error().Describe();
}

// ── Synthetic meshes ─────────────────────────────────────────────────────────

struct Vec2 {
    double x, y;
};
struct Vec3 {
    double x, y, z;
};

Vec3 Normalize(Vec3 v) {
    const double l = std::sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
    return {v.x / l, v.y / l, v.z / l};
}

struct Corner {
    std::array<float, 3> position{};
    std::array<float, 3> normal{};
    std::array<float, 2> uv{};
    std::array<float, 4> tangent{};
    uint32_t material = 0;
    uint32_t island = 0;
};

struct Mesh {
    std::vector<Corner> corners;
    std::vector<uint32_t> triangles;

    uint32_t Add(const Corner& corner) {
        corners.push_back(corner);
        return static_cast<uint32_t>(corners.size() - 1);
    }
    void Triangle(uint32_t a, uint32_t b, uint32_t c) {
        triangles.insert(triangles.end(), {a, b, c});
    }
    [[nodiscard]] size_t TriangleCount() const { return triangles.size() / 3; }
    [[nodiscard]] Vec2 Uv(size_t triangle, size_t k) const {
        const Corner& c = corners[triangles[triangle * 3 + k]];
        return {c.uv[0], c.uv[1]};
    }
};

Corner MakeCorner(Vec3 p, Vec3 n, Vec2 uv, Vec3 t, float sign, uint32_t material,
                  uint32_t island) {
    Corner c;
    c.position = {static_cast<float>(p.x), static_cast<float>(p.y), static_cast<float>(p.z)};
    c.normal = {static_cast<float>(n.x), static_cast<float>(n.y), static_cast<float>(n.z)};
    c.uv = {static_cast<float>(uv.x), static_cast<float>(uv.y)};
    c.tangent = {static_cast<float>(t.x), static_cast<float>(t.y), static_cast<float>(t.z), sign};
    c.material = material;
    c.island = island;
    return c;
}

/// The analytic plane of the plane fixture: position (u - 1/2, 0, 1/2 - v), normal +Y, tangent
/// +X, sign -1 (so both frame buffers have a known non-trivial value).
Vec3 PlanePosition(double u, double v) { return {u - 0.5, 0.0, 0.5 - v}; }

/// A unit plane mapped to the whole 0-1 square, as a grid of `n` x `n` quads with shared corners.
Mesh PlaneMesh(int n) {
    Mesh mesh;
    for (int j = 0; j <= n; ++j) {
        for (int i = 0; i <= n; ++i) {
            const Vec2 uv{static_cast<double>(i) / n, static_cast<double>(j) / n};
            mesh.Add(MakeCorner(PlanePosition(uv.x, uv.y), {0, 1, 0}, uv, {1, 0, 0}, -1.0f, 4, 9));
        }
    }
    const auto at = [&](int i, int j) { return static_cast<uint32_t>(j * (n + 1) + i); };
    for (int j = 0; j < n; ++j) {
        for (int i = 0; i < n; ++i) {
            mesh.Triangle(at(i, j), at(i + 1, j), at(i + 1, j + 1));
            mesh.Triangle(at(i, j), at(i + 1, j + 1), at(i, j + 1));
        }
    }
    return mesh;
}

/// A UV sphere: `segments` x `rings`, one corner per triangle corner, UVs in [0.05, 0.95].
Mesh SphereMesh(int segments, int rings) {
    Mesh mesh;
    const auto corner = [&](int i, int j) {
        const double theta = std::numbers::pi * i / rings;
        const double phi = 2.0 * std::numbers::pi * j / segments;
        const Vec3 p{std::sin(theta) * std::cos(phi), std::cos(theta),
                     std::sin(theta) * std::sin(phi)};
        const Vec2 uv{0.05 + 0.9 * j / segments, 0.95 - 0.9 * i / rings};
        return mesh.Add(MakeCorner(p, p, uv, {-std::sin(phi), 0.0, std::cos(phi)}, 1.0f, 0, 0));
    };
    for (int i = 0; i < rings; ++i) {
        for (int j = 0; j < segments; ++j) {
            if (i > 0) mesh.Triangle(corner(i, j), corner(i + 1, j), corner(i, j + 1));
            if (i + 1 < rings) mesh.Triangle(corner(i, j + 1), corner(i + 1, j), corner(i + 1, j + 1));
        }
    }
    return mesh;
}

/// A cube [-1, 1]^3 with bevelled edges and corners: 6 faces, 12 edge bevels and 8 corner
/// triangles, each its own UV island in a 6 x 5 grid of cells, rotated by an island-dependent
/// angle. Faces are material 0, bevels material 1; the island id is the piece's index.
Mesh BevelledCubeMesh() {
    constexpr double b = 0.2;
    constexpr double in = 1.0 - b;
    Mesh mesh;
    uint32_t island = 0;
    // Places a planar piece (3D points with 2D layout coordinates in [-1, 1]^2) into its cell.
    const auto piece = [&](const std::vector<Vec3>& points, const std::vector<Vec2>& layout,
                           Vec3 normal, uint32_t material) {
        const int cellX = static_cast<int>(island % 6);
        const int cellY = static_cast<int>(island / 6);
        const double angle = 0.37 * (island + 1);
        const double radius = 0.42 / std::sqrt(2.0);  // of a cell, after rotation
        const double cw = 1.0 / 6.0, ch = 1.0 / 5.0;
        std::vector<uint32_t> ids;
        for (size_t k = 0; k < points.size(); ++k) {
            const Vec2 l = layout[k];
            const double rx = l.x * std::cos(angle) - l.y * std::sin(angle);
            const double ry = l.x * std::sin(angle) + l.y * std::cos(angle);
            const Vec2 uv{(cellX + 0.5 + rx * radius) * cw, (cellY + 0.5 + ry * radius) * ch};
            ids.push_back(mesh.Add(MakeCorner(points[k], normal, uv, {1, 0, 0}, 1.0f, material,
                                              island)));
        }
        for (size_t k = 1; k + 1 < ids.size(); ++k) mesh.Triangle(ids[0], ids[k], ids[k + 1]);
        ++island;
    };
    const auto axisPoint = [](int axis, double a, int axis1, double v1, int axis2, double v2) {
        double p[3] = {0, 0, 0};
        p[axis] = a;
        p[axis1] = v1;
        p[axis2] = v2;
        return Vec3{p[0], p[1], p[2]};
    };
    const auto unit = [](int axis, double s) {
        double p[3] = {0, 0, 0};
        p[axis] = s;
        return Vec3{p[0], p[1], p[2]};
    };
    const std::vector<Vec2> square{{-1, -1}, {1, -1}, {1, 1}, {-1, 1}};
    const std::vector<Vec2> strip{{-1, -0.3}, {1, -0.3}, {1, 0.3}, {-1, 0.3}};
    const std::vector<Vec2> tri{{-1, -0.8}, {1, -0.8}, {0, 1}};
    for (int axis = 0; axis < 3; ++axis) {
        for (const double s : {-1.0, 1.0}) {
            const int a1 = (axis + 1) % 3, a2 = (axis + 2) % 3;
            piece({axisPoint(axis, s, a1, -in, a2, -in), axisPoint(axis, s, a1, in, a2, -in),
                   axisPoint(axis, s, a1, in, a2, in), axisPoint(axis, s, a1, -in, a2, in)},
                  square, unit(axis, s), 0);
        }
    }
    for (int axis = 0; axis < 3; ++axis) {  // the edge runs along `axis`
        const int a1 = (axis + 1) % 3, a2 = (axis + 2) % 3;
        for (const double s1 : {-1.0, 1.0}) {
            for (const double s2 : {-1.0, 1.0}) {
                const auto point = [&](double along, double v1, double v2) {
                    return axisPoint(axis, along, a1, v1, a2, v2);
                };
                Vec3 n{0, 0, 0};
                n = Normalize({unit(a1, s1).x + unit(a2, s2).x, unit(a1, s1).y + unit(a2, s2).y,
                               unit(a1, s1).z + unit(a2, s2).z});
                piece({point(-in, s1, s2 * in), point(in, s1, s2 * in), point(in, s1 * in, s2),
                       point(-in, s1 * in, s2)},
                      strip, n, 1);
            }
        }
    }
    for (const double sx : {-1.0, 1.0}) {
        for (const double sy : {-1.0, 1.0}) {
            for (const double sz : {-1.0, 1.0}) {
                piece({{sx, sy * in, sz * in}, {sx * in, sy, sz * in}, {sx * in, sy * in, sz}}, tri,
                      Normalize({sx, sy, sz}), 1);
            }
        }
    }
    return mesh;
}

/// A sliver narrower than a tenth of a texel at 256 x 256, plus a sub-texel triangle.
Mesh ThinMesh() {
    Mesh mesh;
    const auto add = [&](Vec2 a, Vec2 b, Vec2 c) {
        const uint32_t i = mesh.Add(MakeCorner({a.x, a.y, 0}, {0, 0, 1}, a, {1, 0, 0}, 1, 0, 0));
        const uint32_t j = mesh.Add(MakeCorner({b.x, b.y, 0}, {0, 0, 1}, b, {1, 0, 0}, 1, 0, 0));
        const uint32_t k = mesh.Add(MakeCorner({c.x, c.y, 0}, {0, 0, 1}, c, {1, 0, 0}, 1, 0, 0));
        mesh.Triangle(i, j, k);
    };
    add({0.101, 0.103}, {0.893, 0.611}, {0.893, 0.6113});
    add({0.5002, 0.2002}, {0.5012, 0.2003}, {0.5003, 0.2013});
    return mesh;
}

/// Two islands, two materials: island 0 is a quad whose triangles have materials 5 and 2, island 1
/// a quad of material 2.
Mesh TwoIslandMesh() {
    Mesh mesh;
    const auto quad = [&](Vec2 lo, Vec2 hi, uint32_t m0, uint32_t m1, uint32_t island) {
        const Vec2 uv[4] = {{lo.x, lo.y}, {hi.x, lo.y}, {hi.x, hi.y}, {lo.x, hi.y}};
        uint32_t ids[6];
        const int order[6] = {0, 1, 2, 0, 2, 3};
        for (int k = 0; k < 6; ++k) {
            const Vec2 p = uv[order[k]];
            ids[k] = mesh.Add(MakeCorner({p.x, p.y, 0}, {0, 0, 1}, p, {1, 0, 0}, 1,
                                         k < 3 ? m0 : m1, island));
        }
        mesh.Triangle(ids[0], ids[1], ids[2]);
        mesh.Triangle(ids[3], ids[4], ids[5]);
    };
    quad({0.1, 0.1}, {0.45, 0.9}, 5, 2, 0);
    quad({0.55, 0.2}, {0.9, 0.8}, 2, 2, 1);
    return mesh;
}

// ── Corner layouts ───────────────────────────────────────────────────────────

/// A mesh's corners in a backend-neutral layout, owning its bytes.
struct Layout {
    std::vector<std::vector<std::byte>> storage;
    CornerBuffers corners;
};

template <class T>
void Put(std::vector<std::byte>& bytes, size_t at, const T& value) {
    std::memcpy(bytes.data() + at, &value, sizeof(T));
}

/// All attributes interleaved in one buffer with a 64-byte stride, in an unusual order with gaps,
/// after a 12-byte header.
Layout Interleaved(const Mesh& mesh) {
    constexpr uint32_t stride = 64, base = 12;
    Layout layout;
    layout.storage.emplace_back(base + mesh.corners.size() * stride, std::byte{0xAB});
    std::vector<std::byte>& bytes = layout.storage[0];
    for (size_t c = 0; c < mesh.corners.size(); ++c) {
        const Corner& k = mesh.corners[c];
        const size_t at = base + c * stride;
        Put(bytes, at + 0, k.island);
        Put(bytes, at + 4, k.uv);
        Put(bytes, at + 16, k.tangent);
        Put(bytes, at + 32, k.normal);
        Put(bytes, at + 44, k.material);
        Put(bytes, at + 48, k.position);
    }
    CornerBuffers& cb = layout.corners;
    cb.buffers = {bytes};
    cb.cornerCount = static_cast<uint32_t>(mesh.corners.size());
    cb.islandId = {0, base + 0, stride};
    cb.uv0 = {0, base + 4, stride};
    cb.tangent = {0, base + 16, stride};
    cb.normal = {0, base + 32, stride};
    cb.materialId = {0, base + 44, stride};
    cb.position = {0, base + 48, stride};
    cb.triangles = mesh.triangles;
    return layout;
}

/// One tightly packed stream per attribute (ids share one buffer at stride 8).
Layout Separate(const Mesh& mesh) {
    Layout layout;
    const size_t n = mesh.corners.size();
    layout.storage.resize(5);
    layout.storage[0].resize(n * 12);
    layout.storage[1].resize(n * 12);
    layout.storage[2].resize(n * 8);
    layout.storage[3].resize(n * 16);
    layout.storage[4].resize(n * 8);
    for (size_t c = 0; c < n; ++c) {
        const Corner& k = mesh.corners[c];
        Put(layout.storage[0], c * 12, k.position);
        Put(layout.storage[1], c * 12, k.normal);
        Put(layout.storage[2], c * 8, k.uv);
        Put(layout.storage[3], c * 16, k.tangent);
        Put(layout.storage[4], c * 8, k.material);
        Put(layout.storage[4], c * 8 + 4, k.island);
    }
    CornerBuffers& cb = layout.corners;
    for (const auto& bytes : layout.storage) cb.buffers.emplace_back(bytes);
    cb.cornerCount = static_cast<uint32_t>(n);
    cb.position = {0, 0, 12};
    cb.normal = {1, 0, 12};
    cb.uv0 = {2, 0, 8};
    cb.tangent = {3, 0, 16};
    cb.materialId = {4, 0, 8};
    cb.islandId = {4, 4, 8};
    cb.triangles = mesh.triangles;
    return layout;
}

// ── Raster and readback ──────────────────────────────────────────────────────

struct Raster {
    uint32_t width = 0, height = 0, uvTile = 0;
    // In the order of UvRasterBuffers::Textures().
    std::array<ReadbackImage, 8> images;

    [[nodiscard]] const ReadbackImage& Position() const { return images[0]; }
    [[nodiscard]] const ReadbackImage& Normal() const { return images[1]; }
    [[nodiscard]] const ReadbackImage& Tangent() const { return images[2]; }
    [[nodiscard]] const ReadbackImage& Bitangent() const { return images[3]; }
    [[nodiscard]] const ReadbackImage& Island() const { return images[4]; }
    [[nodiscard]] const ReadbackImage& Material() const { return images[5]; }
    [[nodiscard]] const ReadbackImage& Triangle() const { return images[6]; }
    [[nodiscard]] const ReadbackImage& Mask() const { return images[7]; }

    [[nodiscard]] std::array<float, 4> Float4(const ReadbackImage& image, uint32_t x,
                                              uint32_t y) const {
        std::array<float, 4> v{};
        std::memcpy(v.data(), image.texels.data() + (size_t{y} * width + x) * 16, 16);
        return v;
    }
    [[nodiscard]] uint32_t Uint(const ReadbackImage& image, uint32_t x, uint32_t y) const {
        uint32_t v = 0;
        std::memcpy(&v, image.texels.data() + (size_t{y} * width + x) * 4, 4);
        return v;
    }
    [[nodiscard]] bool Masked(uint32_t x, uint32_t y) const {
        return Mask().texels[size_t{y} * width + x] != std::byte{0};
    }
};

constexpr std::array<const char*, 8> kBufferNames = {
    "position", "normal", "tangent", "bitangent", "island_id", "material_id", "triangle",
    "conservative"};

struct Job {
    const CornerBuffers* corners;
    UvRasterRequest request;
};

/// Rasterises and reads every buffer back inside one engine request; destroys the buffers.
Result<Raster> RasterAndRead(EngineContext& context, const Job& job) {
    Result<UvRasterBuffers> buffers = RasterizeUv(context, *job.corners, job.request);
    if (!buffers) return Unexpected(buffers.error());
    Raster raster;
    raster.width = buffers->width;
    raster.height = buffers->height;
    raster.uvTile = buffers->uvTile;
    std::optional<Error> error;
    {
        TextureReadback readback(context);
        std::vector<ReadbackId> ids;
        for (uz::RHITextureHandle texture : buffers->Textures()) {
            ReadbackDesc desc;
            desc.texture = texture;
            Result<ReadbackId> id = readback.Request(desc);
            if (!id) {
                error = id.error();
                break;
            }
            ids.push_back(*id);
        }
        for (size_t i = 0; i < ids.size(); ++i) {
            Result<ReadbackImage> image = readback.Complete(ids[i]);
            if (!image) {
                if (!error) error = image.error();
                continue;
            }
            raster.images[i] = std::move(*image);
        }
    }
    buffers->Destroy(context.Device());
    if (error) return Unexpected(*error);
    return raster;
}

/// The engine of a GPU case; null (and exit 77) without a DX12 device.
std::unique_ptr<Engine> MakeEngine(const fs::path& dir) {
    EngineOptions options;
    options.kernelCacheRoot = dir / "kernel-cache";
    auto engine = std::make_unique<Engine>(options);
    if (engine->DeviceError()) {
        std::printf("SKIP no DX12 device: %s\n", engine->DeviceError()->Describe().c_str());
        return nullptr;
    }
    return engine;
}

Result<Raster> Run(Engine& engine, const CornerBuffers& corners, UvRasterRequest request) {
    auto job = std::make_shared<const Job>(Job{&corners, std::move(request)});
    auto future = engine.Submit(job, [](EngineContext& context, const Job& j) {
        return RasterAndRead(context, j);
    });
    if (future.wait_for(std::chrono::seconds(300)) != std::future_status::ready) {
        return Fail(ErrorCode::RequestFailed, std::nullopt, "no result within 300 s");
    }
    return future.get();
}

UvRasterRequest Request(uint32_t width, uint32_t height, std::vector<uint32_t> materials = {}) {
    UvRasterRequest request;
    request.width = width;
    request.height = height;
    request.materials = std::move(materials);
    return request;
}

// ── Reference (double precision) ─────────────────────────────────────────────

/// A triangle in texel space (x = u W, y = v H) with its oriented edge functions.
struct RefTriangle {
    Vec2 p[3];
    double orientation = 0;  // sign of the doubled area

    explicit RefTriangle(const Mesh& mesh, size_t t, uint32_t w, uint32_t h) {
        for (size_t k = 0; k < 3; ++k) {
            const Vec2 uv = mesh.Uv(t, k);
            p[k] = {uv.x * w, uv.y * h};
        }
        const double area = Edge(p[0], p[1], p[2]);
        orientation = area > 0 ? 1.0 : (area < 0 ? -1.0 : 0.0);
    }
    static double Edge(Vec2 a, Vec2 b, Vec2 q) {
        return (b.x - a.x) * (q.y - a.y) - (b.y - a.y) * (q.x - a.x);
    }
    /// Signed distance of q from edge i (opposite vertex i), positive inside.
    [[nodiscard]] double Distance(size_t i, Vec2 q) const {
        const Vec2 a = p[(i + 1) % 3], b = p[(i + 2) % 3];
        const double length = std::hypot(b.x - a.x, b.y - a.y);
        return orientation * Edge(a, b, q) / length;
    }
    /// The centre lies inside with every edge at least `margin` texels away (negative: outside by
    /// at most -margin).
    [[nodiscard]] bool Contains(Vec2 q, double margin) const {
        if (orientation == 0) return false;
        for (size_t i = 0; i < 3; ++i) {
            if (Distance(i, q) < margin) return false;
        }
        return true;
    }
    /// The interior overlaps the square [x0, x1] x [y0, y1] (positive area).
    [[nodiscard]] bool Overlaps(double x0, double y0, double x1, double y1) const {
        if (orientation == 0) return false;
        const double minX = std::min({p[0].x, p[1].x, p[2].x});
        const double maxX = std::max({p[0].x, p[1].x, p[2].x});
        const double minY = std::min({p[0].y, p[1].y, p[2].y});
        const double maxY = std::max({p[0].y, p[1].y, p[2].y});
        if (!(minX < x1 && maxX > x0 && minY < y1 && maxY > y0)) return false;
        const Vec2 corners[4] = {{x0, y0}, {x1, y0}, {x0, y1}, {x1, y1}};
        for (size_t i = 0; i < 3; ++i) {
            const double apex = Distance(i, p[i]);
            double lo = INFINITY, hi = -INFINITY;
            for (const Vec2& c : corners) {
                const double d = Distance(i, c);
                lo = std::min(lo, d);
                hi = std::max(hi, d);
            }
            if (!(hi > 0 && lo < apex)) return false;
        }
        return true;
    }
};

/// Texel centre of (col, row) in texel space.
Vec2 Centre(uint32_t col, uint32_t row, uint32_t height) {
    return {col + 0.5, height - row - 0.5};
}

struct CoverageReport {
    size_t centre = 0;          ///< GPU texel-centre covered texels
    size_t conservative = 0;    ///< GPU conservative texels
    size_t missedTouched = 0;   ///< robustly touched texels missing from the mask
    size_t extraMasked = 0;     ///< masked texels no triangle comes near
    size_t centreNotMasked = 0; ///< centre-covered texels missing from the mask
    size_t missedCentres = 0;   ///< robustly covered centres the GPU left uncovered
    size_t extraCentres = 0;    ///< GPU-covered centres no triangle comes near
    size_t wrongTriangle = 0;   ///< covered centres whose triangle does not contain them
    size_t referenceCentre = 0; ///< robustly covered centres
    size_t referenceTouched = 0;
    std::string first;
};

/// Compares the GPU coverage with the double-precision reference.
CoverageReport CompareCoverage(const Mesh& mesh, const Raster& raster) {
    const uint32_t w = raster.width, h = raster.height;
    std::vector<RefTriangle> tris;
    for (size_t t = 0; t < mesh.TriangleCount(); ++t) tris.emplace_back(mesh, t, w, h);
    std::vector<uint8_t> robustTouch(size_t{w} * h, 0), looseTouch(size_t{w} * h, 0);
    std::vector<uint8_t> robustCentre(size_t{w} * h, 0), looseCentre(size_t{w} * h, 0);
    for (const RefTriangle& tri : tris) {
        const double minX = std::min({tri.p[0].x, tri.p[1].x, tri.p[2].x});
        const double maxX = std::max({tri.p[0].x, tri.p[1].x, tri.p[2].x});
        const double minY = std::min({tri.p[0].y, tri.p[1].y, tri.p[2].y});
        const double maxY = std::max({tri.p[0].y, tri.p[1].y, tri.p[2].y});
        const int x0 = std::max(0, static_cast<int>(std::floor(minX - 1)));
        const int x1 = std::min(static_cast<int>(w), static_cast<int>(std::ceil(maxX + 1)));
        const int y0 = std::max(0, static_cast<int>(std::floor(minY - 1)));
        const int y1 = std::min(static_cast<int>(h), static_cast<int>(std::ceil(maxY + 1)));
        for (int y = y0; y < y1; ++y) {
            for (int x = x0; x < x1; ++x) {
                const uint32_t row = h - 1 - static_cast<uint32_t>(y);
                const size_t i = size_t{row} * w + static_cast<uint32_t>(x);
                if (tri.Overlaps(x + kEps, y + kEps, x + 1 - kEps, y + 1 - kEps)) robustTouch[i] = 1;
                if (tri.Overlaps(x - kEps, y - kEps, x + 1 + kEps, y + 1 + kEps)) looseTouch[i] = 1;
                const Vec2 c{x + 0.5, y + 0.5};
                if (tri.Contains(c, kEps)) robustCentre[i] = 1;
                if (tri.Contains(c, -kEps)) looseCentre[i] = 1;
            }
        }
    }
    CoverageReport r;
    const auto note = [&](const char* what, uint32_t x, uint32_t y) {
        if (r.first.empty()) {
            r.first = std::string(what) + " at (" + std::to_string(x) + ", " + std::to_string(y) + ")";
        }
    };
    for (uint32_t y = 0; y < h; ++y) {
        for (uint32_t x = 0; x < w; ++x) {
            const size_t i = size_t{y} * w + x;
            const bool masked = raster.Masked(x, y);
            const uint32_t triangle = raster.Uint(raster.Triangle(), x, y);
            const bool centre = triangle != kUvRasterNoId;
            r.centre += centre;
            r.conservative += masked;
            r.referenceCentre += robustCentre[i];
            r.referenceTouched += robustTouch[i];
            if (robustTouch[i] && !masked) ++r.missedTouched, note("touched texel not masked", x, y);
            if (masked && !looseTouch[i]) ++r.extraMasked, note("masked texel not touched", x, y);
            if (centre && !masked) ++r.centreNotMasked, note("centre not masked", x, y);
            if (robustCentre[i] && !centre) ++r.missedCentres, note("centre missed", x, y);
            if (centre && !looseCentre[i]) ++r.extraCentres, note("extra centre", x, y);
            if (centre && (triangle >= tris.size() ||
                           !tris[triangle].Contains(Centre(x, y, h), -kEps))) {
                ++r.wrongTriangle, note("wrong triangle", x, y);
            }
        }
    }
    return r;
}

void CheckCoverage(const std::string& name, const Mesh& mesh, const Raster& raster) {
    const CoverageReport r = CompareCoverage(mesh, raster);
    Info(name + ": " + std::to_string(r.centre) + " texel-centre texels (reference " +
         std::to_string(r.referenceCentre) + " robust), " + std::to_string(r.conservative) +
         " conservative texels (reference " + std::to_string(r.referenceTouched) + " robust)");
    Check(r.missedTouched == 0,
          name + ": the conservative mask covers every texel a triangle touches",
          std::to_string(r.missedTouched) + " missed; " + r.first);
    Check(r.extraMasked == 0, name + ": the conservative mask marks no untouched texel",
          std::to_string(r.extraMasked) + " extra; " + r.first);
    Check(r.centreNotMasked == 0, name + ": the conservative mask contains the texel-centre coverage",
          std::to_string(r.centreNotMasked) + " not contained; " + r.first);
    Check(r.missedCentres == 0 && r.extraCentres == 0 && r.wrongTriangle == 0,
          name + ": texel-centre coverage equals the reference",
          std::to_string(r.missedCentres) + " missed, " + std::to_string(r.extraCentres) +
              " extra, " + std::to_string(r.wrongTriangle) + " wrong triangle; " + r.first);
}

bool SameBytes(const Raster& a, const Raster& b, std::string& detail) {
    for (size_t i = 0; i < a.images.size(); ++i) {
        if (a.images[i].texels != b.images[i].texels) {
            detail = std::string(kBufferNames[i]) + " differs";
            return false;
        }
    }
    return true;
}

// ── Cases ────────────────────────────────────────────────────────────────────

int RunValidate() {
    const Mesh mesh = PlaneMesh(2);
    const auto rejects = [&](const char* name, auto mutate, std::string_view expected) {
        Layout layout = Separate(mesh);
        UvRasterRequest request = Request(64, 64);
        mutate(layout.corners, request);
        Result<void> result = ValidateUvRaster(layout.corners, request, Backend::Dx12);
        const bool ok = !result && result.error().code == ErrorCode::RequestFailed &&
                        result.error().reason.find(expected) != std::string::npos;
        Check(ok, name, Describe(result));
    };
    {
        const Layout layout = Separate(mesh);
        Result<void> separate = ValidateUvRaster(layout.corners, Request(64, 64), Backend::Dx12);
        const Layout inter = Interleaved(mesh);
        Result<void> interleaved = ValidateUvRaster(inter.corners, Request(64, 64), Backend::Dx12);
        Check(separate && interleaved, "separate and interleaved layouts are accepted",
              Describe(separate) + "; " + Describe(interleaved));
    }
    rejects("a stride smaller than the attribute is rejected",
            [](CornerBuffers& c, UvRasterRequest&) { c.position.stride = 8; }, "stride 8");
    rejects("a zero stride is rejected (no default stride)",
            [](CornerBuffers& c, UvRasterRequest&) { c.uv0.stride = 0; }, "stride 0");
    rejects("an unaligned offset is rejected",
            [](CornerBuffers& c, UvRasterRequest&) { c.normal.offset = 2; }, "multiples of 4");
    rejects("an attribute past the end of its buffer is rejected",
            [](CornerBuffers& c, UvRasterRequest&) { c.tangent.offset = 4; }, "corners end at byte");
    rejects("an unknown buffer index is rejected",
            [](CornerBuffers& c, UvRasterRequest&) { c.islandId.buffer = 9; }, "names buffer 9");
    rejects("a corner id out of range is rejected",
            [&](CornerBuffers& c, UvRasterRequest&) { c.cornerCount = 3; }, "names corner");
    rejects("a size of 0 is rejected",
            [](CornerBuffers&, UvRasterRequest& r) { r.width = 0; }, "size 0x64");
    rejects("UV tiles other than 1001 are rejected in v1",
            [](CornerBuffers&, UvRasterRequest& r) { r.uvTile = 1002; }, "UV tile 1002");
    return Finish();
}

int RunPlane(const fs::path& dir) {
    const std::unique_ptr<Engine> engine = MakeEngine(dir);
    if (!engine) return kExitSkip;
    constexpr uint32_t size = 256;
    const Mesh mesh = PlaneMesh(5);
    const Layout inter = Interleaved(mesh);
    const Layout separate = Separate(mesh);
    Result<Raster> a = Run(*engine, inter.corners, Request(size, size));
    Result<Raster> b = Run(*engine, separate.corners, Request(size, size));
    Check(a.has_value(), "the plane rasterises (interleaved corners, stride 64)", Describe(a));
    Check(b.has_value(), "the plane rasterises (separate corner streams)", Describe(b));
    if (!a || !b) return Finish();
    std::string detail;
    Check(SameBytes(*a, *b, detail),
          "interleaved and separate corner layouts give byte-identical buffers", detail);
    Check(a->uvTile == kUvTile1001, "the buffers are indexed by UV tile 1001",
          std::to_string(a->uvTile));
    const std::array<std::pair<const ReadbackImage*, uz::RHIFormat>, 8> formats = {{
        {&a->Position(), uz::RHIFormat::RGBA32Float},
        {&a->Normal(), uz::RHIFormat::RGBA32Float},
        {&a->Tangent(), uz::RHIFormat::RGBA32Float},
        {&a->Bitangent(), uz::RHIFormat::RGBA32Float},
        {&a->Island(), uz::RHIFormat::R32Uint},
        {&a->Material(), uz::RHIFormat::R32Uint},
        {&a->Triangle(), uz::RHIFormat::R32Uint},
        {&a->Mask(), uz::RHIFormat::R8Unorm},
    }};
    Check(std::all_of(formats.begin(), formats.end(),
                      [](const auto& f) { return f.first->format == f.second; }),
          "position, normal and tangent frame are RGBA32F, ids R32Uint");

    size_t uncovered = 0, unmasked = 0, positionErrors = 0, frameErrors = 0, idErrors = 0;
    double maxError = 0;
    std::string first;
    for (uint32_t y = 0; y < size; ++y) {
        for (uint32_t x = 0; x < size; ++x) {
            const double u = (x + 0.5) / size, v = 1.0 - (y + 0.5) / size;
            uncovered += a->Uint(a->Triangle(), x, y) == kUvRasterNoId;
            unmasked += !a->Masked(x, y);
            const auto p = a->Float4(a->Position(), x, y);
            const Vec3 want = PlanePosition(u, v);
            const double error = std::max({std::abs(p[0] - want.x), std::abs(p[1] - want.y),
                                           std::abs(p[2] - want.z), std::abs(p[3] - 1.0)});
            maxError = std::max(maxError, error);
            if (error > 1e-6) {
                if (positionErrors++ == 0) {
                    first = "(" + std::to_string(x) + ", " + std::to_string(y) + "): " +
                            std::to_string(p[0]) + " " + std::to_string(p[1]) + " " +
                            std::to_string(p[2]);
                }
            }
            const auto n = a->Float4(a->Normal(), x, y);
            const auto t = a->Float4(a->Tangent(), x, y);
            const auto bt = a->Float4(a->Bitangent(), x, y);
            // cross(+Y, +X) = -Z, times sign -1: +Z.
            const double frame = std::max(
                {std::abs(n[0]), std::abs(n[1] - 1), std::abs(n[2]), std::abs(n[3]),
                 std::abs(t[0] - 1), std::abs(t[1]), std::abs(t[2]), std::abs(t[3] + 1),
                 std::abs(bt[0]), std::abs(bt[1]), std::abs(bt[2] - 1), std::abs(bt[3])});
            frameErrors += frame > 1e-6;
            idErrors += a->Uint(a->Island(), x, y) != 9 || a->Uint(a->Material(), x, y) != 4;
        }
    }
    Check(uncovered == 0, "every texel of the 256 x 256 plane is covered at its centre",
          std::to_string(uncovered) + " uncovered");
    Check(unmasked == 0, "the conservative mask covers the whole plane",
          std::to_string(unmasked) + " unmasked");
    Info("max |position - analytic| " + std::to_string(maxError));
    Check(positionErrors == 0,
          "interpolated positions equal the analytic values at texel centres (|error| <= 1e-6)",
          std::to_string(positionErrors) + " texels; first " + first);
    Check(frameErrors == 0, "normal, tangent (with sign) and bitangent equal the analytic frame",
          std::to_string(frameErrors) + " texels");
    Check(idErrors == 0, "island and material ids equal the plane's", std::to_string(idErrors));
    CheckCoverage("plane", mesh, *a);
    return Finish();
}

int RunThin(const fs::path& dir) {
    const std::unique_ptr<Engine> engine = MakeEngine(dir);
    if (!engine) return kExitSkip;
    const Mesh mesh = ThinMesh();
    const Layout layout = Separate(mesh);
    Result<Raster> raster = Run(*engine, layout.corners, Request(256, 256));
    Check(raster.has_value(), "the sliver rasterises", Describe(raster));
    if (!raster) return Finish();
    CheckCoverage("sliver", mesh, *raster);
    const CoverageReport r = CompareCoverage(mesh, *raster);
    Check(r.conservative > 200 && r.conservative > 10 * r.centre,
          "the conservative mask marks the sliver's texels although few or no centres are covered",
          std::to_string(r.conservative) + " masked, " + std::to_string(r.centre) + " centres");
    // The sub-texel triangle covers no texel centre, yet its texel is marked.
    const uint32_t x = static_cast<uint32_t>(0.5002 * 256);
    const uint32_t y = 255 - static_cast<uint32_t>(0.2002 * 256);
    Check(raster->Masked(x, y) && raster->Uint(raster->Triangle(), x, y) == kUvRasterNoId,
          "a triangle inside one texel marks it in the mask with an empty texel centre");
    return Finish();
}

int RunCoverage(const fs::path& dir) {
    const std::unique_ptr<Engine> engine = MakeEngine(dir);
    if (!engine) return kExitSkip;
    const std::array<std::pair<const char*, Mesh>, 2> meshes = {
        {{"sphere", SphereMesh(24, 12)}, {"bevelled cube", BevelledCubeMesh()}}};
    for (const auto& [name, mesh] : meshes) {
        const Layout layout = Interleaved(mesh);
        for (const auto [w, h] : {std::pair<uint32_t, uint32_t>{512, 512}, {300, 200}}) {
            Result<Raster> raster = Run(*engine, layout.corners, Request(w, h));
            const std::string label =
                std::string(name) + " " + std::to_string(w) + "x" + std::to_string(h);
            Check(raster.has_value(), label + ": rasterises", Describe(raster));
            if (raster) CheckCoverage(label, mesh, *raster);
        }
    }
    return Finish();
}

int RunIds(const fs::path& dir) {
    const std::unique_ptr<Engine> engine = MakeEngine(dir);
    if (!engine) return kExitSkip;
    constexpr uint32_t size = 128;
    const Mesh mesh = TwoIslandMesh();
    const Layout layout = Interleaved(mesh);
    Result<Raster> all = Run(*engine, layout.corners, Request(size, size));
    Result<Raster> set5 = Run(*engine, layout.corners, Request(size, size, {5}));
    Check(all.has_value() && set5.has_value(), "the two-island mesh rasterises",
          Describe(all) + "; " + Describe(set5));
    if (!all || !set5) return Finish();
    std::vector<RefTriangle> tris;
    for (size_t t = 0; t < mesh.TriangleCount(); ++t) tris.emplace_back(mesh, t, size, size);
    size_t wrong = 0, wrongSet = 0, checked = 0;
    std::array<size_t, 2> islandTexels{};
    std::string first;
    for (uint32_t y = 0; y < size; ++y) {
        for (uint32_t x = 0; x < size; ++x) {
            const Vec2 c = Centre(x, y, size);
            std::optional<size_t> inside;
            bool ambiguous = false;
            for (size_t t = 0; t < tris.size(); ++t) {
                if (tris[t].Contains(c, kEps)) inside = t;
                else if (tris[t].Contains(c, -kEps)) ambiguous = true;
            }
            if (ambiguous) continue;
            ++checked;
            const uint32_t material = all->Uint(all->Material(), x, y);
            const uint32_t island = all->Uint(all->Island(), x, y);
            uint32_t wantMaterial = kUvRasterNoId, wantIsland = kUvRasterNoId;
            if (inside) {
                const Corner& corner = mesh.corners[mesh.triangles[*inside * 3]];
                wantMaterial = corner.material;
                wantIsland = corner.island;
                ++islandTexels[wantIsland];
            }
            if (material != wantMaterial || island != wantIsland) {
                if (wrong++ == 0) {
                    first = "(" + std::to_string(x) + ", " + std::to_string(y) + "): material " +
                            std::to_string(material) + " island " + std::to_string(island);
                }
            }
            const bool inSet = inside && wantMaterial == 5;
            const uint32_t setTriangle = set5->Uint(set5->Triangle(), x, y);
            if (inSet ? setTriangle != *inside || set5->Uint(set5->Material(), x, y) != 5
                      : setTriangle != kUvRasterNoId) {
                ++wrongSet;
            }
        }
    }
    Info("checked " + std::to_string(checked) + " unambiguous texels; island 0: " +
         std::to_string(islandTexels[0]) + ", island 1: " + std::to_string(islandTexels[1]));
    Check(islandTexels[0] > 1000 && islandTexels[1] > 1000, "both islands cover texels");
    Check(wrong == 0, "material and island ids are correct per texel",
          std::to_string(wrong) + " wrong; first " + first);
    Check(wrongSet == 0,
          "a texture-set filter rasterises only its material's triangles, keeping their indices",
          std::to_string(wrongSet) + " wrong");
    CheckCoverage("two islands", mesh, *all);
    return Finish();
}

int RunRepeat(const fs::path& dir) {
    const std::unique_ptr<Engine> engine = MakeEngine(dir);
    if (!engine) return kExitSkip;
    const Mesh mesh = BevelledCubeMesh();
    const Layout layout = Interleaved(mesh);
    Result<Raster> a = Run(*engine, layout.corners, Request(1024, 1024));
    Result<Raster> b = Run(*engine, layout.corners, Request(1024, 1024));
    Check(a.has_value() && b.has_value(), "the bevelled cube rasterises twice",
          Describe(a) + "; " + Describe(b));
    if (!a || !b) return Finish();
    std::string detail;
    Check(SameBytes(*a, *b, detail), "two runs in one process give byte-identical buffers", detail);
    for (size_t i = 0; i < a->images.size(); ++i) {
        char hex[24];
        std::snprintf(hex, sizeof(hex), "%016llx",
                      static_cast<unsigned long long>(Xxh64(a->images[i].texels)));
        std::printf("HASH %s %s\n", kBufferNames[i], hex);
    }
    std::fflush(stdout);
    return Finish();
}

// ── Tier 0 corpus meshes (phase1.4_render-core-layer) ────────────────────────

/// One OBJ of the Tier 0 corpus (`v`, `vt`, `vn`, `usemtl`, `f v/vt/vn` with positive indices),
/// fan-triangulated with one corner per face corner. The material id is the `usemtl` index in
/// order of appearance; island ids and tangents are not in the file (island 0, tangent +X).
std::optional<Mesh> LoadObj(const fs::path& path, std::string& error) {
    std::ifstream file(path);
    if (!file) {
        error = "cannot open " + path.string();
        return std::nullopt;
    }
    std::vector<Vec3> positions, normals;
    std::vector<Vec2> uvs;
    std::vector<std::string> materials;
    uint32_t material = 0;
    Mesh mesh;
    std::string line;
    size_t lineNumber = 0;
    while (std::getline(file, line)) {
        ++lineNumber;
        std::istringstream in(line);
        std::string tag;
        in >> tag;
        if (tag == "v" || tag == "vn") {
            Vec3 v{};
            in >> v.x >> v.y >> v.z;
            (tag == "v" ? positions : normals).push_back(v);
        } else if (tag == "vt") {
            Vec2 uv{};
            in >> uv.x >> uv.y;
            uvs.push_back(uv);
        } else if (tag == "usemtl") {
            std::string name;
            in >> name;
            const auto it = std::find(materials.begin(), materials.end(), name);
            material = static_cast<uint32_t>(it - materials.begin());
            if (it == materials.end()) materials.push_back(name);
        } else if (tag == "f") {
            std::vector<uint32_t> ids;
            std::string token;
            while (in >> token) {
                unsigned v = 0, t = 0, n = 0;
                if (std::sscanf(token.c_str(), "%u/%u/%u", &v, &t, &n) != 3 || v == 0 ||
                    t == 0 || n == 0 || v > positions.size() || t > uvs.size() ||
                    n > normals.size()) {
                    error = path.filename().string() + ":" + std::to_string(lineNumber) +
                            ": unsupported face corner " + token;
                    return std::nullopt;
                }
                ids.push_back(mesh.Add(MakeCorner(positions[v - 1], normals[n - 1], uvs[t - 1],
                                                  {1, 0, 0}, 1.0f, material, 0)));
            }
            for (size_t k = 1; k + 1 < ids.size(); ++k) mesh.Triangle(ids[0], ids[k], ids[k + 1]);
        }
    }
    if (mesh.TriangleCount() == 0) {
        error = path.filename().string() + " has no faces";
        return std::nullopt;
    }
    return mesh;
}

/// The plane, sphere and bevelled cube of the Tier 0 corpus (`parity/TIER0-SEMANTICS.md` §2),
/// read from `<work-dir>/tier0-meshes/` where the driving test copies them: the conservative mask
/// and texel-centre coverage equal the reference at a square and a non-square size; the plane,
/// mapped to the whole 0-1 square, covers every texel centre.
int RunTier0Meshes(const fs::path& dir) {
    const std::unique_ptr<Engine> engine = MakeEngine(dir);
    if (!engine) return kExitSkip;
    for (const char* name : {"plane", "sphere", "bevelled-cube"}) {
        std::string error;
        const std::optional<Mesh> mesh = LoadObj(dir / "tier0-meshes" / (std::string(name) + ".obj"),
                                                 error);
        Check(mesh.has_value(), std::string(name) + ".obj loads", error);
        if (!mesh) continue;
        Info(std::string(name) + ".obj: " + std::to_string(mesh->TriangleCount()) + " triangles");
        const Layout layout = Interleaved(*mesh);
        for (const auto [w, h] : {std::pair<uint32_t, uint32_t>{512, 512}, {300, 200}}) {
            Result<Raster> raster = Run(*engine, layout.corners, Request(w, h));
            const std::string label =
                std::string(name) + " " + std::to_string(w) + "x" + std::to_string(h);
            Check(raster.has_value(), label + ": rasterises", Describe(raster));
            if (!raster) continue;
            CheckCoverage(label, *mesh, *raster);
            if (std::string_view(name) == "plane") {
                size_t uncovered = 0;
                for (uint32_t y = 0; y < h; ++y) {
                    for (uint32_t x = 0; x < w; ++x) {
                        uncovered += raster->Uint(raster->Triangle(), x, y) == kUvRasterNoId;
                    }
                }
                Check(uncovered == 0, label + ": every texel centre is covered",
                      std::to_string(uncovered) + " uncovered");
            }
        }
    }
    return Finish();
}

// ── Vulkan (phase3.1_vulkan-compute-parity items 2.5, 3.2) ───────────────────

/// The fixtures of the cross-backend cases: the plane, the sphere and the bevelled cube.
std::vector<std::pair<std::string, Mesh>> ParityMeshes() {
    std::vector<std::pair<std::string, Mesh>> meshes;
    meshes.emplace_back("plane", PlaneMesh(5));
    meshes.emplace_back("sphere", SphereMesh(24, 12));
    meshes.emplace_back("bevelled cube", BevelledCubeMesh());
    return meshes;
}

/// The first differing byte of two buffers, or empty.
std::string FirstDifference(const std::vector<std::byte>& a, const std::vector<std::byte>& b) {
    if (a.size() != b.size()) {
        return std::to_string(a.size()) + " bytes vs " + std::to_string(b.size());
    }
    size_t count = 0;
    size_t first = 0;
    for (size_t i = 0; i < a.size(); ++i) {
        if (a[i] == b[i]) continue;
        if (count++ == 0) first = i;
    }
    if (count == 0) return {};
    return std::to_string(count) + " bytes differ, the first at byte " + std::to_string(first);
}

/// Each fixture rasterised at 512 x 512 and 300 x 200 on a DX12 engine and on an engine over the
/// qualified Vulkan device: every buffer byte for byte equal, and the Vulkan coverage checked
/// against the double-precision reference as the DX12 cases check theirs.
int RunVulkanRaster(const fs::path& dir) {
    if (VulkanDeviceMissing()) return kExitSkip;
    const std::unique_ptr<Engine> dx12 = MakeEngine(dir / "dx12");
    if (!dx12) return kExitSkip;
    Engine vulkan(VulkanTestEngineOptions(dir / "vulkan"));
    Check(!vulkan.DeviceError(), "the Vulkan engine runs on the qualified device",
          vulkan.DeviceError() ? vulkan.DeviceError()->Describe() : "");
    if (vulkan.DeviceError()) return Finish();
    for (const auto& [name, mesh] : ParityMeshes()) {
        const Layout layout = Interleaved(mesh);
        for (const auto [w, h] : {std::pair<uint32_t, uint32_t>{512, 512}, {300, 200}}) {
            const std::string label = name + " " + std::to_string(w) + "x" + std::to_string(h);
            Result<Raster> a = Run(*dx12, layout.corners, Request(w, h));
            Result<Raster> b = Run(vulkan, layout.corners, Request(w, h));
            Check(a.has_value() && b.has_value(), label + ": rasterises on DX12 and on Vulkan",
                  Describe(a) + "; " + Describe(b));
            if (!a || !b) continue;
            uint64_t bytes = 0;
            for (size_t i = 0; i < a->images.size(); ++i) {
                const std::string difference =
                    FirstDifference(a->images[i].texels, b->images[i].texels);
                Check(difference.empty(),
                      label + ": " + kBufferNames[i] + " on Vulkan equals DX12 byte for byte",
                      difference);
                bytes += a->images[i].texels.size();
            }
            CheckCoverage(label + " (Vulkan)", mesh, *b);
            size_t covered = 0;
            for (uint32_t y = 0; y < h; ++y) {
                for (uint32_t x = 0; x < w; ++x) {
                    covered += b->Uint(b->Triangle(), x, y) != kUvRasterNoId ? 1 : 0;
                }
            }
            char hash[24];
            std::snprintf(hash, sizeof(hash), "%016llx",
                          static_cast<unsigned long long>(Xxh64(b->Position().texels)));
            Info(label + ": " + std::to_string(bytes) + " bytes compared over 8 buffers, " +
                 std::to_string(covered) + " texel centres covered, position XXH64 " + hash);
        }
    }
    return Finish();
}

}  // namespace

std::vector<std::unique_ptr<UvRasterFixture>> SyntheticUvRasterFixtures() {
    std::vector<std::unique_ptr<UvRasterFixture>> fixtures;
    for (auto& [name, mesh] : ParityMeshes()) {
        auto fixture = std::make_unique<UvRasterFixture>();
        fixture->name = name;
        Layout layout = Interleaved(mesh);
        fixture->storage = std::move(layout.storage);
        fixture->triangles = mesh.triangles;
        fixture->corners = layout.corners;
        fixture->corners.buffers.clear();
        for (const std::vector<std::byte>& bytes : fixture->storage) {
            fixture->corners.buffers.emplace_back(bytes);
        }
        fixture->corners.triangles = fixture->triangles;
        fixtures.push_back(std::move(fixture));
    }
    return fixtures;
}

EngineOptions VulkanTestEngineOptions(const fs::path& dir) {
    EngineOptions options;
    options.kernelCacheRoot = dir / "kernel-cache";
    options.device.backend = Backend::Vulkan;
    options.createDevice = []() -> Result<std::unique_ptr<IDevice>> {
        const VulkanSurvey survey = SurveyVulkan();
        const VulkanQualification qualification = QualifyVulkan(survey, 0);
        Result<std::unique_ptr<VulkanDevice>> device =
            CreateQualifiedVulkanDevice(survey, qualification, {});
        if (!device) return Unexpected(device.error());
        return std::unique_ptr<IDevice>(std::move(*device));
    };
    return options;
}

bool VulkanDeviceMissing() {
    const VulkanSurvey survey = SurveyVulkan();
    if (!survey.devices.empty()) return false;
    std::printf("SKIP no Vulkan physical device: %s%s\n", survey.instance.loaderError.c_str(),
                survey.instance.instanceError.c_str());
    return true;
}

/// Runs a `uv-raster-*` case; -1 when `mode` is not one.
int RunUvRasterCase(std::string_view mode, const std::filesystem::path& dir) {
    if (mode == "uv-raster-validate") return RunValidate();
    if (mode == "uv-raster-plane") return RunPlane(dir);
    if (mode == "uv-raster-thin") return RunThin(dir);
    if (mode == "uv-raster-coverage") return RunCoverage(dir);
    if (mode == "uv-raster-ids") return RunIds(dir);
    if (mode == "uv-raster-repeat") return RunRepeat(dir);
    if (mode == "uv-raster-tier0") return RunTier0Meshes(dir);
    if (mode == "vulkan-uv-raster") return RunVulkanRaster(dir);
    return -1;
}
