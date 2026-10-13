// `uzpainter.resource`: project resources by content hash, their URLs, imports and the in-place
// replacement of a bitmap or mask resource on one node (LAY-08).
//
// A project resource is identified by `resource://project/<name>?version=<sha256>`
// (03-project-model.md §3). Importing identical bytes again under the same name changes nothing
// (the hash is reported as skipped); under another name it adds a named entry for the stored
// bytes. `replace_node_resource` rebinds one source of one node and keeps the node's uid; nothing
// else changes. `list_used_resources` lists the entries the layer stacks and mesh maps bind, and
// `resource_origin` the file an entry was imported from (the resource reload of the facade,
// phase1.21).

#include <algorithm>
#include <fstream>
#include <iterator>
#include <set>

#include "python/bindings.h"
#include "python/edits.h"
#include "python/errors.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/resource_url.h"

namespace uzp::python {

namespace {

using Usage = ResourceUsage;

struct ResourceHandle {
    ResourceIdHandle id;
    std::string usage;
};


/// The resource hashes the fills and effects of `layers` bind.
void CollectBound(const std::vector<core::Layer>& layers, std::set<std::string>& hashes) {
    const auto visit = [&](const std::optional<core::FillContent>& fill) {
        if (!fill) return;
        const auto bound = [&](const core::Source& source) {
            if (source.kind() == core::SourceKind::bitmap) {
                hashes.insert(std::get<core::BitmapSource>(source.value).resource.sha256);
            }
        };
        for (const auto& [channel, source] : fill->sources) bound(source);
        if (fill->mono_source) bound(*fill->mono_source);
    };
    for (const core::Layer& layer : layers) {
        visit(layer.fill);
        for (const core::Effect& effect : layer.content_effects) visit(effect.fill);
        if (layer.mask) {
            for (const core::Effect& effect : layer.mask->effects) visit(effect.fill);
        }
        CollectBound(layer.children, hashes);
    }
}

}  // namespace

void BindResource(py::module_& m) {
    py::enum_<Usage>(m, "Usage")
        .value("TEXTURE", Usage::TEXTURE)
        .value("ENVIRONMENT", Usage::ENVIRONMENT)
        .value("COLOR_LUT", Usage::COLOR_LUT)
        .value("GENERATOR", Usage::GENERATOR)
        .value("SMART_MATERIAL", Usage::SMART_MATERIAL);

    py::class_<ResourceIdHandle> id(m, "ResourceID", "`resource://project/<name>?version=<sha256>`.");
    id.def(py::init([](std::string context, std::string name, std::optional<std::string> version) {
               return ResourceIdHandle{std::move(context), std::move(name), version.value_or("")};
           }),
           py::arg("context"), py::arg("name"), py::arg("version") = py::none())
        .def_static("from_url",
                    [](const std::string& url) {
                        const core::ProjectResourceUrl parsed = core::ParseResourceUrl(url);
                        return ResourceIdHandle{"project", parsed.name, parsed.sha256};
                    })
        .def_static(
            "from_project",
            [](const std::string& name, std::optional<std::string> version) {
                return ResourceIdHandle{"project", name, version.value_or("")};
            },
            py::arg("name"), py::arg("version") = py::none())
        .def_readonly("context", &ResourceIdHandle::context)
        .def_readonly("name", &ResourceIdHandle::name)
        .def_property_readonly("version", [](const ResourceIdHandle& r) -> py::object {
            return r.version.empty() ? py::none() : py::object(py::str(r.version));
        })
        .def("url",
             [](const ResourceIdHandle& r) {
                 if (r.version.empty()) throw core::ValueError("a resource URL needs the version (the content hash)");
                 return core::FormatResourceUrl({r.name, r.version});
             })
        .def("__eq__", [](const ResourceIdHandle& a, const ResourceIdHandle& b) {
            return a.context == b.context && a.name == b.name && a.version == b.version;
        })
        .def("__hash__", [](const ResourceIdHandle& r) { return py::hash(py::make_tuple(r.context, r.name, r.version)); })
        .def("__repr__", [](const ResourceIdHandle& r) {
            return "ResourceID(" + r.context + ", " + r.name + ", " + (r.version.empty() ? "None" : r.version) + ")";
        });
    SealClass(id);

    py::class_<ResourceHandle> resource(m, "Resource", "A project resource entry.");
    resource.def("identifier", [](const ResourceHandle& r) { return r.id; })
        .def("gui_name", [](const ResourceHandle& r) { return r.id.name; })
        .def("usages", [](const ResourceHandle& r) { return std::vector<std::string>{r.usage}; });
    SealClass(resource);

    m.def(
        "import_project_resource",
        [](const std::string& file_path, Usage usage, std::optional<std::string> name, std::optional<std::string> group) {
            const ResourceFile file = ReadResourceFile(file_path, usage, name);
            const std::shared_ptr<OpenProject> project = Session::Get().Current();
            std::string sha256;
            core::json::Object args{{"name", file.entry}, {"usage", file.kind}, {"file", file.file_name}};
            if (group) args["group"] = *group;
            Mutate("resource.import_project_resource", args,
                   [&](core::Edit& edit) { sha256 = ImportResourceFile(edit, *project->store, file, group); });
            return ResourceHandle{{"project", file.entry, sha256}, file.kind};
        },
        py::arg("file_path"), py::arg("usage"), py::arg("name") = py::none(), py::arg("group") = py::none());

    m.def("list_project_resources", [] {
        std::vector<ResourceIdHandle> ids;
        for (const auto& [sha256, entries] : Read()->resources) {
            for (const core::ResourceMeta& meta : entries) ids.push_back({"project", meta.name, sha256});
        }
        return ids;
    });

    m.def(
        "list_used_resources",
        [] {
            const auto project = Read();
            std::set<std::string> hashes;
            for (const core::TextureSet& set : project->texture_sets) {
                for (const auto& [usage, binding] : set.mesh_maps) hashes.insert(binding.resource);
                for (const core::Stack& stack : set.stacks) CollectBound(stack.root_layers, hashes);
            }
            std::vector<ResourceIdHandle> ids;
            for (const std::string& sha256 : hashes) {
                const auto entries = project->resources.find(sha256);
                if (entries == project->resources.end()) continue;
                for (const core::ResourceMeta& meta : entries->second) ids.push_back({"project", meta.name, sha256});
            }
            return ids;
        },
        "The project resource entries the layer stacks and mesh maps bind.");

    m.def(
        "resource_origin",
        [](const ResourceIdHandle& id) -> py::object {
            const auto project = Read();
            const std::string sha256 = ResolveResource(*project, id);
            for (const core::ResourceMeta& meta : project->resources.at(sha256)) {
                if (meta.name == id.name && !meta.origin.empty()) return py::str(meta.origin);
            }
            return py::none();
        },
        py::arg("resource_id"), "The file the entry was imported from, or None.");

    m.def(
        "replace_node_resource",
        [](const Node& node, const ResourceIdHandle& replacement, std::optional<core::ChannelType> channel) {
            core::json::Object args{{"node", static_cast<std::int64_t>(node.uid)},
                                    {"resource", replacement.name + "@" + replacement.version}};
            if (channel) args["channel"] = std::string(core::ToString(*channel));
            return Mutate("resource.replace_node_resource", args, [&](core::Edit& edit) {
                const std::string sha256 = ResolveResource(edit.project(), replacement);
                EditBitmap(edit, node.uid, channel).resource.sha256 = sha256;
            });
        },
        py::arg("node"), py::arg("new_resource"), py::arg("channel") = py::none(),
        "LAY-08: rebinds the bitmap (or mask) source of one node to another project resource; the node keeps "
        "its uid and every other binding is unchanged.");

    m.def(
        "update_layer_stack_resource",
        [](const ResourceIdHandle& old_resource, const ResourceIdHandle& new_resource) {
            std::vector<core::Id> nodes;
            Mutate("resource.update_layer_stack_resource",
                   core::json::Object{{"old", old_resource.name + "@" + old_resource.version},
                                      {"new", new_resource.name + "@" + new_resource.version}},
                   [&](core::Edit& edit) { nodes = ReplaceLayerStackResource(edit, old_resource, new_resource); });
            py::list handles;
            const auto project = Read();
            for (const core::Id uid : nodes) handles.append(MakeNode(*project, uid));
            return handles;
        },
        py::arg("old_resource"), py::arg("new_resource"));
}

}  // namespace uzp::python
