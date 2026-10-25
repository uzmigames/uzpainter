#include "procedural/filter_observation_source.h"

#include <cstdint>
#include <limits>
#include <set>
#include <stdexcept>
#include <utility>

#include "store/filter_observations.h"
#include "store/planes.h"
#include "store/snapshots.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/recipe.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/resource_url.h"

namespace uzp::procedural {
namespace {
using core::json::Array;
using core::json::Object;
using core::json::Value;

void Require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
const Object& ObjectOf(const Value& value) { return std::get<Object>(value.data); }
const std::string& Text(const Object& value, const char* key) { return std::get<std::string>(value.at(key).data); }
bool SameTyped(const Value& a, const Value& b) {
    return core::json::WriteCanonical(a) == core::json::WriteCanonical(b);
}

void ParametersMatch(const Object& stored, const Object& observed) {
    Require(stored.size() == observed.size(), "parameter names differ from the descriptor");
    for (const auto& [name, value] : stored) {
        const auto found = observed.find(name);
        Require(found != observed.end(), "parameter names differ from the descriptor");
        const auto a = store::ParamByValue(value);
        const auto b = store::ParamByValue(found->second);
        Require(a && b && SameTyped(*a, *b), "parameters differ from the descriptor");
    }
}

struct Domain {
    const core::TextureSet* set = nullptr;
    const core::Stack* stack = nullptr;
    const core::Layer* host = nullptr;
    const core::Effect* filter = nullptr;
    const core::ProceduralRef* host_ref = nullptr;
    core::ChannelType channel = core::ChannelType::BaseColor;
};

void ReferenceDomain(const core::ProceduralRef& ref) {
    Require(core::IsObservationPin(ref.asset), "the reference is not an observation descriptor pin");
    Require(!ref.preset && ref.image_inputs.empty(), "presets and external procedural inputs are outside V1");
    for (const auto& [name, value] : ref.params) {
        (void)name;
        Require(store::ParamByValue(value).has_value(), "unsupported core parameter type");
    }
}

Domain CheckDomain(const core::Project& project, const Value& manifest) {
    Require(store::ManifestPlaneReferences(manifest).empty() && store::ManifestPlaneBindings(manifest).empty(),
            "raster plane references or bindings are outside V1");
    const auto snapshots = project.extra.find(std::string(store::kSnapshotsKey));
    Require(snapshots == project.extra.end() ||
                (snapshots->second.IsObject() && ObjectOf(snapshots->second).empty()),
            "procedural snapshots must be absent or an empty object");
    Require(!project.display.environment.resource && !project.display.color_lut,
            "environment and LUT resources are outside V1");
    Domain result;
    for (const auto& set : project.texture_sets) {
        Require(set.mesh_maps.empty(), "mesh maps are outside V1");
        for (const auto& stack : set.stacks) {
            for (const auto& layer : stack.root_layers) {
                Require(result.host == nullptr, "V1 requires exactly one host Fill");
                result.set = &set;
                result.stack = &stack;
                result.host = &layer;
            }
        }
    }
    Require(result.host != nullptr, "V1 requires one host Fill");
    const auto& host = *result.host;
    // Same neutral-mask predicate as the evaluator DAG; no Painter default is assumed.
    Require(!host.geometry_mask.inclusion_list && host.geometry_mask.items.empty(),
            "active geometry masks are outside V1");
    Require(host.kind == core::LayerKind::fill && host.fill && !host.paint && !host.mask &&
                host.children.empty() && host.instance_source == core::kNoId && !host.preset_ref,
            "host shape is outside V1");
    const auto& fill = *host.fill;
    Require(fill.source_mode == core::SourceMode::Split && fill.sources.size() == 1 &&
                fill.active_channels.size() == 1 && !fill.mono_source && !fill.material_source,
            "host must have one active Split source");
    result.channel = fill.sources.begin()->first;
    Require(fill.active_channels.contains(result.channel) && result.stack->channels.contains(result.channel),
            "host source channel is not its sole active declared channel");
    const auto* source = std::get_if<core::ProceduralSource>(&fill.sources.begin()->second.value);
    Require(source != nullptr, "host must have a procedural source");
    result.host_ref = &source->ref;
    ReferenceDomain(*result.host_ref);
    Require(host.content_effects.size() == 1, "V1 requires exactly one content Filter");
    result.filter = &host.content_effects.front();
    const auto& filter = *result.filter;
    Require(filter.kind == core::EffectKind::filter && filter.procedural && !filter.fill && !filter.paint &&
                !filter.levels && !filter.compare_mask && !filter.color_selection && !filter.anchor_name &&
                !filter.preset_ref && !filter.mono_blending,
            "content effect is outside the Filter-only domain");
    ReferenceDomain(*filter.procedural);
    return result;
}

Object Context(store::ProjectStore& store, const core::Project& project, const std::string& uuid) {
    Value manifest = core::ProjectToJson(project);
    CheckDomain(project, manifest);
    std::get<Object>(manifest.data).erase(std::string(store::kFilterObservationsKey));
    Require(project.mesh.has_value(), "mesh resource is missing");
    const std::string& hash = project.mesh->resource;
    Require(project.resources.size() == 1 && project.resources.contains(hash), "resource catalog must contain only the mesh");
    const std::set<std::string> onlyMesh{hash};
    Require(core::MeshResourceHashes(project) == onlyMesh && core::RecipeResourceHashes(project) == onlyMesh,
            "external graph resources are outside V1");
    const auto external = project.mesh->import_report.find(core::kMeshExternalFiles);
    Require(external == project.mesh->import_report.end() ||
                (external->second.IsArray() && std::get<Array>(external->second.data).empty()),
            "external mesh inputs are outside V1");
    const auto& metadata = project.resources.at(hash);
    Require(!metadata.empty(), "mesh resource metadata is missing");
    const auto& first = metadata.front();
    Require(!first.mime.empty() && first.size >= 0, "mesh metadata MIME or size is invalid");
    for (const auto& item : metadata) {
        Require(item.mime == first.mime && item.size == first.size, "mesh resource metadata disagrees");
    }
    const std::string bytes = store.ReadResource(hash);
    Require(bytes.size() <= static_cast<size_t>(std::numeric_limits<std::int64_t>::max()) &&
                static_cast<std::int64_t>(bytes.size()) == first.size && core::Sha256Hex(bytes) == hash,
            "mesh bytes do not match snapshot metadata and identity");
    return Object{{"schema", std::string(store::kObservationContextSchema)}, {"project", std::move(manifest)},
                  {"store_uuid", uuid},
                  {"resources", Array{Object{{"binding_path", std::string("/mesh/resource")},
                                             {"kind", std::string("mesh")}, {"identity", hash}, {"mime", first.mime},
                                             {"sha256", hash}, {"size_bytes", first.size}}}}};
}
}  // namespace

std::expected<Object, std::string> CurrentFilterObservationContext(store::ProjectStore& store,
                                                                  const core::Project& project) {
    try {
        const std::string uuid = store.project_uuid();
        return Context(store, project, uuid);
    } catch (const std::exception&) {
        return std::expected<Object, std::string>(
            std::unexpect, "filter observation: current project is outside the verified V1 context");
    }
}

std::expected<FilterObservation, std::string> ObservedFilter(store::ProjectStore& store,
                                                           const core::Project& project, core::Id filter_uid) {
    try {
        const std::string uuid = store.project_uuid();
        const auto namespaceIt = project.extra.find(std::string(store::kFilterObservationsKey));
        Require(namespaceIt != project.extra.end(), "observation namespace is missing");
        Require(store::FilterObservationsProblem(namespaceIt->second, uuid).empty(), "observation namespace is invalid");
        const auto& space = ObjectOf(namespaceIt->second);
        const auto& bindings = ObjectOf(space.at("bindings"));
        const auto binding = bindings.find(std::to_string(filter_uid));
        Require(binding != bindings.end(), "Filter observation binding is missing");
        const std::string key = std::get<std::string>(binding->second.data);
        const auto& entry = ObjectOf(ObjectOf(space.at("entries")).at(key));
        const auto& recorded = ObjectOf(entry.at("binding"));
        const Domain domain = CheckDomain(project, core::ProjectToJson(project));
        const auto matchesId = [&](const char* name, core::Id id) {
            const auto value = std::get<std::int64_t>(recorded.at(name).data);
            return value >= 0 && static_cast<std::uint64_t>(value) == static_cast<std::uint64_t>(id);
        };
        Require(domain.filter->uid == filter_uid && matchesId("filter_uid", filter_uid) &&
                    matchesId("host_uid", domain.host->uid) && matchesId("texture_set", domain.set->id) &&
                    matchesId("stack", domain.stack->id) && matchesId("effect_index", 0) &&
                    Text(recorded, "node_stack") == "Content" &&
                    Text(recorded, "host_channel") == core::ToString(domain.channel),
                "Filter observation position or channel is stale");
        Require(SameTyped(recorded.at("host_reference"), core::ProceduralRefToJson(*domain.host_ref)) &&
                    SameTyped(recorded.at("filter_reference"), core::ProceduralRefToJson(*domain.filter->procedural)),
                "complete procedural reference is stale");
        const auto& descriptors = ObjectOf(space.at("descriptors"));
        const auto& hostDescriptor = ObjectOf(descriptors.at(Text(entry, "host_descriptor")));
        const auto& filterDescriptor = ObjectOf(descriptors.at(Text(entry, "filter_descriptor")));
        ParametersMatch(domain.host_ref->params, ObjectOf(hostDescriptor.at("parameters")));
        ParametersMatch(domain.filter->procedural->params, ObjectOf(filterDescriptor.at("parameters")));
        const Object context = Context(store, project, uuid);
        Require(SameTyped(entry.at("context"), context) && Text(entry, "context_sha256") == store::ObservationKey(context),
                "Filter observation context is stale");
        FilterObservation result;
        result.entry_key = key;
        const auto& observations = ObjectOf(entry.at("observations"));
        if (const auto value = observations.find("parameters"); value != observations.end()) {
            result.parameters = ObjectOf(value->second);
        }
        if (const auto value = observations.find("resource_id"); value != observations.end()) {
            result.resource_id = ObjectOf(value->second);
        }
        if (const auto value = observations.find("image_outputs"); value != observations.end()) {
            result.image_outputs.emplace();
            for (const auto& name : std::get<Array>(value->second.data)) {
                result.image_outputs->push_back(std::get<std::string>(name.data));
            }
        }
        return result;
    } catch (const std::exception&) {
        return std::expected<FilterObservation, std::string>(
            std::unexpect, "filter observation: missing, invalid, foreign, stale or mismatched observation");
    }
}

}  // namespace uzp::procedural
