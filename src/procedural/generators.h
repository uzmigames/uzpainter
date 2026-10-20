#pragma once

// UzPainter's mesh-map generator families (docs/architecture/05-procedural-content.md §3, the
// Mesh-map generators row; rulebook task phase3.2_proc-generator-families; decision 329). A
// generator reads the texture set's mesh maps by usage (05 §7): its image inputs are named by
// `core::MeshMapUsage` (`AO`, `Curvature`, `Position`, `WorldSpaceNormal`, `Thickness`), each at
// the output's resolution (no resampling), and a missing or invalid mesh map fails evaluation
// loudly (`BindMeshMaps`). The output is one float32 mask channel.
//
// Every family is an `IHlslFamily` of the HLSL host: kernel passes and a CPU reference built from
// the primitive library (`primitives.h`: flushed single operations, no contraction, no division
// in a kernel), equal bit for bit. A parameter is rounded once to float32; the host rounds
// `1 / (high - low)` once to float32. The shared shaping is Peachey's boxstep and smoothstep
// (Ebert et al., Texturing and Modeling, 3rd ed., ch. 2):
//
//   Clamp01(x)          = x > 0 ? (x < 1 ? x : 1) : 0      (NaN and -0 give +0)
//   Boxstep(v, lo, inv) = Clamp01((v - lo) x inv)          inv = float32(1 / (high - low))
//   Shape(v)            = Boxstep, then Fade1985 (3t^2 - 2t^3) when `smooth`, then 1 - t when
//                         `invert`
//
// The mesh-map encodings are the documented ones (A-HELP-BAKING): curvature 0.5 on flat
// surfaces, above on convex and below on concave ones; AO 1 where unoccluded; position
// normalised to the bounding box per axis; world space normal n x 0.5 + 0.5.
//
// - Curvature (`kCurvatureAsset`): Shape(2c - 1), or Shape(1 - 2c) for `mode` 1 (concave).
// - Position (`kPositionAsset`): Shape(p[axis]).
// - World Space Normals (`kWorldNormalAsset`): Shape(2 n[axis / 2] - 1), negated (1 - 2 n) for
//   an odd `axis` (+X, -X, +Y, -Y, +Z, -Z).
// - Ambient Occlusion (`kOcclusionAsset`): Shape(1 - ao).
// - Dirt (`kDirtAsset`; after Miller 1994 and Hsu and Wong 1995: dirt gathers where a surface is
//   least accessible): pass 0 the weighted cavity and occlusion
//   Clamp01(cavity_weight x Clamp01(1 - 2c) + occlusion_weight x (1 - ao)); pass 1 its disk
//   dilation of radius `spread` (Gonzalez and Woods ch. 9, clamped at the border); pass 2
//   Boxstep(spread + noise_amount x N) from `low` to `high`, where N is the fBm of Perlin 2002
//   noise (four octaves, lacunarity 2, gain 1/2, the request's seed) at the position map x
//   `noise_scale`, so the breakup has no seam across UV islands.
// - Metal Edge Wear (`kEdgeWearAsset`; after Paquette, Poulin and Drettakis 2001: wear gathers
//   on exposed convex edges): pass 0 Clamp01(Clamp01(2c - 1) - occlusion_protect x (1 - ao));
//   passes 1 and 2 as Dirt's.
// - Mask Builder (Legacy) (`kMaskBuilderAsset`): pass 0 one `source` (0 convex edges
//   Clamp01(2c - 1), 1 cavities Clamp01(1 - 2c), 2 occlusion 1 - ao, 3 height p.y, 4 upward normal
//   Clamp01(2 n.y - 1)) boxstepped from `low` to `high`; pass 1 Lerp(t, t x M, noise_amount), M
//   the noise mask Boxstep(0.5 N + 0.5) from `noise_low` to `noise_high` (N as Dirt's); pass 2
//   `grow` texels of disk dilation, or -`grow` of erosion when negative.
// - Mask Editor (`kMaskEditorAsset`): the weighted sum edges_weight x convex + cavity_weight x
//   cavities + occlusion_weight x occlusion + height_weight x p.y + up_weight x upward normal +
//   thickness_weight x thickness, summed in that order, boxstepped from `low` to `high` and
//   inverted when `invert`. It reads five mesh maps, so it runs in two passes (a pass has at most
//   four inputs).
//
// Each family's record, domain and status are those of its provenance record in the asset
// library (`RegisterGeneratorFamilies`), so the seam and the certification harness read one
// declaration. None is certified: the records say `unavailable`, the seam refuses them, and no
// alias of the library names them (decision 324).

