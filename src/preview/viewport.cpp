#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "preview/viewport.h"

#include "render/image_pass.h"
#include "render/kernel_cache.h"
#include "render/texture_readback.h"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstring>
#include <deque>
#include <limits>
#include <numbers>
#include <span>

#include <dxgi1_6.h>
#include <wrl/client.h>

namespace uzp::preview {

namespace {

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc23-extensions"
constexpr char kViewportHlsl[] = {
#embed "shaders/viewport.hlsl"  // painter_viewport kernel
};
#pragma clang diagnostic pop

using render::ErrorCode;
using render::Result;
using render::Unexpected;
using Vec = std::array<double, 3>;

constexpr uint32_t kTile = 16;
constexpr uint32_t kTriangleWords = 40;
constexpr uint32_t kMaterialWords = 20;
constexpr uint32_t kNoMap = 0xFFFFFFFFu;
/// The lighting buffer's header: 27 SH words, 3 words per radiance level, the albedo table offset.
constexpr uint32_t kLightingHeaderWords = 27 + 3 * kRadianceLevels + 1;

const render::KernelSource& ViewportKernel() {
    static const render::KernelSource source = render::image_pass_detail::Kernel(
        "painter_viewport", std::string_view(kViewportHlsl, sizeof(kViewportHlsl)), "main");
    return source;
}

Vec Sub(const Vec& a, const Vec& b) { return {a[0] - b[0], a[1] - b[1], a[2] - b[2]}; }
double Dot(const Vec& a, const Vec& b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
Vec Cross(const Vec& a, const Vec& b) {
    return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}
Vec Normalised(const Vec& a) {
    const double length = std::sqrt(Dot(a, a));
    return {a[0] / length, a[1] / length, a[2] / length};
}

constexpr double kDegree = std::numbers::pi / 180.0;

/// The world-space data of one corner: position, normal, uv, tangent and sign.
struct WorldCorner {
    Vec position;
    Vec normal;
    float u = 0.0f;
    float v = 0.0f;
    Vec tangent;
    float sign = 1.0f;
};

/// `m` (column-major, object -> scene) applied to a point, a direction and a normal.
struct Transform {
    mesh::Matrix4 m;
    double scale = 1.0;
    std::array<double, 9> normalMatrix{};  // inverse transpose of the upper 3x3, row-major

    explicit Transform(const mesh::Matrix4& matrix, double unitScale) : m(matrix), scale(unitScale) {
        const auto a = [&](int r, int c) { return m[static_cast<size_t>(c * 4 + r)]; };
        const double c00 = a(1, 1) * a(2, 2) - a(1, 2) * a(2, 1);
        const double c01 = a(1, 2) * a(2, 0) - a(1, 0) * a(2, 2);
        const double c02 = a(1, 0) * a(2, 1) - a(1, 1) * a(2, 0);
        const double c10 = a(0, 2) * a(2, 1) - a(0, 1) * a(2, 2);
        const double c11 = a(0, 0) * a(2, 2) - a(0, 2) * a(2, 0);
        const double c12 = a(0, 1) * a(2, 0) - a(0, 0) * a(2, 1);
        const double c20 = a(0, 1) * a(1, 2) - a(0, 2) * a(1, 1);
        const double c21 = a(0, 2) * a(1, 0) - a(0, 0) * a(1, 2);
        const double c22 = a(0, 0) * a(1, 1) - a(0, 1) * a(1, 0);
        // The inverse transpose is the cofactor matrix divided by the determinant; the sign of
        // the determinant is kept so that a mirroring transform flips the normals.
        const double det = a(0, 0) * c00 + a(0, 1) * c01 + a(0, 2) * c02;
        const double inv = det == 0.0 ? 0.0 : 1.0 / det;
        normalMatrix = {c00 * inv, c01 * inv, c02 * inv, c10 * inv, c11 * inv, c12 * inv, c20 * inv, c21 * inv, c22 * inv};
    }
    Vec Point(const mesh::Float3& p) const {
        const auto a = [&](int r, int c) { return m[static_cast<size_t>(c * 4 + r)]; };
        return {(a(0, 0) * p.x + a(0, 1) * p.y + a(0, 2) * p.z + a(0, 3)) * scale,
                (a(1, 0) * p.x + a(1, 1) * p.y + a(1, 2) * p.z + a(1, 3)) * scale,
                (a(2, 0) * p.x + a(2, 1) * p.y + a(2, 2) * p.z + a(2, 3)) * scale};
    }
    Vec Direction(double x, double y, double z) const {
        const auto a = [&](int r, int c) { return m[static_cast<size_t>(c * 4 + r)]; };
        return {a(0, 0) * x + a(0, 1) * y + a(0, 2) * z, a(1, 0) * x + a(1, 1) * y + a(1, 2) * z,
                a(2, 0) * x + a(2, 1) * y + a(2, 2) * z};
    }
    Vec Normal(const mesh::Float3& n) const {
        const auto& k = normalMatrix;
        return {k[0] * n.x + k[1] * n.y + k[2] * n.z, k[3] * n.x + k[4] * n.y + k[5] * n.z,
                k[6] * n.x + k[7] * n.y + k[8] * n.z};
    }
};

double UnitScale(const mesh::TexturingMesh& mesh) {
    return mesh.units.scale_to_internal > 0.0 ? mesh.units.scale_to_internal : 1.0;
}

void PushFloat(std::vector<uint32_t>& words, double value) {
    words.push_back(std::bit_cast<uint32_t>(static_cast<float>(value)));
}

std::span<const std::byte> Bytes(const std::vector<uint32_t>& words) {
    return std::as_bytes(std::span<const uint32_t>(words));
}

Unexpected Invalid(render::Backend backend, std::string reason) {
    return render::Fail(ErrorCode::RequestFailed, backend, "painter_viewport: " + std::move(reason));
}

Result<void> CheckMap(const std::optional<MaterialMap>& map, uint32_t components, const char* name, size_t material,
                      render::Backend backend) {
    if (!map) return {};
    if (map->components != components || map->width == 0 || map->height == 0 ||
        map->values.size() != size_t{map->width} * map->height * components) {
        return Invalid(backend, "material " + std::to_string(material) + ": the " + name + " map is not a " +
                                    std::to_string(components) + "-component raster of its size");
    }
    return {};
}

/// Upload and default-heap buffer pairs of one render, released with it unless abandoned.
class Buffers {
public:
    explicit Buffers(render::IDevice& device) : m_device(device) {}
    ~Buffers() {
        for (const Pair& pair : m_pairs) {
            m_device.DestroyBuffer(pair.upload);
            m_device.DestroyBuffer(pair.gpu);
        }
    }
    Buffers(const Buffers&) = delete;
    Buffers& operator=(const Buffers&) = delete;

    /// A raw shader-readable buffer holding `bytes` (zero-padded to 16 bytes); its SRV index.
    Result<uint32_t> Raw(std::span<const std::byte> bytes, const char* name) {
        Pair pair;
        pair.size = std::max<uint64_t>(16, (bytes.size() + 15) / 16 * 16);
        uz::RHIBufferDesc desc;
        desc.sizeBytes = pair.size;
        desc.usage = uz::RHIBufferUsage::CopySrc;
        desc.memory = uz::RHIMemoryType::Upload;
        desc.debugName = name;
        Result<uz::RHIBufferHandle> upload = m_device.CreateBuffer(desc);
        if (!upload) return Unexpected(upload.error());
        pair.upload = *upload;
        desc.stride = 0;
        desc.usage = uz::RHIBufferUsage::StructuredBuffer | uz::RHIBufferUsage::CopyDst;
        desc.memory = uz::RHIMemoryType::Default;
        Result<uz::RHIBufferHandle> gpu = m_device.CreateBuffer(desc);
        if (!gpu) {
            m_device.DestroyBuffer(pair.upload);
            return Unexpected(gpu.error());
        }
        pair.gpu = *gpu;
        m_pairs.push_back(pair);
        auto* mapped = static_cast<std::byte*>(m_device.Rhi().MapBuffer(pair.upload));
        if (!mapped) {
            return render::Fail(ErrorCode::ResourceCreationFailed, m_device.GetBackend(),
                                std::string("painter_viewport: upload buffer '") + name + "' not mapped");
        }
        std::memset(mapped, 0, pair.size);
        if (!bytes.empty()) std::memcpy(mapped, bytes.data(), bytes.size());
        m_device.Rhi().UnmapBuffer(pair.upload);
        return m_device.Rhi().GetBufferSRVIndex(pair.gpu);
    }

    void RecordUploads(uz::IRHICommandList& cmd) const {
        for (const Pair& pair : m_pairs) {
            const uz::RHIBarrierDesc toCopy{uz::RHITextureHandle::Invalid(), pair.gpu, uz::RHIResourceState::Common,
                                            uz::RHIResourceState::CopyDst};
            cmd.ResourceBarrier(&toCopy, 1);
            cmd.CopyBuffer(pair.upload, 0, pair.gpu, 0, pair.size);
            const uz::RHIBarrierDesc toRead{uz::RHITextureHandle::Invalid(), pair.gpu, uz::RHIResourceState::CopyDst,
                                            uz::RHIResourceState::ShaderResource};
            cmd.ResourceBarrier(&toRead, 1);
        }
    }

    void Abandon() { m_pairs.clear(); }

private:
    struct Pair {
        uz::RHIBufferHandle upload = uz::RHIBufferHandle::Invalid();
        uz::RHIBufferHandle gpu = uz::RHIBufferHandle::Invalid();
        uint64_t size = 0;
    };
    render::IDevice& m_device;
    std::deque<Pair> m_pairs;
};

}  // namespace

CameraPose PoseOf(const OrbitCamera& camera) {
    const double yaw = camera.yawDegrees * kDegree;
    const double pitch = camera.pitchDegrees * kDegree;
    const Vec offset{std::cos(pitch) * std::sin(yaw), std::sin(pitch), std::cos(pitch) * std::cos(yaw)};
    CameraPose pose;
    pose.eye = {camera.target[0] + camera.distance * offset[0], camera.target[1] + camera.distance * offset[1],
                camera.target[2] + camera.distance * offset[2]};
    pose.forward = {-offset[0], -offset[1], -offset[2]};
    pose.right = Normalised(Cross(pose.forward, Vec{0.0, 1.0, 0.0}));
    pose.up = Cross(pose.right, pose.forward);
    pose.fovDegrees = camera.fovDegrees;
    pose.nearPlane = camera.distance * 1e-6;
    return pose;
}

std::string DriverVersion(uint32_t adapterIndex) {
    Microsoft::WRL::ComPtr<IDXGIFactory6> factory;
    if (FAILED(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)))) return "unknown";
    Microsoft::WRL::ComPtr<IDXGIAdapter1> adapter;
    if (FAILED(factory->EnumAdapterByGpuPreference(adapterIndex, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,
                                                   IID_PPV_ARGS(&adapter)))) {
        return "unknown";
    }
    LARGE_INTEGER umd{};
    if (FAILED(adapter->CheckInterfaceSupport(__uuidof(IDXGIDevice), &umd))) return "unknown";
    const uint64_t v = static_cast<uint64_t>(umd.QuadPart);
    return std::to_string(v >> 48) + "." + std::to_string((v >> 32) & 0xFFFF) + "." + std::to_string((v >> 16) & 0xFFFF) +
           "." + std::to_string(v & 0xFFFF);
}

