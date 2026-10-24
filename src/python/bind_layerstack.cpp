// `uzpainter.layerstack`, `uzpainter.source` and `uzpainter.levels`: node handles, insertion and
// deletion, name addressing (LAY-06), the native `sync_stack` composite (LAY-07), fill sources and
// projections, levels parameters (bindings.h).
//
// Every setter has a getter that reads the value back through a freshly resolved handle. The
// native API never resets values when the active channels change (LAY-01): `active_channels`
// replaces the set and leaves every source as it was. Channel arguments follow Painter's contexts:
// a node of a content stack needs a channel (None raises `EditionContextException`), a node of a
// mask stack takes None (a channel raises `ValueError`).

#include <algorithm>
#include <bit>
#include <cmath>
#include <fstream>
#include <iterator>

#include "python/bindings.h"
#include "python/edits.h"
#include "python/errors.h"
#include "python/stack_sync.h"
#include "uzp_core/naming/naming.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/resource_url.h"
#include "uzp_core/types/validation.h"

namespace uzp::python {

namespace {

using core::ChannelType;
using core::Id;

// ── Source handles (`uzpainter.source`) ─────────────────────────────────────────────────────────

struct SourceUniformColor {
    Id node = core::kNoId;
    ChannelArg channel;
};
struct SourceBitmap {
    Id node = core::kNoId;
    ChannelArg channel;
};
struct SourceSubstance {
    Id node = core::kNoId;
    ChannelArg channel;
    /// The source of a generator or filter effect (`get_source()` takes no channel there).
    bool effect = false;
};

enum class SourceResolutionMode { Auto, Document, Manual, TextureSet, UVTile };
struct SourceResolutionOverride {
    SourceResolutionMode mode;
    std::array<int, 2> value;
    int log2_offset;
};

void CheckProceduralParameters(const core::json::Object& params) {
    for (const auto& [name, value] : params) {
        if (!value.IsInt() && !value.IsDouble() && !value.IsString()) {
            ThrowNotYetSupported("procedural parameter " + name + " is outside the scalar snapshot domain");
        }
    }
}

void CheckSourceResolution(const SourceResolutionOverride& resolution) {
    switch (resolution.mode) {
        case SourceResolutionMode::Auto:
        case SourceResolutionMode::Document:
        case SourceResolutionMode::Manual:
        case SourceResolutionMode::TextureSet:
        case SourceResolutionMode::UVTile: break;
        default: throw core::ValueError("unknown procedural resolution mode");
    }
    for (int size : resolution.value) {
        if (size < 128 || size > 4096 || !std::has_single_bit(static_cast<unsigned>(size))) {
            throw core::ValueError("resolution value must contain powers of two between 128 and 4096");
        }
    }
}

struct LevelsParamsMono {
    double input_min = 0.0, input_max = 1.0, gamma = 1.0, output_min = 0.0, output_max = 1.0;
    bool clamp = false;
};
struct LevelsParamsRGB {
    std::array<double, 3> input_min{0.0, 0.0, 0.0}, input_max{1.0, 1.0, 1.0}, gamma{1.0, 1.0, 1.0},
        output_min{0.0, 0.0, 0.0}, output_max{1.0, 1.0, 1.0};
    bool clamp = false;
};

struct UVTransformationParams {
    std::optional<core::ScaleMode> scale_mode;
    std::optional<std::array<double, 2>> scale;
    std::optional<double> rotation;
    std::optional<std::array<double, 2>> offset;
};
struct UVProjectionParams {
    std::optional<core::FilteringMode> filtering_mode;
    std::optional<core::UVWrapMode> uv_wrapping_mode;
    UVTransformationParams uv_transformation;
};

core::json::Object NodeArgs(Id uid) { return {{"node", static_cast<std::int64_t>(uid)}}; }
core::json::Object NodeArgs(Id uid, const ChannelArg& channel) {
    core::json::Object args = NodeArgs(uid);
    args["channel"] = channel ? core::json::Value(std::string(core::ToString(*channel))) : core::json::Value(nullptr);
    return args;
}

bool InMask(const NodeInfo& info) { return info.in_mask(); }

const core::FillContent& FillOf(const NodeInfo& info, Id uid) {
    const std::optional<core::FillContent>& fill = info.layer ? info.layer->fill : info.effect->fill;
    if (!fill) throw core::ValueError("node " + std::to_string(uid) + " is not a fill");
    return *fill;
}

/// The source of `channel` (or the mono source) of a fill, nullptr when it has none.
const core::Source* SourceOf(const NodeInfo& info, Id uid, const ChannelArg& channel) {
    const core::FillContent& fill = FillOf(info, uid);
    CheckChannel(InMask(info), channel, uid);
    if (!channel) return fill.mono_source ? &*fill.mono_source : nullptr;
    const auto it = fill.sources.find(*channel);
    return it == fill.sources.end() ? nullptr : &it->second;
}

py::object SourceObject(const core::Source* source, Id uid, const ChannelArg& channel) {
    if (source == nullptr) return py::none();
    switch (source->kind()) {
        case core::SourceKind::uniform_color: return py::cast(SourceUniformColor{uid, channel});
        case core::SourceKind::bitmap: return py::cast(SourceBitmap{uid, channel});
        case core::SourceKind::vector:
        case core::SourceKind::font:
            ThrowNotYetSupported("vector and font sources are release gaps (phase4.1_nodes-vector-font-sources)");
        case core::SourceKind::procedural:
            return py::cast(SourceSubstance{uid, channel});
        case core::SourceKind::reference:
            ThrowNotYetSupported("anchor reference sources are release gaps (phase4.1_nodes-instances-anchors)");
    }
    return py::none();
}

/// The generator or filter effect `uid` (handles of opened projects; neither can be inserted yet).
const core::Effect& ProceduralEffectOf(const NodeInfo& info, Id uid) {
    if (info.effect == nullptr ||
        (info.effect->kind != core::EffectKind::generator && info.effect->kind != core::EffectKind::filter)) {
        throw core::ValueError("node " + std::to_string(uid) + " is not a generator or filter effect");
    }
    return *info.effect;
}

/// The stored procedural of a source handle, read through a freshly resolved node.
core::ProceduralRef ReadProcedural(const SourceSubstance& s) {
    const auto project = Read();
    const NodeInfo info = Resolve(*project, s.node);
    if (s.effect) {
        const core::Effect& effect = ProceduralEffectOf(info, s.node);
        if (!effect.procedural) throw core::ValueError("stale handle: the effect no longer has a procedural source");
        return *effect.procedural;
    }
    const core::Source* src = SourceOf(info, s.node, s.channel);
    if (src == nullptr || src->kind() != core::SourceKind::procedural) {
        throw core::ValueError("stale handle: the node no longer has this procedural source");
    }
    return std::get<core::ProceduralSource>(src->value).ref;
}

core::ProceduralRef& EditProcedural(core::Edit& edit, const SourceSubstance& s) {
    if (!s.effect) {
        return std::get<core::ProceduralSource>(EditSource(edit, s.node, s.channel, core::SourceKind::procedural).value).ref;
    }
    core::Effect& effect = EditEffect(edit, s.node);
    if (effect.kind != core::EffectKind::generator && effect.kind != core::EffectKind::filter) {
        throw core::ValueError("node " + std::to_string(s.node) + " is not a generator or filter effect");
    }
    if (!effect.procedural) throw core::ValueError("stale handle: the effect no longer has a procedural source");
    return *effect.procedural;
}

core::json::Object SourceArgs(const SourceSubstance& s) {
    core::json::Object args = s.effect ? NodeArgs(s.node) : NodeArgs(s.node, s.channel);
    if (s.effect) args["effect"] = true;
    return args;
}

// ── Blending ────────────────────────────────────────────────────────────────────────────────────

core::Blending ReadBlending(const NodeInfo& info, Id uid, const ChannelArg& channel) {
    if (info.effect && info.in_mask()) {
        CheckChannel(true, channel, uid);
        return info.effect->mono_blending.value_or(core::Blending{});
    }
    CheckChannel(false, channel, uid);
    const core::ChannelBlending& blending = info.layer ? info.layer->blending : info.effect->blending;
    const auto it = blending.find(*channel);
    return it == blending.end() ? core::Blending{} : it->second;
}

// ── Insertion ───────────────────────────────────────────────────────────────────────────────────

core::json::Object PositionArgs(const core::InsertPosition& p) {
    static constexpr const char* kKinds[] = {"top_of_stack", "above_node", "below_node", "inside_node"};
    return {{"kind", kKinds[static_cast<int>(p.kind)]},
            {"node", static_cast<std::int64_t>(p.node)},
            {"node_stack", std::string(core::ToString(p.node_stack))},
            {"stack", static_cast<std::int64_t>(p.stack)},
            {"texture_set", static_cast<std::int64_t>(p.texture_set)}};
}

/// Inserts a node of `type` at `position`. With a name (LAY-06), a node of that name and type
/// already in the position's list is returned instead (the call is a no-op), a node of that name
/// and another type or several such nodes fail before anything changes.
py::object Insert(const std::string& tool, const core::InsertPosition& position, core::NodeType type,
                  const std::optional<std::string>& name, Id instance_source = core::kNoId,
                  const std::function<void(core::Edit&, Id)>& configure = nullptr) {
    core::json::Object args = PositionArgs(position);
    args["type"] = std::string(core::ToString(type));
    if (name) args["name"] = *name;
    if (instance_source != core::kNoId) args["instance_source"] = static_cast<std::int64_t>(instance_source);
    Id uid = core::kNoId;
    Mutate(tool, args, [&](core::Edit& edit) { uid = InsertNode(edit, position, type, name, instance_source, configure).uid; });
    return MakeNode(*Read(), uid);
}

core::InsertPosition PositionFromStack(const StackHandle& stack) {
    return core::InsertPosition::FromStack(stack.texture_set, stack.stack);
}

// ── Node lists ──────────────────────────────────────────────────────────────────────────────────

py::list Handles(const core::Project& project, const std::vector<Id>& ids) {
    py::list list;
    for (const Id id : ids) list.append(MakeNode(project, id));
    return list;
}

template <typename T>
std::vector<Id> UidsOf(const std::vector<T>& nodes) {
    std::vector<Id> ids;
    for (const T& node : nodes) ids.push_back(node.uid);
    return ids;
}

/// The uids of the list holding `info`, top first.
std::vector<Id> Siblings(const core::Project& project, const NodeInfo& info) {
    if (info.root) return UidsOf(ResolveStack(project, {info.texture_set, info.stack}).root_layers);
    const core::Layer* owner = core::FindLayer(project, info.owner);
    switch (info.owner_stack) {
        case core::NodeStack::Substack: return UidsOf(owner->children);
        case core::NodeStack::Content: return UidsOf(owner->content_effects);
        case core::NodeStack::Mask: return UidsOf(owner->mask->effects);
    }
    return {};
}

const core::Layer& LayerOf(const NodeInfo& info, Id uid) {
    if (info.layer == nullptr) throw core::ValueError("node " + std::to_string(uid) + " is not a layer");
    return *info.layer;
}

// ── Projection parameters ───────────────────────────────────────────────────────────────────────

UVProjectionParams ParamsOf(const core::UVProjectionParams& uv) {
    return {uv.filtering_mode, uv.uv_wrapping_mode,
            {uv.uv_transformation.scale_mode, uv.uv_transformation.scale, uv.uv_transformation.rotation,
             uv.uv_transformation.offset}};
}

// ── Bindings ────────────────────────────────────────────────────────────────────────────────────

template <typename Class>
void BindFillMethods(Class& cls) {
    using Handle = typename Class::type;
    cls.def_property(
           "active_channels",
           [](const Handle& n) {
               const auto project = Read();
               const NodeInfo info = Resolve(*project, n.uid);
               const core::FillContent& fill = FillOf(info, n.uid);
               py::set channels;
               for (const ChannelType c : fill.active_channels) channels.add(py::cast(c));
               return channels;
           },
           [](const Handle& n, const std::set<ChannelType>& channels) {
               core::json::Array names;
               for (const ChannelType c : channels) names.push_back(std::string(core::ToString(c)));
               core::json::Object args = NodeArgs(n.uid);
               args["channels"] = names;
               Mutate("layerstack.FillLayerNode.active_channels", args, [&](core::Edit& edit) {
                   bool mask = false;
                   core::FillContent& fill = EditFill(edit, n.uid, &mask);
                   if (mask) throw core::ValueError("a mask-stack fill has no active channels");
                   fill.active_channels = channels;  // sources are kept as they are (LAY-01)
               });
           },
           "The channels the fill writes. Assigning it changes no source (LAY-01).")
        .def("source_mode",
             [](const Handle& n) { return FillOf(Resolve(*Read(), n.uid), n.uid).source_mode; })
        .def(
            "get_source",
            [](const Handle& n, const ChannelArg& channel) {
                const auto project = Read();
                return SourceObject(SourceOf(Resolve(*project, n.uid), n.uid, channel), n.uid, channel);
            },
            py::arg("channeltype") = py::none())
        .def(
            "set_source",
            [](const Handle& n, const ChannelArg& channel, const py::object& value,
               const std::optional<std::string>& color_space) {
                core::Source source;
                core::json::Object args = NodeArgs(n.uid, channel);
                std::optional<Color> color;
                std::optional<ResourceIdHandle> resource;
                if (py::isinstance<Color>(value)) {
                    color = value.cast<Color>();
                    args["color"] = core::json::Array{color->value_raw[0], color->value_raw[1], color->value_raw[2]};
                    args["color_space"] = color->color_space.value_or("");
                } else if (py::isinstance<ResourceIdHandle>(value)) {
                    resource = value.cast<ResourceIdHandle>();
                } else if (py::hasattr(value, "identifier") && !py::isinstance<Node>(value)) {
                    resource = value.attr("identifier")().cast<ResourceIdHandle>();
                } else if (py::isinstance<AnchorPointEffectNode>(value)) {
                    ThrowNotYetSupported("anchor reference sources are release gaps (phase4.1_nodes-instances-anchors)");
                } else {
                    throw py::type_error("source must be a colormanagement.Color or a resource.ResourceID");
                }
                if (color_space && !resource) throw py::type_error("color_space is given for a bitmap source only");
                if (resource) args["resource"] = resource->name + "@" + resource->version;
                if (color_space) args["bitmap_color_space"] = *color_space;
                Mutate("layerstack.FillLayerNode.set_source", args, [&](core::Edit& edit) {
                    if (resource) {
                        const std::string sha256 = ResolveResource(edit.project(), *resource);
                        source.value = core::BitmapSource{core::ResourceBinding{sha256, std::nullopt, {}},
                                                          color_space.value_or(""), {}};
                    }
                    bool mask = false;
                    core::FillContent& fill = EditFill(edit, n.uid, &mask);
                    CheckChannel(mask, channel, n.uid);
                    if (color) {
                        source.value = StoredUniformColour(edit.project(), n.uid, channel, color->value_raw,
                                                           color->color_space);
                    }
                    if (fill.source_mode == core::SourceMode::Material) {
                        throw ApiError("RuntimeError", "the fill is in SourceMode.Material");
                    }
                    if (channel) fill.sources[*channel] = source;
                    else fill.mono_source = source;
                });
                const auto project = Read();
                return SourceObject(SourceOf(Resolve(*project, n.uid), n.uid, channel), n.uid, channel);
            },
            py::arg("channeltype"), py::arg("source"), py::arg("color_space") = py::none(),
            "Sets the channel's source. A uniform colour is stored as Painter stores it, its working value in the "
            "Working space (decision 240). A bitmap is bound in `color_space` (its tag, \"\" when None) in the same "
            "call, so the support check sees the bitmap as bound (decision 207).")
        .def(
            "reset_source",
            [](const Handle& n, const ChannelArg& channel) {
                return Mutate("layerstack.FillLayerNode.reset_source", NodeArgs(n.uid, channel), [&](core::Edit& edit) {
                    bool mask = false;
                    core::FillContent& fill = EditFill(edit, n.uid, &mask);
                    CheckChannel(mask, channel, n.uid);
                    if (channel) fill.sources.erase(*channel);
                    else fill.mono_source.reset();
                });
            },
            py::arg("channeltype") = py::none())
        .def("get_projection_mode",
             [](const Handle& n) { return FillOf(Resolve(*Read(), n.uid), n.uid).projection.mode; })
        .def("set_projection_mode",
             [](const Handle& n, core::ProjectionMode mode) {
                 core::json::Object args = NodeArgs(n.uid);
                 args["projection_mode"] = std::string(core::ToString(mode));
                 return Mutate("layerstack.FillLayerNode.set_projection_mode", args,
                               [&](core::Edit& edit) { EditFill(edit, n.uid).projection.mode = mode; });
             })
        .def("get_projection_parameters",
             [](const Handle& n) {
                 const core::Projection& projection = FillOf(Resolve(*Read(), n.uid), n.uid).projection;
                 if (projection.mode != core::ProjectionMode::UV && projection.mode != core::ProjectionMode::Fill) {
                     ThrowNotYetSupported("parameters of the " + std::string(core::ToString(projection.mode)) +
                                          " projection are release gaps (phase3.4_smart-projections)");
                 }
                 return ParamsOf(projection.uv);
             })
        .def("set_projection_parameters",
             [](const Handle& n, const UVProjectionParams& params) {
                 core::json::Object args = NodeArgs(n.uid);
                 const UVTransformationParams& t = params.uv_transformation;
                 if (params.filtering_mode) args["filtering_mode"] = std::string(core::ToString(*params.filtering_mode));
                 if (params.uv_wrapping_mode) args["uv_wrapping_mode"] = std::string(core::ToString(*params.uv_wrapping_mode));
                 if (t.scale_mode) args["scale_mode"] = std::string(core::ToString(*t.scale_mode));
                 if (t.scale) args["scale"] = core::json::Array{(*t.scale)[0], (*t.scale)[1]};
                 if (t.rotation) args["rotation"] = *t.rotation;
                 if (t.offset) args["offset"] = core::json::Array{(*t.offset)[0], (*t.offset)[1]};
                 return Mutate("layerstack.FillLayerNode.set_projection_parameters", args, [&](core::Edit& edit) {
                     core::Projection& projection = EditFill(edit, n.uid).projection;
                     if (projection.mode != core::ProjectionMode::UV && projection.mode != core::ProjectionMode::Fill) {
                         throw core::ValueError("UVProjectionParams need the UV or Fill projection mode");
                     }
                     core::UVProjectionParams& uv = projection.uv;
                     if (params.filtering_mode) uv.filtering_mode = *params.filtering_mode;
                     if (params.uv_wrapping_mode) uv.uv_wrapping_mode = *params.uv_wrapping_mode;
                     if (t.scale_mode) uv.uv_transformation.scale_mode = *t.scale_mode;
                     if (t.scale) uv.uv_transformation.scale = F32(*t.scale);
                     if (t.rotation) uv.uv_transformation.rotation = F32(*t.rotation);
                     if (t.offset) uv.uv_transformation.offset = F32(*t.offset);
                 });
             })
        .def("is_symmetry_enabled", [](const Handle& n) { return FillOf(Resolve(*Read(), n.uid), n.uid).symmetry.enabled; })
        .def("set_symmetry_enabled",
             [](const Handle& n, bool enabled) {
                 core::json::Object args = NodeArgs(n.uid);
                 args["enabled"] = enabled;
                 return Mutate("layerstack.FillLayerNode.set_symmetry_enabled", args,
                               [&](core::Edit& edit) { EditFill(edit, n.uid).symmetry.enabled = enabled; });
             })
        .def("get_material_source",
             [](const Handle& n) -> py::object {
                 const core::FillContent& fill = FillOf(Resolve(*Read(), n.uid), n.uid);
                 if (fill.source_mode != core::SourceMode::Material) {
                     throw ApiError("RuntimeError", "the fill is not in SourceMode.Material");
                 }
                 throw ApiError("UnsupportedProcedural", "material sources are release gaps (phase3.2_proc-material-families)");
             })
        .def("set_material_source", [](const Handle&, const py::object&) -> py::object {
            throw ApiError("UnsupportedProcedural", "material sources are release gaps (phase3.2_proc-material-families)");
        });
}

}  // namespace

void BindLayerStack(py::module_& m, py::module_& source, py::module_& levels) {

    BindEnum<core::BlendingMode>(m, "BlendingMode");
    BindEnum<core::NodeType>(m, "NodeType");
    BindEnum<core::NodeStack>(m, "NodeStack");
    BindEnum<core::MaskBackground>(m, "MaskBackground");
    BindEnum<core::ProjectionMode>(m, "ProjectionMode");
    BindEnum<core::FilteringMode>(m, "FilteringMode");
    BindEnum<core::UVWrapMode>(m, "UVWrapMode");
    BindEnum<core::ScaleMode>(m, "ScaleMode");
    BindEnum<core::SourceMode>(source, "SourceMode");

    // ── Parameter classes ───────────────────────────────────────────────────────────────────────
    py::class_<UVTransformationParams> transformation(m, "UVTransformationParams");
    transformation
        .def(py::init([](std::optional<core::ScaleMode> scale_mode, std::optional<std::array<double, 2>> scale,
                         std::optional<double> rotation, std::optional<std::array<double, 2>> offset) {
                 return UVTransformationParams{scale_mode, scale, rotation, offset};
             }),
             py::arg("scale_mode") = py::none(), py::arg("scale") = py::none(), py::arg("rotation") = py::none(),
             py::arg("offset") = py::none())
        .def_readwrite("scale_mode", &UVTransformationParams::scale_mode)
        .def_readwrite("scale", &UVTransformationParams::scale)
        .def_readwrite("rotation", &UVTransformationParams::rotation)
        .def_readwrite("offset", &UVTransformationParams::offset);
    SealClass(transformation);
    py::class_<UVProjectionParams> projection(m, "UVProjectionParams");
    projection
        .def(py::init([](std::optional<core::FilteringMode> filtering, std::optional<core::UVWrapMode> wrapping,
                         std::optional<UVTransformationParams> transformation) {
                 return UVProjectionParams{filtering, wrapping, transformation.value_or(UVTransformationParams{})};
             }),
             py::arg("filtering_mode") = py::none(), py::arg("uv_wrapping_mode") = py::none(),
             py::arg("uv_transformation") = py::none())
        .def_readwrite("filtering_mode", &UVProjectionParams::filtering_mode)
        .def_readwrite("uv_wrapping_mode", &UVProjectionParams::uv_wrapping_mode)
        .def_readwrite("uv_transformation", &UVProjectionParams::uv_transformation);
    SealClass(projection);

    py::class_<LevelsParamsMono> mono(levels, "LevelsParamsMono");
    mono.def(py::init([](double a, double b, double g, double c, double d, bool clamp) {
                 return LevelsParamsMono{a, b, g, c, d, clamp};
             }),
             py::arg("input_min") = 0.0, py::arg("input_max") = 1.0, py::arg("gamma") = 1.0, py::arg("output_min") = 0.0,
             py::arg("output_max") = 1.0, py::arg("clamp") = false)
        .def_readwrite("input_min", &LevelsParamsMono::input_min)
        .def_readwrite("input_max", &LevelsParamsMono::input_max)
        .def_readwrite("gamma", &LevelsParamsMono::gamma)
        .def_readwrite("output_min", &LevelsParamsMono::output_min)
        .def_readwrite("output_max", &LevelsParamsMono::output_max)
        .def_readwrite("clamp", &LevelsParamsMono::clamp);
    SealClass(mono);
    using Triple = std::array<double, 3>;
    py::class_<LevelsParamsRGB> rgb(levels, "LevelsParamsRGB");
    rgb.def(py::init([](Triple a, Triple b, Triple g, Triple c, Triple d, bool clamp) {
                return LevelsParamsRGB{a, b, g, c, d, clamp};
            }),
            py::arg("input_min") = Triple{0, 0, 0}, py::arg("input_max") = Triple{1, 1, 1},
            py::arg("gamma") = Triple{1, 1, 1}, py::arg("output_min") = Triple{0, 0, 0},
            py::arg("output_max") = Triple{1, 1, 1}, py::arg("clamp") = false)
        .def_readwrite("input_min", &LevelsParamsRGB::input_min)
        .def_readwrite("input_max", &LevelsParamsRGB::input_max)
        .def_readwrite("gamma", &LevelsParamsRGB::gamma)
        .def_readwrite("output_min", &LevelsParamsRGB::output_min)
        .def_readwrite("output_max", &LevelsParamsRGB::output_max)
        .def_readwrite("clamp", &LevelsParamsRGB::clamp);
    SealClass(rgb);

    // ── Sources ─────────────────────────────────────────────────────────────────────────────────
    py::enum_<SourceResolutionMode>(source, "_ResolutionMode", py::arithmetic())
        .value("Auto", SourceResolutionMode::Auto)
        .value("Document", SourceResolutionMode::Document)
        .value("Manual", SourceResolutionMode::Manual)
        .value("TextureSet", SourceResolutionMode::TextureSet)
        .value("UVTile", SourceResolutionMode::UVTile);
    py::class_<SourceUniformColor> uniform(source, "SourceUniformColor");
    uniform
        .def("get_color",
             [](const SourceUniformColor& s) {
                 const auto project = Read();
                 const core::Source* src = SourceOf(Resolve(*project, s.node), s.node, s.channel);
                 if (src == nullptr || src->kind() != core::SourceKind::uniform_color) {
                     throw core::ValueError("stale handle: the node no longer has this uniform colour source");
                 }
                 const auto& u = std::get<core::UniformColorSource>(src->value);
                 return Color{u.rgb, u.color_space.empty() ? std::nullopt : std::optional<std::string>(u.color_space)};
             })
        .def("set_color", [](const SourceUniformColor& s, const Color& color) {
            core::json::Object args = NodeArgs(s.node, s.channel);
            args["color"] = core::json::Array{color.value_raw[0], color.value_raw[1], color.value_raw[2]};
            args["color_space"] = color.color_space.value_or("");
            return Mutate("source.SourceUniformColor.set_color", args, [&](core::Edit& edit) {
                auto& u = std::get<core::UniformColorSource>(
                    EditSource(edit, s.node, s.channel, core::SourceKind::uniform_color).value);
                const core::UniformColorSource stored =
                    StoredUniformColour(edit.project(), s.node, s.channel, color.value_raw, color.color_space);
                u.rgb = stored.rgb;
                u.color_space = stored.color_space;
            });
        });
    SealClass(uniform);

    py::class_<SourceBitmap> bitmap(source, "SourceBitmap");
    const auto read_bitmap = [](const SourceBitmap& s) {
        const auto project = Read();
        const core::Source* src = SourceOf(Resolve(*project, s.node), s.node, s.channel);
        if (src == nullptr || src->kind() != core::SourceKind::bitmap) {
            throw core::ValueError("stale handle: the node no longer has this bitmap source");
        }
        return std::make_pair(project, std::get<core::BitmapSource>(src->value));
    };
    bitmap
        .def("resource_id",
             [read_bitmap](const SourceBitmap& s) {
                 const auto [project, b] = read_bitmap(s);
                 return ResourceIdOf(*project, b.resource.sha256);
             })
        .def("get_color_space", [read_bitmap](const SourceBitmap& s) { return read_bitmap(s).second.color_space; })
        .def("set_color_space",
             [](const SourceBitmap& s, const py::object& space) {
                 const std::string name = py::isinstance<py::str>(space) ? space.cast<std::string>()
                                                                         : space.attr("name").cast<std::string>();
                 core::json::Object args = NodeArgs(s.node, s.channel);
                 args["color_space"] = name;
                 return Mutate("source.SourceBitmap.set_color_space", args, [&](core::Edit& edit) {
                     std::get<core::BitmapSource>(EditSource(edit, s.node, s.channel, core::SourceKind::bitmap).value)
                         .color_space = name;
                 });
             })
        .def("reset_color_space", [](const SourceBitmap& s) {
            return Mutate("source.SourceBitmap.reset_color_space", NodeArgs(s.node, s.channel), [&](core::Edit& edit) {
                std::get<core::BitmapSource>(EditSource(edit, s.node, s.channel, core::SourceKind::bitmap).value).color_space = "";
            });
        });
    SealClass(bitmap);

    py::class_<SourceResolutionOverride> resolution(source, "_ResolutionOverride");
    resolution.def(py::init([](SourceResolutionMode mode, std::array<int, 2> value, int offset) {
                      SourceResolutionOverride result{mode, value, offset};
                      CheckSourceResolution(result);
                      return result;
                  }), py::arg("mode"), py::arg("value"), py::arg("log2_offset"))
        .def_readonly("mode", &SourceResolutionOverride::mode)
        .def_readonly("value", &SourceResolutionOverride::value)
        .def_readonly("log2_offset", &SourceResolutionOverride::log2_offset);
    SealClass(resolution);

    const auto read_procedural = [](const SourceSubstance& s) { return ReadProcedural(s); };
    const auto output_key = [](const SourceSubstance& s, const core::ProceduralRef& ref) {
        if (!s.channel || ref.output_mapping.size() != 1) {
            ThrowNotYetSupported("active_output requires an explicit single-channel procedural source");
        }
        const std::string key(core::ToString(*s.channel));
        const auto output = ref.output_mapping.find(key);
        if (output == ref.output_mapping.end() || output->second.empty()) {
            throw core::ValueError("procedural source has no explicit active output for this channel");
        }
        return key;
    };
    py::class_<SourceSubstance> substance(source, "SourceSubstance");
    substance
        .def("get_parameters", [read_procedural](const SourceSubstance& s) {
            const auto ref = read_procedural(s);
            CheckProceduralParameters(ref.params);
            return FromJson(ref.params);
        })
        .def("set_parameters", [read_procedural](const SourceSubstance& s, const py::dict& values) {
            const auto ref = read_procedural(s);
            CheckProceduralParameters(ref.params);
            core::json::Object updates;
            for (const auto& item : values) {
                if (!py::isinstance<py::str>(item.first)) throw py::type_error("parameter names must be strings");
                const std::string name = item.first.cast<std::string>();
                const auto existing = ref.params.find(name);
                if (existing == ref.params.end()) throw core::ValueError("unknown procedural parameter: " + name);
                const auto value = item.second;
                if (py::isinstance<py::bool_>(value)) throw py::type_error("boolean procedural parameters require integer values");
                if (existing->second.IsInt() && py::isinstance<py::int_>(value)) {
                    updates[name] = value.cast<std::int64_t>();
                } else if (existing->second.IsDouble() && py::isinstance<py::float_>(value)) {
                    const double number = value.cast<double>();
                    if (!std::isfinite(number)) throw core::ValueError("procedural parameters must be finite");
                    updates[name] = number;
                } else if (existing->second.IsString() && py::isinstance<py::str>(value)) {
                    updates[name] = value.cast<std::string>();
                } else {
                    throw py::type_error("procedural parameter type mismatch: " + name);
                }
            }
            auto args = SourceArgs(s);
            args["parameters"] = updates;
            return Mutate("source.SourceSubstance.set_parameters", args, [&](core::Edit& edit) {
                auto& target = EditProcedural(edit, s);
                for (const auto& [name, value] : updates) target.params[name] = value;
            });
        })
        .def("resource_id", [read_procedural](const SourceSubstance& s) {
            const auto asset = core::ParseAssetUrl(read_procedural(s).asset);
            return ResourceIdHandle{"uzasset", asset.family + "/" + asset.id, asset.version};
        })
        .def_property("active_output", [read_procedural, output_key](const SourceSubstance& s) {
            const auto ref = read_procedural(s);
            return ref.output_mapping.at(output_key(s, ref));
        }, [read_procedural, output_key](const SourceSubstance& s, const std::string& output) {
            const auto key = output_key(s, read_procedural(s));
            if (output.empty()) throw core::ValueError("active_output must not be empty");
            auto args = SourceArgs(s);
            args["output"] = output;
            Mutate("source.SourceSubstance.active_output", args, [&](core::Edit& edit) {
                auto& ref = EditProcedural(edit, s);
                ref.output_mapping.at(key) = output;
            });
        })
        .def_property("resolution", [read_procedural](const SourceSubstance& s) -> py::object {
            const auto ref = read_procedural(s);
            if (!ref.resolution_override) return py::none();
            SourceResolutionOverride result{SourceResolutionMode::Auto, {128, 128}, 0};
            if (const auto* legacy = std::get_if<core::Resolution>(&*ref.resolution_override)) {
                result.mode = SourceResolutionMode::Manual;
                result.value = {legacy->width, legacy->height};
            } else {
                const auto& stored = std::get<core::ProceduralResolutionOverride>(*ref.resolution_override);
                using Mode = core::ProceduralResolutionMode;
                switch (stored.mode) {
                    case Mode::Auto: result.mode = SourceResolutionMode::Auto; break;
                    case Mode::Asset: case Mode::Document: result.mode = SourceResolutionMode::Document; break;
                    case Mode::Custom: case Mode::Manual: result.mode = SourceResolutionMode::Manual; break;
                    case Mode::TextureSet: result.mode = SourceResolutionMode::TextureSet; break;
                    case Mode::UVTile: result.mode = SourceResolutionMode::UVTile; break;
                }
                result.value = stored.value;
                result.log2_offset = stored.log2_offset;
            }
            CheckSourceResolution(result);
            return py::cast(result);
        }, [read_procedural](const SourceSubstance& s, const SourceResolutionOverride& value) {
            read_procedural(s);
            // python-doc: the setter raises ValueError for a source used in a FilterEffectNode.
            if (s.effect && ProceduralEffectOf(Resolve(*Read(), s.node), s.node).kind == core::EffectKind::filter) {
                throw core::ValueError("the resolution of a source used in a FilterEffectNode cannot be set");
            }
            CheckSourceResolution(value);
            auto args = SourceArgs(s);
            args["mode"] = static_cast<int>(value.mode);
            args["value"] = core::json::Array{value.value[0], value.value[1]};
            args["log2_offset"] = value.log2_offset;
            Mutate("source.SourceSubstance.resolution", args, [&](core::Edit& edit) {
                auto& ref = EditProcedural(edit, s);
                core::ProceduralResolutionOverride stored;
                if (ref.resolution_override) {
                    if (const auto* current = std::get_if<core::ProceduralResolutionOverride>(&*ref.resolution_override)) {
                        stored = *current;
                    } else {
                        stored.extra = std::get<core::Resolution>(*ref.resolution_override).extra;
                    }
                }
                using Mode = core::ProceduralResolutionMode;
                switch (value.mode) {
                    case SourceResolutionMode::Auto: stored.mode = Mode::Auto; break;
                    case SourceResolutionMode::Document:
                        if (stored.mode != Mode::Asset) stored.mode = Mode::Document;
                        break;
                    case SourceResolutionMode::Manual:
                        if (stored.mode != Mode::Custom) stored.mode = Mode::Manual;
                        break;
                    case SourceResolutionMode::TextureSet: stored.mode = Mode::TextureSet; break;
                    case SourceResolutionMode::UVTile: stored.mode = Mode::UVTile; break;
                }
                stored.value = value.value;
                stored.log2_offset = value.log2_offset;
                ref.resolution_override = stored;
            });
        });
    SealClass(substance);

    // ── Positions ───────────────────────────────────────────────────────────────────────────────
    py::class_<core::InsertPosition> position(m, "InsertPosition");
    position.def_static("from_textureset_stack", [](const StackHandle& stack) { return PositionFromStack(stack); })
        .def_static("above_node", [](const Node& node) { return core::InsertPosition::Above(node.uid); })
        .def_static("below_node", [](const Node& node) { return core::InsertPosition::Below(node.uid); })
        .def_static("inside_node",
                    [](const Node& node, core::NodeStack stack) { return core::InsertPosition::Inside(node.uid, stack); });
    SealClass(position);

    // ── Nodes ───────────────────────────────────────────────────────────────────────────────────
    py::class_<Node> node(m, "Node", "A layer or effect, by its persistent 64-bit uid.");
    node.def("uid", [](const Node& n) { return n.uid; })
        .def("get_type", [](const Node& n) { return Resolve(*Read(), n.uid).type(); })
        .def("get_name",
             [](const Node& n) {
                 const NodeInfo info = Resolve(*Read(), n.uid);
                 return info.layer ? info.layer->name : info.effect->name;
             })
        .def("set_name",
             [](const Node& n, const std::string& name) {
                 core::json::Object args = NodeArgs(n.uid);
                 args["name"] = name;
                 return Mutate("layerstack.Node.set_name", args, [&](core::Edit& edit) {
                     if (core::Layer* layer = core::FindLayer(edit.project(), n.uid)) layer->name = name;
                     else EditEffect(edit, n.uid).name = name;
                 });
             })
        .def("is_visible",
             [](const Node& n) {
                 const NodeInfo info = Resolve(*Read(), n.uid);
                 return info.layer ? info.layer->visible : info.effect->visible;
             })
        .def("set_visible",
             [](const Node& n, bool visible) {
                 core::json::Object args = NodeArgs(n.uid);
                 args["visible"] = visible;
                 return Mutate("layerstack.Node.set_visible", args, [&](core::Edit& edit) {
                     if (core::Layer* layer = core::FindLayer(edit.project(), n.uid)) layer->visible = visible;
                     else EditEffect(edit, n.uid).visible = visible;
                 });
             })
        .def("is_in_mask_stack", [](const Node& n) { return Resolve(*Read(), n.uid).in_mask(); })
        .def("has_blending", [](const Node& n) { return HasBlending(Resolve(*Read(), n.uid).type()); })
        .def(
            "get_blending_mode",
            [](const Node& n, const ChannelArg& channel) { return ReadBlending(Resolve(*Read(), n.uid), n.uid, channel).mode; },
            py::arg("channel") = py::none())
        .def(
            "set_blending_mode",
            [](const Node& n, core::BlendingMode mode, const ChannelArg& channel) {
                core::json::Object args = NodeArgs(n.uid, channel);
                args["blending_mode"] = std::string(core::ToString(mode));
                return Mutate("layerstack.Node.set_blending_mode", args,
                              [&](core::Edit& edit) { EditBlending(edit, n.uid, channel).mode = mode; });
            },
            py::arg("blending_mode"), py::arg("channel") = py::none())
        .def(
            "get_opacity",
            [](const Node& n, const ChannelArg& channel) { return ReadBlending(Resolve(*Read(), n.uid), n.uid, channel).opacity; },
            py::arg("channel") = py::none())
        .def(
            "set_opacity",
            [](const Node& n, double opacity, const ChannelArg& channel) {
                core::json::Object args = NodeArgs(n.uid, channel);
                args["opacity"] = opacity;
                return Mutate("layerstack.Node.set_opacity", args,
                              [&](core::Edit& edit) { EditBlending(edit, n.uid, channel).opacity = F32(opacity); });
            },
            py::arg("opacity"), py::arg("channel") = py::none())
        .def("get_stack",
             [](const Node& n) {
                 const NodeInfo info = Resolve(*Read(), n.uid);
                 return StackHandle{info.texture_set, info.stack};
             })
        .def("get_texture_set", [](const Node& n) { return TextureSetHandle{Resolve(*Read(), n.uid).texture_set}; })
        .def("get_parent",
             [](const Node& n) -> py::object {
                 const auto project = Read();
                 const NodeInfo info = Resolve(*project, n.uid);
                 return info.root ? py::none() : MakeNode(*project, info.owner);
             })
        // Painter's next sibling is the node below, its previous sibling the node above
        // (`phase1-layer-navigation` s30-s43, both recordings); the lists are top first.
        .def("get_next_sibling",
             [](const Node& n) -> py::object {
                 const auto project = Read();
                 const NodeInfo info = Resolve(*project, n.uid);
                 const std::vector<Id> siblings = Siblings(*project, info);
                 if (info.index + 1 >= siblings.size()) return py::none();
                 return MakeNode(*project, siblings[info.index + 1]);
             })
        .def("get_previous_sibling",
             [](const Node& n) -> py::object {
                 const auto project = Read();
                 const NodeInfo info = Resolve(*project, n.uid);
                 if (info.index == 0) return py::none();
                 return MakeNode(*project, Siblings(*project, info)[info.index - 1]);
             })
        .def("__eq__", [](const Node& a, const py::object& b) { return py::isinstance<Node>(b) && a.uid == b.cast<const Node&>().uid; })
        .def("__hash__", [](const Node& n) { return py::hash(py::int_(n.uid)); })
        .def("__repr__", [](const py::object& self) {
            return py::str(py::type::of(self).attr("__name__")).cast<std::string>() + "(" +
                   std::to_string(self.cast<const Node&>().uid) + ")";
        });
    SealClass(node);

    py::class_<LayerNode, Node> layer(m, "LayerNode");
    layer.def("has_mask", [](const LayerNode& n) { return LayerOf(Resolve(*Read(), n.uid), n.uid).mask.has_value(); })
        .def("add_mask",
             [](const LayerNode& n, core::MaskBackground background) {
                 core::json::Object args = NodeArgs(n.uid);
                 args["background"] = std::string(core::ToString(background));
                 return Mutate("layerstack.LayerNode.add_mask", args, [&](core::Edit& edit) {
                     core::Layer& l = EditLayer(edit, n.uid);
                     if (l.mask) throw core::ValueError("layer " + std::to_string(n.uid) + " already has a mask");
                     core::Mask mask;
                     mask.background = background;
                     l.mask = std::move(mask);
                 });
             })
        .def("remove_mask",
             [](const LayerNode& n) {
                 return Mutate("layerstack.LayerNode.remove_mask", NodeArgs(n.uid), [&](core::Edit& edit) {
                     core::Layer& l = EditLayer(edit, n.uid);
                     if (!l.mask) throw core::ValueError("layer " + std::to_string(n.uid) + " has no mask");
                     l.mask.reset();
                 });
             })
        .def("get_mask_background",
             [](const LayerNode& n) {
                 const core::Layer& l = LayerOf(Resolve(*Read(), n.uid), n.uid);
                 if (!l.mask) throw core::ValueError("layer " + std::to_string(n.uid) + " has no mask");
                 return l.mask->background;
             })
        .def("set_mask_background",
             [](const LayerNode& n, core::MaskBackground background) {
                 core::json::Object args = NodeArgs(n.uid);
                 args["background"] = std::string(core::ToString(background));
                 return Mutate("layerstack.LayerNode.set_mask_background", args, [&](core::Edit& edit) {
                     core::Layer& l = EditLayer(edit, n.uid);
                     if (!l.mask) throw core::ValueError("layer " + std::to_string(n.uid) + " has no mask");
                     l.mask->background = background;
                 });
             })
        .def("is_mask_enabled",
             [](const LayerNode& n) {
                 const core::Layer& l = LayerOf(Resolve(*Read(), n.uid), n.uid);
                 if (!l.mask) throw core::ValueError("layer " + std::to_string(n.uid) + " has no mask");
                 return l.mask->enabled;
             })
        .def("enable_mask",
             [](const LayerNode& n, bool enabled) {
                 core::json::Object args = NodeArgs(n.uid);
                 args["enabled"] = enabled;
                 return Mutate("layerstack.LayerNode.enable_mask", args, [&](core::Edit& edit) {
                     core::Layer& l = EditLayer(edit, n.uid);
                     if (!l.mask) throw core::ValueError("layer " + std::to_string(n.uid) + " has no mask");
                     l.mask->enabled = enabled;
                 });
             })
        .def("content_effects",
             [](const LayerNode& n) {
                 const auto project = Read();
                 return Handles(*project, UidsOf(LayerOf(Resolve(*project, n.uid), n.uid).content_effects));
             })
        .def("mask_effects",
             [](const LayerNode& n) {
                 const auto project = Read();
                 const core::Layer& l = LayerOf(Resolve(*project, n.uid), n.uid);
                 return Handles(*project, l.mask ? UidsOf(l.mask->effects) : std::vector<Id>{});
             })
        .def("instances", [](const LayerNode& n) {
            const auto project = Read();
            Resolve(*project, n.uid);
            std::vector<Id> ids;
            core::ForEachNode(*project, [&](const core::NodeVisit& visit) {
                if (visit.layer && visit.layer->kind == core::LayerKind::instance && visit.layer->instance_source == n.uid) {
                    ids.push_back(visit.layer->uid);
                }
            });
            return Handles(*project, ids);
        });
    SealClass(layer);

    py::class_<EffectNode, Node> effect(m, "EffectNode");
    SealClass(effect);

    py::class_<FillLayerNode, LayerNode> fill_layer(m, "FillLayerNode");
    BindFillMethods(fill_layer);
    SealClass(fill_layer);
    py::class_<FillEffectNode, EffectNode> fill_effect(m, "FillEffectNode");
    BindFillMethods(fill_effect);
    SealClass(fill_effect);

    py::class_<GroupLayerNode, LayerNode> group(m, "GroupLayerNode");
    group
        .def("sub_layers",
             [](const GroupLayerNode& n) {
                 const auto project = Read();
                 return Handles(*project, UidsOf(LayerOf(Resolve(*project, n.uid), n.uid).children));
             })
        .def("is_collapsed", [](const GroupLayerNode& n) { return LayerOf(Resolve(*Read(), n.uid), n.uid).collapsed; })
        .def("set_collapsed", [](const GroupLayerNode& n, bool collapsed) {
            core::json::Object args = NodeArgs(n.uid);
            args["collapsed"] = collapsed;
            return Mutate("layerstack.GroupLayerNode.set_collapsed", args,
                          [&](core::Edit& edit) { EditLayer(edit, n.uid).collapsed = collapsed; });
        });
    SealClass(group);

    py::class_<InstanceLayerNode, LayerNode> instance(m, "InstanceLayerNode");
    instance.def("instance_source", [](const InstanceLayerNode& n) {
        const auto project = Read();
        return MakeNode(*project, LayerOf(Resolve(*project, n.uid), n.uid).instance_source);
    });
    SealClass(instance);

    py::class_<LevelsEffectNode, EffectNode> levels_node(m, "LevelsEffectNode");
    levels_node
        .def_property(
            "affected_channel",
            [](const LevelsEffectNode& n) -> py::object {
                const NodeInfo info = Resolve(*Read(), n.uid);
                if (!info.effect->levels || !info.effect->levels->affected_channel) return py::none();
                return py::cast(*info.effect->levels->affected_channel);
            },
            [](const LevelsEffectNode& n, ChannelType channel) {
                core::json::Object args = NodeArgs(n.uid);
                args["affected_channel"] = std::string(core::ToString(channel));
                Mutate("layerstack.LevelsEffectNode.affected_channel", args,
                       [&](core::Edit& edit) { SetAffectedChannel(edit, n.uid, channel); });
            })
        .def("get_parameters",
             [](const LevelsEffectNode& n) -> py::object {
                 const auto project = Read();
                 const NodeInfo info = Resolve(*project, n.uid);
                 const core::LevelsParams* params = info.effect->levels ? &*info.effect->levels : nullptr;
                 // One component on an RGB channel holds for all three, as the evaluator reads it.
                 const auto component = [&](std::size_t i) {
                     if (params == nullptr || params->components.empty()) return core::LevelsComponent{};
                     return params->components[params->components.size() == 3 ? i : 0];
                 };
                 if (RgbChannel(*project, info, params)) {
                     LevelsParamsRGB out;
                     for (std::size_t i = 0; i < 3; ++i) {
                         const core::LevelsComponent c = component(i);
                         out.input_min[i] = c.input_min;
                         out.input_max[i] = c.input_max;
                         out.gamma[i] = c.gamma;
                         out.output_min[i] = c.output_min;
                         out.output_max[i] = c.output_max;
                     }
                     out.clamp = component(0).clamp;
                     return py::cast(out);
                 }
                 const core::LevelsComponent c = component(0);
                 return py::cast(LevelsParamsMono{c.input_min, c.input_max, c.gamma, c.output_min, c.output_max, c.clamp});
             })
        .def("set_parameters", [](const LevelsEffectNode& n, const py::object& value) {
            std::vector<core::LevelsComponent> components;
            if (py::isinstance<LevelsParamsMono>(value)) {
                const auto p = value.cast<LevelsParamsMono>();
                components.push_back(Component(p.input_min, p.input_max, p.gamma, p.output_min, p.output_max, p.clamp));
            } else if (py::isinstance<LevelsParamsRGB>(value)) {
                const auto p = value.cast<LevelsParamsRGB>();
                for (std::size_t i = 0; i < 3; ++i) {
                    components.push_back(Component(p.input_min[i], p.input_max[i], p.gamma[i], p.output_min[i],
                                                   p.output_max[i], p.clamp));
                }
            } else {
                throw py::type_error("parameters must be levels.LevelsParamsMono or levels.LevelsParamsRGB");
            }
            core::json::Array json;
            for (const core::LevelsComponent& c : components) {
                json.push_back(core::json::Object{{"clamp", c.clamp}, {"gamma", c.gamma}, {"input_max", c.input_max},
                                                  {"input_min", c.input_min}, {"output_max", c.output_max},
                                                  {"output_min", c.output_min}});
            }
            core::json::Object args = NodeArgs(n.uid);
            args["components"] = json;
            return Mutate("layerstack.LevelsEffectNode.set_parameters", args, [&](core::Edit& edit) {
                core::Effect& e = EditEffect(edit, n.uid);
                if (!e.levels) e.levels = core::LevelsParams{};
                // RGB parameters on a mono channel or a mask keep their mean (`phase1-levels-params`).
                const bool rgb = RgbChannel(edit.project(), Resolve(edit.project(), n.uid), &*e.levels);
                e.levels->components = components.size() == 3 && !rgb
                                           ? std::vector<core::LevelsComponent>{MonoOf(components)}
                                           : components;
            });
        });
    SealClass(levels_node);

    // The node kinds outside the Phase 1 subset keep their classes (handles of opened projects).
    SealClass(py::class_<PaintLayerNode, LayerNode>(m, "PaintLayerNode"));
    SealClass(py::class_<PaintEffectNode, EffectNode>(m, "PaintEffectNode"));
    // get_source() of a stored generator or filter effect: the procedural, or None (python-doc).
    // Their insertion and set_source/remove_source stay release gaps (phase3.3_procedural-families).
    const auto effect_source = [](const Node& n) -> py::object {
        const auto project = Read();
        if (!ProceduralEffectOf(Resolve(*project, n.uid), n.uid).procedural) return py::none();
        return py::cast(SourceSubstance{n.uid, std::nullopt, true});
    };
    SealClass(py::class_<GeneratorEffectNode, EffectNode>(m, "GeneratorEffectNode").def("get_source", effect_source));
    SealClass(py::class_<FilterEffectNode, EffectNode>(m, "FilterEffectNode").def("get_source", effect_source));
    SealClass(py::class_<CompareMaskEffectNode, EffectNode>(m, "CompareMaskEffectNode"));
    SealClass(py::class_<ColorSelectionEffectNode, EffectNode>(m, "ColorSelectionEffectNode"));
    SealClass(py::class_<AnchorPointEffectNode, EffectNode>(m, "AnchorPointEffectNode"));

    // ── Navigation ──────────────────────────────────────────────────────────────────────────────
    m.def(
        "get_root_layer_nodes",
        [](const std::optional<StackHandle>& stack) {
            const auto project = Read();
            return Handles(*project, UidsOf(ResolveStack(*project, StackOrActive(stack)).root_layers));
        },
        py::arg("stack") = py::none());
    m.def("get_node_by_uid", [](Id uid) { return MakeNode(*Read(), uid); }, py::arg("node_id"));
    m.def(
        "get_node_by_name",
        [](const std::string& name, const std::optional<StackHandle>& stack, const std::optional<Node>& parent,
           core::NodeStack node_stack) -> py::object {
            const auto project = Read();
            const StackHandle s = StackOrActive(stack);
            const core::NameScope scope{s.texture_set, s.stack, parent ? parent->uid : core::kNoId, node_stack};
            const std::optional<Id> found = core::ResolveName(*project, scope, name);
            return found ? MakeNode(*project, *found) : py::none();
        },
        py::arg("name"), py::arg("stack") = py::none(), py::arg("parent") = py::none(),
        py::arg("node_stack") = core::NodeStack::Substack,
        "LAY-06: the one node named `name` in the list of `parent` (`node_stack`), or among the root layers of "
        "`stack` (the active stack by default); None when there is none; AmbiguousNameError (a ValueError listing "
        "every candidate id) when several match.");
    m.def(
        "find_nodes_by_name",
        [](const std::string& name) {
            const auto project = Read();
            return Handles(*project, core::FindAllByName(*project, name));
        },
        py::arg("name"), "Every layer and effect of the project named `name`, in tree order.");

    // ── Edition ─────────────────────────────────────────────────────────────────────────────────
    const auto insert = [&m](const char* name, core::NodeType layer_type, std::optional<core::NodeType> effect_type) {
        m.def(
            name,
            [name, layer_type, effect_type](const core::InsertPosition& position, std::optional<std::string> node_name) {
                core::NodeType type = layer_type;
                if (effect_type) {
                    // Painter's insert_fill / insert_paint insert an effect inside or beside an effect.
                    const auto project = Read();
                    const bool effect_position =
                        (position.kind == core::InsertPosition::Kind::InsideNode && position.node_stack != core::NodeStack::Substack) ||
                        ((position.kind == core::InsertPosition::Kind::AboveNode ||
                          position.kind == core::InsertPosition::Kind::BelowNode) &&
                         Resolve(*project, position.node).effect != nullptr);
                    if (effect_position) type = *effect_type;
                }
                const bool named = node_name.has_value();
                return Insert(std::string("layerstack.") + name, position, type, node_name, core::kNoId,
                              [named](core::Edit& edit, Id uid) { InsertDefaults(edit, uid, named); });
            },
            py::arg("position"), py::arg("name") = py::none());
    };
    insert("insert_fill", core::NodeType::FillLayer, core::NodeType::FillEffect);
    insert("insert_paint", core::NodeType::PaintLayer, core::NodeType::PaintEffect);
    insert("insert_group", core::NodeType::GroupLayer, std::nullopt);
    insert("insert_levels_effect", core::NodeType::LevelsEffect, std::nullopt);
    insert("insert_compare_mask_effect", core::NodeType::CompareMaskEffect, std::nullopt);
    insert("insert_color_selection_effect", core::NodeType::ColorSelectionEffect, std::nullopt);
    insert("insert_anchor_point_effect", core::NodeType::AnchorPointEffect, std::nullopt);
    m.def(
        "instantiate",
        [](const core::InsertPosition& position, const LayerNode& source, std::optional<std::string> name) {
            return Insert("layerstack.instantiate", position, core::NodeType::InstanceLayer, name, source.uid);
        },
        py::arg("position"), py::arg("layer"), py::arg("name") = py::none());
    for (const char* name : {"insert_generator_effect", "insert_filter_effect", "insert_smart_material", "insert_smart_mask"}) {
        m.def(name, [name](const py::args&, const py::kwargs&) -> py::object {
            throw ApiError("UnsupportedProcedural", std::string(name) +
                                                        ": procedural content and smart presets are release gaps "
                                                        "(phase3.3_procedural-families, phase3.6_smart-presets-projections)");
        });
    }
    m.def("delete_node", [](const Node& n) {
        return Mutate("layerstack.delete_node", NodeArgs(n.uid), [&](core::Edit& edit) { RemoveNode(edit.project(), n.uid); });
    });

    m.def(
        "sync_stack",
        [](const py::object& stack_json, const std::string& masks_dir, const std::optional<StackHandle>& stack,
           const std::vector<std::string>& keep_visible, std::optional<std::string> stack_key) {
            core::json::Value document;
            std::string source_name = "<dict>";
            if (py::isinstance<py::dict>(stack_json)) {
                document = ToJson(stack_json);
            } else {
                const std::string path = py::str(stack_json).cast<std::string>();
                std::ifstream file(PathFromUtf8(path), std::ios::binary);
                if (!file) throw core::ValueError("sync_stack: cannot read " + path);
                document = core::json::Parse(std::string{std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()});
                source_name = path;
            }
            if (stack_key) {
                // `a.b`: the object under key a, then b (painter_layer_stack.py --stack-key).
                std::string rest = *stack_key;
                while (!rest.empty()) {
                    const std::size_t dot = rest.find('.');
                    const std::string key = rest.substr(0, dot);
                    rest = dot == std::string::npos ? "" : rest.substr(dot + 1);
                    if (!document.IsObject() || !std::get<core::json::Object>(document.data).contains(key)) {
                        throw core::ValueError("sync_stack: " + source_name + " has no key '" + *stack_key + "'");
                    }
                    core::json::Value inner = std::get<core::json::Object>(document.data).at(key);
                    document = std::move(inner);
                }
            }
            if (!document.IsObject()) throw core::ValueError("sync_stack: the stack is not a JSON object");
            const core::json::Object object = std::get<core::json::Object>(document.data);
            const StackHandle target = StackOrActive(stack);
            const std::shared_ptr<OpenProject> project = Session::Get().Current();
            const std::filesystem::path dir = PathFromUtf8(masks_dir);
            SyncOptions options{target.texture_set, target.stack, keep_visible, "", std::nullopt};
            core::json::Array keep;
            for (const std::string& k : keep_visible) keep.push_back(k);
            core::json::Object args{{"stack", object}, {"keep_visible", keep},
                                    {"texture_set", static_cast<std::int64_t>(target.texture_set)},
                                    {"stack_id", static_cast<std::int64_t>(target.stack)}};
            core::json::Object report;
            CallResult result = Mutate("layerstack.sync_stack", args, [&](core::Edit& edit) {
                report = SyncStack(edit, *project->store, object, MaskImageReader(dir), options);
                edit.returned()["sync"] = report;
            });
            result.returned["sync"] = report;
            return result;
        },
        py::arg("stack_json"), py::arg("masks_dir"), py::arg("stack") = py::none(),
        py::arg("keep_visible") = std::vector<std::string>{}, py::arg("stack_key") = py::none(),
        "LAY-07: rebuilds the root group the stack JSON names from it and the PNG images of masks_dir, in one "
        "transaction; every other visible root layer is hidden, never deleted, unless its name starts with a "
        "keep_visible prefix. The Result's `returned['sync']` lists the groups, layers, imports and hidden nodes.");
}

}  // namespace uzp::python
