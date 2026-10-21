#include "bake/bake_publication.h"

#include <algorithm>
#include <stdexcept>
#include <utility>
#include <vector>

#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

namespace uzp::bake {

using core::NotYetSupported;
using core::ValueError;

namespace {

constexpr const char* kOwner = "phase3.3_baker-evidence-publication, decision 347";

core::MeshMapUsage CoreUsage(MeshMapUsage usage) {
    const std::optional<core::MeshMapUsage> value = core::FromString<core::MeshMapUsage>(UsageName(usage));
    if (!value) throw std::logic_error(std::string("no project mesh-map usage ") + UsageName(usage));
    return *value;
}

/// Stages `bytes` and gives them a resource entry named `name` unless one exists.
std::string AddResource(core::Edit& edit, const StageResource& stage, std::string bytes, const std::string& mime,
                        const std::string& name, const std::string& usage, const std::string& origin,
                        const std::string& when) {
    const std::string expected = core::Sha256Hex(bytes);
    const auto size = static_cast<std::int64_t>(bytes.size());
    const std::string sha256 = stage(std::move(bytes), mime);
    if (sha256 != expected) throw std::logic_error("the resource stager returned another hash");
    std::vector<core::ResourceMeta>& entries = edit.project().resources[sha256];
    if (std::any_of(entries.begin(), entries.end(), [&](const core::ResourceMeta& m) { return m.name == name; })) {
        edit.NoteSkippedResource(sha256);
        return sha256;
    }
    core::ResourceMeta meta;
    meta.id = edit.AllocateId();
    meta.name = name;
    meta.mime = entries.empty() ? mime : entries.front().mime;
    meta.size = size;
    meta.usage = usage;
    meta.origin = origin;
    meta.imported_at = when;
    meta.color_space = "Raw";
    entries.push_back(std::move(meta));
    return sha256;
}

/// The digest of the per-part custom cages: SHA-256 of their content hashes, one per line.
std::optional<std::string> CageDigest(const BakeReceipt& receipt) {
    std::string joined;
    for (const ReceiptPart& part : receipt.inputs.parts) {
        if (!part.cage.sha256) return std::nullopt;
        joined += *part.cage.sha256 + "\n";
    }
    return core::Sha256Hex(joined);
}

}  // namespace

core::ChannelFormat PublishedFormat(MeshMapUsage usage) {
    switch (usage) {
        case MeshMapUsage::AO: return core::ChannelFormat::L16;
        case MeshMapUsage::Normal: return core::ChannelFormat::RGB16;
        case MeshMapUsage::WorldSpaceNormal:
        case MeshMapUsage::Position:
        case MeshMapUsage::Opacity:
        case MeshMapUsage::Height:
            throw NotYetSupported(std::string("publishing ") + UsageName(usage) +
                                  ": its map is float32 with no established channel format (decisions 337 and 341); "
                                  "a binding declares Painter's format, which the Tier 2b goldens settle (owner " +
                                  UsageOwnerTask(usage) + ", " + kOwner + ")");
        case MeshMapUsage::ID:
            throw NotYetSupported(
                "publishing ID: the bake makes the Mesh ID labels only, no colour map (decision 337; owner "
                "phase3.4_baker-id, " + std::string(kOwner) + ")");
        case MeshMapUsage::Thickness:
            throw NotYetSupported(
                "publishing Thickness: the bake keeps per-ray evidence only, no per-texel value (decision 341; owner "
                "phase3.4_baker-thickness, " + std::string(kOwner) + ")");
        case MeshMapUsage::Curvature:
        case MeshMapUsage::BentNormals: break;
    }
    throw NotYetSupported(std::string("publishing ") + UsageName(usage) + ": the CPU baker does not bake it (owner " +
                          UsageOwnerTask(usage) + ")");
}

PublicationOutcome PublishBake(core::Document& document, core::MutationRequest mutation, const BakeRequest& request,
                               const BakeResult& result, const Capabilities& caps, const PublicationContext& context,
                               const StageResource& stage) {
    PublicationOutcome publication;
    std::optional<BakeReceipt> receipt;
    std::string receipt_sha;
    publication.outcome = core::Execute(document, std::move(mutation), [&](core::Edit& edit) {
        // Every check before any change.
        const std::int64_t revision = document.revision();
        if (request.input_revision != std::to_string(revision)) {
            throw ValueError("the bake read input revision '" + request.input_revision + "', the document is at " +
                             std::to_string(revision) + ": a stale bake is not published (" + kOwner + ")");
        }
        if (result.diagnostic_unqualified) {
            throw ValueError("a bake on the diagnostic path of an unqualified BVH build is never evidence and is not "
                             "published (decision 306)");
        }
        if (context.published_at.empty()) throw ValueError("publication needs the time of the new resource entries");
        core::Project& project = edit.project();
        const auto set = std::find_if(project.texture_sets.begin(), project.texture_sets.end(),
                                      [&](const core::TextureSet& s) { return s.name == request.texture_set; });
        if (set == project.texture_sets.end()) {
            throw ValueError("the project has no texture set '" + request.texture_set + "'");
        }
        if (set->resolution.width != static_cast<int>(result.width) ||
            set->resolution.height != static_cast<int>(result.height)) {
            throw NotYetSupported("publishing a " + std::to_string(result.width) + "x" + std::to_string(result.height) +
                                  " bake into texture set '" + set->name + "' of " +
                                  std::to_string(set->resolution.width) + "x" + std::to_string(set->resolution.height) +
                                  ": resampling a mesh map is not established (" + kOwner + ")");
        }
        std::vector<core::ChannelFormat> formats;
        for (MeshMapUsage usage : request.usages) formats.push_back(PublishedFormat(usage));
        if (std::find(request.usages.begin(), request.usages.end(), MeshMapUsage::Normal) != request.usages.end()) {
            if (result.normal_format != project.settings.normal_map_format ||
                result.tangent_space != project.settings.tangent_space) {
                throw ValueError("the Normal bake's format or tangent space is not the project's");
            }
        }
        core::ResultRecordHeader header;
        header.revision = revision;
        header.evaluator_profile = project.versions.evaluator_profile;
        header.compat_profile = project.versions.compat_profile;
        header.app_version = project.versions.app_version;
        header.resource_hashes = context.input_resources;
        receipt = BuildReceipt(request, result, caps, ReceiptContext{context.job_id, header, context.build_hash});

        // The maps, the receipt, then the bindings.
        const std::string origin = "bake job " + std::to_string(context.job_id);
        std::vector<std::string> maps;
        for (MeshMapUsage usage : request.usages) {
            std::string bytes = EncodeMapFile(*CompatibleMap(result, usage));
            maps.push_back(AddResource(edit, stage, std::move(bytes), "image/png",
                                       set->name + "." + UsageName(usage) + ".baked.png", "mesh_map", origin,
                                       context.published_at));
            if (maps.back() != receipt->usages[maps.size() - 1].map_sha256) {
                throw std::logic_error("the published map is not the receipt's");
            }
        }
        receipt_sha = AddResource(edit, stage, ReceiptBytes(*receipt), "application/json",
                                  set->name + ".bake-receipt." + std::to_string(context.job_id) + ".json",
                                  "bake_receipt", origin, context.published_at);
        const std::optional<std::string> cage = CageDigest(*receipt);
        const core::MeshHashes mesh_hashes = LowMeshHashes(request);
        const std::vector<const BakeMesh*>& high = request.detail.low_as_high ? request.low : request.high;
        for (std::size_t u = 0; u < request.usages.size(); ++u) {
            const ReceiptUsage& entry = receipt->usages[u];
            core::BakedProvenance baked;
            baked.baker_version = receipt->tools.baker_version;
            baked.backend = receipt->tools.backend;
            baked.settings_hash = receipt->settings_hash;
            for (const BakeMesh* mesh : high) baked.high_meshes.push_back(MeshContentHash(*mesh));
            baked.cage = cage;
            baked.mesh_hashes = mesh_hashes;
            baked.effective_normalization = entry.effective_normalization;
            baked.extra = core::json::Object{
                {"receipt", receipt_sha},
                {"job_id", core::json::Value(context.job_id)},
                {"fidelity_evidence", FidelityEvidenceName(entry.account.fidelity_evidence)},
                {"parity_status", receipt->parity_status},
            };
            core::MeshMapBinding binding;
            binding.resource = maps[u];
            binding.format = formats[u];
            binding.color_space = "Raw";
            binding.provenance = std::move(baked);
            set->mesh_maps[CoreUsage(request.usages[u])] = std::move(binding);
        }
        edit.returned()["bake"] = core::json::Object{{"receipt", receipt_sha},
                                                     {"texture_set", set->name},
                                                     {"input_revision", request.input_revision}};
    });
    const core::RequestOutcome& outcome = publication.outcome;
    if (outcome.result && outcome.result->status == core::ResultStatus::committed) {
        publication.receipt = std::move(receipt);
        publication.receipt_sha256 = receipt_sha;
    }
    return publication;
}

}  // namespace uzp::bake
