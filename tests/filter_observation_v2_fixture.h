#pragma once

// The authored V2 Filter observation fixture (decision 363) shared by the store tests and the
// procedural tests. Everything here is synthetic: the provenance hashes are placeholders, never
// Painter records, and the native proof record built here is a self-consistent structure only, not
// execution evidence. The mesh is the public authored plane (parity/fixtures/meshes/plane.obj),
// read beside this header so the test binaries do not depend on their working directory.

#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>

#include "store/filter_observations.h"
#include "store/observation_inventory.h"
#include "store/planes.h"
#include "store/project_store.h"
#include "store/snapshots.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/project.h"

namespace uzp::v2fixture {

namespace json = uzp::core::json;

/// The authored host resource URL (not a Painter resource): the snapshot pin names its SHA-256.
inline constexpr const char* kHostUrl = "resource://authored/host?version=1";

/// The bytes of the public authored plane, checked against the domain's mesh literal.
inline std::string PlaneObj() {
    const std::filesystem::path path =
        // `__FILE__` is the path the includer named (`tests/store/../filter_observation_v2_fixture.h`).
        std::filesystem::path(__FILE__).lexically_normal().parent_path().parent_path() / "parity" / "fixtures" /
        "meshes" / "plane.obj";
    std::ifstream file(path, std::ios::binary);
    std::ostringstream bytes;
    bytes << file.rdbuf();
    const std::string data = bytes.str();
    if (core::Sha256Hex(data) != store::kFrozenHostPlaneMesh) {
        throw std::runtime_error("the authored plane at " + path.string() + " is not the domain's mesh");
    }
    return data;
}

/// The host's snapshot pin.
inline std::string HostAsset() { return "uzasset://snapshot/" + core::Sha256Hex(kHostUrl) + "@1"; }

/// The Filter descriptor: an authored ResourceID and decision 361 parameters (an integral double
/// and a negative zero, which the canonical hash keeps).
inline json::Object FilterDescriptor() {
    return json::Object{{"schema", std::string(store::kObservationDescriptorSchema)},
                        {"role", std::string("filter")},
                        {"resource_id", json::Object{{"url", std::string("resource://authored/filter?version=1")},
                                                     {"context", std::string("authored")},
                                                     {"name", std::string("filter")},
                                                     {"version", std::string("1")}}},
                        {"parameters", json::Object{{"radius", 1.0}, {"zero", -0.0}}}};
}

/// The node ids of a scene.
struct SceneIds {
    core::Id set = core::kNoId;
    core::Id stack = core::kNoId;
    core::Id host = core::kNoId;
    core::Id paint = core::kNoId;
    core::Id filter = core::kNoId;
};

/// The frozen-host scene with `host_amount` as the host's parameter and `filter_pin` as the
/// Filter's reference; its snapshots are recorded afterwards.
inline core::Project Scene(const std::string& filter_pin, std::size_t plane_bytes, SceneIds& ids,
                           double host_amount = 0.5) {
    core::Project p;
    p.versions.app_version = "0.0.0";
    p.versions.evaluator_profile = "painter-12.1-isolated-linear";
    core::TextureSet set;
    set.id = ids.set = p.AllocateId();
    set.name = "uzp_plane";
    set.original_name = "uzp_plane";
    set.material_id = "material-0";
    set.resolution.width = 128;
    set.resolution.height = 128;
    set.uv_tiles = {core::UVTile{p.AllocateId(), 1001, {}}};
    core::Stack stack;
    stack.id = ids.stack = p.AllocateId();
    stack.channels[core::ChannelType::User0] = core::Channel{core::ChannelFormat::L32F, "", {}};

    core::Layer host;
    host.uid = ids.host = p.AllocateId();
    host.kind = core::LayerKind::fill;
    host.name = "host";
    host.blending[core::ChannelType::User0] = core::Blending{core::BlendingMode::Normal, 1.0, {}};
    core::ProceduralSource source;
    source.ref.asset = HostAsset();
    source.ref.params = {{"amount", host_amount}};
    source.ref.output_mapping = {{"User0", "scalar"}};
    core::FillContent fill;
    fill.source_mode = core::SourceMode::Split;
    fill.sources[core::ChannelType::User0] = core::Source{source};
    fill.active_channels = {core::ChannelType::User0};
    host.fill = std::move(fill);
    core::Effect filter;
    filter.uid = ids.filter = p.AllocateId();
    filter.kind = core::EffectKind::filter;
    filter.name = "Blur";
    filter.active_channels = {core::ChannelType::User0};
    filter.blending[core::ChannelType::User0] = core::Blending{core::BlendingMode::Normal, 1.0, {}};
    filter.procedural.emplace();
    filter.procedural->asset = filter_pin;
    filter.procedural->params = {{"radius", std::int64_t{1}}, {"zero", 0.0}};
    host.content_effects.push_back(std::move(filter));

    core::Layer paint;
    paint.uid = ids.paint = p.AllocateId();
    paint.kind = core::LayerKind::paint;
    paint.name = "Layer 1";
    paint.paint = core::PaintContent{};
    stack.root_layers = {std::move(host), std::move(paint)};
    set.stacks = {std::move(stack)};
    p.texture_sets = {std::move(set)};

    core::ResourceMeta meta;
    meta.id = p.AllocateId();
    meta.name = "plane.obj";
    meta.mime = "model/obj";
    meta.size = static_cast<std::int64_t>(plane_bytes);
    meta.usage = "MESH";
    meta.origin = "import";
    meta.imported_at = "2026-10-26T00:00:00Z";
    p.resources[std::string(store::kFrozenHostPlaneMesh)] = {meta};
    p.mesh.emplace();
    p.mesh->resource = std::string(store::kFrozenHostPlaneMesh);
    return p;
}

/// An authored 128 x 128 L32F raster: finite values from `seed`.
inline store::PlaneImage Raster(std::uint32_t seed) {
    store::PlaneImage image{128, 128, core::ChannelFormat::L32F, std::string(128 * 128 * 4, '\0')};
    for (std::size_t i = 0; i < 128 * 128; ++i) {
        const std::uint32_t bits = 0x3E800000u + static_cast<std::uint32_t>((i * 104729u + seed) & 0x3FFFFFu);
        std::memcpy(image.texels.data() + i * 4, &bits, 4);
    }
    return image;
}

/// `/3` metadata of a host snapshot with `amount`: both observations, or only one of them.
inline store::SourceMetadata Metadata(double amount, bool typed = true, bool identified = true) {
    store::SourceMetadata metadata;
    metadata.image_outputs = {"scalar"};
    if (typed) metadata.typed_effective_parameters = json::Object{{"amount", amount}};
    if (identified) metadata.observed_resource_id = store::ObservedResourceId{kHostUrl, "authored", "host", "1"};
    return metadata;
}

/// A store-level host signature (the shape of procedural `SignatureJson`) with `amount`, the output
/// `format` and `seed`; the procedural tests record the provider's own request instead.
inline json::Object Signature(double amount, const std::string& format = "f32", std::int64_t seed = 0) {
    return json::Object{
        {"asset", "uzasset://snapshot/" + core::Sha256Hex(kHostUrl)},
        {"version", std::string("1")},
        {"params", json::Object{{"amount", amount}}},
        {"preset", json::Value()},
        {"seed", seed},
        {"output", json::Object{{"id", std::string("scalar")}, {"resolution", std::int64_t{128}},
                                {"format", format}, {"colour_space", std::string("raw")}, {"channels", std::int64_t{1}}}},
        {"inputs", json::Object{}},
        {"mesh", json::Object{{"class", std::string("quad")}, {"uv_tiles", std::int64_t{1}}}},
        {"settings", json::Object{}}};
}

/// The V2 context of `project`, from one census of the store.
inline json::Object Context(store::ProjectStore& store, const core::Project& project) {
    json::Value manifest = core::ProjectToJson(project);
    std::get<json::Object>(manifest.data).erase(std::string(store::kFilterObservationsKey));
    return json::Object{{"schema", std::string(store::kObservationContextSchemaV2)},
                        {"project", std::move(manifest)},
                        {"store_uuid", store.project_uuid()},
                        {"inventory", store.ReadObservationInventory(project).ToJson()}};
}

inline json::Object ArtifactRef(const std::string& kind, const std::string& seed) {
    return json::Object{{"kind", kind}, {"sha256", core::Sha256Hex(seed)}, {"size_bytes", std::int64_t{1}}};
}

/// The census plane `plane_id` of a context.
inline const json::Object& ContextPlane(const json::Object& context, std::int64_t plane_id) {
    for (const json::Value& plane : std::get<json::Array>(std::get<json::Object>(context.at("inventory").data).at("planes").data)) {
        const auto& object = std::get<json::Object>(plane.data);
        if (std::get<std::int64_t>(object.at("plane_id").data) == plane_id) return object;
    }
    throw std::runtime_error("the context holds no plane " + std::to_string(plane_id));
}

/// Recomputes the hashes an entry derives from its context (context hash, destination host
/// context, proof projection and inventory hashes), after a test changed the context.
inline void Reseal(json::Object& entry) {
    const json::Object& context = std::get<json::Object>(entry.at("context").data);
    const std::string hash = store::ObservationKey(context);
    entry["context_sha256"] = hash;
    auto& migration = std::get<json::Object>(std::get<json::Object>(entry.at("capture").data).at("migration").data);
    migration["destination_host_context_sha256"] = hash;
    auto& proof = std::get<json::Object>(migration.at("native_evidence").data);
    proof["prospective_projection_sha256"] = store::ObservationKey(context.at("project"));
    proof["inventory_sha256"] = store::ObservationKey(context.at("inventory"));
}

/// A complete, self-consistent synthetic V2 entry of `project` (inside the frozen-host domain)
/// observing `descriptor`, over the host snapshot `host_key` of `context`.
inline json::Object Entry(const std::string& project_uuid, const json::Object& descriptor, const json::Object& context,
                          const core::Project& project, const std::string& host_key) {
    store::FrozenHostNodes nodes;
    if (const std::string problem = store::FrozenHostDomainProblem(project, nodes); !problem.empty()) {
        throw std::runtime_error("fixture outside the domain: " + problem);
    }
    std::int64_t planeId = 0;
    for (const store::SnapshotEntry& snapshot : store::ProjectSnapshots(project)) {
        if (snapshot.key == host_key) planeId = static_cast<std::int64_t>(snapshot.plane_id);
    }
    const json::Object& plane = ContextPlane(context, planeId);
    const std::string raster = std::get<std::string>(plane.at("sha256").data);
    const std::string contextHash = store::ObservationKey(context);
    const json::Object proof{
        {"schema", std::string(store::kFrozenHostProofSchema)},
        {"rule", std::string(store::kFrozenHostRule)},
        {"validator_code_sha256", core::Sha256Hex("authored validator")},
        {"binary_sha256", core::Sha256Hex("authored binary")},
        {"domain_sha256", store::ObservationKey(store::FrozenHostDomain())},
        {"project_uuid", project_uuid},
        {"prospective_projection_sha256", store::ObservationKey(context.at("project"))},
        {"inventory_sha256", store::ObservationKey(context.at("inventory"))},
        {"signature_sha256", host_key},
        {"plane_id", planeId},
        {"version_id", plane.at("version_id")},
        {"chunk_root", plane.at("chunk_root")},
        {"raster_sha256", raster},
        {"uploaded_sha256", raster},
        {"final_output_sha256", raster},
        {"sample_count", std::int64_t{128 * 128}},
        {"nonfinite_count", std::int64_t{0}},
        {"fixed_point_mismatches", std::int64_t{0}},
        {"upload_mismatches", std::int64_t{0}},
        {"final_output_mismatches", std::int64_t{0}}};
    const json::Object provenance{
        {"recorder", std::string("authored")},
        {"envelope_id", std::string("authored")},
        {"painter_build_id", std::string("authored")},
        {"recipe_sha256", core::Sha256Hex("recipe")},
        {"resource_query", std::string("authored")},
        {"authored_inputs", json::Array{}},
        {"receipts", json::Array{json::Object{{"condition", std::string("same_session")}, {"sha256", core::Sha256Hex("r1")}},
                                 json::Object{{"condition", std::string("after_save_reopen")},
                                              {"sha256", core::Sha256Hex("r2")}}}}};
    const auto round = [](const char* condition) {
        const std::string c(condition);
        return json::Object{{"condition", c},
                            {"probe_sequence_sha256", core::Sha256Hex(c + " probes")},
                            {"context_readback_sha256", core::Sha256Hex(c + " context")},
                            {"host_readback_sha256", core::Sha256Hex(c + " host")},
                            {"filter_readback_sha256", core::Sha256Hex(c + " filter")}};
    };
    const json::Object capture{
        {"schema", std::string(store::kObservationCaptureSchemaV2)},
        {"filter", json::Object{{"provenance", provenance},
                                {"manifest", ArtifactRef("filter_manifest", "manifest")},
                                {"record", ArtifactRef("filter_record", "record")},
                                {"environment", ArtifactRef("filter_environment", "environment")},
                                {"rounds", json::Array{round("same_session"), round("after_save_reopen")}}}},
        // The same blob twice: repeated identical exports are legitimate.
        {"host", json::Object{{"protocol", std::string("paired-scalar-rgb")},
                              {"receipt", ArtifactRef("snapshot_receipt", "receipt")},
                              {"request", ArtifactRef("snapshot_request", "request")},
                              {"environment", json::Value()},
                              {"environment_binding", json::Value()},
                              {"scalar_exports", json::Array{ArtifactRef("snapshot_scalar_export", "scalar"),
                                                             ArtifactRef("snapshot_scalar_export", "scalar")}},
                              {"rgb_exports", json::Array{ArtifactRef("snapshot_rgb_export", "rgb"),
                                                          ArtifactRef("snapshot_rgb_export", "rgb")}}}},
        {"migration", json::Object{{"rule", std::string(store::kFrozenHostRule)},
                                   {"raster_stage", std::string("frozen_output")},
                                   {"raster_sha256", raster},
                                   {"capture_context_sha256", core::Sha256Hex("authored H readback context")},
                                   {"destination_host_context_sha256", contextHash},
                                   {"native_evidence", proof}}}};
    const std::string filterKey = store::ObservationKey(descriptor);
    return json::Object{
        {"schema", std::string(store::kObservationEntrySchemaV2)},
        {"project_uuid", project_uuid},
        {"role", std::string("filter")},
        {"host_snapshot", json::Object{{"signature_sha256", host_key}, {"plane_id", planeId}}},
        {"filter_descriptor", filterKey},
        {"binding", json::Object{{"texture_set", static_cast<std::int64_t>(nodes.set->id)},
                                 {"stack", static_cast<std::int64_t>(nodes.stack->id)},
                                 {"host_uid", static_cast<std::int64_t>(nodes.host->uid)},
                                 {"filter_uid", static_cast<std::int64_t>(nodes.filter->uid)},
                                 {"initial_paint_uid", static_cast<std::int64_t>(nodes.paint->uid)},
                                 {"node_stack", std::string("Content")},
                                 {"effect_index", std::int64_t{0}},
                                 {"host_channel", std::string("User0")},
                                 {"host_reference", core::ProceduralRefToJson(*nodes.host_ref)},
                                 {"filter_reference", core::ProceduralRefToJson(*nodes.filter->procedural)}}},
        {"context", context},
        {"context_sha256", contextHash},
        {"capture", capture},
        {"observations", json::Object{{"parameters", descriptor.at("parameters")},
                                      {"resource_id", descriptor.at("resource_id")},
                                      {"image_outputs", json::Array{}}}}};
}

/// The V2 namespace holding `entries` (the first bound to `filter_uid`) and `descriptor`.
inline json::Object Namespace(const json::Object& descriptor, const std::vector<json::Object>& entries, core::Id filter_uid) {
    json::Object stored;
    for (const json::Object& entry : entries) stored[store::ObservationKey(entry)] = entry;
    return json::Object{{"schema", std::string(store::kFilterObservationsSchemaV2)},
                        {"descriptors", json::Object{{store::ObservationKey(descriptor), descriptor}}},
                        {"entries", std::move(stored)},
                        {"bindings", json::Object{{std::to_string(filter_uid), store::ObservationKey(entries.front())}}}};
}

}  // namespace uzp::v2fixture
