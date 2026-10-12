// `uzpainter.diagnostics`: the diagnostic views of the stack (task phase2.1_recipe-diagnostic-views,
// decision 136; docs/architecture/04-layer-stack-and-compositing.md §8, 10-python-api.md §7).
//
// `isolate`, `contribution`, `material_views` and `region_stats` evaluate the committed revision
// (diagnostics.h) with the GIL released and return plain dicts naming the export source of each
// view (decision 076) and the revision read. A map is `{width, height, components, values}`,
// `values` the float32 little-endian bytes of its samples, rows top first, `components` per texel.
// `snapshot_layer_tree` and `diff_snapshots` are the layer-tree snapshot and its structural diff
// (`uzp_core/document/layer_tree.h`). Nothing here commits a revision or changes the document.

#include <string>
#include <utility>
#include <vector>

#include "evaluator/diagnostics.h"
#include "python/bindings.h"
#include "python/diagnostics.h"
#include "python/errors.h"
#include "uzp_core/document/layer_tree.h"

namespace uzp::python {

namespace {

using evaluator::DiagnosticMap;
using evaluator::DiagnosticMapId;
using evaluator::DiagnosticSource;

core::Id NodeUid(const py::object& node) {
    if (py::isinstance<Node>(node)) return node.cast<const Node&>().uid;
    if (py::isinstance<py::int_>(node) && !py::isinstance<py::bool_>(node)) {
        const long long uid = node.cast<long long>();
        if (uid > 0) return static_cast<core::Id>(uid);
    }
    throw ApiError("TypeError", "a node is a layerstack node or its positive uid");
}

/// A ChannelType, or a map name: a channel type's name, "Normal_OpenGL" or "Normal_DirectX".
DiagnosticMapId MapArg(const py::object& map) {
    if (py::isinstance<core::ChannelType>(map)) return DiagnosticMapId::Channel(map.cast<core::ChannelType>());
    if (py::isinstance<py::str>(map)) {
        render::Result<DiagnosticMapId> parsed = evaluator::ParseMapName(map.cast<std::string>());
        if (parsed) return *parsed;
        throw ApiError("ValueError", "unknown map " + map.cast<std::string>() +
                                         ": a channel type name, Normal_OpenGL or Normal_DirectX");
    }
    throw ApiError("TypeError", "a map is a textureset.ChannelType or its name, Normal_OpenGL or Normal_DirectX");
}

py::dict MapDict(const DiagnosticMap& map) {
    py::dict out;
    out["width"] = map.width;
    out["height"] = map.height;
    out["components"] = map.components;
    out["values"] = py::bytes(reinterpret_cast<const char*>(map.values.data()), map.values.size() * sizeof(float));
    return out;
}

py::list Triple(const std::array<float, 3>& v) { return py::cast(std::vector<double>{v[0], v[1], v[2]}); }

py::dict IsolateDict(const core::Snapshot& snapshot, const DiagnosticMapId& map, const evaluator::IsolationResult& r) {
    py::dict out;
    out["source"] = evaluator::SourceName({DiagnosticSource::Kind::Isolated, map, {}, r.node});
    out["revision"] = snapshot.revision;
    out["node"] = r.node;
    out["was_visible"] = r.wasVisible;
    out["map"] = MapDict(r.map);
    return out;
}

py::dict ContributionDict(const core::Snapshot& snapshot, const DiagnosticMapId& map,
                          const evaluator::ContributionResult& r) {
    py::dict out;
    out["source"] = evaluator::SourceName({DiagnosticSource::Kind::Contribution, map, {}, r.node});
    out["isolated_source"] = evaluator::SourceName({DiagnosticSource::Kind::Isolated, map, {}, r.node});
    out["revision"] = snapshot.revision;
    out["node"] = r.node;
    out["full"] = MapDict(r.full);
    out["isolated"] = MapDict(r.isolated);
    out["difference"] = MapDict(r.difference);
    return out;
}

py::dict MaterialViewsDict(const core::Snapshot& snapshot, const DiagnosticMaterialViews& r) {
    const core::Id material = r.views.material;
    py::dict views;
    for (const evaluator::MaterialView& view : r.views.views) {
        py::dict v;
        v["source"] = evaluator::SourceName({DiagnosticSource::Kind::MaterialView, {}, view.view, material});
        v["leaks_source"] = evaluator::SourceName({DiagnosticSource::Kind::MaterialLeaks, {}, view.view, material});
        v["channel"] = view.view == evaluator::MaterialViewKind::ID ? py::object(py::none())
                                                                    : py::object(py::cast(view.channel));
        v["values"] = MapDict(view.values);
        v["leaks"] = MapDict(view.leaks);
        v["leak_count"] = view.leakTexels.size();
        py::list texels;
        for (const evaluator::LeakTexel& t : view.leakTexels) {
            py::dict texel;
            texel["x"] = t.x;
            texel["y"] = t.y;
            texel["value"] = Triple(t.value);
            texel["own"] = Triple(t.own);
            texels.append(std::move(texel));
        }
        v["leak_texels"] = std::move(texels);
        v["modal_id"] = view.modalId ? py::object(Triple(*view.modalId)) : py::object(py::none());
        views[py::str(std::string(evaluator::MaterialViewName(view.view)))] = std::move(v);
    }
    py::list missing;
    for (const evaluator::MaterialViewKind view : r.views.missing) missing.append(std::string(evaluator::MaterialViewName(view)));
    py::dict refused;
    for (const auto& [view, reason] : r.refused) refused[py::str(view)] = reason;
    py::dict out;
    out["revision"] = snapshot.revision;
    out["material"] = material;
    out["mask_source"] = evaluator::SourceName({DiagnosticSource::Kind::MaterialMask, {}, {}, material});
    out["mask"] = MapDict(r.views.mask);
    out["inside"] = r.views.inside;
    out["views"] = std::move(views);
    out["missing"] = std::move(missing);
    out["refused"] = std::move(refused);
    return out;
}

}  // namespace

void BindDiagnostics(py::module_& m) {
    m.def(
        "isolate",
        [](const py::object& node, const py::object& map) {
            const core::Id uid = NodeUid(node);
            const DiagnosticMapId id = MapArg(map);
            std::unique_ptr<DiagnosticRun> run;
            evaluator::IsolationResult result;
            {
                py::gil_scoped_release release;
                run = std::make_unique<DiagnosticRun>();
                result = run->Isolate(uid, id);
            }
            return IsolateDict(run->snapshot(), id, result);
        },
        py::arg("node"), py::arg("map"),
        "`map` of the committed revision evaluated with `node` hidden in a private copy (LAY-09): the document, "
        "its revision and every visibility flag are unchanged. {source, revision, node, was_visible, map}.");
    m.def(
        "contribution",
        [](const py::object& node, const py::object& map) {
            const core::Id uid = NodeUid(node);
            const DiagnosticMapId id = MapArg(map);
            std::unique_ptr<DiagnosticRun> run;
            evaluator::ContributionResult result;
            {
                py::gil_scoped_release release;
                run = std::make_unique<DiagnosticRun>();
                result = run->Contribution(uid, id);
            }
            return ContributionDict(run->snapshot(), id, result);
        },
        py::arg("node"), py::arg("map"),
        "The full map, the map with `node` hidden and their difference (full - isolated, one float32 subtraction "
        "per sample, never clamped). {source, isolated_source, revision, node, full, isolated, difference}.");
    m.def(
        "material_views",
        [](const py::object& material) {
            const core::Id uid = NodeUid(material);
            std::unique_ptr<DiagnosticRun> run;
            DiagnosticMaterialViews result;
            {
                py::gil_scoped_release release;
                run = std::make_unique<DiagnosticRun>();
                result = run->MaterialViews(uid);
            }
            return MaterialViewsDict(run->snapshot(), result);
        },
        py::arg("material"),
        "The material's effective mask and its ID, BaseColor, Height, Normal, Roughness and Metallic views with "
        "their leaks (LAY-14, decision 075). {revision, material, mask_source, mask, inside, views: {name: "
        "{source, leaks_source, channel, values, leaks, leak_count, leak_texels, modal_id}}, missing, refused}.");
    m.def(
        "region_stats",
        [](const py::object& map, const py::object& mask) {
            const DiagnosticMapId id = MapArg(map);
            const core::Id uid = NodeUid(mask);
            std::unique_ptr<DiagnosticRun> run;
            std::string stats;
            {
                py::gil_scoped_release release;
                run = std::make_unique<DiagnosticRun>();
                stats = evaluator::RegionStatsJson(run->RegionStats(id, uid));
            }
            py::dict out;
            out["source"] = evaluator::SourceName({DiagnosticSource::Kind::RegionStats, id, {}, uid});
            out["revision"] = run->snapshot().revision;
            out["stats"] = FromJson(core::json::Parse(stats));
            return out;
        },
        py::arg("map"), py::arg("mask"),
        "Statistics of `map` inside the region of the material `mask` (DIA-01): {source, revision, stats}, "
        "`stats` the canonical statistics the export writes for the source.");
    m.def(
        "snapshot_layer_tree",
        [] {
            const core::Snapshot snapshot = Session::Get().Current()->document->snapshot();
            return FromJson(core::json::Value(core::SnapshotLayerTree(*snapshot.project, snapshot.revision)));
        },
        "The layer tree of the committed revision: {schema, revision, stacks, nodes} with every node's uid, kind, "
        "name, visibility, place and parameters.");
    m.def(
        "diff_snapshots",
        [](const py::object& before, const py::object& after) {
            return FromJson(core::json::Value(core::DiffSnapshots(ToJson(before), ToJson(after))));
        },
        py::arg("before"), py::arg("after"),
        "The nodes and stacks added, removed and modified between two snapshots, each change a JSON pointer "
        "with its values: {schema, before_revision, after_revision, stacks, added, removed, modified}.");
}

}  // namespace uzp::python
