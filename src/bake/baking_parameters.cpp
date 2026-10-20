#include "bake/baking_parameters.h"

#include <algorithm>
#include <limits>
#include <set>
#include <stdexcept>

#include "uzp_core/types/errors.h"

namespace uzp::bake {

using core::NotYetSupported;
using core::ValueError;

const char* PropertyTypeName(PropertyType type) {
    switch (type) {
        case PropertyType::Bool: return "Bool";
        case PropertyType::Int: return "Int";
        case PropertyType::IntPair: return "IntPair";
        case PropertyType::Enum: return "Enum";
        case PropertyType::String: return "String";
        case PropertyType::Pending: return "Pending";
    }
    return "unknown";
}

namespace {

// Sources (`docs/approved-sources.md`).
constexpr const char* kTask = "docs/architecture/06-baking.md section 2 (key)";
constexpr const char* kPage =
    "A-HELP-BAKING, https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/baking/"
    "mesh-map-settings (label, widget)";
constexpr const char* kPyDoc =
    "python-doc substance_painter/baking.html, module example (option label)";

std::string Join(std::initializer_list<const char*> parts) {
    std::string out;
    for (const char* part : parts) out += (out.empty() ? "" : "; ") + std::string(part);
    return out;
}

PropertySpec Spec(std::string key, PropertyGroup group, PropertyType type, std::string label,
                  std::string source, std::string description) {
    PropertySpec spec;
    spec.short_name = std::move(key);
    spec.group = group;
    spec.type = type;
    spec.label = std::move(label);
    spec.source = std::move(source);
    spec.description = std::move(description);
    return spec;
}

PropertySpec WithOptions(PropertySpec spec, std::vector<std::string> options, bool complete) {
    spec.option_labels = std::move(options);
    spec.options_complete = complete;
    return spec;
}

PropertySpec WithDefault(PropertySpec spec, PropertyValue value, std::string source) {
    spec.default_value = std::move(value);
    spec.default_source = std::move(source);
    return spec;
}

std::vector<PropertySpec> BuildSpecs() {
    using G = PropertyGroup;
    using T = PropertyType;
    const std::string task_page = Join({kTask, kPage});
    const char* listed = "docs/architecture/06-baking.md section 2 (listed default)";
    std::vector<PropertySpec> specs;
    // Common.
    specs.push_back(Spec("OutputSize", G::Common, T::IntPair, "Output size",
                         Join({kTask, "the log2 pair", kPage}),
                         "Width and height of the baked maps, each written as a power-of-two exponent."));
    specs.push_back(Spec("DilationWidth", G::Common, T::Int, "Dilation width",
                         Join({kTask, "a count of texels", kPage}),
                         "How many texels the baked values are carried outward from the UV islands into "
                         "unused texture space."));
    specs.push_back(Spec("ApplyDiffusion", G::Common, T::Bool, "Apply diffusion", task_page,
                         "Whether the texels reached by dilation are also smoothed as they spread."));
    // Detail (high-poly).
    specs.push_back(Spec("HipolyMesh", G::Detail, T::String, "High definition meshes",
                         Join({kTask, "file:/// URLs joined by '|'", kPage}),
                         "The high-resolution meshes the maps are baked from, as a '|'-separated list of "
                         "file URLs."));
    specs.push_back(Spec("LowAsHigh", G::Detail, T::Bool, "Use Low poly mesh as high poly mesh", task_page,
                         "Take the texture set's own mesh as the bake source instead of separate "
                         "high-resolution meshes."));
    specs.push_back(WithOptions(
        Spec("CageMode", G::Detail, T::Enum, "Cage", task_page,
             "Where the primary rays start: at fixed distances along the low normal, on an "
             "automatically built shell, or on a cage mesh the user supplies."),
        {"Distance based", "Automatic (experimental)", "Custom file"}, true));
    specs.push_back(Spec("CageMesh", G::Detail, T::Pending, "", kTask,
                         "The user-supplied cage mesh used by the custom cage mode."));
    specs.push_back(Spec("MaxHeight", G::Detail, T::Pending, "", kTask,
                         "Distance above the low surface at which a distance-based primary ray begins."));
    specs.push_back(Spec("MaxDepth", G::Detail, T::Pending, "", kTask,
                         "Distance below the low surface down to which a distance-based primary ray "
                         "keeps looking for the high mesh."));
    specs.push_back(Spec("RelativeScale", G::Detail, T::Pending, "", kTask,
                         "Selects whether the cage distances are absolute or measured against the "
                         "bounding box."));
    specs.push_back(Spec("SmoothNormals", G::Detail, T::Pending, "", kTask,
                         "Normal smoothing of the ray directions (listed by the task; its type waits "
                         "for the discovery capture)."));
    specs.push_back(Spec("IgnoreBackface", G::Detail, T::Bool, "Ignore backface", task_page,
                         "Primary rays go through high-mesh faces they meet from behind instead of "
                         "stopping there."));
    specs.push_back(WithOptions(Spec("FilterMethod", G::Detail, T::Enum, "Match", task_page,
                                     "Whether any high mesh may serve any low mesh, or only the high "
                                     "meshes whose names pair with it."),
                                {"Always", "By mesh name"}, true));
    specs.push_back(WithDefault(Spec("LowpolySuffix", G::Detail, T::String, "Low poly mesh suffix", task_page,
                                     "Name ending that identifies a low mesh when meshes are paired by "
                                     "name."),
                                std::string("_low"), listed));
    specs.push_back(WithDefault(Spec("HipolySuffix", G::Detail, T::String, "High poly mesh suffix", task_page,
                                     "Name ending that identifies a high mesh when meshes are paired by "
                                     "name."),
                                std::string("_high"), listed));
    specs.push_back(WithDefault(Spec("BackfaceCullingSuffix", G::Detail, T::String, "", kTask,
                                     "Name ending that makes primary rays go through the back faces of "
                                     "that one high mesh."),
                                std::string("_ignorebf"), listed));
    specs.push_back(WithOptions(Spec("SubSampling", G::Detail, T::Enum, "Antialiasing",
                                     Join({kTask, "options as listed there", kPage}),
                                     "How many primary samples are taken inside each texel and averaged."),
                                {"None", "2×2", "4×4", "8×8"}, true));
    specs.push_back(Spec("SkewFaceBehavior", G::Detail, T::Pending, "", kTask,
                         "Skew-correction behaviour (listed by the task; type and meaning wait for the "
                         "discovery capture)."));
    specs.push_back(Spec("OffsetMap", G::Detail, T::Pending, "", kTask,
                         "Offset map input (listed by the task; type and meaning wait for the discovery "
                         "capture)."));
    // AO.
    specs.push_back(Spec("NbSecondary", G::Ao, T::Pending, "Secondary rays", task_page,
                         "Rays sent out from each surface point to estimate how open it is."));
    specs.push_back(Spec("MinDistance", G::Ao, T::Pending, "Min Occluder distance", task_page,
                         "Geometry nearer than this along a ray does not block it."));
    specs.push_back(Spec("MaxDistance", G::Ao, T::Pending, "Max occluder distance", task_page,
                         "A ray that gets this far without meeting geometry counts as unblocked."));
    specs.push_back(Spec("MaxDistanceRelativeScale", G::Ao, T::Bool, "Relative to bounding box", task_page,
                         "Read the occluder distances as fractions of the mesh's bounding-box size rather "
                         "than in scene units."));
    specs.push_back(Spec("Spread", G::Ao, T::Pending, "Spread angle", task_page,
                         "Opening angle of the cone the rays are drawn from."));
    specs.push_back(WithOptions(Spec("Distribution", G::Ao, T::Enum, "Distribution", Join({kTask, kPage, kPyDoc}),
                                     "How the ray directions are laid out over the hemisphere."),
                                {"Cosine"}, false));
    specs.push_back(Spec("IgnoreBackfaceSecondary", G::Ao, T::Pending, "Ignore backface", task_page,
                         "Whether faces met from behind block the secondary rays."));
    specs.push_back(Spec("FilterMethodSecondary", G::Ao, T::Pending, "", kTask,
                         "Which meshes the secondary rays of a given mesh may hit."));
    specs.push_back(Spec("Attenuation", G::Ao, T::Pending, "Attenuation", task_page,
                         "How much less an occluder counts the farther away it is."));
    specs.push_back(Spec("GroundPlane", G::Ao, T::Bool, "Ground plane", task_page,
                         "Adds a floor plane beneath the mesh as an extra occluder."));
    specs.push_back(Spec("GroundOffset", G::Ao, T::Pending, "Ground plane offset", task_page,
                         "Moves that floor plane up or down."));
    return specs;
}

std::string TierZero(const std::string& what) {
    return what + " is not established: it comes from the Tier 0 discovery capture "
                  "(phase3.1_baker-request-model items 2.8 and 3.1)";
}

}  // namespace

const std::vector<PropertySpec>& PropertySpecs() {
    static const std::vector<PropertySpec> specs = BuildSpecs();
    return specs;
}

/// One copy of a group of parameters: a texture set's own, or a link group's shared one.
struct ParameterSlot {
    std::map<std::string, PropertyValue> values;
};

struct ParameterStore {
    std::string texture_set;
    std::shared_ptr<ParameterSlot> common = std::make_shared<ParameterSlot>();  // common and detail keys
    std::shared_ptr<ParameterSlot> ao = std::make_shared<ParameterSlot>();
    /// Shared by the texture sets of one session; null for a set outside a session.
    std::shared_ptr<std::uint64_t> revision;

