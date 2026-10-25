#pragma once

#include "evaluator/procedural_source.h"
#include "procedural/admission.h"
#include "procedural/snapshot_backend.h"
#include "store/project_store.h"

#include <expected>
#include <string>
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

private:
    /// The admitted request of a fill source and the snapshots that admitted it, or why not.
    std::expected<std::pair<ProceduralRequest, SnapshotBackend>, std::string> Admitted(
        const core::Project& project, const core::TextureSet& set, core::ChannelType channel,
        core::ChannelFormat format, const core::FillContent& fill, const core::ProceduralRef& ref,
        core::Id node, bool mask) const;

    store::ProjectStore& store_;
    core::Project project_;
};

}  // namespace uzp::procedural
