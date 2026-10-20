#pragma once

// UzPainter's material family (docs/architecture/05-procedural-content.md §3, the Materials row;
// rulebook task phase3.2_proc-material-families; decision 334): felt, burlap, leather grain
// and leather pattern, each `uzasset://material/<id>@1`, usage BASE_MATERIAL. A material is a
// multi-output asset: one texture of one UV tile per output, each reached through a request's
// output id (`ProceduralRequest::outputId`, `SourceSubstance.active_output`), which a material
// source maps to channels with `output_mapping` (05 §7). Every material has the same six
// outputs (its record's `outputs`):
//
//   basecolor          RGB, srgb    the colour, shaded by the material's tone field
//   normal             RGB, linear  tangent space, encoded n x 0.5 + 0.5, green = +v (OpenGL)
//   roughness          mono, linear
//   metallic           mono, linear 0: the materials are dielectrics
//   height             mono, linear the relief in [0, 1]
//   ambient_occlusion  mono, linear 1 - the crevice term
//
// Every output is computed from two per-texel fields of the material, its height and its tone,
// over periodic lattices (the cell index taken modulo the period: the texture wraps seamlessly):
//
// - felt (Kallmes and Corte 1960, a non-woven mat of straight fibres of random position and
//   orientation): two layers of fibre segments per cell, their directions from a table that
//   `fibre_alignment` narrows, kept with a probability that `fibre_density` sets, over fBm
//   clouds of Perlin 2002 noise (Musgrave's fBm, Ebert et al.);
// - burlap (Peachey's periodic weave in Ebert et al.; Irawan and Marschner 2012 for the twisted
//   fibres along a yarn): a plain weave of warp and weft yarns with a `gap` between them, a
//   thickness that varies per yarn (`irregularity`), slanted twist ridges and a `fuzz` of fBm;
// - leather grain (Worley 1996): domed cells with grooves at their borders (F2 - F1 under
//   `groove_width`), the points' jitter set by `irregularity`, and pores from a finer Worley
//   lattice (`pore_amount`);
// - leather pattern (Worley 1996; Musgrave's ridged multifractal): deep creases at coarse cell
//   borders (`crease_depth`), ridged-fBm wrinkles (`wrinkles`) and a fine cell grain
//   (`grain_amount`).
//
// From the fields: basecolor = Clamp01(colour x (1 + color_variation x (2 tone - 1))); roughness
// = Clamp01(roughness + roughness_variation x (1/2 - height)); the normal is Blinn's 1978
// perturbed normal from the height's central differences (scaled by `normal_intensity` x R /
// 256, so it does not depend on the resolution R), normalised by Lomont's inverse square root
// with four Newton steps; ambient_occlusion is 1 - ao_intensity x Clamp01(4 x (mean - height)),
// the mean of the height R / 512 texels away in the four directions (Luft, Colditz and Deussen
// 2006). The normal and the occlusion read the height of neighbouring texels, so they run in two
// passes: the fields over the whole texture, then the output.
//
// One source for both lanes: the kernel functions are written once, in
// `shaders/proc_materials.hlsli`, in a subset of HLSL that is also C++ (flushed single operations
// of the primitive library, dyadic constants, integer hashing). The HLSL host compiles them with
// the generated wrapper; materials.cpp compiles the same text as the CPU reference. A parameter
// block computed on the host (`MaterialWords`) carries every derived float, so the kernel has no
// division and no transcendental, and DX12 equals the CPU reference bit for bit.
//
// Physical size (`PhysicalScale`): a material's record states the size its texture spans
// (`physical_size_cm`). A UV projection with `ScaleMode.MaterialPhysicalSize` or
// `CustomPhysicalSize` (scale in centimetres, A-PYDOC) repeats the texture by that size under the
// project unit rule (12-mesh-import.md §3: Painter's unit is the centimetre, `mesh_unit_scale`
// 0/None follows the file unit), and the effective units are recorded.
//
// None of these assets is certified: the records say `unavailable`, the seam refuses them, and no
// alias of the library names them (decision 324). The domains are those of the records.

#include "procedural/admission.h"
#include "procedural/asset_library.h"
#include "procedural/hlsl_backend.h"
#include "procedural/seam.h"

#include "uzp_core/manifest/json.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/project.h"

#include <array>
#include <cstdint>
#include <expected>
#include <map>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace uzp::procedural {

/// The family of every material asset (`uzasset://material/<id>@1`).
inline constexpr std::string_view kMaterialFamily = "material";

/// The ids of the family's assets: felt, burlap, leather-grain, leather-pattern.
[[nodiscard]] std::span<const std::string_view> MaterialAssetIds();

/// The output ids every material has, in record order.
[[nodiscard]] std::span<const std::string_view> MaterialOutputIds();

/// The joint rule of a material request, which the domain's JSON cannot state: the request names
/// one of the record's outputs, and its output spec has that output's channels and colour space.
/// The refusal (`outside certified domain`) names the field (`output.id`, `output.channels`,
/// `output.colour_space`), the value and the output's value. Empty when the rule holds.
[[nodiscard]] std::optional<UnsupportedProcedural> MaterialJointRefusal(const ProceduralRequest& request,
                                                                        const AssetRecord& record);

/// Registers every material with `hlsl`, each with the record `library` holds for it (its domain,
/// its outputs, its status, its provenance). Refused when the library lacks a record, a record
/// does not list the six outputs, or the host refuses the registration.
std::expected<void, std::string> RegisterMaterialFamilies(HlslBackend& hlsl, const AssetLibrary& library);

