// `uzpainter.baking.BakingParameters` and `uzpainter.properties.Property`: the bake parameter
// model (`src/bake/baking_parameters.h`, phase3.1_baker-request-model item 3.1, decision 323)
// bound to Python, shaped like Painter's documented `substance_painter.baking.BakingParameters`
// and `substance_painter.properties.Property`.
//
// Both are thin handles, like every handle here (bindings.h): a `BakingParameters` holds its
// texture set's id, a `Property` that id and its key's spec. Each call resolves them again
// against the project the thread reads, through `bake::LoadBakingSession`, so a value set by any
// path (this API, the MCP tools, a reopened project) is the one read back.
//
// - `common()` and `baker(usage)` give the keys of the authored table, ordered by short name.
// - `set({Property: value})` is one transaction (`bake::EditBakingSession` inside `Mutate`). An
//   `Enum` takes the integer `enum_value(label)` gives, as Painter's does.
// - `get_curvature_method()`, `get_enabled_bakers()` and `is_textureset_enabled()` give the fresh
//   texture set's baking state: no call stores another one yet.
//
// What raises `NotYetSupported`, never a guess (decision 323): `Property.properties()`, the value
// of a key whose default is not established, a value outside a key's range, a value for a baker
// other than AO, and the texture set's baking state setters and UV-tile members (owner
// phase3.5_embree-bakers).

#include <cstdint>
#include <map>
#include <string>
#include <utility>
#include <vector>

#include "bake/baking_parameters.h"
#include "bake/baking_project.h"
#include "python/bindings.h"
#include "python/errors.h"
#include "uzp_core/types/errors.h"

