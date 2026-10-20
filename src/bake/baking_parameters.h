#pragma once

// The bake parameter model (phase3.1_baker-request-model item 2.8; `docs/architecture/06-baking.md`
// §2; decisions 306 and 323), shaped like Painter's documented `BakingParameters` and `Property`
// (`substance_painter.baking`, `substance_painter.properties`): `common()` (common and detail
// keys), `baker(usage)`, `set({Property: value})` and the `Property` accessors.
//
// Every key, name, label, widget type, value type, enum value, range and default comes from
// `assets/defaults/baking.json` (`baking_catalog.h`). UzmiGames authored that table from Painter's
// documented API, and each entry names the private observation it must equal, the Tier 0
// baking-defaults record. `python -m tools.bake.bake_defaults check` compares the two on the
// owner's machine (item 2.9, decision 028).
//
// What still raises `uzp::core::NotYetSupported`, never a guess (decision 323):
// - `Property::properties()`: Painter's meta properties carry its descriptive text, which is not
//   reproduced;
// - a default the observation does not establish (`OutputSize`, `TonemappingBounds`);
// - a value outside a key's range: how Painter treats it is not recorded;
// - storing a value for a baker other than AO, Position, ID (decision 337) and Height (decision
//   341), which its owner baker task brings.
//
// Decision 311 adds the mapping to a `BakeRequest`, linked groups (`BakingSession`, the documented
// `substance_painter.baking` link functions) and the project manifest's `bake_settings`.

#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <variant>
#include <vector>

#include "bake/bake_request.h"
#include "uzp_core/types/project.h"

namespace uzp::bake {

/// `Common.*` and `Detail.*` keys form `common()`; a baker's keys form `baker(usage)`.
enum class PropertyGroup { Common, Detail, Baker };

/// The value type of a key, from the type of Painter's `value()` (an `Enum` is an int with
/// `enum_values`).
enum class PropertyType { Bool, Int, Float, IntPair, FloatPair, Enum, String };

const char* PropertyTypeName(PropertyType type);

/// An `Enum` value, given by its label (a key of `enum_values()`).
struct EnumLabel {
    std::string label;
    bool operator==(const EnumLabel&) const = default;
};

using PropertyValue = std::variant<bool, std::int64_t, std::pair<std::int64_t, std::int64_t>, double, EnumLabel,
                                   std::string, std::pair<double, double>>;

struct PropertySpec {
    std::string short_name;
    /// Painter's full name (`Common.DilationWidth`, `Detail.SecondaryCommon.NbSecondary`).
    std::string name;
    std::string label;
    std::string widget_type;
    PropertyGroup group = PropertyGroup::Common;
    /// The baker of a `Baker` key.
    MeshMapUsage usage = MeshMapUsage::AO;
    PropertyType type = PropertyType::Bool;
    /// `Enum`: every label with its integer, in integer order.
    std::vector<std::pair<std::string, int>> enum_values;
    /// The inclusive range Painter states, of the key's type (`Int`, `Float`, `IntPair` per
    /// component); absent when unbounded on that side.
    std::optional<PropertyValue> minimum;
    std::optional<PropertyValue> maximum;
    /// The value on a fresh project (an `Enum` as its label); absent when not established.
    std::optional<PropertyValue> default_value;
    std::string default_note;
    /// The private observation the entry must equal: the record's SHA-256 and its output.
    std::string record_sha256;
    std::string output_id;
};

/// True for the bakers whose values `set()` stores: AO, Position and ID (decision 337) and Height
/// (decision 341). Only AO's form link groups; another baker's value is always the texture set's own.
bool StoresBakerValues(MeshMapUsage usage);

/// Every key: `common()`'s in Painter's order, then each baker's, in `MeshMapUsage` order.
const std::vector<PropertySpec>& PropertySpecs();

/// A fresh texture set's baking state (`get_curvature_method`, `get_enabled_bakers`,
/// `is_textureset_enabled`), from the same table.
struct TextureSetBakeState {
    std::string curvature_method;
    std::vector<std::string> enabled_bakers;
    bool textureset_enabled = true;
};
const TextureSetBakeState& DefaultTextureSetState();

struct ParameterStore;
class BakingParameters;
class BakingSession;
core::BakeSettings ToBakeSettings(const BakingParameters& parameters);
void LoadBakeSettings(const BakingParameters& parameters, const core::BakeSettings& settings);

/// A handle to one parameter of one texture set's `BakingParameters`.
class Property {
public:
    const std::string& short_name() const;
    PropertyType type() const;
    PropertyGroup group() const;
    const PropertySpec& spec() const { return *spec_; }

