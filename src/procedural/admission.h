#pragma once

// Procedural edits through the seam (docs/architecture/05-procedural-content.md §2, §4, §6;
// decision 324 §10): the request of a stored `ProceduralRef`, and the edit that sets one on a
// generator or filter effect only after the seam has admitted it. A request that no backend can
// serve is refused before any transaction opens: the revision does not advance, nothing is
// clamped, nothing is evaluated and no other asset is substituted.
//
// The project stores what the user chose (`ProceduralRef`: the pinned asset, the parameters, the
// preset, the image inputs by hash). What evaluation also needs comes from where the procedural
// is used (`UseContext`: the target's output spec, the mesh class, the image inputs' specs, the
// seed, the tile); its callers resolve it from the texture set, the channel and the mesh (item
// 2.6, phase3.3_procedural-families).

#include "procedural/asset_library.h"
#include "procedural/seam.h"

#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/project.h"

#include <expected>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <string_view>

namespace uzp::procedural {

/// The image input of a filter: the layer content at the filter's position in the effect list
/// (05 §3; filters.h).
inline constexpr std::string_view kContentInput = "content";

/// What a procedural use needs from its place in the document.
struct UseContext {
    std::string meshClass;
    uint32_t uvTiles = 1;
    RasterSpec output;
    /// The spec of each image input the reference binds, by input name.
    std::map<std::string, RasterSpec> inputs;
    /// A filter's `content` input: the spec and the hash of the layer content at the filter's
    /// position in the effect list (05 §3). It is not stored in the reference: it changes with
    /// every edit below the filter.
    std::optional<ImageInput> content;
    uint64_t seed = 0;
    TileRect tile;
    /// The asset output the use evaluates (`ProceduralRequest::outputId`).
    std::string outputId;
    /// The project settings that affect evaluation (`EvaluationSettings`).
    Params settings;
};

/// The project settings that affect a procedural evaluation, as the signature names them
/// (05 §4, decision 327): `normal_map_format`, `tangent_space`, `mesh_unit_scale` and the colour
/// management's `color_management.mode`, `color_management.config_hash`,
/// `color_management.working_space` and `color_management.io_rules_sha256` (the SHA-256 of the
/// rules' canonical JSON). Every setting that can change a procedural's texels is listed, so a
/// snapshot recorded under other settings never matches.
[[nodiscard]] Params EvaluationSettings(const core::ProjectSettings& settings);
/// Recording and project-backed callers additionally pin the actual imported mesh bytes.
/// A mesh reload changes the signature even when its class, UV tiles and settings are unchanged.
[[nodiscard]] Params EvaluationSettings(const core::Project& project);

/// The request of `ref` in `context`: its pinned asset; its parameters over the record's defaults
/// when the library holds the asset (booleans as integers); its preset; its image inputs by
/// hash, with the specs of `context`; the output id and settings of `context`; and the
/// context's `content` input of a filter. Refused: a URL that is not a pin, a parameter that is
/// not a supported scalar, vector or tagged color, an image input whose spec `context` does not give, and a
/// bound input named `content` beside the context's.
[[nodiscard]] std::expected<ProceduralRequest, UnsupportedProcedural> RequestFor(
    const core::ProceduralRef& ref, const UseContext& context, const AssetLibrary& library);

/// The backend that serves `request`, or the refusal. A snapshot with the exact signature serves
/// it whether or not the library holds the asset (05 §4); otherwise a pin the library does not
/// hold is refused as such, and any other refusal is the seam's.
[[nodiscard]] std::expected<IProceduralBackend*, UnsupportedProcedural> Admit(
    const ProceduralRequest& request, const AssetLibrary& library, const ProceduralSeam& seam);

/// Submits one transaction (`ProjectStore::Submit` or `core::Execute` with the caller's request).
using SubmitEdit = std::function<core::RequestOutcome(const std::function<void(core::Edit&)>&)>;

/// Sets `ref` as the procedural of the generator or filter effect `effect`, in one transaction of
/// `submit`, after `RequestFor` and `Admit`. A refusal returns before `submit` is called.
std::expected<core::RequestOutcome, UnsupportedProcedural> SetEffectProcedural(
    core::Id effect, const core::ProceduralRef& ref, const UseContext& context,
    const AssetLibrary& library, const ProceduralSeam& seam, const SubmitEdit& submit);

}  // namespace uzp::procedural
