// `uzpainter.project`: create, open, close, the save modes, revert, the mesh reload, revisions and
// metadata over the project store (session.h).
//
// The store commits every call durably (09-project-file-format.md §4): `save` marks the current
// revision as a named checkpoint (`ProjectSaveMode.Full` also compacts the file), `needs_saving()`
// is "the current revision is not the last named checkpoint", and reopening a file gives its
// current revision. A project created from a mesh has no file path until `save_as`.
//
// `reload_mesh(path)` is one transaction (`mesh/reload.h`): the current mesh is re-derived from its
// stored bytes, the new file is imported and the texture sets are matched by material; the new
// mesh's bytes are stored with the commit. Texture sets the reload adds get the default template's
// channels, as `create` gives them. A refused reload commits nothing and raises its typed error.

#include <filesystem>
#include <fstream>
#include <iterator>
#include <map>
#include <optional>

#include "evaluator/templates.h"
#include "mesh/mesh_import.h"
#include "mesh/reload.h"
#include "python/bindings.h"
#include "python/errors.h"

namespace uzp::python {

namespace {

enum class ProjectSaveMode { Incremental, Full };

store::SaveMode ModeOf(ProjectSaveMode mode) {
    return mode == ProjectSaveMode::Full ? store::SaveMode::full : store::SaveMode::incremental;
}

std::filesystem::path PathOf(const std::string& text) { return PathFromUtf8(text); }


struct Metadata {
    std::string context;
};

/// `reload_mesh`: see above. Returns the call's result (`returned["reload"]` is the report).
CallResult ReloadMesh(const std::string& mesh_file_path, std::optional<bool> import_cameras,
                      const std::map<std::string, std::string>& material_mapping) {
    if (Session::Get().TransactionOpen()) {
        throw ApiError("RuntimeError", "reload_mesh replaces the committed mesh: commit the open Transaction first");
    }
    const std::shared_ptr<OpenProject> project = Session::Get().Current();
    const std::filesystem::path path = PathOf(mesh_file_path);
    std::ifstream file(path, std::ios::binary);
    if (!file) ThrowProjectError("cannot read " + mesh_file_path);
    const std::string bytes{std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};

    const evaluator::TemplateLibrary templates =
        evaluator::TemplateLibrary::Load(evaluator::TemplateLibrary::DefaultDirectory());
    const evaluator::ProjectTemplate* fresh = templates.Find(evaluator::kDefaultTemplateId);
    if (fresh == nullptr) throw ApiError("RuntimeError", "the default project template is not installed");
    mesh::ReloadSettings settings;
    settings.import.mesh_unit_scale = project->document->snapshot().project->settings.mesh_unit_scale;
    settings.material_mapping = material_mapping;
    settings.new_set_channels = fresh->StackChannels();

    store::ProjectStore* store = project->store.get();
    const mesh::ResourceReader read = [store](const std::string& sha256) { return store->ReadResource(sha256); };
    const mesh::MeshSource source{Utf8(path), NowUtc()};
    core::json::Object arguments{{"mesh", Utf8(path.filename())}};
    if (import_cameras) arguments["import_cameras"] = *import_cameras;
    CallResult result = Mutate("project.reload_mesh", std::move(arguments), [&](core::Edit& edit) {
        const mesh::ImportResult current = mesh::RederiveMesh(edit.base(), read);
        const mesh::ImportResult next =
            mesh::ImportMesh(bytes, Utf8(path.filename()), settings.import, path.parent_path());
        store->StageResource(bytes, std::string(mesh::MimeOf(next.format)));
        mesh::ApplyReload(edit, current, next, source, settings);
        if (import_cameras) edit.project().settings.import_cameras = *import_cameras;
    });
    project->mesh_path = Utf8(path);
    return result;
}

py::dict CheckpointsDict(const core::Checkpoints& c) {
    py::dict out;
    out["current"] = c.current;
    out["named"] = c.named ? py::object(py::int_(*c.named)) : py::none();
    out["previous"] = c.previous ? py::object(py::int_(*c.previous)) : py::none();
    return out;
}

}  // namespace

void BindProject(py::module_& m) {
    BindEnum<core::NormalMapFormat>(m, "NormalMapFormat");
    BindEnum<core::TangentSpace>(m, "TangentSpace");
    BindEnum<core::ProjectWorkflow>(m, "ProjectWorkflow");
    py::enum_<ProjectSaveMode>(m, "ProjectSaveMode")
        .value("Incremental", ProjectSaveMode::Incremental)
        .value("Full", ProjectSaveMode::Full);

    py::class_<CreateSettings> settings(m, "Settings", "The project settings `create` reads.");
    settings
        .def(py::init([](std::optional<core::NormalMapFormat> normal_map_format, std::optional<core::TangentSpace> tangent,
                         std::optional<core::ProjectWorkflow> workflow, std::optional<int> resolution,
                         std::optional<double> mesh_unit_scale, std::optional<bool> import_cameras) {
                 return CreateSettings{normal_map_format, tangent, workflow, resolution, mesh_unit_scale, import_cameras};
             }),
             py::arg("normal_map_format") = py::none(), py::arg("tangent_space_mode") = py::none(),
             py::arg("project_workflow") = py::none(), py::arg("default_texture_resolution") = py::none(),
             py::arg("mesh_unit_scale") = py::none(), py::arg("import_cameras") = py::none())
        .def_readwrite("normal_map_format", &CreateSettings::normal_map_format)
        .def_readwrite("tangent_space_mode", &CreateSettings::tangent_space)
        .def_readwrite("project_workflow", &CreateSettings::workflow)
        .def_readwrite("default_texture_resolution", &CreateSettings::default_texture_resolution)
        .def_readwrite("mesh_unit_scale", &CreateSettings::mesh_unit_scale)
        .def_readwrite("import_cameras", &CreateSettings::import_cameras);
    SealClass(settings);

    m.def(
        "create",
        [](const std::string& mesh_file_path, std::optional<CreateSettings> settings) {
            py::gil_scoped_release release;
            Session::Get().Create(PathOf(mesh_file_path), settings.value_or(CreateSettings{}));
        },
        py::arg("mesh_file_path"), py::arg("settings") = py::none(),
        "Imports the mesh and creates a project with one texture set per material (untitled until save_as).");
    m.def(
        "open",
        [](const std::string& path) {
            py::gil_scoped_release release;
            Session::Get().Open(PathOf(path));
        },
        py::arg("project_file_path"));
    m.def("close", [] {
        py::gil_scoped_release release;
        Session::Get().Close();
    });
    m.def("is_open", [] { return Session::Get().IsOpen(); });
    m.def(
        "reload_mesh",
        [](const std::string& path, std::optional<bool> import_cameras,
           const std::map<std::string, std::string>& material_mapping) {
            return ResultObject(ReloadMesh(path, import_cameras, material_mapping));
        },
        py::arg("mesh_file_path"), py::arg("import_cameras") = py::none(),
        py::arg("material_mapping") = std::map<std::string, std::string>{},
        "Replaces the project's mesh, keeping the texture sets matched by material (one transaction); "
        "`material_mapping` accepts renames (current name -> new name). Returns the Result; "
        "`returned['reload']` is the report.");
    m.def(
        "save",
        [](ProjectSaveMode mode) {
            py::gil_scoped_release release;
            Session::Get().Save(ModeOf(mode));
        },
        py::arg("mode") = ProjectSaveMode::Incremental);
    m.def(
        "save_as",
        [](const std::string& path, ProjectSaveMode mode) {
            py::gil_scoped_release release;
            Session::Get().SaveAs(PathOf(path), ModeOf(mode));
        },
        py::arg("project_file_path"), py::arg("mode") = ProjectSaveMode::Incremental);
    m.def(
        "save_as_copy",
        [](const std::string& path, ProjectSaveMode) {
            // A copy is always written compacted (VACUUM INTO): both modes give the smallest file.
            py::gil_scoped_release release;
            Session::Get().SaveAsCopy(PathOf(path));
        },
        py::arg("backup_file_path"), py::arg("mode") = ProjectSaveMode::Incremental);
    m.def(
        "revert",
        [](const py::object& target) {
            std::optional<std::int64_t> revision;
            std::string checkpoint;
            if (py::isinstance<py::int_>(target)) revision = target.cast<std::int64_t>();
            else checkpoint = target.cast<std::string>();
            py::gil_scoped_release release;
            return Session::Get().Revert(revision, checkpoint);
        },
        py::arg("target"),
        "Appends a revision whose content is that of `target`: a revision number or a checkpoint name.");
    m.def("revision", [] { return Session::Get().Revision(); }, "The current revision (the transaction's base inside a Transaction).");
    m.def("checkpoints", [] { return CheckpointsDict(Session::Get().Current()->document->checkpoints()); },
          "{'current', 'named', 'previous'} revisions.");
    m.def("needs_saving", [] { return Session::Get().Current()->document->NeedsSaving(); });
    m.def("file_path", []() -> py::object {
        const std::optional<std::filesystem::path> path = Session::Get().FilePath();
        return path ? py::object(py::str(Utf8(*path))) : py::none();
    });
    m.def("name", [] {
        // A project never saved is named "Untitled", as Painter names it (textureset-project-readback,
        // both recordings; the `$project` export wildcard reads the same name).
        const std::optional<std::filesystem::path> path = Session::Get().FilePath();
        return path ? Utf8(path->stem()) : std::string("Untitled");
    });
    m.def("get_uuid", [] {
        return py::module_::import("uuid").attr("UUID")(Session::Get().Current()->document->project_uuid());
    });
    m.def("last_imported_mesh_path", [] { return Session::Get().Current()->mesh_path; });
    m.def("dump_recipe", [](const py::args&, const py::kwargs&) -> py::object {
        ThrowNotYetSupported("project.dump_recipe is a release gap (phase2.2_recipe-and-diagnostics)");
    });

    py::class_<Metadata> metadata(m, "Metadata", "Project metadata of one context, saved with the project.");
    metadata.def(py::init([](std::string context) { return Metadata{std::move(context)}; }), py::arg("context"))
        .def("list",
             [](const Metadata& md) {
                 std::vector<std::string> keys;
                 const auto project = Read();
                 if (const auto it = project->metadata.find(md.context); it != project->metadata.end()) {
                     for (const auto& [key, value] : it->second) keys.push_back(key);
                 }
                 return keys;
             })
        .def("get",
             [](const Metadata& md, const std::string& key) -> py::object {
                 const auto project = Read();
                 const auto it = project->metadata.find(md.context);
                 if (it == project->metadata.end()) return py::none();
                 const auto value = it->second.find(key);
                 return value == it->second.end() ? py::none() : FromJson(value->second);
             })
        .def("set", [](const Metadata& md, const std::string& key, const py::object& value) {
            const core::json::Value json = ToJson(value);
            return Mutate("project.Metadata.set", core::json::Object{{"context", md.context}, {"key", key}, {"value", json}},
                          [&](core::Edit& edit) { edit.project().metadata[md.context][key] = json; });
        });
    SealClass(metadata);
}

}  // namespace uzp::python