/// The parameter block of the kernel pass of `request` that writes its output (or, with
/// `fields`, the first pass of a two-pass output: the height and tone fields). Refused for an
/// asset outside the family, an unknown output or a parameter the request lacks.
[[nodiscard]] std::expected<std::vector<uint32_t>, std::string> MaterialWords(const ProceduralRequest& request,
                                                                              bool fields = false);

/// The CPU reference of the single-pass function of `words` (an output that reads no
/// neighbour, or the fields pass) at texel (x, y), for the request seed `seed`: the kernel's
/// float4. Any integer position is valid: a position outside [0, R) gives the texture continued
/// periodically, so (x + R, y) and (x, y + R) give the texel of (x, y).
[[nodiscard]] std::array<float, 4> MaterialTexel(std::span<const uint32_t> words, int32_t x, int32_t y,
                                                 uint32_t seed);

/// The default `output_mapping` of a material: each output to the channel its record names
/// (BaseColor, Normal, Roughness, Metallic, Height, AO).
[[nodiscard]] std::map<std::string, std::string> DefaultOutputMapping(const AssetRecord& record);

/// One channel of a material source and the request that evaluates it.
struct MaterialChannelRequest {
    core::ChannelType channel;
    ProceduralRequest request;
};

/// The requests of a material reference `ref` in `context`, one per entry of
/// `ref.output_mapping`, in channel order: `RequestFor` with the mapped output id, and the
/// output spec of `context` with the channels and colour space of that output in the record.
/// Refused: an empty mapping, a key that is not a ChannelType, and an output the record does not
/// list (`outside certified domain`, field `output_mapping.<channel>`). For an asset the library
/// does not hold, the spec of `context` is used as given and admission decides.
[[nodiscard]] std::expected<std::vector<MaterialChannelRequest>, UnsupportedProcedural> MaterialRequests(
    const core::ProceduralRef& ref, const UseContext& context, const AssetLibrary& library);

/// Sets `ref` as the material source of the fill layer `layer` (`SourceMode.Material`), in one
/// transaction of `submit`, after `MaterialRequests` and `Admit` of every mapped channel. A
/// refusal returns before `submit` is called: the revision does not advance, nothing is clamped
/// or substituted. An admitted reference is committed exactly as given.
std::expected<core::RequestOutcome, UnsupportedProcedural> SetMaterialSource(
    core::Id layer, const core::ProceduralRef& ref, const UseContext& context, const AssetLibrary& library,
    const ProceduralSeam& seam, const SubmitEdit& submit);

// ── Physical size (item 2.4) ─────────────────────────────────────────────────

/// The effective scale of a physical-size projection of a material, and the units it was derived
/// under (PRJ-07): what an evaluation or export receipt records.
///
/// - The size one texture spans: the record's `physical_size_cm` for `MaterialPhysicalSize`, the
///   transformation's `scale` (centimetres, A-PYDOC) for `CustomPhysicalSize`.
/// - The project unit rule (12 §3): the mesh import report's `units` give the centimetres per
///   file unit (`scale_to_internal`), whether they follow the file unit or `mesh_unit_scale`
///   (`from`), and the scale requested. A 3D projection repeats the texture
///   `cm per file unit / size` times per file unit of position.
/// - The UV projection: one UV unit of the texture set spans `sqrt(W H) / p50` centimetres, where
///   p50 is the import certificate's surface-weighted median texel density of the set (px/cm on
///   its W x H grid), so the texture repeats `cm per UV / size` times per UV unit. Painter's own
///   rule is not discovered (item 2.1; test 3.2's oracle half), and this one is UzPainter's.
struct PhysicalScale {
    core::ScaleMode mode = core::ScaleMode::MaterialPhysicalSize;
    std::array<double, 2> physicalSizeCm{};
    std::string sizeFrom;  ///< "material" or "custom".
    std::string unitsSource;
    std::string unitsFrom;  ///< "file" or "mesh_unit_scale".
    std::optional<double> requestedMeshUnitScale;
    double cmPerFileUnit = 1.0;
    std::array<double, 2> texturesPerFileUnit{};
    std::string textureSet;  ///< The certificate's set (the texture set's material id).
    double densityPxPerCm = 0.0;
    std::array<int64_t, 2> grid{};
    double cmPerUv = 0.0;
    std::array<double, 2> uvScale{};

    /// `{scale_mode, physical_size_cm, size_from, units {source, from, requested_mesh_unit_scale,
    /// scale_to_internal}, textures_per_file_unit, uv {texture_set, density_px_per_cm_p50, grid,
    /// cm_per_uv, scale}}`.
    [[nodiscard]] core::json::Object ToJson() const;
};

/// The physical scale of `transformation` for `material` on texture set `set` of the project's
/// `mesh`. Refused (the reason): the `Factors` mode (not a physical size), a `CustomPhysicalSize`
/// scale that is not two finite positive centimetre values, `MaterialPhysicalSize` for an asset
/// without a physical size (or none given), and an import report without units, a positive
/// `scale_to_internal`, a certificate grid or a positive density for the set.
[[nodiscard]] std::expected<PhysicalScale, std::string> EvaluatePhysicalScale(
    const core::UVTransformation& transformation, const AssetRecord* material, const core::MeshReference& mesh,
    const core::TextureSet& set);

}  // namespace uzp::procedural
