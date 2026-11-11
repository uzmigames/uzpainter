#pragma once

#include "evaluator/procedural_source.h"
#include "procedural/admission.h"
#include "procedural/snapshot_backend.h"
#include "store/project_store.h"

#include <expected>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace uzp::procedural {

/// The use context of a snapshot fill source of texture set `set` (the provider's admission and
/// `assets bind-snapshot`): the recorded plane's mesh class, the set's UV tiles and square
/// resolution as a raw F32 scalar parent output, `outputId`, `EvaluationSettings(project)`, the
/// seed of the effective `$randomseed` integer (int64 bits kept as uint64; absent means zero) and
/// the set's dimensions for the TextureSet/UVTile modes. Nothing is taken from a signature.
/// Refused for a non-square set, a set without UV tiles and a non-integer seed.
std::expected<UseContext, std::string> SnapshotUseContext(const core::Project& project, const core::TextureSet& set,
                                                         const core::ProceduralRef& ref, const std::string& outputId);

/// The request a source `ref` of output `outputId` asks for on texture set `set` (decision 428):
/// `SnapshotUseContext` and `RequestFor`, at an effective source resolution equal to the set's.
/// Refused outside the capture settings: one square texture set of one UV tile 1001 at a
/// power-of-two resolution from 128 to 4096 on an imported mesh, under the default workflow,
/// Legacy, OpenGL normals, PerVertex tangents and mesh scale 1. The mesh's identity is a signature
/// field (`EvaluationSettings`), so another mesh is a signature mismatch, not a domain refusal.
std::expected<ProceduralRequest, std::string> SnapshotSetRequest(const core::Project& project, const core::TextureSet& set,
                                                                 const core::ProceduralRef& ref, const std::string& outputId);

/// The image inputs a generator snapshot's signature holds: every mesh map bound to `set`, by
/// usage name, with the binding's SHA-256 and its spec (the set's resolution and the binding's
/// sample type, channels and colour space, as `MeshMapSpec` of generators.h gives them). Refused
/// for an invalid binding. A generator capture plugs exactly these maps into Painter.
std::expected<std::map<std::string, ImageInput>, std::string> SnapshotMeshMapInputs(const core::TextureSet& set);

/// The request a generator `ref` asks for on `set` (decision 428): `SnapshotSetRequest` with the
/// set's mesh maps (`SnapshotMeshMapInputs`) as its image inputs. Refused when the reference binds
/// image inputs or plugged sources itself.
std::expected<ProceduralRequest, std::string> SnapshotGeneratorRequest(const core::Project& project, const core::TextureSet& set,
                                                                       const core::ProceduralRef& ref, const std::string& outputId);

/// The request a snapshot fill source asks for, from `project` alone (no store read): the
/// provider's domain (a User L32F fill in the capture settings of `SnapshotSetRequest`, the
/// identity UV or Fill projection with BilinearHQ and Repeat, one explicit scalar output mapping,
/// no raster image input or mask output; a preset and plugged input sources join the signature),
/// `SnapshotUseContext` and `RequestFor`, at the set's resolution. A fill in Material mode is `SnapshotMaterialRequest` of `channel` and `format`. `SnapshotSourceProvider` admits only such a request; this does not say that
/// a snapshot holds it. With `mask`, the source of a fill effect of a mask stack (decision 431):
/// the same capture domain and projection, only the fixed grunges `grunge/rock` and
/// `grunge/dirt-large`, no preset, image input or plugged source, and the output named by
/// `mask_output` (no output mapping); `channel` and `format` play no part.
std::expected<ProceduralRequest, std::string> SnapshotFillRequest(
    const core::Project& project, const core::TextureSet& set, core::ChannelType channel, core::ChannelFormat format,
    const core::FillContent& fill, const core::ProceduralRef& ref, core::Id node, bool mask);

/// Why a material fill whose mask output is not the output mapped to Height is refused (P413-C:
/// such a mask is exact in the same session only; its save/reopen value differs).
inline constexpr std::string_view kMaterialMaskRefusal =
    "a material mask output other than the output mapped to Height is not recorded exactly "
    "(phase3.3_procedural-families item 2.7)";

/// Why a material channel outside the recorded channel rules is refused (item 2.16).
inline constexpr std::string_view kMaterialChannelOwner = "phase3.3_procedural-families item 2.16";

