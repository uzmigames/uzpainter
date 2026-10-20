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

#include <expected>
#include <functional>
#include <map>
#include <string>

namespace uzp::procedural {

/// What a procedural use needs from its place in the document.
struct UseContext {
    std::string meshClass;
    uint32_t uvTiles = 1;
    RasterSpec output;
    /// The spec of each image input the reference binds, by input name.
    std::map<std::string, RasterSpec> inputs;
    uint64_t seed = 0;
    TileRect tile;
};

/// The request of `ref` in `context`: its pinned asset; its parameters over the record's defaults
/// when the library holds the asset (booleans as integers); its preset; its image inputs by
/// hash, with the specs of `context`. Refused: a URL that is not a pin, a parameter that is not a
/// number, a boolean or a string, and an image input whose spec `context` does not give.
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