    ParameterSlot& SlotOf(PropertyGroup group) const { return group == PropertyGroup::Ao ? *ao : *common; }
};

// ── Property ─────────────────────────────────────────────────────────────────────────────────

const std::string& Property::short_name() const { return spec_->short_name; }
PropertyType Property::type() const { return spec_->type; }
PropertyGroup Property::group() const { return spec_->group; }
const std::string& Property::description() const { return spec_->description; }
const std::vector<std::string>& Property::documented_option_labels() const { return spec_->option_labels; }

PropertyValue Property::value() const {
    const auto& values = store_->SlotOf(spec_->group).values;
    const auto it = values.find(spec_->short_name);
    if (it != values.end()) return it->second;
    if (spec_->default_value) return *spec_->default_value;
    throw NotYetSupported("the default of " + spec_->short_name +
                          " is not established: it comes from the private defaults capture "
                          "(phase3.1_baker-request-model item 2.9)");
}

std::string Property::label() const {
    if (spec_->label.empty()) throw NotYetSupported(TierZero("the label of " + spec_->short_name));
    return spec_->label;
}

std::string Property::name() const { throw NotYetSupported(TierZero("the full name of " + spec_->short_name)); }

std::string Property::widget_type() const {
    throw NotYetSupported(TierZero("the widget type of " + spec_->short_name));
}

std::map<std::string, int> Property::enum_values() const {
    throw NotYetSupported(TierZero("the enum integers of " + spec_->short_name));
}

int Property::enum_value(const std::string& enum_label) const {
    throw NotYetSupported(TierZero("the enum integer of " + spec_->short_name + " '" + enum_label + "'"));
}

std::string Property::properties() const {
    throw NotYetSupported(TierZero("the meta properties of " + spec_->short_name));
}

// ── BakingParameters ─────────────────────────────────────────────────────────────────────────

BakingParameters::BakingParameters(std::string texture_set) : store_(std::make_shared<ParameterStore>()) {
    store_->texture_set = std::move(texture_set);
}

const std::string& BakingParameters::texture_set() const { return store_->texture_set; }

std::map<std::string, Property> BakingParameters::common() const {
    std::map<std::string, Property> out;
    for (const PropertySpec& spec : PropertySpecs()) {
        if (spec.group == PropertyGroup::Common || spec.group == PropertyGroup::Detail) {
            out.emplace(spec.short_name, Property(store_, &spec));
        }
    }
    return out;
}

namespace {

void RefuseOtherUsage(MeshMapUsage usage, const std::string& what) {
    if (usage != MeshMapUsage::AO) {
        throw NotYetSupported(what + " of " + UsageName(usage) + " (owned by " + UsageOwnerTask(usage) + ")");
    }
}

}  // namespace

std::map<std::string, Property> BakingParameters::baker(MeshMapUsage usage) const {
    RefuseOtherUsage(usage, "the bake parameters");
    std::map<std::string, Property> out;
    for (const PropertySpec& spec : PropertySpecs()) {
        if (spec.group == PropertyGroup::Ao) out.emplace(spec.short_name, Property(store_, &spec));
    }
    return out;
}

namespace {

/// The value `value` takes in the store for `spec`, or the refusal.
PropertyValue Checked(const PropertySpec& spec, const PropertyValue& value) {
    const std::string& key = spec.short_name;
    const auto wrong = [&] {
        return ValueError(key + " takes a " + PropertyTypeName(spec.type) + " value");
    };
    switch (spec.type) {
        case PropertyType::Pending: throw NotYetSupported(TierZero("the value type of " + key));
        case PropertyType::Bool:
            if (!std::holds_alternative<bool>(value)) throw wrong();
            return value;
        case PropertyType::Int:
            if (!std::holds_alternative<std::int64_t>(value)) throw wrong();
            return value;
        case PropertyType::IntPair:
            if (!std::holds_alternative<std::pair<std::int64_t, std::int64_t>>(value)) throw wrong();
            return value;
        case PropertyType::Enum: {
            const auto* label = std::get_if<EnumLabel>(&value);
            if (!label) throw wrong();
            const auto& options = spec.option_labels;
            if (std::find(options.begin(), options.end(), label->label) != options.end()) return value;
            if (spec.options_complete) throw ValueError(key + " has no option '" + label->label + "'");
            throw NotYetSupported(TierZero("the option '" + label->label + "' of " + key));
        }
        case PropertyType::String:
            if (!std::holds_alternative<std::string>(value)) throw wrong();
            return value;
    }
    throw wrong();
}

/// Advances each distinct session revision once.
void Advance(const std::vector<const ParameterStore*>& stores) {
    std::set<std::uint64_t*> seen;
    for (const ParameterStore* store : stores) {
        if (store->revision && seen.insert(store->revision.get()).second) ++*store->revision;
    }
}

}  // namespace

void BakingParameters::set(const std::vector<std::pair<Property, PropertyValue>>& values) {
    std::vector<PropertyValue> checked;
    checked.reserve(values.size());
    // A linked group's sets share one slot: a key named twice in one slot is one parameter set twice.
    std::set<std::pair<const ParameterSlot*, std::string>> seen;
    for (const auto& [property, value] : values) {
        const ParameterSlot* slot = &property.store_->SlotOf(property.spec_->group);
        if (!seen.emplace(slot, property.spec_->short_name).second) {
            throw ValueError(property.spec_->short_name + " of texture set '" + property.store_->texture_set +
                             "' appears twice in one set() (directly or through a link group)");
        }
        checked.push_back(Checked(*property.spec_, value));
    }
    std::vector<const ParameterStore*> stores;
    for (std::size_t i = 0; i < values.size(); ++i) {
        const Property& property = values[i].first;
        property.store_->SlotOf(property.spec_->group).values[property.spec_->short_name] = std::move(checked[i]);
        stores.push_back(property.store_.get());
    }
    Advance(stores);
}

// ── BakingSession ────────────────────────────────────────────────────────────────────────────

BakingSession::BakingSession(std::vector<std::string> texture_sets)
    : names_(std::move(texture_sets)), revision_(std::make_shared<std::uint64_t>(0)) {
    std::set<std::string> unique(names_.begin(), names_.end());
    if (unique.size() != names_.size()) throw ValueError("a session's texture sets need distinct names");
    for (const std::string& name : names_) {
        auto store = std::make_shared<ParameterStore>();
        store->texture_set = name;
        store->revision = revision_;
        stores_.push_back(std::move(store));
    }
    if (names_.size() >= 2) {
        const auto shared = std::make_shared<ParameterSlot>();
        for (const auto& store : stores_) store->common = shared;
        common_group_ = names_;
    }
}

std::size_t BakingSession::IndexOf(const std::string& texture_set) const {
    const auto it = std::find(names_.begin(), names_.end(), texture_set);
    if (it == names_.end()) throw ValueError("the project has no texture set '" + texture_set + "'");
    return static_cast<std::size_t>(it - names_.begin());
}

BakingParameters BakingSession::parameters(const std::string& texture_set) const {
    return BakingParameters(stores_[IndexOf(texture_set)]);
}

std::uint64_t BakingSession::revision() const { return *revision_; }

void BakingSession::Link(const std::vector<std::string>& group, const std::string& reference, Slot slot) {
    std::set<std::size_t> members;
    for (const std::string& name : group) {
        if (!members.insert(IndexOf(name)).second) {
            throw ValueError("texture set '" + name + "' appears twice in the group");
        }
    }
    const std::size_t ref = IndexOf(reference);
    if (!members.count(ref)) {
        throw NotYetSupported("linking with the reference '" + reference +
                              "' outside the group is not established (decision 311)");
    }
    if (members.size() < 2) {
        throw NotYetSupported("a link group of fewer than two texture sets is not established (decision 311)");
    }
    std::vector<std::string> ordered;
    for (std::size_t i : members) ordered.push_back(names_[i]);
    std::vector<std::string>& current = GroupOf(slot);
    if (!current.empty() && current != ordered) {
        throw NotYetSupported(
            "regrouping: another group is already linked for these parameters, and how Painter replaces "
            "it is not established (unlink_all first; decision 311)");
    }
    const ParameterStore& source = *stores_[ref];
    const auto shared = std::make_shared<ParameterSlot>(slot == Slot::Ao ? *source.ao : *source.common);
    for (std::size_t i : members) (slot == Slot::Ao ? stores_[i]->ao : stores_[i]->common) = shared;
    current = std::move(ordered);
    ++*revision_;
}

void BakingSession::Unlink(Slot slot) {
    std::vector<std::string>& current = GroupOf(slot);
    if (current.empty()) return;
    for (const std::string& name : current) {
        std::shared_ptr<ParameterSlot>& own = slot == Slot::Ao ? stores_[IndexOf(name)]->ao : stores_[IndexOf(name)]->common;
        own = std::make_shared<ParameterSlot>(*own);
    }
    current.clear();
    ++*revision_;
}

void BakingSession::set_linked_group(const std::vector<std::string>& group, const std::string& reference,
                                     MeshMapUsage usage) {
    RefuseOtherUsage(usage, "a link group of the bake parameters");
    Link(group, reference, Slot::Ao);
}

void BakingSession::set_linked_group_common_parameters(const std::vector<std::string>& group,
                                                       const std::string& reference) {
    Link(group, reference, Slot::Common);
}

void BakingSession::unlink_all(MeshMapUsage usage) {
    RefuseOtherUsage(usage, "the link group of the bake parameters");
    Unlink(Slot::Ao);
}

void BakingSession::unlink_all_common_parameters() { Unlink(Slot::Common); }

std::vector<std::string> BakingSession::get_link_group(MeshMapUsage usage) const {
    RefuseOtherUsage(usage, "the link group of the bake parameters");
    return ao_group_;
}

std::vector<std::string> BakingSession::get_link_group_common_parameters() const { return common_group_; }

std::vector<std::string> BakingSession::Linked(const std::string& texture_set, Slot slot) const {
    IndexOf(texture_set);
    const std::vector<std::string>& group = GroupOf(slot);
    if (std::find(group.begin(), group.end(), texture_set) != group.end()) return group;
    return {texture_set};
}

std::vector<std::string> BakingSession::get_linked_texture_sets(const std::string& texture_set,
                                                                MeshMapUsage usage) const {
    RefuseOtherUsage(usage, "the link group of the bake parameters");
    return Linked(texture_set, Slot::Ao);
}

std::vector<std::string> BakingSession::get_linked_texture_sets_common_parameters(const std::string& texture_set) const {
    return Linked(texture_set, Slot::Common);
}

// ── The manifest's bake_settings ─────────────────────────────────────────────────────────────

namespace {

core::json::Value ToJson(const PropertySpec& spec, const PropertyValue& value) {
    switch (spec.type) {
        case PropertyType::Bool: return std::get<bool>(value);
        case PropertyType::Int: return std::get<std::int64_t>(value);
        case PropertyType::IntPair: {
            const auto& pair = std::get<std::pair<std::int64_t, std::int64_t>>(value);
            return core::json::Array{pair.first, pair.second};
        }
        case PropertyType::Enum: return std::get<EnumLabel>(value).label;
        case PropertyType::String: return std::get<std::string>(value);
        case PropertyType::Pending: break;
    }
    throw std::logic_error("a pending property holds no value");
}

PropertyValue FromJson(const PropertySpec& spec, const core::json::Value& json, const std::string& where) {
    const auto wrong = [&] {
        return ValueError(where + "." + spec.short_name + " is not a " + PropertyTypeName(spec.type) + " value");
    };
    switch (spec.type) {
        case PropertyType::Bool:
            if (!json.IsBool()) throw wrong();
            return std::get<bool>(json.data);
        case PropertyType::Int:
            if (!json.IsInt()) throw wrong();
            return std::get<std::int64_t>(json.data);
        case PropertyType::IntPair: {
            if (!json.IsArray()) throw wrong();
            const auto& array = std::get<core::json::Array>(json.data);
            if (array.size() != 2 || !array[0].IsInt() || !array[1].IsInt()) throw wrong();
            return std::pair<std::int64_t, std::int64_t>{std::get<std::int64_t>(array[0].data),
                                                         std::get<std::int64_t>(array[1].data)};
        }
        case PropertyType::Enum:
            if (!json.IsString()) throw wrong();
            return EnumLabel{std::get<std::string>(json.data)};
        case PropertyType::String:
            if (!json.IsString()) throw wrong();
            return std::get<std::string>(json.data);
        case PropertyType::Pending: break;
    }
    return PropertyValue{};  // a pending type: Checked() refuses it
}

const PropertySpec* SpecOf(const std::string& key) {
    for (const PropertySpec& spec : PropertySpecs()) {
        if (spec.short_name == key) return &spec;
    }
    return nullptr;
}

}  // namespace

core::BakeSettings ToBakeSettings(const BakingParameters& parameters) {
    core::BakeSettings out;
    const ParameterStore& store = *parameters.store_;
    for (const PropertySpec& spec : PropertySpecs()) {
        const auto& values = store.SlotOf(spec.group).values;
        const auto it = values.find(spec.short_name);
        if (it == values.end()) continue;
        core::json::Value json = ToJson(spec, it->second);
        switch (spec.group) {
            case PropertyGroup::Common: out.common[spec.short_name] = std::move(json); break;
            case PropertyGroup::Detail: out.detail[spec.short_name] = std::move(json); break;
            case PropertyGroup::Ao: out.per_baker[UsageName(MeshMapUsage::AO)][spec.short_name] = std::move(json); break;
        }
    }
    return out;
}

void LoadBakeSettings(const BakingParameters& parameters, const core::BakeSettings& settings) {
    ParameterSlot common, ao;
    const auto load = [](const core::json::Object& object, PropertyGroup group, const std::string& where,
                         ParameterSlot& into) {
        for (const auto& [key, json] : object) {
            const PropertySpec* spec = SpecOf(key);
            if (!spec || spec->group != group) throw ValueError(where + " has no key '" + key + "'");
            into.values[key] = Checked(*spec, FromJson(*spec, json, where));
        }
    };
    load(settings.common, PropertyGroup::Common, "bake_settings.common", common);
    load(settings.detail, PropertyGroup::Detail, "bake_settings.detail", common);
    for (const auto& [baker, object] : settings.per_baker) {
        if (baker == UsageName(MeshMapUsage::AO)) {
            load(object, PropertyGroup::Ao, "bake_settings.per_baker.AO", ao);
            continue;
        }
        bool known = false;
        for (int u = 0; u <= static_cast<int>(MeshMapUsage::Opacity); ++u) {
            const auto usage = static_cast<MeshMapUsage>(u);
            if (baker != UsageName(usage)) continue;
            known = true;
            if (!object.empty()) RefuseOtherUsage(usage, "the bake parameters");
        }
        if (!known) throw ValueError("bake_settings.per_baker has no baker '" + baker + "'");
    }
    ParameterStore& store = *parameters.store_;
    store.common->values = std::move(common.values);
    store.ao->values = std::move(ao.values);
    Advance({&store});
}

// ── Parameters to a request ──────────────────────────────────────────────────────────────────

MappedRequest RequestFromParameters(const BakingParameters& parameters, BakeRequest base) {
    const std::map<std::string, Property> common = parameters.common();
    const auto value = [&](const std::map<std::string, Property>& group, const char* key) {
        return group.at(key).value();
    };
    const auto label = [&](const std::map<std::string, Property>& group, const char* key) {
        return std::get<EnumLabel>(value(group, key)).label;
    };
    const auto boolean = [&](const std::map<std::string, Property>& group, const char* key) {
        return std::get<bool>(value(group, key));
    };
    const auto text = [&](const std::map<std::string, Property>& group, const char* key) {
        return std::get<std::string>(value(group, key));
    };
    MappedRequest out;
    BakeRequest& r = base;
    r.texture_set = parameters.texture_set();
    const auto size = std::get<std::pair<std::int64_t, std::int64_t>>(value(common, "OutputSize"));
    for (const std::int64_t log2 : {size.first, size.second}) {
        if (log2 < 0 || log2 > 31) throw ValueError("OutputSize needs log2 sizes in [0, 31]");
    }
    r.output_size_log2[0] = static_cast<std::uint32_t>(size.first);
    r.output_size_log2[1] = static_cast<std::uint32_t>(size.second);
    const std::int64_t dilation = std::get<std::int64_t>(value(common, "DilationWidth"));
    if (dilation < 0 || dilation > std::numeric_limits<std::uint32_t>::max()) {
        throw ValueError("DilationWidth needs a texel count >= 0");
    }
    r.common.dilation_width = static_cast<std::uint32_t>(dilation);
    r.common.apply_diffusion = boolean(common, "ApplyDiffusion");
    r.detail.low_as_high = boolean(common, "LowAsHigh");
    const std::string cage = label(common, "CageMode");
    r.detail.cage_mode = cage == "Distance based"             ? CageMode::DistanceBased
                         : cage == "Automatic (experimental)" ? CageMode::Automatic
                                                              : CageMode::CustomFile;
    r.detail.ignore_backface = boolean(common, "IgnoreBackface");
    r.detail.filter_method = label(common, "FilterMethod") == "Always" ? FilterMethod::Always : FilterMethod::ByMeshName;
    r.detail.low_suffix = text(common, "LowpolySuffix");
    r.detail.high_suffix = text(common, "HipolySuffix");
    r.detail.ignore_backface_suffix = text(common, "BackfaceCullingSuffix");
    const std::string sub = label(common, "SubSampling");
    r.detail.subsampling = sub == "None" ? 1u : sub == "2×2" ? 2u : sub == "4×4" ? 4u : 8u;
    out.keys_from_request = {"MaxHeight", "MaxDepth", "RelativeScale"};
    if (std::find(r.usages.begin(), r.usages.end(), MeshMapUsage::AO) != r.usages.end()) {
        const std::map<std::string, Property> ao = parameters.baker(MeshMapUsage::AO);
        r.ao.relative_to_bounding_box = boolean(ao, "MaxDistanceRelativeScale");
        // `Cosine` is the only documented option, so the only one set() accepts.
        (void)label(ao, "Distribution");
        r.ao.distribution = Distribution::Cosine;
        if (boolean(ao, "GroundPlane")) {
            throw NotYetSupported("GroundPlane: the AO ground plane is not implemented (phase3.4_baker-ao)");
        }
        for (const char* key : {"NbSecondary", "MinDistance", "MaxDistance"}) out.keys_from_request.push_back(key);
    }
    out.request = std::move(r);
    return out;
}

}  // namespace uzp::bake
