#pragma once

// The `painter_viewport` pass (docs/architecture/07-preview-and-render-parity.md §1, §5, §6; task
// phase2.1_preview-viewport-window item 2.2): a forward pass over the texturing mesh with the
// project's material channels, lit by the precomputed environment (environment.h) and displayed
// through the pinned display transform (display_transform.h). It is a preview and a fast check,
// never parity or acceptance evidence (decision 018).
//
// Pass, one compute dispatch on the render layer (src/render/):
// - Visibility: the CPU bins every triangle by its screen bounds into 16 x 16-pixel tiles (with
//   a perspective camera, a triangle crossing the camera plane goes to every tile; an
//   orthographic projection is affine, so it keeps its bounds); each pixel casts its centre ray
//   against its tile's triangles in ascending index order and keeps the nearest hit (ties: the
//   lowest index). No clipping, no depth buffer; both faces are visible.
// - Material (decision 042: the default open-pbr instance at its defaults, emission luminance 0,
//   opacity off): base colour, base metalness, specular roughness and the tangent-space normal
//   (the project's combined virtual normal map, Normal_OpenGL, which carries height as bump), each
//   sampled bilinearly in UV with wrapping (texel (c, r) centred at u = (c + 1/2) / W,
//   v = 1 - (r + 1/2) / H); a channel without a map uses its constant. Normals in the MikkTSpace
//   frame: n = normalize(t.x T + t.y B + t.z N), B = sign cross(N, T) of the interpolated corner
//   frame, faded toward the interpolated normal N as the view's mirror reflection about n sinks
//   toward the geometric tangent plane (decision 256): with e = dot(reflect(-view, n), Ng),
//   e >= 0.2 keeps n, e <= 0 or n facing away gives N, and in between the two blend by
//   smoothstep(0, 0.2, e).
// - Lighting: split-sum GGX specular (F0 = mix(0.04, base colour, metalness), IOR 1.5) and
//   Burley diffuse on the SH irradiance, scaled by (1 - the dielectric specular albedo); the
//   environment radiance is multiplied by 2^exposure and the intensity scale of
//   parity/semantics/iray.json `environment-mapping`. Pixels without a hit show the clear colour.
// - Self-occlusion (decision 251): each term is multiplied, per RGB channel, by its visibility
//   ratio sum V w L / sum w L over rays traced from the hit against every triangle of every
//   texture set (visibility.h). Diffuse: `diffuseRays` directions from the balance-heuristic
//   mixture of cosine-weighted and environment-importance directions (environment.h
//   `ImportanceDistribution`), w = cos / p_mix. Specular: `specularRays` directions from the
//   balance-heuristic mixture of reflections about GGX visible normals (Heitz 2018) and
//   environment-importance directions, w = F D G2 / (4 n.v p_mix). Directions below the
//   geometric facet are left out of both sums; a ratio is 1 where no ray is blocked and where its
//   denominator is zero or not finite, otherwise clamped to [0, 1]. Ray origins are moved off the
//   triangle along its geometric normal (Wachter and Binder 2019) and the hit triangle is
//   skipped. The samples are a Hammersley set scrambled by a hash of the pixel coordinates only.
//   Visibility only, one bounce, no interreflection; the ratio of two Monte-Carlo sums is a
//   consistent but biased estimator, a preview approximation that claims no closeness to Iray.
// - Ambient occlusion (decision 257): the texture set's AO mesh map (`occlusion`, sampled like
//   the other maps; none reads 1) gives a = 1 + s (ao - 1) with s = `kOcclusionStrength`, an
//   assumed directional AO: each ray of either term that no triangle blocks counts with the weight
//   V_ao = mu^k, mu = dot(s, d) about the faded shading normal s and k = 2 (1 - a) / a, whose
//   cosine-weighted mean over the hemisphere is exactly a (the calibration of Oat and Sander 2007's
//   visibility cone; the power law is UzPainter's). A ray V_ao weighs below 1 counts as blocked
//   (the ratio is then the sums' quotient). a = 1 skips the weight (the pixel is that of the pass
//   without it), a = 0 removes every ray. No horizon or other occlusion term; the painted AO
//   channel is not applied.
// - Cavity (decision 258): where the texture set has a normal map, a = a_ao a_cav in the weight
//   above, and the specular ratio is the lesser of that weighted ratio and a_cav times the ratio
//   with a = a_ao (both over the same rays): seen head-on the specular lobe sits on the weight's
//   axis, where mu^k stays near 1. The normal map is read as a height field whose slope along the
//   shading tangent T and bitangent B is (-t.x, -t.y) / max(t.z, 0.3) of its unit tangent-space
//   normal t; kappa = trace(J^-1 D) is the divergence of that slope per world length (the Laplacian
//   of the implied height, positive where concave), with D the slope's central differences per
//   texel from four bilinear taps at +- (g_u / W, 0) and +- (0, g_v / H) about a point and J the
//   world length of a texel step on (T, B) from the hit triangle's dP/du and dP/dv, so it holds
//   under any texel density, mirroring, shear or rotation of the UVs. h is the pixel's footprint in
//   texels per axis, at least 1, from the ray differentials of the next pixel's rays on the hit
//   plane (Igehy 1999); n = min(ceil(h), 3) points per axis spread over it, with spacing g = max(1,
//   h / n), and a_cav is the mean over them of 1 / (1 + r max(0, kappa)), with r =
//   `kCavityRadiusMetres` in scene units (`CavityRadiusOf`): a box filter of a_cav, so a crease and
//   its convex shoulders in one footprint do not cancel. h <= 1 is one point. No normal map, kappa
//   <= 0, a zero-area UV triangle, a degenerate frame and a footprint that does not resolve (the
//   next pixel's ray misses the hit plane, or the taps span the whole map) give a_cav = 1 exactly,
//   so the pixel is that of the pass without it.
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
#include <span>
#include <string>
#include <string_view>
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
/// it: open-pbr's defaults base colour 0.8, metalness 0, specular roughness 0.3, flat normal; no
/// occlusion map reads ao = 1.
struct MaterialInputs {
    std::optional<MaterialMap> baseColor;  ///< 3 components, linear
    std::optional<MaterialMap> metalness;  ///< 1 component
    std::optional<MaterialMap> roughness;  ///< 1 component
    std::optional<MaterialMap> normal;     ///< 3 components, OpenGL tangent-space normal encoded in [0, 1]
    std::optional<MaterialMap> occlusion;  ///< 1 component, the AO mesh map, linear (decision 257)
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

/// A camera as its eye and orthonormal basis (right, up, forward), its vertical field of view,
/// and the distance along `forward` at or below which a corner counts as behind the eye (triangle
/// binning only). Captures pass Painter's camera records this way (python/capture.h).
///
/// Orthographic (decision 163): every pixel's ray runs along `forward` from its point on the plane
/// through the eye, `orthographicHeight` (scene units) high and `orthographicHeight * aspect` wide;
/// `fovDegrees` is not used. Only hits in front of that plane count, as for perspective rays.
struct CameraPose {
    std::array<double, 3> eye{0.0, 0.0, 0.0};
    std::array<double, 3> right{1.0, 0.0, 0.0};
    std::array<double, 3> up{0.0, 1.0, 0.0};
    std::array<double, 3> forward{0.0, 0.0, -1.0};
    double fovDegrees = 40.0;
    double nearPlane = 1e-6;
    bool orthographic = false;
    double orthographicHeight = 0.0;
};

/// The pose of an orbit camera (its near distance is `distance * 1e-6`).
[[nodiscard]] CameraPose PoseOf(const OrbitCamera& camera);

/// The intensity scale of parity/semantics/iray.json `environment-mapping` (fitted once).
inline constexpr float kEnvironmentIntensityScale = 1.01919f;

/// The visibility rays of every hit (decision 251), chosen by measurement on the ladder (8, 4) to
/// (256, 128): the smallest pair whose ratios meet the 0.5 / sqrt(N) noise bound on the concave
/// fixture, and whose render of the Wand at the preview window's default view fits its 200 ms
/// period on the owner's RTX 4090 (src/preview/PREVIEW.md).
inline constexpr uint32_t kDiffuseVisibilityRays = 128;
inline constexpr uint32_t kSpecularVisibilityRays = 64;
/// The visibility model's name in a capture's render state and receipt.
inline constexpr std::string_view kVisibilityModel = "ray_traced_self_occlusion";
/// The AO strength s of a = 1 + s (ao - 1) (glTF 2.0 `occlusionTexture.strength`): UzPainter's
/// provisional preview default, a fixed constant that only a decision changes (decision 257).
inline constexpr float kOcclusionStrength = 1.0f;
/// The occlusion model's name in a capture's render state and receipt (decision 257).
inline constexpr std::string_view kOcclusionModel = "cosine_power_visibility";
/// The cavity radius r of a_cav = 1 / (1 + r max(0, kappa)), in metres: UzPainter's provisional
/// preview default, a fixed constant that only a decision changes (decision 258).
inline constexpr double kCavityRadiusMetres = 0.00025;
/// The cavity model's name in a capture's render state and receipt (decision 258).
inline constexpr std::string_view kCavityModel = "normal_divergence";

/// Whether the scene unit of `mesh` is known: the file states its unit or the caller gave a mesh
/// unit scale, so the scene is in centimetres (`units.scale_to_internal`). Otherwise (an OBJ
/// without a scale) the scene unit is the file's, read as the metre (decision 258).
[[nodiscard]] bool SceneUnitKnown(const mesh::TexturingMesh& mesh);
/// `kCavityRadiusMetres` in the scene units of `mesh` (`SceneUnitKnown`).
[[nodiscard]] double CavityRadiusOf(const mesh::TexturingMesh& mesh);

/// What a render writes in place of the linear colour: the colour, or (tests) the diffuse or
/// specular visibility ratio of each hit, or its cavity (a_cav, kappa, 1 where the cavity was
/// computed and 0 where the hit has no normal map or the cavity is off).
enum class ViewportOutput : uint32_t { Colour = 0, DiffuseVisibility = 1, SpecularVisibility = 2, Cavity = 3 };

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
    /// The visibility rays per hit; 0 leaves that term unoccluded. Captures and the window keep
    /// the defaults; tests and the measurement of the counts set others.
    uint32_t diffuseRays = kDiffuseVisibilityRays;
    uint32_t specularRays = kSpecularVisibilityRays;
    /// The cavity term (decision 258). Captures and the window keep it on; tests turn it off to
    /// compare against the pass without it.
    bool cavity = true;
    ViewportOutput output = ViewportOutput::Colour;
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
/// error naming decision 038), the mesh, the lighting, the camera, the size and every material
/// map. Errors are `request_failed` with the reason.
[[nodiscard]] render::Result<void> ValidateViewport(const ViewportScene& scene, const OrbitCamera& camera,
                                                    uint32_t width, uint32_t height, render::Backend backend);
[[nodiscard]] render::Result<void> ValidateViewport(const ViewportScene& scene, const CameraPose& camera,
                                                    uint32_t width, uint32_t height, render::Backend backend);

/// The camera-independent inputs of one scene kept on the GPU between its renders (decision 257):
/// the materials and their maps, the lighting, the display table and the visibility BVH. A caller
/// that renders one scene many times (the preview window, one scene per revision) keeps one,
/// passes it to every render of that scene and calls `Invalidate` when the scene changes; the next
/// render then rebuilds and uploads them, and the renders after it upload only the camera's inputs
/// (the frame words, the triangles and their tiles). Renders without one upload everything each
/// time. It is used and released on the engine thread only: `Release` (from a request on that
/// engine) before the engine stops, else `Abandon`; `Invalidate` may be called between requests
/// from any thread.
class ResidentInputs {
public:
    ResidentInputs();
    ~ResidentInputs();
    ResidentInputs(const ResidentInputs&) = delete;
    ResidentInputs& operator=(const ResidentInputs&) = delete;