#include "procedural/admission.h"
#include "procedural/asset_library.h"
#include "procedural/hlsl_backend.h"
#include "procedural/seam.h"

#include "evaluator/resources.h"

#include "uzp_core/types/enums.h"
#include "uzp_core/types/project.h"

#include <expected>
#include <map>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace uzp::procedural {

inline constexpr std::string_view kCurvatureAsset = "uzasset://generator/curvature@1";
inline constexpr std::string_view kPositionAsset = "uzasset://generator/position@1";
inline constexpr std::string_view kWorldNormalAsset = "uzasset://generator/world-normal@1";
inline constexpr std::string_view kOcclusionAsset = "uzasset://generator/occlusion@1";
inline constexpr std::string_view kDirtAsset = "uzasset://generator/dirt@1";
inline constexpr std::string_view kEdgeWearAsset = "uzasset://generator/edge-wear@1";
inline constexpr std::string_view kMaskBuilderAsset = "uzasset://generator/mask-builder@1";
inline constexpr std::string_view kMaskEditorAsset = "uzasset://generator/mask-editor@1";

/// The generator assets of this file, in registration order.
[[nodiscard]] std::span<const std::string_view> GeneratorAssets();

/// The mesh maps generator `asset` reads, by usage (any version of the asset id); empty for an
/// asset that is not one of these generators.
[[nodiscard]] std::vector<core::MeshMapUsage> GeneratorUsages(const core::AssetUrl& asset);

/// The joint rule of every generator, which the domain's JSON cannot state: each mesh-map input
/// has the output's resolution. The refusal (`outside certified domain`) names the input's field,
/// its value and the output's value; nothing is resampled. Empty when the rule holds.
[[nodiscard]] std::optional<UnsupportedProcedural> GeneratorJointRefusal(const ProceduralRequest& request);

/// Registers every generator with `hlsl`, each with the record `library` holds for it (its
/// domain, its status, its provenance). Refused when the library lacks a record or the host
/// refuses the registration.
std::expected<void, std::string> RegisterGeneratorFamilies(HlslBackend& hlsl, const AssetLibrary& library);

/// The mesh maps of a texture set, bound by usage: the request inputs (by usage name: the
/// binding's SHA-256 and spec) and their decoded rasters.
struct BoundMeshMaps {
    std::map<std::string, ImageInput> inputs;
    InputImages images;
};

/// The spec of a mesh-map binding: the set's resolution, the sample type and channel count of the
/// binding's format (`L8`, `RGB8` and `sRGB8` as u8; `L16`, `RGB16` as u16; `L16F`, `RGB16F` as
/// f16; `L32F`, `RGB32F` as f32) and its colour space as stored.
[[nodiscard]] RasterSpec MeshMapSpec(const core::MeshMapBinding& binding, uint32_t resolution);

/// Binds `usages` from `set` by usage and decodes them through `resources`: a UNORM code is
/// float32(code / (2^n - 1)), a float sample keeps its bits. Fails loudly (`request_failed`),
/// naming the mesh map, when the set has no binding of a usage, the binding is marked invalid
/// (its report quoted), the resources do not hold its image, the image's size, channels or sample
/// type are not the binding's, or the set is not square. Nothing is substituted.
[[nodiscard]] render::Result<BoundMeshMaps> BindMeshMaps(const core::TextureSet& set,
                                                         std::span<const core::MeshMapUsage> usages,
                                                         const evaluator::IResourceProvider& resources);

/// The request of generator reference `ref` in `context` (`RequestFor`) with the mesh maps
/// `meshMaps` (from `BindMeshMaps`) as its image inputs. Refused when the reference itself binds
/// an image input named like a mesh map: a generator reads its mesh maps from the texture set.
[[nodiscard]] std::expected<ProceduralRequest, UnsupportedProcedural> GeneratorRequest(
    const core::ProceduralRef& ref, const UseContext& context, const std::map<std::string, ImageInput>& meshMaps,
    const AssetLibrary& library);

/// Sets `ref` as the procedural of the generator effect `effect`, in one transaction of
/// `submit`, after `GeneratorRequest` and `Admit` (decision 324 §10). A refusal returns before
/// `submit` is called: the revision does not advance, nothing is clamped or substituted.
std::expected<core::RequestOutcome, UnsupportedProcedural> SetGeneratorEffect(
    core::Id effect, const core::ProceduralRef& ref, const UseContext& context,
    const std::map<std::string, ImageInput>& meshMaps, const AssetLibrary& library, const ProceduralSeam& seam,
    const SubmitEdit& submit);

}  // namespace uzp::procedural
