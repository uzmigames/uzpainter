#include "bake/baking_parameters.h"

#include <algorithm>
#include <set>

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

struct ParameterStore {
    std::string texture_set;
    std::map<std::string, PropertyValue> values;
};

// ── Property ─────────────────────────────────────────────────────────────────────────────────

const std::string& Property::short_name() const { return spec_->short_name; }
PropertyType Property::type() const { return spec_->type; }
PropertyGroup Property::group() const { return spec_->group; }
const std::string& Property::description() const { return spec_->description; }
const std::vector<std::string>& Property::documented_option_labels() const { return spec_->option_labels; }

PropertyValue Property::value() const {
    const auto it = store_->values.find(spec_->short_name);
    if (it != store_->values.end()) return it->second;
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

std::map<std::string, Property> BakingParameters::baker(MeshMapUsage usage) const {
    if (usage != MeshMapUsage::AO) {
        throw NotYetSupported(std::string("the bake parameters of ") + UsageName(usage) + " (owned by " +
                              UsageOwnerTask(usage) + ")");
    }
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

}  // namespace

void BakingParameters::set(const std::vector<std::pair<Property, PropertyValue>>& values) {
    std::vector<PropertyValue> checked;
    checked.reserve(values.size());
    std::set<std::pair<const ParameterStore*, std::string>> seen;
    for (const auto& [property, value] : values) {
        if (!seen.emplace(property.store_.get(), property.spec_->short_name).second) {
            throw ValueError(property.spec_->short_name + " of texture set '" + property.store_->texture_set +
                             "' appears twice in one set()");
        }
        checked.push_back(Checked(*property.spec_, value));
    }
    for (std::size_t i = 0; i < values.size(); ++i) {
        const Property& property = values[i].first;
        property.store_->values[property.spec_->short_name] = std::move(checked[i]);
    }
}

}  // namespace uzp::bake