    /// The value set through `BakingParameters::set`, else the default, else `NotYetSupported`.
    PropertyValue value() const;
    const std::string& name() const;
    const std::string& label() const;
    const std::string& widget_type() const;
    /// Empty for a key that is not an `Enum`.
    std::map<std::string, int> enum_values() const;
    /// `ValueError` for a label the key does not have.
    int enum_value(const std::string& enum_label) const;
    /// `NotYetSupported`: the meta properties carry Painter's descriptive text (decision 323).
    std::string properties() const;

private:
    friend class BakingParameters;
    Property(std::shared_ptr<ParameterStore> store, const PropertySpec* spec)
        : store_(std::move(store)), spec_(spec) {}
    std::shared_ptr<ParameterStore> store_;
    const PropertySpec* spec_;
};

/// One texture set's bake parameters.
class BakingParameters {
public:
    explicit BakingParameters(std::string texture_set);
    const std::string& texture_set() const;
    /// The common and detail parameters.
    std::map<std::string, Property> common() const;
    /// The parameters of `usage` (none for `Normal`, `WorldSpaceNormal` and `Opacity`). Every
    /// baker's are readable; those `StoresBakerValues` names take values (`set`).
    std::map<std::string, Property> baker(MeshMapUsage usage) const;
    /// Sets the values in one transaction: every value is checked first, and one failure leaves
    /// every parameter, of every texture set in the batch, unchanged. Refusals: `ValueError` (a
    /// wrong type or an unknown enum label), `NotYetSupported` (a value outside the key's range, or
    /// a baker `StoresBakerValues` refuses, naming its owner task). A value set on a member of a link group is
    /// the whole group's (one parameter, so naming it twice is a `ValueError`).
    static void set(const std::vector<std::pair<Property, PropertyValue>>& values);

private:
    friend class BakingSession;
    friend core::BakeSettings ToBakeSettings(const BakingParameters& parameters);
    friend void LoadBakeSettings(const BakingParameters& parameters, const core::BakeSettings& settings);
    explicit BakingParameters(std::shared_ptr<ParameterStore> store) : store_(std::move(store)) {}
    std::shared_ptr<ParameterStore> store_;
};

/// The bake parameters of a project's texture sets and their link groups (`06-baking.md` section 3,
/// Painter's documented `set_linked_group*`, `unlink_all*`, `get_link_group*`,
/// `get_linked_texture_sets*`; decision 311). A linked group shares one copy of its parameters:
/// the common group the common and detail keys, a usage's group that usage's keys. Lists are in
/// texture set order. Only AO's group exists (every other usage names its owner baker task).
/// Every change is one transaction: it is checked whole first, and a refusal changes nothing and
/// leaves `revision()` where it was.
class BakingSession {
public:
    /// The project's texture sets, in order. With two or more, all start in the common group
    /// (the documented example: common parameters are shared "at project creation").
    explicit BakingSession(std::vector<std::string> texture_sets);

    const std::vector<std::string>& texture_sets() const { return names_; }
    /// `ValueError` for a texture set the session does not have.
    BakingParameters parameters(const std::string& texture_set) const;
    /// Advances once per accepted change (a `set()` on any of its sets, a link, an unlink or a
    /// load); never on a refusal.
    std::uint64_t revision() const;