/// The channel view a material fill's `channel` of `format` reads (decision 413, P413-A; the
/// 2026-11-11 material channel survey): Height (L16F or L32F), BaseMetalness and SpecularRoughness
/// (L8) read the raw F32 scalar view (1); BaseColor (sRGB8) and Normal (RGB16F) the RGB view (3).
/// Empty for any other channel or format, which no recording composes.
std::optional<uint32_t> MaterialChannelView(core::ChannelType channel, core::ChannelFormat format);

/// The request a material fill (`SourceMode::Material`, decision 413, P413-A/C, item 2.16) asks for
/// on `channel` of `format`: the shared capture domain of `SnapshotFillRequest`, the channel mapped,
/// no raster image input; on Height a mask output absent or equal to Height's output
/// (`kMaterialMaskRefusal` otherwise), on another channel none. Its preset and plugged input
/// sources join the signature. The request is the `MaterialChannelView` of the output mapped to the
/// channel (refused, naming `kMaterialChannelOwner`, for an unrecorded channel or format). The
/// defaults are Height's scalar view, which the material handle's recorded reads use.
std::expected<ProceduralRequest, std::string> SnapshotMaterialRequest(const core::Project& project,
                                                                      const core::TextureSet& set,
                                                                      const core::FillContent& fill,
                                                                      const core::ProceduralRef& ref, core::Id node,
                                                                      core::ChannelType channel = core::ChannelType::Height,
                                                                      core::ChannelFormat format = core::ChannelFormat::L32F);

/// Provider lifetime must not outlive the store. Each revision owns its provider.
class SnapshotSourceProvider final : public evaluator::IProceduralSourceProvider {
public:
    SnapshotSourceProvider(store::ProjectStore& store, const core::Project& project);
    render::Result<std::shared_ptr<const evaluator::ProceduralImage>> Resolve(
        const core::Project& project, const core::TextureSet& set, core::ChannelType channel,
        core::ChannelFormat format, const core::FillContent& fill, const core::ProceduralRef& ref,
        core::Id node, bool mask) const override;
    bool Available(const evaluator::ProceduralImage& image) const override;
    /// A copy of the `image_outputs` recorded with the snapshot that serves this fill source's
    /// current exact signature, or why there is none (the same admission as `Resolve`; a snapshot
    /// of any other signature is never consulted).
    std::expected<std::vector<std::string>, std::string> ImageOutputs(
        const core::Project& project, const core::TextureSet& set, core::ChannelType channel,
        core::ChannelFormat format, const core::FillContent& fill, const core::ProceduralRef& ref,
        core::Id node, bool mask) const;
    /// A copy of the whole `source_metadata` of that same snapshot, or why there is none.
    std::expected<store::SourceMetadata, std::string> Metadata(
        const core::Project& project, const core::TextureSet& set, core::ChannelType channel,
        core::ChannelFormat format, const core::FillContent& fill, const core::ProceduralRef& ref,
        core::Id node, bool mask) const;

    /// The observations recorded with the snapshot serving this fill source's current exact
    /// signature (decision 361). Empty only when legitimately absent: the source names no snapshot
    /// asset, no snapshot holds its exact signature, or that snapshot recorded no metadata. Any
    /// other failure (a corrupt, foreign or unloadable store, a use outside the admitted domain,
    /// an invalid reference) is an error, never an absence.
    std::expected<std::optional<store::SourceMetadata>, std::string> Observations(
        const core::Project& project, const core::TextureSet& set, core::ChannelType channel,
        core::ChannelFormat format, const core::FillContent& fill, const core::ProceduralRef& ref,
        core::Id node, bool mask) const;

private:
    /// The admitted request of a fill source and the snapshots that admitted it, or why not.
    /// `unrecorded`, when given, is set when the loaded snapshots hold no entry of the request's
    /// exact signature.
    std::expected<std::pair<ProceduralRequest, SnapshotBackend>, std::string> Admitted(
        const core::Project& project, const core::TextureSet& set, core::ChannelType channel,
        core::ChannelFormat format, const core::FillContent& fill, const core::ProceduralRef& ref,
        core::Id node, bool mask, bool* unrecorded = nullptr) const;

    store::ProjectStore& store_;
    core::Project project_;
};

}  // namespace uzp::procedural