OrbitCamera FitCamera(const mesh::TexturingMesh& mesh) {
    Vec lo{std::numeric_limits<double>::max(), std::numeric_limits<double>::max(), std::numeric_limits<double>::max()};
    Vec hi{-lo[0], -lo[1], -lo[2]};
    for (const mesh::Object& object : mesh.objects) {
        const Transform transform(object.transform, UnitScale(mesh));
        for (const mesh::Triangle& triangle : object.triangles) {
            for (const uint32_t corner : triangle.corners) {
                const Vec p = transform.Point(mesh.positions[mesh.corners[corner].position]);
                for (int i = 0; i < 3; ++i) {
                    lo[i] = std::min(lo[i], p[i]);
                    hi[i] = std::max(hi[i], p[i]);
                }
            }
        }
    }
    OrbitCamera camera;
    if (lo[0] > hi[0]) return camera;
    camera.target = {(lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0, (lo[2] + hi[2]) / 2.0};
    const double radius = std::max(1e-6, std::sqrt(Dot(Sub(hi, lo), Sub(hi, lo))) / 2.0);
    camera.distance = radius * 1.1 / std::sin(camera.fovDegrees * std::numbers::pi / 360.0);
    return camera;
}

uint64_t ViewportKernelKey(render::KernelTarget target, std::string_view compilerVersion) {
    return render::KernelKey(ViewportKernel(), target, compilerVersion);
}

Result<void> ValidateViewport(const ViewportScene& scene, const OrbitCamera& camera, uint32_t width, uint32_t height,
                              render::Backend backend) {
    if (const std::optional<std::string> unsupported = UnsupportedConfiguration(scene.display)) {
        return render::Fail(ErrorCode::RequestFailed, backend, *unsupported);
    }
    if (!(camera.distance > 0.0) || !(camera.fovDegrees > 0.0 && camera.fovDegrees < 180.0) ||
        !(std::abs(camera.pitchDegrees) < 90.0)) {
        return Invalid(backend, "the camera needs a positive distance, a field of view in (0, 180) and a pitch "
                                "in (-90, 90)");
    }
    return ValidateViewport(scene, PoseOf(camera), width, height, backend);
}

Result<void> ValidateViewport(const ViewportScene& scene, const CameraPose& camera, uint32_t width, uint32_t height,
                              render::Backend backend) {
    if (const std::optional<std::string> unsupported = UnsupportedConfiguration(scene.display)) {
        return render::Fail(ErrorCode::RequestFailed, backend, *unsupported);
    }
    if (width == 0 || height == 0 || width > kMaxViewportSide || height > kMaxViewportSide) {
        return Invalid(backend, "the size " + std::to_string(width) + " x " + std::to_string(height) +
                                    " is outside 1 to " + std::to_string(kMaxViewportSide));
    }
    if (!scene.mesh) return Invalid(backend, "no mesh");
    if (!scene.lighting || scene.lighting->radiance.size() != kRadianceLevels ||
        scene.lighting->brdf.size() != size_t{kBrdfTableSize} * kBrdfTableSize * 3) {
        return Invalid(backend, "no precomputed environment lighting");
    }
    const auto finite = [](const Vec& v) { return std::isfinite(v[0]) && std::isfinite(v[1]) && std::isfinite(v[2]); };
    const auto unit = [&](const Vec& v) { return finite(v) && std::abs(Dot(v, v) - 1.0) < 1e-9; };
    if (!(camera.fovDegrees > 0.0 && camera.fovDegrees < 180.0) || !(camera.nearPlane > 0.0) ||
        !std::isfinite(camera.nearPlane) || !finite(camera.eye) || !unit(camera.right) || !unit(camera.up) ||
        !unit(camera.forward) || std::abs(Dot(camera.right, camera.up)) > 1e-9 ||
        std::abs(Dot(camera.up, camera.forward)) > 1e-9 || std::abs(Dot(camera.forward, camera.right)) > 1e-9) {
        return Invalid(backend, "the camera needs a finite eye, an orthonormal basis, a field of view in (0, 180) "
                                "and a positive near distance");
    }
    const mesh::TexturingMesh& mesh = *scene.mesh;
    for (const mesh::Object& object : mesh.objects) {
        for (const mesh::Triangle& triangle : object.triangles) {
            for (const uint32_t corner : triangle.corners) {
                if (corner >= mesh.corners.size() || mesh.corners[corner].position >= mesh.positions.size()) {
                    return Invalid(backend, "a triangle names a corner or position out of range");
                }
            }
        }
    }
    for (size_t i = 0; i < scene.materials.size(); ++i) {
        const MaterialInputs& m = scene.materials[i];
        for (Result<void> checked :
             {CheckMap(m.baseColor, 3, "base colour", i, backend), CheckMap(m.metalness, 1, "metalness", i, backend),
              CheckMap(m.roughness, 1, "roughness", i, backend), CheckMap(m.normal, 3, "normal", i, backend)}) {
            if (!checked) return checked;
        }
    }
    return {};
}

Result<ViewportImage> RenderViewport(render::EngineContext& context, const ViewportScene& scene,
                                     const OrbitCamera& camera, uint32_t width, uint32_t height) {
    if (Result<void> valid = ValidateViewport(scene, camera, width, height, context.Device().GetBackend()); !valid) {
        return Unexpected(valid.error());
    }
    return RenderViewport(context, scene, PoseOf(camera), width, height);
}

Result<ViewportImage> RenderViewport(render::EngineContext& context, const ViewportScene& scene,
                                     const CameraPose& view, uint32_t width, uint32_t height) {
    render::IDevice& device = context.Device();
    if (Result<void> valid = ValidateViewport(scene, view, width, height, device.GetBackend()); !valid) {
        return Unexpected(valid.error());
    }
    const mesh::TexturingMesh& mesh = *scene.mesh;
    const double tanHalf = std::tan(view.fovDegrees * kDegree / 2.0);
    const double aspect = static_cast<double>(width) / height;
    const uint32_t tilesX = (width + kTile - 1) / kTile;
    const uint32_t tilesY = (height + kTile - 1) / kTile;

    // Triangles in world space, in object then triangle order, and their tiles.
    std::vector<uint32_t> triangles;
    triangles.reserve(mesh.corners.size() / 3 * kTriangleWords);
    std::vector<std::array<uint32_t, 4>> bounds;  // tile x0, y0, x1, y1 (inclusive); x0 > x1: none
    const double nearPlane = view.nearPlane;
    for (const mesh::Object& object : mesh.objects) {
        const Transform transform(object.transform, UnitScale(mesh));
        for (const mesh::Triangle& triangle : object.triangles) {
            std::array<Vec, 3> positions{};
            for (int k = 0; k < 3; ++k) {
                const mesh::Corner& corner = mesh.corners[triangle.corners[static_cast<size_t>(k)]];
                positions[static_cast<size_t>(k)] = transform.Point(mesh.positions[corner.position]);
                for (double value : positions[static_cast<size_t>(k)]) PushFloat(triangles, value);
                for (double value : transform.Normal(corner.normal)) PushFloat(triangles, value);
                triangles.push_back(std::bit_cast<uint32_t>(corner.uv0.u));
                triangles.push_back(std::bit_cast<uint32_t>(corner.uv0.v));
                for (double value : transform.Direction(corner.tangent[0], corner.tangent[1], corner.tangent[2])) {
                    PushFloat(triangles, value);
                }
                triangles.push_back(std::bit_cast<uint32_t>(corner.tangent[3]));
            }
            triangles.push_back(mesh.corners[triangle.corners[0]].material);
            triangles.insert(triangles.end(), {0u, 0u, 0u});

            // Screen bounds of the projected corners, one pixel wider on each side.
            double minX = std::numeric_limits<double>::max();
            double minY = minX;
            double maxX = -minX;
            double maxY = -minX;
            int behind = 0;
            for (const Vec& p : positions) {
                const Vec rel = Sub(p, view.eye);
                const double z = Dot(rel, view.forward);
                if (z <= nearPlane) {
                    ++behind;
                    continue;
                }
                const double sx = Dot(rel, view.right) / (z * tanHalf * aspect);
                const double sy = Dot(rel, view.up) / (z * tanHalf);
                minX = std::min(minX, (sx + 1.0) / 2.0 * width);
                maxX = std::max(maxX, (sx + 1.0) / 2.0 * width);
                minY = std::min(minY, (1.0 - sy) / 2.0 * height);
                maxY = std::max(maxY, (1.0 - sy) / 2.0 * height);
            }
            if (behind == 3) {
                bounds.push_back({1, 0, 0, 0});
            } else if (behind > 0) {
                bounds.push_back({0, 0, tilesX - 1, tilesY - 1});
            } else if (maxX < -1.0 || maxY < -1.0 || minX > width + 1.0 || minY > height + 1.0) {
                bounds.push_back({1, 0, 0, 0});
            } else {
                const auto tileOf = [](double pixel, uint32_t count) {
                    return static_cast<uint32_t>(std::clamp(pixel, 0.0, static_cast<double>(count * kTile - 1)) / kTile);
                };
                bounds.push_back({tileOf(std::floor(minX) - 1.0, tilesX), tileOf(std::floor(minY) - 1.0, tilesY),
                                  tileOf(std::ceil(maxX) + 1.0, tilesX), tileOf(std::ceil(maxY) + 1.0, tilesY)});
            }
        }
    }
    std::vector<uint32_t> tileOffsets(size_t{tilesX} * tilesY + 1, 0);
    for (const auto& b : bounds) {
        if (b[0] > b[2]) continue;
        for (uint32_t ty = b[1]; ty <= b[3]; ++ty) {
            for (uint32_t tx = b[0]; tx <= b[2]; ++tx) ++tileOffsets[size_t{ty} * tilesX + tx + 1];
        }
    }
    for (size_t i = 1; i < tileOffsets.size(); ++i) tileOffsets[i] += tileOffsets[i - 1];
    std::vector<uint32_t> tileTriangles(tileOffsets.back());
    {
        std::vector<uint32_t> cursor(tileOffsets.begin(), tileOffsets.end() - 1);
        for (uint32_t t = 0; t < bounds.size(); ++t) {
            const auto& b = bounds[t];
            if (b[0] > b[2]) continue;
            for (uint32_t ty = b[1]; ty <= b[3]; ++ty) {
                for (uint32_t tx = b[0]; tx <= b[2]; ++tx) tileTriangles[cursor[size_t{ty} * tilesX + tx]++] = t;
            }
        }
    }

    // Materials and their maps.
    std::vector<uint32_t> materials;
    materials.reserve(scene.materials.size() * kMaterialWords);
    std::vector<uint32_t> maps;
    const auto addMap = [&](const std::optional<MaterialMap>& map) {
        if (!map) {
            materials.insert(materials.end(), {kNoMap, 0u, 0u});
            return;
        }
        materials.insert(materials.end(), {static_cast<uint32_t>(maps.size()), map->width, map->height});
        for (float value : map->values) maps.push_back(std::bit_cast<uint32_t>(value));
    };
    for (const MaterialInputs& m : scene.materials) {
        addMap(m.baseColor);
        addMap(m.metalness);
        addMap(m.roughness);
        addMap(m.normal);
        for (float value : m.baseColorValue) materials.push_back(std::bit_cast<uint32_t>(value));
        materials.push_back(std::bit_cast<uint32_t>(m.metalnessValue));
        materials.push_back(std::bit_cast<uint32_t>(m.roughnessValue));
        materials.insert(materials.end(), {0u, 0u, 0u});
    }

    // Lighting: header, then the albedo table and the radiance levels.
    const EnvironmentLighting& lighting = *scene.lighting;
    std::vector<uint32_t> lightingWords;
    for (float value : lighting.sh) lightingWords.push_back(std::bit_cast<uint32_t>(value));
    uint32_t offset = kLightingHeaderWords + static_cast<uint32_t>(lighting.brdf.size());
    for (const RadianceLevel& level : lighting.radiance) {
        lightingWords.insert(lightingWords.end(), {offset, level.width, level.height});
        offset += static_cast<uint32_t>(level.rgb.size());
    }
    lightingWords.push_back(kLightingHeaderWords);
    for (float value : lighting.brdf) lightingWords.push_back(std::bit_cast<uint32_t>(value));
    for (const RadianceLevel& level : lighting.radiance) {
        for (float value : level.rgb) lightingWords.push_back(std::bit_cast<uint32_t>(value));
    }

    // The display table, two codes per word (even index in the low half).
    const std::vector<uint16_t>& table = DisplayTable();
    std::vector<uint32_t> tableWords(table.size() / 2);
    for (size_t i = 0; i < tableWords.size(); ++i) {
        tableWords[i] = static_cast<uint32_t>(table[2 * i]) | (static_cast<uint32_t>(table[2 * i + 1]) << 16);
    }

    std::vector<uint32_t> frame;
    for (const Vec* v : {&view.eye, &view.right, &view.up, &view.forward}) {
        for (double value : *v) PushFloat(frame, value);
    }
    PushFloat(frame, tanHalf);
    PushFloat(frame, aspect);
    for (float value : scene.background) frame.push_back(std::bit_cast<uint32_t>(value));
    PushFloat(frame, scene.environmentRotationDegrees / 360.0);
    PushFloat(frame, std::exp2(scene.environmentExposure) * kEnvironmentIntensityScale);
    frame.push_back(static_cast<uint32_t>(bounds.size()));
    frame.push_back(static_cast<uint32_t>(scene.materials.size()));
    frame.push_back(kRadianceLevels);
    frame.push_back(kBrdfTableSize);
    frame.push_back(tilesX);

    Result<render::ComputeKernel> kernel = context.Kernel(ViewportKernel());
    if (!kernel) return Unexpected(kernel.error());

    Buffers buffers(device);
    std::array<uint32_t, 8> srv{};
    {
        const std::array<std::pair<const std::vector<uint32_t>*, const char*>, 8> inputs{{
            {&frame, "viewport_frame"},
            {&triangles, "viewport_triangles"},
            {&tileOffsets, "viewport_tile_offsets"},
            {&tileTriangles, "viewport_tile_triangles"},
            {&materials, "viewport_materials"},
            {&maps, "viewport_maps"},
            {&lightingWords, "viewport_lighting"},
            {&tableWords, "viewport_display_table"},
        }};
        for (size_t i = 0; i < inputs.size(); ++i) {
            Result<uint32_t> index = buffers.Raw(Bytes(*inputs[i].first), inputs[i].second);
            if (!index) return Unexpected(index.error());
            srv[i] = *index;
        }
    }

    const auto makeTexture = [&](uz::RHIFormat format, const char* name) -> Result<uz::RHITextureHandle> {
        uz::RHITextureDesc desc;
        desc.width = width;
        desc.height = height;
        desc.format = format;
        desc.usage = uz::RHITextureUsage::ShaderResource | uz::RHITextureUsage::UnorderedAccess |
                     uz::RHITextureUsage::CopySrc;
        desc.debugName = name;
        return device.CreateTexture(desc);
    };
    Result<uz::RHITextureHandle> linear = makeTexture(uz::RHIFormat::RGBA16Float, "viewport_linear");
    if (!linear) return Unexpected(linear.error());
    Result<uz::RHITextureHandle> display = makeTexture(uz::RHIFormat::RGBA16Unorm, "viewport_display");
    if (!display) {
        device.DestroyTexture(*linear);
        return Unexpected(display.error());
    }
    const std::array<uz::RHITextureHandle, 2> outputs{*linear, *display};

    const std::array<uint32_t, 12> root{width,  height, srv[0], srv[1], srv[2], srv[3], srv[4], srv[5], srv[6], srv[7],
                                        device.Rhi().GetTextureUAVIndex(*linear),
                                        device.Rhi().GetTextureUAVIndex(*display)};
    const auto transition = [&](uz::IRHICommandList& cmd, uz::RHIResourceState before, uz::RHIResourceState after) {
        const uz::RHIBarrierDesc barriers[2] = {{outputs[0], uz::RHIBufferHandle::Invalid(), before, after},
                                                {outputs[1], uz::RHIBufferHandle::Invalid(), before, after}};
        cmd.ResourceBarrier(barriers, 2);
    };
    Result<void> done = context.SubmitAndWait([&](uz::IRHICommandList& cmd) {
        buffers.RecordUploads(cmd);
        transition(cmd, uz::RHIResourceState::Common, uz::RHIResourceState::UnorderedAccess);
        cmd.SetPipeline(kernel->pipeline);
        cmd.SetRootConstants(render::kRootConstantsParam, root.data(), static_cast<uint32_t>(root.size()));
        cmd.Dispatch((width + 7) / 8, (height + 7) / 8, 1);
        transition(cmd, uz::RHIResourceState::UnorderedAccess, uz::RHIResourceState::Common);
    });
    const auto release = [&] {
        for (uz::RHITextureHandle texture : outputs) device.DestroyTexture(texture);
    };
    if (!done) {
        if (done.error().code == ErrorCode::Timeout) {
            buffers.Abandon();  // the GPU may still read them; the engine keeps its device
            return Unexpected(done.error());
        }
        release();
        return Unexpected(done.error());
    }

    ViewportImage image;
    image.width = width;
    image.height = height;
    {
        render::TextureReadback readback(context);
        for (size_t i = 0; i < outputs.size(); ++i) {
            render::ReadbackDesc desc;
            desc.texture = outputs[i];
            Result<render::ReadbackId> id = readback.Request(desc);
            if (!id) {
                release();
                return Unexpected(id.error());
            }
            Result<render::ReadbackImage> read = readback.Complete(*id);
            if (!read) {
                if (read.error().code != ErrorCode::Timeout) release();
                return Unexpected(read.error());
            }
            std::vector<uint16_t>& target = i == 0 ? image.linear : image.display;
            target.resize(size_t{width} * height * 4);
            std::memcpy(target.data(), read->texels.data(), target.size() * sizeof(uint16_t));
        }
    }
    release();
    return image;
}

}  // namespace uzp::preview
