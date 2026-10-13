// `uzpainter.textureset`: texture sets, stacks, channels, resolutions and mesh-map bindings, and
// the active stack (the default `(texture set, stack)` address, inert state otherwise).

#include <algorithm>

#include "python/bindings.h"
#include "python/edits.h"
#include "python/errors.h"
#include "uzp_core/types/errors.h"

namespace uzp::python {

namespace {

struct ChannelHandle {
    StackHandle stack;
    core::ChannelType type = core::ChannelType::BaseColor;
};

struct UVTileHandle {
    int u = 0;
    int v = 0;
    core::Id texture_set = core::kNoId;
};

const core::Channel& ResolveChannel(const core::Project& project, const ChannelHandle& handle) {
    const core::Stack& stack = ResolveStack(project, handle.stack);
    const auto it = stack.channels.find(handle.type);
    if (it == stack.channels.end()) {
        throw core::ValueError("the stack has no " + std::string(core::ToString(handle.type)) + " channel");
    }
    return it->second;
}

bool IsColor(core::ChannelFormat format) {
    return format == core::ChannelFormat::sRGB8 || format == core::ChannelFormat::RGB8 ||
           format == core::ChannelFormat::RGB16 || format == core::ChannelFormat::RGB16F ||
           format == core::ChannelFormat::RGB32F;
}

bool IsFloating(core::ChannelFormat format) {
    return format == core::ChannelFormat::L16F || format == core::ChannelFormat::RGB16F ||
           format == core::ChannelFormat::L32F || format == core::ChannelFormat::RGB32F;
}

int BitDepth(core::ChannelFormat format) {
    switch (format) {
        case core::ChannelFormat::sRGB8:
        case core::ChannelFormat::L8:
        case core::ChannelFormat::RGB8: return 8;
        case core::ChannelFormat::L16:
        case core::ChannelFormat::RGB16:
        case core::ChannelFormat::L16F:
        case core::ChannelFormat::RGB16F: return 16;
        case core::ChannelFormat::L32F:
        case core::ChannelFormat::RGB32F: return 32;
    }
    return 8;
}

core::json::Object SetArgs(core::Id set) { return {{"texture_set", static_cast<std::int64_t>(set)}}; }
core::json::Object StackArgs(const StackHandle& s) {
    return {{"texture_set", static_cast<std::int64_t>(s.texture_set)}, {"stack", static_cast<std::int64_t>(s.stack)}};
}

}  // namespace

void BindTextureSet(py::module_& m) {
    BindEnum<core::ChannelType>(m, "ChannelType");
    BindEnum<core::ChannelFormat>(m, "ChannelFormat");
    BindEnum<core::MeshMapUsage>(m, "MeshMapUsage");

    py::class_<core::Resolution> resolution(m, "Resolution");
    resolution
        .def(py::init([](int width, int height) { return core::Resolution{width, height, {}}; }), py::arg("width") = 1024,
             py::arg("height") = 1024)
        .def_readonly("width", &core::Resolution::width)
        .def_readonly("height", &core::Resolution::height)
        .def("__eq__", [](const core::Resolution& a, const core::Resolution& b) { return a.width == b.width && a.height == b.height; })
        .def("__repr__", [](const core::Resolution& r) {
            return "Resolution(" + std::to_string(r.width) + ", " + std::to_string(r.height) + ")";
        });
    resolution.attr("__hash__") = py::none();
    SealClass(resolution);

    py::class_<UVTileHandle> uvtile(m, "UVTile");
    uvtile.def_readonly("u", &UVTileHandle::u)
        .def_readonly("v", &UVTileHandle::v)
        .def("name", [](const UVTileHandle& t) { return std::to_string(1001 + t.u + 10 * t.v); })
        .def("__repr__", [](const UVTileHandle& t) { return "UVTile(" + std::to_string(t.u) + ", " + std::to_string(t.v) + ")"; });
    SealClass(uvtile);

    py::class_<ChannelHandle> channel(m, "Channel", "A channel of a stack, resolved again on every call.");
    channel.def("type", [](const ChannelHandle& c) { return c.type; })
        .def("format", [](const ChannelHandle& c) { return ResolveChannel(*Read(), c).format; })
        .def("label", [](const ChannelHandle& c) { return ResolveChannel(*Read(), c).label; })
        .def("is_color", [](const ChannelHandle& c) { return IsColor(ResolveChannel(*Read(), c).format); })
        .def("is_floating", [](const ChannelHandle& c) { return IsFloating(ResolveChannel(*Read(), c).format); })
        .def("bit_depth", [](const ChannelHandle& c) { return BitDepth(ResolveChannel(*Read(), c).format); })
        .def(
            "edit",
            [](const ChannelHandle& c, core::ChannelFormat format, std::optional<std::string> label) {
                core::json::Object args = StackArgs(c.stack);
                args["channel"] = std::string(core::ToString(c.type));
                args["format"] = std::string(core::ToString(format));
                return Mutate("textureset.Stack.edit_channel", args, [&](core::Edit& edit) {
                    core::Stack& stack = EditStack(edit, c.stack);
                    const auto it = stack.channels.find(c.type);
                    if (it == stack.channels.end()) throw core::ValueError("the stack has no such channel");
                    it->second.format = format;
                    if (label) it->second.label = *label;
                });
            },
            py::arg("channel_format"), py::arg("label") = py::none());
    SealClass(channel);

    py::class_<StackHandle> stack(m, "Stack", "A layer stack of a texture set.");
    py::class_<TextureSetHandle> texture_set(m, "TextureSet", "A texture set, by its persistent id.");

    stack.def_static(
             "from_name",
             [](const std::string& texture_set, const std::string& name) {
                 const auto project = Read();
                 for (const core::TextureSet& set : project->texture_sets) {
                     if (set.name != texture_set) continue;
                     for (const core::Stack& s : set.stacks) {
                         if (s.name == name) return StackHandle{set.id, s.id};
                     }
                     throw core::ValueError("texture set '" + texture_set + "' has no stack named '" + name + "'");
                 }
                 throw core::ValueError("no texture set named '" + texture_set + "'");
             },
             py::arg("texture_set_name"), py::arg("stack_name") = "")
        .def("uid", [](const StackHandle& s) { return s.stack; })
        .def("name", [](const StackHandle& s) { return ResolveStack(*Read(), s).name; })
        .def("material", [](const StackHandle& s) { return TextureSetHandle{s.texture_set}; })
        .def("all_channels",
             [](const StackHandle& s) {
                 py::dict channels;
                 for (const auto& [type, ch] : ResolveStack(*Read(), s).channels) channels[py::cast(type)] = ChannelHandle{s, type};
                 return channels;
             })
        .def("has_channel", [](const StackHandle& s, core::ChannelType type) { return ResolveStack(*Read(), s).channels.contains(type); })
        .def("get_channel",
             [](const StackHandle& s, core::ChannelType type) {
                 ResolveChannel(*Read(), ChannelHandle{s, type});
                 return ChannelHandle{s, type};
             })
        .def(
            "add_channel",
            [](const StackHandle& s, core::ChannelType type, core::ChannelFormat format, std::optional<std::string> label) {
                core::json::Object args = StackArgs(s);
                args["channel"] = std::string(core::ToString(type));
                args["format"] = std::string(core::ToString(format));
                Mutate("textureset.Stack.add_channel", args, [&](core::Edit& edit) {
                    core::Stack& target = EditStack(edit, s);
                    if (target.channels.contains(type)) {
                        throw core::ValueError("the stack already has a " + std::string(core::ToString(type)) + " channel");
                    }
                    target.channels[type] = core::Channel{format, label.value_or(""), {}};
                });
                return ChannelHandle{s, type};
            },
            py::arg("channel_type"), py::arg("channel_format"), py::arg("label") = py::none())
        .def("remove_channel",
             [](const StackHandle& s, core::ChannelType type) {
                 core::json::Object args = StackArgs(s);
                 args["channel"] = std::string(core::ToString(type));
                 return Mutate("textureset.Stack.remove_channel", args, [&](core::Edit& edit) {
                     core::Stack& target = EditStack(edit, s);
                     if (target.channels.erase(type) == 0) {
                         throw core::ValueError("the stack has no " + std::string(core::ToString(type)) + " channel");
                     }
                     StripChannel(target.root_layers, type);
                 });
             })
        .def(
            "edit_channel",
            [](const StackHandle& s, core::ChannelType type, core::ChannelFormat format, std::optional<std::string> label) {
                core::json::Object args = StackArgs(s);
                args["channel"] = std::string(core::ToString(type));
                args["format"] = std::string(core::ToString(format));
                return Mutate("textureset.Stack.edit_channel", args, [&](core::Edit& edit) {
                    core::Stack& target = EditStack(edit, s);
                    const auto it = target.channels.find(type);
                    if (it == target.channels.end()) {
                        throw core::ValueError("the stack has no " + std::string(core::ToString(type)) + " channel");
                    }
                    it->second.format = format;
                    if (label) it->second.label = *label;
                });
            },
            py::arg("channel_type"), py::arg("channel_format"), py::arg("label") = py::none())
        .def("__eq__", [](const StackHandle& a, const StackHandle& b) { return a.texture_set == b.texture_set && a.stack == b.stack; })
        .def("__hash__", [](const StackHandle& s) { return py::hash(py::make_tuple(s.texture_set, s.stack)); })
        .def("__repr__", [](const StackHandle& s) {
            return "Stack(texture_set=" + std::to_string(s.texture_set) + ", stack=" + std::to_string(s.stack) + ")";
        });
    SealClass(stack);

    texture_set
        .def_static("from_name",
                    [](const std::string& name) {
                        for (const core::TextureSet& set : Read()->texture_sets) {
                            if (set.name == name) return TextureSetHandle{set.id};
                        }
                        throw core::ValueError("no texture set named '" + name + "'");
                    })
        .def("uid", [](const TextureSetHandle& t) { return t.id; })
        .def("name", [](const TextureSetHandle& t) { return ResolveSet(*Read(), t.id).name; })
        .def("original_name", [](const TextureSetHandle& t) { return ResolveSet(*Read(), t.id).original_name; })
        .def("description", [](const TextureSetHandle& t) { return ResolveSet(*Read(), t.id).description; })
        .def("get_resolution", [](const TextureSetHandle& t) { return ResolveSet(*Read(), t.id).resolution; })
        .def("set_resolution",
             [](const TextureSetHandle& t, const core::Resolution& resolution) {
                 core::json::Object args = SetArgs(t.id);
                 args["width"] = resolution.width;
                 args["height"] = resolution.height;
                 return Mutate("textureset.TextureSet.set_resolution", args, [&](core::Edit& edit) {
                     core::TextureSet& set = EditSet(edit, t.id);
                     set.resolution.width = resolution.width;
                     set.resolution.height = resolution.height;
                 });
             })
        .def("all_stacks",
             [](const TextureSetHandle& t) {
                 std::vector<StackHandle> stacks;
                 for (const core::Stack& s : ResolveSet(*Read(), t.id).stacks) stacks.push_back({t.id, s.id});
                 return stacks;
             })
        .def(
            "get_stack",
            [](const TextureSetHandle& t, const std::string& name) {
                for (const core::Stack& s : ResolveSet(*Read(), t.id).stacks) {
                    if (s.name == name) return StackHandle{t.id, s.id};
                }
                throw core::ValueError("the texture set has no stack named '" + name + "'");
            },
            py::arg("stack_name") = "")
        .def("has_uv_tiles", [](const TextureSetHandle& t) { return ResolveSet(*Read(), t.id).uv_tiles.size() > 1; })
        .def("all_uv_tiles",
             [](const TextureSetHandle& t) {
                 std::vector<UVTileHandle> tiles;
                 for (const core::UVTile& tile : ResolveSet(*Read(), t.id).uv_tiles) {
                     tiles.push_back({(tile.udim - 1001) % 10, (tile.udim - 1001) / 10, t.id});
                 }
                 return tiles;
             })
        .def("get_mesh_map_resource",
             [](const TextureSetHandle& t, core::MeshMapUsage usage) -> py::object {
                 const auto project = Read();
                 const core::TextureSet& set = ResolveSet(*project, t.id);
                 const auto it = set.mesh_maps.find(usage);
                 if (it == set.mesh_maps.end()) return py::none();
                 return py::cast(ResourceIdOf(*project, it->second.resource));
             })
        .def("set_mesh_map_resource",
             [](const TextureSetHandle& t, core::MeshMapUsage usage, std::optional<ResourceIdHandle> resource) {
                 core::json::Object args = SetArgs(t.id);
                 args["usage"] = std::string(core::ToString(usage));
                 args["resource"] = resource ? core::json::Value(resource->name + "@" + resource->version) : core::json::Value(nullptr);
                 return Mutate("textureset.TextureSet.set_mesh_map_resource", args,
                               [&](core::Edit& edit) { SetMeshMapResource(edit, t.id, usage, resource); });
             })
        .def("__eq__", [](const TextureSetHandle& a, const TextureSetHandle& b) { return a.id == b.id; })
        .def("__hash__", [](const TextureSetHandle& t) { return py::hash(py::int_(t.id)); })
        .def("__repr__", [](const TextureSetHandle& t) { return "TextureSet(" + std::to_string(t.id) + ")"; });
    SealClass(texture_set);

    m.def("all_texture_sets", [] {
        std::vector<TextureSetHandle> sets;
        for (const core::TextureSet& set : Read()->texture_sets) sets.push_back({set.id});
        return sets;
    });
    m.def("set_resolutions", [](const std::vector<TextureSetHandle>& sets, const core::Resolution& resolution) {
        core::json::Array ids;
        for (const TextureSetHandle& t : sets) ids.push_back(static_cast<std::int64_t>(t.id));
        return Mutate("textureset.set_resolutions",
                      core::json::Object{{"texture_sets", ids}, {"width", resolution.width}, {"height", resolution.height}},
                      [&](core::Edit& edit) {
                          for (const TextureSetHandle& t : sets) {
                              core::TextureSet& set = EditSet(edit, t.id);
                              set.resolution.width = resolution.width;
                              set.resolution.height = resolution.height;
                          }
                      });
    });
    m.def("get_active_stack", [] { return StackOrActive(std::nullopt); },
          "The default (texture set, stack) address of calls that take a stack.");
    m.def("set_active_stack", [](const StackHandle& s) {
        ResolveStack(*Read(), s);
        const std::shared_ptr<OpenProject> project = Session::Get().Current();
        project->active_set = s.texture_set;
        project->active_stack = s.stack;
    });
}

}  // namespace uzp::python
