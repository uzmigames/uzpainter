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
// mesh's bytes are stored with the commit. Texture sets the reload adds get the channels of the
// project's template, as `create` gives them. A refused reload commits nothing and raises its typed
// error.

#include <filesystem>
#include <fstream>
#include <iterator>
#include <map>
#include <optional>

#include "evaluator/templates.h"
#include "mesh/mesh_import.h"
#include "mesh/reload.h"
#include "python/bindings.h"
#include "python/edits.h"
#include "python/errors.h"
#include "python/recipe.h"

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
    const MeshReloadCall reload(mesh_file_path, import_cameras, material_mapping);
    CallResult result = Mutate("project.reload_mesh", reload.arguments(), [&](core::Edit& edit) { reload.Apply(edit); });
    reload.Finish();
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
                         std::optional<double> mesh_unit_scale, std::optional<bool> import_cameras,
                         std::optional<std::string> template_id, std::optional<std::string> ocio_config_hash) {
                 return CreateSettings{normal_map_format, tangent,        workflow,    resolution,
                                       mesh_unit_scale,   import_cameras, template_id, ocio_config_hash};
             }),
             py::arg("normal_map_format") = py::none(), py::arg("tangent_space_mode") = py::none(),
             py::arg("project_workflow") = py::none(), py::arg("default_texture_resolution") = py::none(),
             py::arg("mesh_unit_scale") = py::none(), py::arg("import_cameras") = py::none(),
             py::arg("template") = py::none(), py::arg("ocio_config_hash") = py::none())
        .def_readwrite("normal_map_format", &CreateSettings::normal_map_format)
        .def_readwrite("tangent_space_mode", &CreateSettings::tangent_space)
        .def_readwrite("project_workflow", &CreateSettings::workflow)
        .def_readwrite("default_texture_resolution", &CreateSettings::default_texture_resolution)
        .def_readwrite("mesh_unit_scale", &CreateSettings::mesh_unit_scale)
        .def_readwrite("import_cameras", &CreateSettings::import_cameras)
        .def_readwrite("template", &CreateSettings::template_id,
                       "The id of an installed project template (`templates()`); None creates the project with "
                       "no template (\"default\"). The project records it: its base values are the backdrop of "
                       "every evaluation and export (decision 116).")
        .def_readwrite("ocio_config_hash", &CreateSettings::ocio_config_hash,
                       "The SHA-256 of the OCIO configuration to create the project under; None creates a Legacy "
                       "project. Only Painter's substance config is supported; any other hash raises "
                       "NotYetSupported before anything is created (decision 207).");
    SealClass(settings);

    m.def(
        "templates",
        [] {
            const evaluator::TemplateLibrary library =
                evaluator::TemplateLibrary::Load(evaluator::TemplateLibrary::DefaultDirectory());
            py::list out;
            for (const std::string& id : library.Ids()) {
                const evaluator::ProjectTemplate* t = library.Find(id);
                if (t == nullptr || t->channelDefaults) continue;
                py::dict entry;
                entry["id"] = t->id;
                entry["name"] = t->name;
                entry["painter_template"] = t->painterTemplate ? py::object(py::str(*t->painterTemplate)) : py::none();
                out.append(std::move(entry));
            }
            return out;
        },
        "The installed project templates: [{id, name, painter_template}], `painter_template` naming the shipped "
        "Painter file a template reproduces (None for \"default\").");
    m.def("template", [] { return Session::Get().Current()->document->snapshot().project->settings.template_id; },
          "The id of the template the open project was created from.");

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
    m.def(
        "absolute_file_path",
        []() -> py::object {
            const std::shared_ptr<OpenProject> project = Session::Get().Current();
            if (!project->untitled_dir.empty()) return py::none();
            return py::str(Utf8(project->project_source));
        },
        "The project's store file as an absolute path, resolved against the working directory when `open` "
        "or `save_as` ran (a bundle directory: the `.uzp` it was imported into; decision 118); None while "
        "untitled.");
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
    m.def(
        "dump_recipe",
        [] {
            core::json::Object dump;
            {
                py::gil_scoped_release release;
                dump = DumpCurrentRecipe();
            }
            return FromJson(core::json::Value(std::move(dump)));
        },
        "The recipe dump of the current revision (decision 122): {schema, revision, evaluator_profile, "
        "compat_profile, app_version, resource_hashes, recipe, rebuild, digest}. `recipe` is every "
        "output-determining field and `digest` the SHA-256 of its canonical JSON; `rebuild` holds what only a "
        "rebuild needs. Inside a Transaction it describes the committed revision.");
    m.def(
        "rebuild_from_recipe",
        [](const py::object& recipe, const std::string& resources_dir) {
            core::json::Value dump;
            if (py::isinstance<py::str>(recipe)) {
                const std::filesystem::path path = PathOf(recipe.cast<std::string>());
                std::ifstream file(path, std::ios::binary);
                if (!file) ThrowProjectError("cannot read " + recipe.cast<std::string>());
                dump = core::json::Parse(std::string{std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()});
            } else {
                dump = ToJson(recipe);
            }
            py::gil_scoped_release release;
            Session::Get().Rebuild(dump, PathOf(resources_dir));
        },
        py::arg("recipe"), py::arg("resources_dir"),
        "Opens a new untitled project rebuilt from a recipe dump (a dict, or the path of its JSON file) and the "
        "resource files of `resources_dir` (named `<sha256>`, any extension), in one transaction. Its exports "
        "equal the original's, and its dump_recipe() digest is the recipe's.");

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
