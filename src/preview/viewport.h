#pragma once

// The `painter_viewport` pass (docs/architecture/07-preview-and-render-parity.md §1, §5, §6; task
// phase2.1_preview-viewport-window item 2.2): a forward pass over the texturing mesh with the
// project's material channels, lit by the precomputed environment (environment.h) and displayed
// through the pinned display transform (display_transform.h). It is a preview and a fast check,
// never parity or acceptance evidence (decision 018).
//
// Pass, one compute dispatch on the render layer (src/render/):
// - Visibility: the CPU bins every triangle by its screen bounds into 16 x 16-pixel tiles (a
//   triangle crossing the camera plane goes to every tile); each pixel casts its centre ray
//   against its tile's triangles in ascending index order and keeps the nearest hit (ties: the
//   lowest index). No clipping, no depth buffer; both faces are visible.
// - Material (decision 042: the default open-pbr instance at its defaults, emission luminance 0,
//   opacity off): base colour, base metalness, specular roughness and the tangent-space normal
//   (the project's combined virtual normal map, Normal_OpenGL, which carries height as bump), each
//   sampled bilinearly in UV with wrapping (texel (c, r) centred at u = (c + 1/2) / W,
//   v = 1 - (r + 1/2) / H); a channel without a map uses its constant. Normals in the MikkTSpace
//   frame: n = normalize(t.x T + t.y B + t.z N), B = sign cross(N, T) of the interpolated corner
//   frame; where n faces away from the viewer the interpolated normal is kept.
// - Lighting: split-sum GGX specular (F0 = mix(0.04, base colour, metalness), IOR 1.5) and
//   Burley diffuse on the SH irradiance, scaled by (1 - the dielectric specular albedo); the
//   environment radiance is multiplied by 2^exposure and the intensity scale of
//   parity/semantics/iray.json `environment-mapping`. Pixels without a hit show the clear colour.
// - Output: the linear colour rounded to binary16 (RGBA16Float, alpha 1) and its 16-bit display
//   codes (RGBA16Unorm) from the display table.
//
// Repeatable: the same scene, build, adapter and driver give the same bytes (kernels compiled
// IEEE-strict, no atomics, a fixed loop order), which the regression goldens check (item 2.6).

#include "mesh/texturing_mesh.h"
#include "preview/display_transform.h"
#include "preview/environment.h"
#include "render/backend.h"
#include "render/engine_thread.h"

#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace uzp::preview {

/// A float raster, rows top first, `components` values per texel.
struct MaterialMap {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t components = 0;
    std::vector<float> values;
};

/// The channels of one texture set (one mesh material). A missing map uses the constant beside
/// it: open-pbr's defaults base colour 0.8, metalness 0, specular roughness 0.3, flat normal.
struct MaterialInputs {
    std::optional<MaterialMap> baseColor;  ///< 3 components, linear
    std::optional<MaterialMap> metalness;  ///< 1 component
    std::optional<MaterialMap> roughness;  ///< 1 component
    std::optional<MaterialMap> normal;     ///< 3 components, OpenGL tangent-space normal encoded in [0, 1]
    std::array<float, 3> baseColorValue{0.8f, 0.8f, 0.8f};
    float metalnessValue = 0.0f;
    float roughnessValue = 0.3f;
};

/// A camera orbiting `target`: yaw 0 and pitch 0 put the eye on +Z looking along -Z, +Y up; yaw
/// turns about +Y, pitch raises the eye. The vertical field of view is `fovDegrees`.
struct OrbitCamera {
    std::array<double, 3> target{0.0, 0.0, 0.0};
    double distance = 60.0;
    double yawDegrees = 0.0;
    double pitchDegrees = 0.0;
    double fovDegrees = 40.0;
};

/// The camera of the render-reference fixtures: the bounds' centre seen from +Z, framing the
/// bounding sphere with a 10 % margin at a 40-degree field of view.
[[nodiscard]] OrbitCamera FitCamera(const mesh::TexturingMesh& mesh);

/// The intensity scale of parity/semantics/iray.json `environment-mapping` (fitted once).
inline constexpr float kEnvironmentIntensityScale = 1.01919f;

struct ViewportScene {
    std::shared_ptr<const mesh::TexturingMesh> mesh;
    /// Indexed by the mesh's material index (texture set order); a material without an entry uses
    /// the defaults.
    std::vector<MaterialInputs> materials;
    std::shared_ptr<const EnvironmentLighting> lighting;
    double environmentRotationDegrees = 0.0;
    double environmentExposure = 0.0;
    /// The clear colour, linear: the v2 common standard's 0.1 (display code 89 in 8 bits).
    std::array<float, 3> background{0.1f, 0.1f, 0.1f};
    DisplayConfiguration display = PinnedConfiguration();
};

/// One rendered frame.
struct ViewportImage {
    uint32_t width = 0;
    uint32_t height = 0;
    /// RGBA binary16 bit patterns of the linear colour, rows top first.
    std::vector<uint16_t> linear;
    /// RGBA 16-bit display codes, rows top first.
    std::vector<uint16_t> display;
};

/// The largest viewport side.
inline constexpr uint32_t kMaxViewportSide = 8192;

/// The scene checked without the GPU: the display configuration (the `unsupported_configuration`
/// error naming decision 038), the mesh, the lighting, the size and every material map. Errors are
/// `request_failed` with the reason.
[[nodiscard]] render::Result<void> ValidateViewport(const ViewportScene& scene, const OrbitCamera& camera,
                                                    uint32_t width, uint32_t height, render::Backend backend);

/// Renders `scene` from `camera` at `width` x `height` inside one engine request; an unsupported
/// display configuration fails before any GPU work.
[[nodiscard]] render::Result<ViewportImage> RenderViewport(render::EngineContext& context, const ViewportScene& scene,
                                                           const OrbitCamera& camera, uint32_t width, uint32_t height);

/// XXH64 of the viewport kernel's cache key for the device's bytecode format: the "build" part of
/// a regression golden's key (it covers the HLSL, the defines, the compile flags and DXC).
[[nodiscard]] uint64_t ViewportKernelKey(render::KernelTarget target, std::string_view compilerVersion);

}  // namespace uzp::preview