namespace uzp::python {

namespace {

constexpr const char* kStateOwner = "phase3.5_embree-bakers";

/// Painter's documented `baking.CurvatureMethod`.
enum class CurvatureMethod { FromMesh, FromNormalMap };

struct BakingParametersHandle {
    core::Id texture_set = core::kNoId;
};

/// One key of one texture set's parameters.
struct PropertyHandle {
    core::Id texture_set = core::kNoId;
    const bake::PropertySpec* spec = nullptr;
};

bake::MeshMapUsage BakeUsage(core::MeshMapUsage usage) {
    const std::string name(core::ToString(usage));
    for (int u = 0; u <= static_cast<int>(bake::MeshMapUsage::Opacity); ++u) {
        const auto candidate = static_cast<bake::MeshMapUsage>(u);
        if (name == bake::UsageName(candidate)) return candidate;
    }
    throw core::ValueError("no baker " + name);
}

core::MeshMapUsage CoreUsage(const std::string& name) {
    for (std::size_t i = 0; i < core::EnumTable<core::MeshMapUsage>::names.size(); ++i) {
        if (core::EnumTable<core::MeshMapUsage>::names[i] == name) return static_cast<core::MeshMapUsage>(i);
    }
    throw core::ValueError("no MeshMapUsage " + name);
}

/// The model `Property` of `handle` in the project the thread reads.
bake::Property Live(const PropertyHandle& handle) {
    const auto project = Read();
    const std::string& name = ResolveSet(*project, handle.texture_set).name;
    const bake::BakingParameters parameters = bake::LoadBakingSession(*project).parameters(name);
    const bake::PropertySpec& spec = *handle.spec;
    const auto properties =
        spec.group == bake::PropertyGroup::Baker ? parameters.baker(spec.usage) : parameters.common();
    return properties.at(spec.short_name);
}

py::dict Handles(core::Id texture_set, const std::map<std::string, bake::Property>& properties) {
    py::dict out;
    for (const auto& [key, property] : properties) out[py::str(key)] = PropertyHandle{texture_set, &property.spec()};
    return out;
}

/// A value as Painter's `value()` returns it: an `Enum` as its integer, a pair as a tuple.
py::object ToPython(const bake::PropertySpec& spec, const bake::PropertyValue& value) {
    return std::visit(
        [&](const auto& v) -> py::object {
            using T = std::decay_t<decltype(v)>;
            if constexpr (std::is_same_v<T, bake::EnumLabel>) {
                for (const auto& [label, integer] : spec.enum_values) {
                    if (label == v.label) return py::int_(integer);
                }
                throw core::ValueError(spec.short_name + " has no enum value '" + v.label + "'");
            } else if constexpr (std::is_same_v<T, std::pair<std::int64_t, std::int64_t>> ||
                                 std::is_same_v<T, std::pair<double, double>>) {
                return py::make_tuple(v.first, v.second);
            } else {
                return py::cast(v);
            }
        },
        value);
}

bool IsInteger(py::handle value) { return py::isinstance<py::int_>(value) && !py::isinstance<py::bool_>(value); }
bool IsNumber(py::handle value) { return IsInteger(value) || py::isinstance<py::float_>(value); }

/// A Python value for `spec`, typed as `set()` takes it; the model checks the type it gets and the
/// range (`bake::BakingParameters::set`), so a value of another type passes through as that type.
bake::PropertyValue FromPython(const bake::PropertySpec& spec, py::handle value) {
    const auto wrong = [&] {
        return core::ValueError(spec.short_name + " takes a " + bake::PropertyTypeName(spec.type) + " value");
    };
    if (spec.type == bake::PropertyType::Enum) {
        if (!IsInteger(value)) throw wrong();
        const std::int64_t integer = value.cast<std::int64_t>();
        for (const auto& [label, known] : spec.enum_values) {
            if (known == integer) return bake::EnumLabel{label};
        }
        throw core::ValueError(spec.short_name + " has no enum value " + std::to_string(integer));
    }
    if (spec.type == bake::PropertyType::IntPair || spec.type == bake::PropertyType::FloatPair) {
        if (!py::isinstance<py::sequence>(value) || py::isinstance<py::str>(value)) throw wrong();
        const py::sequence pair = py::reinterpret_borrow<py::sequence>(value);
        if (pair.size() != 2) throw core::ValueError(spec.short_name + " takes a pair of two values");
        if (spec.type == bake::PropertyType::IntPair) {
            if (!IsInteger(pair[0]) || !IsInteger(pair[1])) throw wrong();
            return std::pair{pair[0].cast<std::int64_t>(), pair[1].cast<std::int64_t>()};
        }
        if (!IsNumber(pair[0]) || !IsNumber(pair[1])) throw wrong();
        return std::pair{pair[0].cast<double>(), pair[1].cast<double>()};
    }
    if (py::isinstance<py::bool_>(value)) return value.cast<bool>();
    if (IsInteger(value)) return value.cast<std::int64_t>();
    if (py::isinstance<py::float_>(value)) return value.cast<double>();
    if (py::isinstance<py::str>(value)) return value.cast<std::string>();
    throw wrong();
}

/// The texture set's baking state as the fresh texture set's (`bake::DefaultTextureSetState`).
const bake::TextureSetBakeState& State(const BakingParametersHandle& handle) {
    ResolveSet(*Read(), handle.texture_set);
    return bake::DefaultTextureSetState();
}

}  // namespace

void BindBaking(py::module_& baking, py::module_& properties) {
    py::enum_<CurvatureMethod>(baking, "CurvatureMethod")
        .value("FromMesh", CurvatureMethod::FromMesh)
        .value("FromNormalMap", CurvatureMethod::FromNormalMap);

    py::class_<PropertyHandle> property(properties, "Property",
                                        "A parameter: one key of a texture set's bake parameters "
                                        "(`baking.BakingParameters.common()` and `baker(usage)`).");
    property.def("value", [](const PropertyHandle& p) { return ToPython(*p.spec, Live(p).value()); })
        .def("name", [](const PropertyHandle& p) { return Live(p).name(); })
        .def("short_name", [](const PropertyHandle& p) { return Live(p).short_name(); })
        .def("label", [](const PropertyHandle& p) { return Live(p).label(); })
        .def("widget_type", [](const PropertyHandle& p) { return Live(p).widget_type(); })
        .def("enum_values", [](const PropertyHandle& p) { return Live(p).enum_values(); })
        .def(
            "enum_value", [](const PropertyHandle& p, const std::string& name) { return Live(p).enum_value(name); },
            py::arg("name"))
        .def("properties", [](const PropertyHandle& p) { return Live(p).properties(); })
        .def("__eq__",
             [](const PropertyHandle& a, const PropertyHandle& b) {
                 return a.texture_set == b.texture_set && a.spec == b.spec;
             })
        .def("__hash__",
             [](const PropertyHandle& p) {
                 return py::hash(py::make_tuple(p.texture_set, p.spec->name, static_cast<int>(p.spec->usage),
                                                p.spec->group == bake::PropertyGroup::Baker));
             })
        .def("__repr__", [](const PropertyHandle& p) {
            return "Property(" + p.spec->name + ", texture_set=" + std::to_string(p.texture_set) + ")";
        });
    SealClass(property);

    py::class_<BakingParametersHandle> parameters(baking, "BakingParameters",
                                                  "A texture set's bake parameters.");
    parameters
        .def(py::init([](core::Id material_id) {
                 ResolveSet(*Read(), material_id);
                 return BakingParametersHandle{material_id};
             }),
             py::arg("material_id"))
        .def_static(
            "from_texture_set",
            [](const TextureSetHandle& t) {
                ResolveSet(*Read(), t.id);
                return BakingParametersHandle{t.id};
            },
            py::arg("texture_set"))
        .def_static(
            "from_texture_set_name",
            [](const std::string& name) {
                for (const core::TextureSet& set : Read()->texture_sets) {
                    if (set.name == name) return BakingParametersHandle{set.id};
                }
                throw core::ValueError("no texture set named '" + name + "'");
            },
            py::arg("texture_set_name"))
        .def("texture_set",
             [](const BakingParametersHandle& h) {
                 ResolveSet(*Read(), h.texture_set);
                 return TextureSetHandle{h.texture_set};
             })
        .def("common",
             [](const BakingParametersHandle& h) {
                 const auto project = Read();
                 const std::string& name = ResolveSet(*project, h.texture_set).name;
                 return Handles(h.texture_set, bake::LoadBakingSession(*project).parameters(name).common());
             })
        .def(
            "baker",
            [](const BakingParametersHandle& h, core::MeshMapUsage usage) {
                const auto project = Read();
                const std::string& name = ResolveSet(*project, h.texture_set).name;
                return Handles(h.texture_set,
                               bake::LoadBakingSession(*project).parameters(name).baker(BakeUsage(usage)));
            },
            py::arg("baked_map"))
        .def_static(
            "set",
            [](const py::dict& property_values) {
                // Converted with the GIL held; `Mutate` releases it.
                std::vector<std::pair<PropertyHandle, bake::PropertyValue>> values;
                core::json::Array keys;
                for (const auto& [key, value] : property_values) {
                    if (!py::isinstance<PropertyHandle>(key)) throw py::type_error("set() takes a dict keyed by Property");
                    const auto& handle = key.cast<const PropertyHandle&>();
                    values.emplace_back(handle, FromPython(*handle.spec, value));
                    keys.push_back(core::json::Array{static_cast<std::int64_t>(handle.texture_set), handle.spec->name});
                }
                const auto project = Read();
                std::vector<std::string> names;
                for (const auto& [handle, value] : values) names.push_back(ResolveSet(*project, handle.texture_set).name);
                return Mutate("baking.BakingParameters.set", core::json::Object{{"properties", keys}}, [&](core::Edit& edit) {
                    bake::EditBakingSession(edit, [&](bake::BakingSession& session) {
                        std::vector<std::pair<bake::Property, bake::PropertyValue>> batch;
                        for (std::size_t i = 0; i < values.size(); ++i) {
                            const bake::PropertySpec& spec = *values[i].first.spec;
                            const bake::BakingParameters set = session.parameters(names[i]);
                            const auto group = spec.group == bake::PropertyGroup::Baker ? set.baker(spec.usage) : set.common();
                            batch.emplace_back(group.at(spec.short_name), values[i].second);
                        }
                        bake::BakingParameters::set(batch);
                    });
                });
            },
            py::arg("property_values"))
        .def("get_curvature_method",
             [](const BakingParametersHandle& h) {
                 const std::string& method = State(h).curvature_method;
                 if (method == "FromMesh") return CurvatureMethod::FromMesh;
                 if (method == "FromNormalMap") return CurvatureMethod::FromNormalMap;
                 throw core::ValueError("no CurvatureMethod " + method);
             })
        .def("get_enabled_bakers",
             [](const BakingParametersHandle& h) {
                 std::vector<core::MeshMapUsage> usages;
                 for (const std::string& baker : State(h).enabled_bakers) usages.push_back(CoreUsage(baker));
                 return usages;
             })
        .def("is_textureset_enabled", [](const BakingParametersHandle& h) { return State(h).textureset_enabled; })
        .def("__eq__", [](const BakingParametersHandle& a, const BakingParametersHandle& b) { return a.texture_set == b.texture_set; })
        .def("__hash__", [](const BakingParametersHandle& h) { return py::hash(py::int_(h.texture_set)); })
        .def("__repr__", [](const BakingParametersHandle& h) {
            return "BakingParameters(" + std::to_string(h.texture_set) + ")";
        });
    // The texture set's baking state is not stored yet, and UV tiles are a release gap: each of
    // these raises before any change (decision 323).
    for (const char* name : {"set_textureset_enabled", "set_enabled_bakers", "is_baker_enabled", "set_baker_enabled",
                             "set_curvature_method", "get_enabled_uv_tiles", "set_enabled_uv_tiles",
                             "is_uv_tile_enabled", "set_uv_tile_enabled"}) {
        const std::string message = std::string("uzpainter.baking.BakingParameters.") + name +
                                    " is a release gap (" + kStateOwner + "; decision 323)";
        parameters.def(name, [message](const BakingParametersHandle&, const py::args&, const py::kwargs&) {
            ThrowNotYetSupported(message);
        });
    }
    SealClass(parameters);
}

}  // namespace uzp::python
