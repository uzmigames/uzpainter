// Shared binding helpers and the top-level `uzpainter` objects: `Result`, `last_result`,
// `Transaction` (bindings.h).

#include <algorithm>
#include <set>

#include "python/bindings.h"
#include "python/errors.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/resource_url.h"

namespace uzp::python {

NodeInfo Resolve(const core::Project& project, core::Id uid) {
    std::optional<NodeInfo> found;
    core::ForEachNode(project, [&](const core::NodeVisit& visit) {
        if (found) return;
        const core::Id id = visit.layer ? visit.layer->uid : visit.effect->uid;
        if (id != uid) return;
        NodeInfo info;
        info.layer = visit.layer;
        info.effect = visit.effect;
        info.texture_set = visit.texture_set;
        info.stack = visit.stack;
        info.owner = visit.owner;
        info.owner_stack = visit.owner_stack;
        info.root = visit.layer != nullptr && visit.owner == visit.stack;
        info.index = visit.index;
        found = info;
    });
    if (!found) throw core::ValueError("stale handle: node " + std::to_string(uid) + " no longer exists");
    return *found;
}

namespace {

template <typename T>
py::object Handle(core::Id uid) {
    T handle;
    handle.uid = uid;
    return py::cast(handle);
}

}  // namespace

py::object MakeNode(const core::Project& project, core::Id uid) {
    switch (Resolve(project, uid).type()) {
        case core::NodeType::FillLayer: return Handle<FillLayerNode>(uid);
        case core::NodeType::PaintLayer: return Handle<PaintLayerNode>(uid);
        case core::NodeType::GroupLayer: return Handle<GroupLayerNode>(uid);
        case core::NodeType::InstanceLayer: return Handle<InstanceLayerNode>(uid);
        case core::NodeType::FillEffect: return Handle<FillEffectNode>(uid);
        case core::NodeType::PaintEffect: return Handle<PaintEffectNode>(uid);
        case core::NodeType::GeneratorEffect: return Handle<GeneratorEffectNode>(uid);
        case core::NodeType::FilterEffect: return Handle<FilterEffectNode>(uid);
        case core::NodeType::LevelsEffect: return Handle<LevelsEffectNode>(uid);
        case core::NodeType::CompareMaskEffect: return Handle<CompareMaskEffectNode>(uid);
        case core::NodeType::ColorSelectionEffect: return Handle<ColorSelectionEffectNode>(uid);
        case core::NodeType::AnchorPointEffect: return Handle<AnchorPointEffectNode>(uid);
    }
    throw core::ValueError("unknown node type");
}

core::Layer& EditLayer(core::Edit& edit, core::Id uid) {
    core::Layer* layer = core::FindLayer(edit.project(), uid);
    if (layer == nullptr) throw core::ValueError("stale handle: layer " + std::to_string(uid) + " no longer exists");
    return *layer;
}

core::Effect& EditEffect(core::Edit& edit, core::Id uid) {
    core::Effect* effect = core::FindEffect(edit.project(), uid);
    if (effect == nullptr) throw core::ValueError("stale handle: effect " + std::to_string(uid) + " no longer exists");
    return *effect;
}

const core::TextureSet& ResolveSet(const core::Project& project, core::Id id) {
    for (const core::TextureSet& set : project.texture_sets) {
        if (set.id == id) return set;
    }
    throw core::ValueError("stale handle: texture set " + std::to_string(id) + " no longer exists");
}

const core::Stack& ResolveStack(const core::Project& project, const StackHandle& handle) {
    const core::Stack* stack = core::FindStack(project, handle.texture_set, handle.stack);
    if (stack == nullptr) throw core::ValueError("stale handle: stack " + std::to_string(handle.stack) + " no longer exists");
    return *stack;
}

StackHandle StackOrActive(const std::optional<StackHandle>& stack) {
    if (stack) return *stack;
    const std::shared_ptr<OpenProject> project = Session::Get().Current();
    if (project->active_stack == core::kNoId) ThrowProjectError("the project has no stack");
    return {project->active_set, project->active_stack};
}

std::string ResolveResource(const core::Project& project, const ResourceIdHandle& id) {
    if (id.context != "project") {
        ThrowNotYetSupported("resource context '" + id.context +
                             "': only project resources exist in this build (shelves: phase1.21_pyapi-dispatcher-lifecycle)");
    }
    std::set<std::string> matches;
    for (const auto& [sha256, entries] : project.resources) {
        if (!id.version.empty() && sha256 != id.version) continue;
        for (const core::ResourceMeta& meta : entries) {
            if (meta.name == id.name) matches.insert(sha256);
        }
    }
    if (matches.empty()) {
        ThrowResourceNotFound("no project resource " + core::FormatResourceUrl({id.name, id.version}));
    }
    if (matches.size() > 1) {
        ThrowResourceNotFound("the project resource name '" + id.name + "' names " + std::to_string(matches.size()) +
                              " versions; give the version");
    }
    return *matches.begin();
}

ResourceIdHandle ResourceIdOf(const core::Project& project, const std::string& sha256) {
    const auto it = project.resources.find(sha256);
    if (it == project.resources.end() || it->second.empty()) ThrowResourceNotFound("no project resource " + sha256);
    return {"project", it->second.front().name, sha256};
}

CallResult Mutate(const std::string& tool, core::json::Object arguments, const std::function<void(core::Edit&)>& call) {
    py::gil_scoped_release release;
    return Session::Get().Mutate(tool, std::move(arguments), call);
}

std::shared_ptr<const core::Project> Read() { return Session::Get().ReadProject(); }

void SealClass(py::handle cls) { py::setattr(cls, "__slots__", py::tuple()); }

namespace {

py::list Ids(const std::vector<core::Id>& ids) {
    py::list list;
    for (const core::Id id : ids) list.append(py::int_(id));
    return list;
}

/// The Python object of a native `Transaction` block.
struct TransactionBlock {
    std::string name;
    std::optional<CallResult> result;
};

}  // namespace

py::object ResultObject(const CallResult& result) { return py::cast(result); }

void BindCore(py::module_& m) {
    py::class_<CallResult> result(m, "Result",
                                  "What one API call (or one Transaction) did (QG-03): status 'committed', "
                                  "'no_op' or 'pending' (inside an open Transaction), the revision, the node ids "
                                  "created, modified, removed and hidden, and the resource hashes imported and "
                                  "skipped.");
    result.def_property_readonly("status", [](const CallResult& r) { return r.status; })
        .def_property_readonly("revision", [](const CallResult& r) { return r.revision; })
        .def_property_readonly("created", [](const CallResult& r) { return Ids(r.changes.created); })
        .def_property_readonly("modified", [](const CallResult& r) { return Ids(r.changes.modified); })
        .def_property_readonly("removed", [](const CallResult& r) { return Ids(r.changes.removed); })
        .def_property_readonly("hidden", [](const CallResult& r) { return Ids(r.changes.hidden); })
        .def_property_readonly("imported", [](const CallResult& r) { return r.changes.imported; })
        .def_property_readonly("skipped", [](const CallResult& r) { return r.changes.skipped; })
        .def_property_readonly("returned", [](const CallResult& r) { return FromJson(r.returned); })
        .def("to_dict",
             [](const CallResult& r) {
                 core::json::Object o = r.changes.ToJson();
                 o["status"] = r.status;
                 o["revision"] = r.revision;
                 o["returned"] = r.returned;
                 return FromJson(o);
             })
        .def("__repr__", [](const CallResult& r) {
            return "Result(status=" + r.status + ", revision=" + std::to_string(r.revision) + ")";
        });
    SealClass(result);

    m.def(
        "last_result",
        []() -> py::object {
            const std::optional<CallResult> last = Session::Get().LastResult();
            return last ? ResultObject(*last) : py::none();
        },
        "The Result of this thread's last API call, or None.");

    py::class_<TransactionBlock> transaction(
        m, "Transaction",
        "Atomic multi-call execution (10-python-api.md §7): every call inside the `with` block is applied "
        "to one working copy, reads on this thread see it, and the block commits one revision when it "
        "ends normally. A block that raises commits nothing.");
    transaction.def(py::init([](std::string name) { return TransactionBlock{std::move(name), std::nullopt}; }),
                    py::arg("name") = "transaction")
        .def("__enter__",
             [](py::object self) {
                 const std::string name = self.cast<TransactionBlock&>().name;
                 {
                     py::gil_scoped_release release;
                     Session::Get().OpenTransaction(name);
                 }
                 return self;
             })
        .def("__exit__",
             [](TransactionBlock& self, const py::object& type, const py::object&, const py::object&) {
                 if (!type.is_none()) {
                     Session::Get().RollbackTransaction();
                     return false;
                 }
                 CallResult committed;
                 {
                     py::gil_scoped_release release;
                     committed = Session::Get().CommitTransaction();
                 }
                 self.result = committed;
                 return false;
             })
        .def_property_readonly("result", [](const TransactionBlock& self) -> py::object {
            return self.result ? ResultObject(*self.result) : py::none();
        });
    SealClass(transaction);
}

}  // namespace uzp::python
