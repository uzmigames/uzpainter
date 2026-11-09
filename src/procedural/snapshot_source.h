#pragma once

#include "evaluator/procedural_source.h"
#include "procedural/admission.h"
#include "procedural/snapshot_backend.h"
#include "store/project_store.h"

#include <expected>
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

/// The request a snapshot fill source asks for, from `project` alone (no store read): the
/// provider's domain (a User L32F fill on the recorded 128px full-UV plane under Legacy, the
/// identity UV or Fill projection with BilinearHQ and Repeat, one explicit scalar output mapping,
/// no raster image input or mask output; a preset and plugged input sources join the signature),
/// `SnapshotUseContext` and `RequestFor`, at a source
/// resolution of 128. A fill in Material mode is `SnapshotMaterialRequest` (channel Height only). `SnapshotSourceProvider` admits only such a request; this does not say that
/// a snapshot holds it.
std::expected<ProceduralRequest, std::string> SnapshotFillRequest(
    const core::Project& project, const core::TextureSet& set, core::ChannelType channel, core::ChannelFormat format,
    const core::FillContent& fill, const core::ProceduralRef& ref, core::Id node, bool mask);

/// Why a material fill whose mask output is not the output mapped to Height is refused (P413-C:
/// such a mask is exact in the same session only; its save/reopen value differs).
inline constexpr std::string_view kMaterialMaskRefusal =
    "a material mask output other than the output mapped to Height is not recorded exactly "
    "(phase3.3_procedural-families item 2.7)";

/// The request a material fill (`SourceMode::Material`, decision 413, P413-A/C) asks for: the
/// shared capture domain of `SnapshotFillRequest`, Height active and mapped, no raster image input,
/// a mask output absent or equal to Height's output (`kMaterialMaskRefusal` otherwise); its preset
/// and plugged input sources join the signature. The request is the raw F32 scalar view of the
/// output mapped to Height. Only Height is evaluated: Painter's material fill activates Height only,
/// as `tz16(float32(2 x - 1))` of that view (the Height bitmap rule).
std::expected<ProceduralRequest, std::string> SnapshotMaterialRequest(const core::Project& project,
                                                                      const core::TextureSet& set,
                                                                      const core::FillContent& fill,
                                                                      const core::ProceduralRef& ref, core::Id node);

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