    /// The group shares `reference`'s current parameters of `usage`. `ValueError` for an unknown
    /// or repeated texture set; `NotYetSupported` for a usage other than AO, a reference outside
    /// the group, fewer than two sets, or a different group already linked for the usage (how
    /// Painter regroups is not established: `unlink_all` first).
    void set_linked_group(const std::vector<std::string>& group, const std::string& reference, MeshMapUsage usage);
    void set_linked_group_common_parameters(const std::vector<std::string>& group, const std::string& reference);
    /// Every set of the group keeps its own copy of the group's current values.
    void unlink_all(MeshMapUsage usage);
    void unlink_all_common_parameters();
    /// Empty when no group exists.
    std::vector<std::string> get_link_group(MeshMapUsage usage) const;
    std::vector<std::string> get_link_group_common_parameters() const;
    /// The sets sharing `texture_set`'s parameters; at least `texture_set` itself.
    std::vector<std::string> get_linked_texture_sets(const std::string& texture_set, MeshMapUsage usage) const;
    std::vector<std::string> get_linked_texture_sets_common_parameters(const std::string& texture_set) const;

private:
    enum class Slot { Common, Ao };
    void Link(const std::vector<std::string>& group, const std::string& reference, Slot slot);
    void Unlink(Slot slot);
    std::vector<std::string>& GroupOf(Slot slot) { return slot == Slot::Common ? common_group_ : ao_group_; }
    const std::vector<std::string>& GroupOf(Slot slot) const {
        return slot == Slot::Common ? common_group_ : ao_group_;
    }
    std::vector<std::string> Linked(const std::string& texture_set, Slot slot) const;
    std::size_t IndexOf(const std::string& texture_set) const;

    std::vector<std::string> names_;
    std::vector<std::shared_ptr<ParameterStore>> stores_;
    std::vector<std::string> common_group_;
    std::vector<std::string> ao_group_;
    std::shared_ptr<std::uint64_t> revision_;
};

/// The values set on `parameters` (never a default) as the manifest's `bake_settings`: common
/// keys in `common`, detail keys in `detail`, a stored baker's keys in `per_baker[<usage>]`, by Painter short
/// name; a `Bool` as a JSON bool, an `Int` as an integer, a `Float` as a number, an `IntPair` as
/// `[a, b]`, an `Enum` as its label and a `String` as a string.
core::BakeSettings ToBakeSettings(const BakingParameters& parameters);

/// Replaces `parameters`' values with `settings` (its `extra` is not read), as one transaction
/// checked like `set()`: an unknown key, a key in the wrong group, a wrong JSON type, a value
/// `set()` refuses or a baker `StoresBakerValues` refuses with values refuses the whole load. Loading a linked
/// set loads its group.
void LoadBakeSettings(const BakingParameters& parameters, const core::BakeSettings& settings);

/// A `BakeRequest` from `parameters` over `base` (decisions 311 and 323). Every key that maps to a
/// request field is read (its set value or its default; a key without either raises
/// `NotYetSupported`). A value selecting behaviour the baker does not implement is refused with
/// `NotYetSupported` naming its owner: `OffsetMap` given, AO `Attenuation` other than None,
/// `Spread` other than 180, `IgnoreBackfaceSecondary` other than Never, `FilterMethodSecondary`
/// other than Always, `GroundPlane` on. Position's four labels map to `BakeRequest::position` and
/// ID's two to `BakeRequest::id` (decision 337), Height's two to `BakeRequest::height` (decision 341);
/// the baker refuses the values it does not establish. `SmoothNormals` and `SkewFaceBehavior` are not read: the
/// baker's own ray-direction reading applies (decision 302), and they are listed in
/// `keys_not_read`. The mesh inputs (`HipolyMesh`, `CageMesh`) are the mesh-input step's: `base`
/// carries the meshes.
struct MappedRequest {
    BakeRequest request;
    std::vector<std::string> keys_not_read;
};
MappedRequest RequestFromParameters(const BakingParameters& parameters, BakeRequest base);

}  // namespace uzp::bake