    /// The next render rebuilds the inputs from its scene.
    void Invalidate();
    /// Destroys the buffers (on the engine thread); the next render rebuilds them.
    void Release();
    /// Forgets the buffers without destroying them, for when the engine thread cannot release
    /// them (the GPU may still read them, or the engine has stopped); the engine keeps its device.
    void Abandon();
    /// The renders that rebuilt the inputs and those that reused them (tests).
    [[nodiscard]] uint64_t Builds() const { return m_builds; }
    [[nodiscard]] uint64_t Reuses() const { return m_reuses; }

    struct State;

private:
    friend struct ResidentAccess;
    std::unique_ptr<State> m_state;
    bool m_stale = true;
    uint64_t m_builds = 0;
    uint64_t m_reuses = 0;
};

/// Renders `scene` from `camera` at `width` x `height` inside one engine request; an unsupported
/// display configuration fails before any GPU work. With `resident`, the scene's
/// camera-independent inputs are those it holds (built from `scene` when invalidated); the image
/// is the same bytes either way.
[[nodiscard]] render::Result<ViewportImage> RenderViewport(render::EngineContext& context, const ViewportScene& scene,
                                                           const OrbitCamera& camera, uint32_t width, uint32_t height,
                                                           ResidentInputs* resident = nullptr);
[[nodiscard]] render::Result<ViewportImage> RenderViewport(render::EngineContext& context, const ViewportScene& scene,
                                                           const CameraPose& camera, uint32_t width, uint32_t height,
                                                           ResidentInputs* resident = nullptr);

/// XXH64 of the viewport kernel's cache key for the device's bytecode format: the "build" part of
/// a regression golden's key (it covers the HLSL, the defines, the compile flags and DXC).
[[nodiscard]] uint64_t ViewportKernelKey(render::KernelTarget target, std::string_view compilerVersion);

/// The corners of every triangle of `mesh` in world space, nine floats per triangle in the
/// viewport's triangle order (object, then triangle): what its visibility rays are traced against.
[[nodiscard]] std::vector<float> WorldCorners(const mesh::TexturingMesh& mesh);

/// A ray of `TraceVisibility`: it leaves `point` moved along `normal` by the pass's origin offset
/// (a zero normal moves nothing), runs along `direction` (any length) and skips triangle `self`.
struct VisibilityRay {
    std::array<float, 3> point{};
    std::array<float, 3> normal{};
    std::array<float, 3> direction{};
    uint32_t self = 0xFFFFFFFFu;
};

/// Per ray, whether a triangle blocks it: through the BVH and by testing every triangle in order.
struct VisibilityHits {
    std::vector<uint8_t> bvh;
    std::vector<uint8_t> linear;
};

/// Traces `rays` against the triangles of `mesh` on the GPU with the pass's own visibility
/// functions (`probe` entry of the viewport kernel), inside one engine request (tests: the
/// traversal against every triangle, decision 251).
[[nodiscard]] render::Result<VisibilityHits> TraceVisibility(render::EngineContext& context,
                                                             const mesh::TexturingMesh& mesh,
                                                             std::span<const VisibilityRay> rays);

/// The user-mode driver version of the DXGI adapter `adapterIndex` (high-performance order) as
/// `a.b.c.d`, or "unknown": the "driver" part of a golden's key and of a capture receipt.
[[nodiscard]] std::string DriverVersion(uint32_t adapterIndex);

}  // namespace uzp::preview
