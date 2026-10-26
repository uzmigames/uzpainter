#include "procedural/frozen_host_proof.h"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <utility>

#include "evaluator/admission.h"
#include "evaluator/cpu_store.h"
#include "evaluator/dag.h"
#include "evaluator/evaluate.h"
#include "procedural/seam.h"
#include "procedural/snapshot_source.h"
#include "store/filter_observations.h"
#include "store/observation_inventory.h"
#include "store/snapshots.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

namespace uzp::procedural {
namespace {

using core::json::Object;
using core::json::Value;

constexpr std::uint32_t kSide = 128;
constexpr std::size_t kSamples = std::size_t{kSide} * kSide;

// This validator's own source, embedded at build time (decision 147: the build keys this object on
// these bytes), so the record names the code the binary was built from.
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc23-extensions"
constexpr unsigned char kHeaderSource[] = {
#embed "frozen_host_proof.h"
};
constexpr unsigned char kSource[] = {
#embed "frozen_host_proof.cpp"
};
#pragma clang diagnostic pop


void Require(bool condition, const std::string& reason) {
    if (!condition) throw std::runtime_error(reason);
}

/// The SHA-256 of the running executable's file, read whole: a short or failed read refuses rather
/// than hashing part of it.
std::string BinarySha256() {
    std::wstring name(32768, L'\0');
    const DWORD length = GetModuleFileNameW(nullptr, name.data(), static_cast<DWORD>(name.size()));
    Require(length != 0 && length != name.size(), "cannot locate the running executable");
    name.resize(length);
    const std::filesystem::path path(name);
    std::error_code error;
    const std::uintmax_t size = std::filesystem::file_size(path, error);
    Require(!error && size > 0, "cannot size the running executable");
    std::ifstream file(path, std::ios::binary);
    Require(static_cast<bool>(file), "cannot open the running executable");
    std::string bytes(static_cast<std::size_t>(size), '\0');
    file.read(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    Require(!file.bad() && file.gcount() == static_cast<std::streamsize>(bytes.size()) &&
                file.peek() == std::ifstream::traits_type::eof(),
            "cannot read the whole running executable");
    return core::Sha256Hex(bytes);
}

/// A real `CpuTileStore` behind every call; `Upload` is witnessed after the actual call by reading
/// the same tile back through the real store, and bitmap projections are counted.
class UploadWitness final : public evaluator::ITileStore {
public:
    [[nodiscard]] render::Result<evaluator::ExecutionIdentity> Execution() const override { return m_store.Execution(); }
    render::Result<evaluator::TileHandle> Allocate(const evaluator::TileFormat& format, uint32_t width,
                                                   uint32_t height) override {
        return m_store.Allocate(format, width, height);
    }
    void Release(evaluator::TileHandle tile) override { m_store.Release(tile); }
    render::Result<void> Upload(evaluator::TileHandle tile, const evaluator::DecodedImage& image, uint32_t x0,
                                uint32_t y0) override {
        auto uploaded = m_store.Upload(tile, image, x0, y0);
        if (!uploaded) return uploaded;
        auto read = m_store.Read(tile);
        if (!read) return render::Unexpected(read.error());
        m_uploads.push_back(std::move(*read));
        return {};
    }
    render::Result<void> Project(const evaluator::ProjectOp& op) override {
        ++m_projects;
        return m_store.Project(op);
    }
    render::Result<void> Blend(const evaluator::BlendOp& op) override { return m_store.Blend(op); }
    render::Result<void> Levels(const evaluator::LevelsOp& op) override { return m_store.Levels(op); }
    render::Result<void> VirtualNormal(const evaluator::VirtualNormalOp& op) override { return m_store.VirtualNormal(op); }
    render::Result<void> Flush() override { return m_store.Flush(); }
    render::Result<evaluator::TileImage> Read(evaluator::TileHandle tile) override { return m_store.Read(tile); }
    [[nodiscard]] uint64_t AllocatedBytes() const override { return m_store.AllocatedBytes(); }

    [[nodiscard]] const std::vector<evaluator::TileImage>& Uploads() const { return m_uploads; }
    [[nodiscard]] std::uint64_t Projects() const { return m_projects; }

private:
    evaluator::CpuTileStore m_store;
    std::vector<evaluator::TileImage> m_uploads;
    std::uint64_t m_projects = 0;
};

/// The 128 x 128 single-channel float32 texels of `bytes` as bits.
std::vector<std::uint32_t> Bits(const std::byte* bytes, std::size_t size, const std::string& what) {
    Require(size == kSamples * 4, what + " is not one 128 x 128 L32F tile");
    std::vector<std::uint32_t> bits(kSamples);
    std::memcpy(bits.data(), bytes, size);
    return bits;
}

std::string BitsSha256(const std::vector<std::uint32_t>& bits) {
    return core::Sha256Hex(std::string_view(reinterpret_cast<const char*>(bits.data()), bits.size() * 4));
}

std::int64_t Mismatches(const std::vector<std::uint32_t>& a, const std::vector<std::uint32_t>& b) {
    std::int64_t count = 0;
    for (std::size_t i = 0; i < a.size(); ++i) count += a[i] != b[i];
    return count;
}

}  // namespace

std::uint32_t FrozenHostReadout(std::uint32_t bits) {
    const float v = std::bit_cast<float>(bits);
    const float shifted = v - 1.0f;
    const float restored = 1.0f + shifted;
    return std::bit_cast<std::uint32_t>(restored);
}

std::string FrozenHostValidatorCodeSha256() {
    std::string source(reinterpret_cast<const char*>(kHeaderSource), sizeof(kHeaderSource));
    source.append(reinterpret_cast<const char*>(kSource), sizeof(kSource));
    return core::Sha256Hex(source);
}

std::expected<FrozenHostRun, std::string> RunFrozenHostProof(store::ProjectStore& store, const core::Project& prospective,
                                                             const evaluator::TemplateLibrary& templates) {
    try {
        // The domain, the host's exact request and its recorded snapshot.
        store::FrozenHostNodes nodes;
        const std::string domain = store::FrozenHostDomainProblem(prospective, nodes);
        Require(domain.empty(), "the project is outside the frozen-host domain: " + domain);
        const core::Layer& host = *nodes.host;
        auto request = SnapshotFillRequest(prospective, *nodes.set, core::ChannelType::User0, core::ChannelFormat::L32F,
                                           *host.fill, *nodes.host_ref, host.uid, false);
        Require(request.has_value(), "the host is outside the snapshot provider's domain");
        const std::string signature = SignatureHash(*request);
        std::optional<store::SnapshotEntry> snapshot;
        for (store::SnapshotEntry& entry : store::ProjectSnapshots(prospective)) {
            if (entry.key == signature) snapshot = std::move(entry);
        }
        Require(snapshot && snapshot->version, "no recorded snapshot holds the host's exact request");

        // The census before the run, and the host plane in it.
        const store::ObservationInventory inventory = store.ReadObservationInventory(prospective);
        const auto plane = std::find_if(inventory.planes.begin(), inventory.planes.end(), [&](const store::InventoryPlane& p) {
            return p.row.plane_id == snapshot->plane_id;
        });
        Require(plane != inventory.planes.end() && plane->row.format == core::ChannelFormat::L32F &&
                    plane->row.width == static_cast<int>(kSide) && plane->row.height == static_cast<int>(kSide),
                "the host snapshot plane is not one 128 x 128 L32F raster");

        // The proof scene: the observed Filter alone removed, everything else (the empty Paint
        // included) kept; the prospective project itself unchanged.
        const std::string before = core::json::WriteCanonical(core::ProjectToJson(prospective));
        core::Project proof = prospective;
        auto& effects = proof.texture_sets[0].stacks[0].root_layers[0].content_effects;
        Require(effects.size() == 1 && effects.front().uid == nodes.filter->uid, "the observed Filter is not the host's one effect");
        effects.clear();
        Value expected = core::ProjectToJson(prospective);
        auto& layers = std::get<core::json::Array>(
            std::get<Object>(std::get<core::json::Array>(
                std::get<Object>(std::get<core::json::Array>(std::get<Object>(expected.data).at("texture_sets").data)[0].data)
                    .at("stacks").data)[0].data).at("root_layers").data);
        std::get<Object>(layers[0].data)["content_effects"] = core::json::Array{};
        Require(core::json::WriteCanonical(core::ProjectToJson(proof)) == core::json::WriteCanonical(expected),
                "the proof scene differs from the project in more than the observed Filter");
        Require(core::IsEmptyPaintLayer(proof.texture_sets[0].stacks[0].root_layers[1]), "the proof scene lost its empty Paint");

        // The real provider and DAG under the registered profile.
        SnapshotSourceProvider provider(store, proof);
        const core::TextureSet& set = proof.texture_sets[0];
        auto dag = evaluator::BuildDag(proof, set.id, set.stacks[0].id, core::ChannelType::User0, templates,
                                       proof.settings.template_id, &provider);
        Require(dag.has_value(), "the proof DAG does not build: " + (dag ? std::string() : dag.error().reason));
        Require(dag->profile.id == proof.versions.evaluator_profile && dag->profile.root == evaluator::RootComposite::Isolated &&
                    dag->root.isolated && dag->readoutBase[0] == 1.0f,
                "the registered profile is not the rule's isolated read-out over base 1");
        Require(dag->root.layers.size() == 1 && dag->root.layers[0].source &&
                    dag->root.layers[0].source->kind == evaluator::DagSource::Kind::Procedural &&
                    dag->root.layers[0].source->procedural && dag->root.layers[0].effects.empty() &&
                    !dag->root.layers[0].maskStack && !dag->root.layers[0].group,
                "the proof DAG is not the one procedural host layer");
        const evaluator::DecodedImage& image = dag->root.layers[0].source->procedural->image;
        Require(image.width == kSide && image.height == kSide && image.channels == 1 &&
                    image.encoding == render::TexelEncoding::Float32 && image.values.size() == kSamples,
                "the resolved host image is not one 128 x 128 float32 channel");

        FrozenHostRun run;
        run.source = image.values;
        Require(BitsSha256(run.source) == plane->sha256, "the resolved host image is not the census plane's raster");
        for (const std::uint32_t bits : run.source) {
            run.nonfinite += !std::isfinite(std::bit_cast<float>(bits));
            run.fixed_point_mismatches += FrozenHostReadout(bits) != bits;
        }

        // The cold full chain on a real CPU store, the upload witnessed.
        UploadWitness witness;
        evaluator::TileCache cache(evaluator::AdmissionLimits{1ull << 30, 1ull << 20});
        evaluator::EvalEnvironment environment{witness, cache};
        environment.procedurals = &provider;
        auto result = evaluator::EvaluateChannel(*dag, environment);
        Require(result.has_value(), "the proof evaluation fails: " + (result ? std::string() : result.error().reason));
        run.uploads = witness.Uploads().size();
        run.projects = witness.Projects();
        Require(run.uploads == 1 && run.projects == 0, "exactly one procedural upload and no projection must be observed");
        const evaluator::TileImage& uploaded = witness.Uploads().front();
        Require(uploaded.width == kSide && uploaded.height == kSide, "the uploaded tile is not 128 x 128");
        run.uploaded = Bits(uploaded.texels.data(), uploaded.texels.size(), "the uploaded tile");
        Require(result->tiles.size() == 1 && !result->tiles[0].constant && result->tiles[0].width == kSide &&
                    result->tiles[0].height == kSide && result->format == core::ChannelFormat::L32F,
                "the final output is not one 128 x 128 L32F tile");
        run.final = Bits(result->tiles[0].texels.data(), result->tiles[0].texels.size(), "the final tile");
        run.upload_mismatches = Mismatches(run.uploaded, run.source);
        run.final_output_mismatches = Mismatches(run.final, run.source);

        // The prospective view must not have changed during the run.
        Require(core::json::WriteCanonical(core::ProjectToJson(prospective)) == before, "the prospective project changed");
        const store::ObservationInventory after = store.ReadObservationInventory(prospective);
        Require(after.Sha256() == inventory.Sha256(), "the census changed during the proof");

        Value projection = core::ProjectToJson(prospective);
        std::get<Object>(projection.data).erase(std::string(store::kFilterObservationsKey));
        run.evidence = Object{
            {"schema", std::string(store::kFrozenHostProofSchema)},
            {"rule", std::string(store::kFrozenHostRule)},
            {"validator_code_sha256", FrozenHostValidatorCodeSha256()},
            {"binary_sha256", BinarySha256()},
            {"domain_sha256", store::ObservationKey(store::FrozenHostDomain())},
            {"project_uuid", inventory.project_uuid},
            {"prospective_projection_sha256", store::ObservationKey(projection)},
            {"inventory_sha256", store::ObservationKey(inventory.ToJson())},
            {"signature_sha256", signature},
            {"plane_id", static_cast<std::int64_t>(snapshot->plane_id)},
            {"version_id", plane->version.version_id},
            {"chunk_root", plane->version.chunk_root},
            {"raster_sha256", plane->sha256},
            {"uploaded_sha256", BitsSha256(run.uploaded)},
            {"final_output_sha256", BitsSha256(run.final)},
            {"sample_count", static_cast<std::int64_t>(kSamples)},
            {"nonfinite_count", run.nonfinite},
            {"fixed_point_mismatches", run.fixed_point_mismatches},
            {"upload_mismatches", run.upload_mismatches},
            {"final_output_mismatches", run.final_output_mismatches}};
        return run;
    } catch (const std::exception& error) {
        return std::expected<FrozenHostRun, std::string>(std::unexpect, std::string("frozen-host proof: ") + error.what());
    }
}

}  // namespace uzp::procedural
