// `uzpainter.display`, `uzpainter.render.display` and `uzpainter.render.shader`: the display state
// of the fixed render pipeline (display.h; decisions 038, 042 and 132). Getters return the
// current state; every setter is one transaction that accepts only the pipeline's values and
// raises before any change for anything else. `uzpainter.render.capture` (capture.h, decision
// 148) changes nothing.

#include "python/bindings.h"
#include "python/capture.h"
#include "python/display.h"
#include "python/errors.h"
#include "uzp_core/types/resource_url.h"

namespace uzp::python {

namespace {

namespace json = core::json;

enum class ToneMappingFunction { Linear, ACES };
enum class CameraProjectionType { Perspective, Orthographic };

/// Painter's `display.Camera(_camera_id)`: the project's default camera is id 0.
struct CameraHandle {
    int id = 0;
};

py::object CameraValue(const char* property) { return FromJson(display::CameraProperty(*Read(), property)); }

py::object SetCameraValue(const char* property, const json::Value& value) {
    return ResultObject(Mutate("display.Camera." + std::string(property), json::Object{{property, value}},
                               [&](core::Edit& edit) { display::SetCameraProperty(edit, property, value); }));
}

/// An optional non-negative-or-any integer argument (not a bool).
std::optional<std::int64_t> IntArg(const py::object& value, const char* name) {
    if (value.is_none()) return std::nullopt;
    if (!py::isinstance<py::int_>(value) || py::isinstance<py::bool_>(value)) {
        throw ApiError("TypeError", std::string(name) + " must be an integer or None");
    }
    return value.cast<std::int64_t>();
}

py::object SetDisplayValue(const char* name, const char* key, const json::Value& value) {
    const std::string symbol = std::string("uzpainter.render.display.") + name;
    return ResultObject(Mutate("render.display." + std::string(name), json::Object{{key, value}},
                               [&](core::Edit& edit) { display::SetValue(edit, symbol, key, value); }));
}

}  // namespace

void BindDisplay(py::module_& display_module, py::module_& render_display, py::module_& shader) {
    // ── uzpainter.display (Painter's documented module, with the camera record calls) ─────────
    py::enum_<ToneMappingFunction>(display_module, "ToneMappingFunction")
        .value("Linear", ToneMappingFunction::Linear)
        .value("ACES", ToneMappingFunction::ACES);
    py::enum_<CameraProjectionType>(display_module, "CameraProjectionType")
        .value("Perspective", CameraProjectionType::Perspective)
        .value("Orthographic", CameraProjectionType::Orthographic);

    display_module.def(
        "get_environment_resource",
        []() -> py::object {
            const auto project = Read();
            const auto& sha256 = project->display.environment.resource;
            if (!sha256) return py::none();
            return py::cast(ResourceIdOf(*project, *sha256));
        },
        "The environment map of the project, or None.");
    display_module.def(
        "set_environment_resource",
        [](const ResourceIdHandle& resource) {
            return ResultObject(Mutate("display.set_environment_resource",
                                       json::Object{{"resource", resource.name + "@" + resource.version}},
                                       [&](core::Edit& edit) {
                                           display::SetEnvironment(edit, "uzpainter.display.set_environment_resource",
                                                                   ResolveResource(edit.project(), resource));
                                       }));
        },
        py::arg("new_env_map"),
        "Sets the environment map: a project resource imported with usage ENVIRONMENT (ResourceNotFoundError otherwise).");
    display_module.def(
        "get_color_lut_resource",
        []() -> py::object {
            const auto project = Read();
            if (!project->display.color_lut) return py::none();
            return py::cast(ResourceIdOf(*project, *project->display.color_lut));
        },
        "The colour LUT of the project: always None under the fixed pipeline (decision 038).");
    display_module.def(
        "set_color_lut_resource",
        [](const py::object& resource) {
            json::Value given;
            if (!resource.is_none()) {
                const ResourceIdHandle id = resource.cast<ResourceIdHandle>();
                given = id.version.empty() ? id.name : core::FormatResourceUrl({id.name, id.version});
            }
            return ResultObject(Mutate("display.set_color_lut_resource", json::Object{{"resource", given}}, [&](core::Edit& edit) {
                display::SetColorLut(edit, "uzpainter.display.set_color_lut_resource", given);
            }));
        },
        py::arg("new_color_lut"), "Accepts only None (no colour LUT); any LUT raises UnsupportedInUzPainter (decision 038).");
    display_module.def(
        "get_tone_mapping", []() -> py::object { display::RefuseToneMapping(*Read(), "uzpainter.display.get_tone_mapping"); },
        "Raises RuntimeError on a colour-managed project (as Painter documents) and UnsupportedInUzPainter on a "
        "Legacy project (decision 042).");
    display_module.def(
        "set_tone_mapping",
        [](ToneMappingFunction) -> py::object { display::RefuseToneMapping(*Read(), "uzpainter.display.set_tone_mapping"); },
        py::arg("new_tone_mapping"), "Raises as get_tone_mapping does; nothing changes.");

    display_module.def(
        "camera", [] { return FromJson(display::DefaultCamera(*Read())); },
        "The default camera as a record (Painter's convention), or None when none is set.");
    display_module.def(
        "set_camera",
        [](const py::object& camera) {
            const json::Value record = ToJson(camera);
            return ResultObject(Mutate("display.set_camera", json::Object{{"camera", record}}, [&](core::Edit& edit) {
                display::SetCamera(edit, record, "uzpainter.display.set_camera");
            }));
        },
        py::arg("camera"),
        "Sets the default camera from a whole record: position, rotation (Euler degrees), projection_type, "
        "field_of_view, focal_length, focus_distance, aperture (0) and orthographic_height.");
    display_module.def(
        "camera_to_blender", [](const py::object& camera) { return FromJson(display::CameraToBlender(ToJson(camera))); },
        py::arg("camera"), "The camera record in Blender's convention (the standard's coordinate_contract).");
    display_module.def(
        "camera_from_blender", [](const py::object& camera) { return FromJson(display::CameraFromBlender(ToJson(camera))); },
        py::arg("camera"), "The camera record of a camera in Blender's convention.");

    py::class_<CameraHandle> camera(display_module, "Camera",
                                    "The project's camera in Painter's Y-up scene space (Painter's documented properties).");
    camera.def(py::init([](int camera_id) { return CameraHandle{camera_id}; }), py::arg("_camera_id"))
        .def_static("get_default_camera", [] {
            Read();  // ProjectError when no project is open
            return CameraHandle{0};
        })
        .def_property(
            "position", [](const CameraHandle&) { return CameraValue("position"); },
            [](const CameraHandle&, const std::array<double, 3>& v) { SetCameraValue("position", json::Array{v[0], v[1], v[2]}); })
        .def_property(
            "rotation", [](const CameraHandle&) { return CameraValue("rotation"); },
            [](const CameraHandle&, const std::array<double, 3>& v) { SetCameraValue("rotation", json::Array{v[0], v[1], v[2]}); })
        .def_property(
            "field_of_view", [](const CameraHandle&) { return CameraValue("field_of_view"); },
            [](const CameraHandle&, double v) { SetCameraValue("field_of_view", v); })
        .def_property(
            "focal_length", [](const CameraHandle&) { return CameraValue("focal_length"); },
            [](const CameraHandle&, double v) { SetCameraValue("focal_length", v); })
        .def_property(
            "focus_distance", [](const CameraHandle&) { return CameraValue("focus_distance"); },
            [](const CameraHandle&, double v) { SetCameraValue("focus_distance", v); })
        .def_property(
            "aperture", [](const CameraHandle&) { return CameraValue("aperture"); },
            [](const CameraHandle&, double v) { SetCameraValue("aperture", v); })
        .def_property(
            "orthographic_height", [](const CameraHandle&) { return CameraValue("orthographic_height"); },
            [](const CameraHandle&, double v) { SetCameraValue("orthographic_height", v); })
        .def_property(
            "projection_type",
            [](const CameraHandle&) {
                const json::Value value = display::CameraProperty(*Read(), "projection_type");
                return std::get<std::string>(value.data) == "Perspective" ? CameraProjectionType::Perspective
                                                                          : CameraProjectionType::Orthographic;
            },
            [](const CameraHandle&, CameraProjectionType type) {
                SetCameraValue("projection_type", type == CameraProjectionType::Perspective ? "Perspective" : "Orthographic");
            });
    SealClass(camera);

    // ── uzpainter.render.display (the fixed pipeline's values and presets) ────────────────────
    render_display.def(
        "state", [] { return FromJson(display::State(*Read())); },
        "The display state: the preset's fields, `parity` (the environment is the preset's standard one and every "
        "shader parameter is at its default), "
        "`environment_default`, `shadows_effect` (the shadows flag changes no render), `ao_strength` and "
        "`ao_channel` (painter_viewport's AO mesh map strength and the AO channel's use, read-only), "
        "`cavity_radius` (painter_viewport's cavity radius in metres, read-only) and the shader.");
    render_display.def(
        "preset", [] { return FromJson(display::PresetOf(*Read())); },
        "The display state as a preset (uzpainter/display-preset/1), which apply_preset takes back.");
    render_display.def(
        "presets", [] { return FromJson(display::StandardPresets()); },
        "The standard's presets: 'common' (the v2 block) and 'ref_match' (v3), with no camera and seed 0.");
    render_display.def(
        "apply_preset",
        [](const py::object& preset) {
            const json::Value value = ToJson(preset);
            return ResultObject(Mutate("render.display.apply_preset", json::Object{{"preset", value}},
                                       [&](core::Edit& edit) { display::ApplyPreset(edit, value); }));
        },
        py::arg("preset"), "Validates the whole preset, then sets it in one transaction.");
    render_display.def("set_exposure", [](double v) { return SetDisplayValue("set_exposure", "exposure", v); },
                       py::arg("exposure"), "Environment exposure: 0 only.");
    render_display.def("set_rotation", [](double v) { return SetDisplayValue("set_rotation", "rotation", v); },
                       py::arg("rotation"), "Environment rotation: 0, or a ref_match per-view rotation.");
    render_display.def("set_opacity", [](double v) { return SetDisplayValue("set_opacity", "opacity", v); },
                       py::arg("opacity"), "Environment opacity: 0 only.");
    render_display.def("set_blur", [](double v) { return SetDisplayValue("set_blur", "blur", v); }, py::arg("blur"),
                       "Environment blur: 0 only.");
    render_display.def("set_shadows", [](bool v) { return SetDisplayValue("set_shadows", "shadows", v); },
                       py::arg("shadows"),
                       "Shadows: the active preset's value only. Recorded, but it changes no render: painter_viewport "
                       "always traces its self-occlusion (decision 251).");
    render_display.def(
        "set_background",
        [](const py::object& rgb) { return SetDisplayValue("set_background", "background", ToJson(rgb)); },
        py::arg("srgb8"), "The clear colour as sRGB8 [r, g, b]: the active preset's only.");

    // ── uzpainter.render.shader ───────────────────────────────────────────────────────────────
    shader.def(
        "parameters", [] { return FromJson(display::Shader(*Read()).at("parameters")); },
        "The shader parameters: the default open-pbr instance's, with the stored double_sided (decisions 042, 196).");
    shader.def(
        "set_parameters",
        [](const py::object& parameters) {
            const json::Value value = ToJson(parameters);
            return ResultObject(Mutate("render.shader.set_parameters", json::Object{{"parameters", value}}, [&](core::Edit& edit) {
                display::SetShaderParameters(edit, "uzpainter.render.shader.set_parameters", value);
            }));
        },
        py::arg("parameters"),
        "Merges into the stored parameters: double_sided takes true or false (project state no render reads; "
        "true is a non-parity state), every other parameter only the default open-pbr instance's value "
        "(decisions 042, 196).");
}

void BindCapture(py::module_& render) {
    render.def(
        "capture",
        [](const py::object& path, const std::string& mode, const py::object& camera, const py::object& size,
           const py::object& samples, const py::object& seed, const py::object& preset,
           const std::optional<StackHandle>& stack) {
            RefuseUnavailableMode(mode);  // before anything else (decision 148)
            CaptureArguments arguments;
            arguments.mode = mode;
            arguments.path = PathFromUtf8(py::module_::import("os").attr("fspath")(path).cast<std::string>());
            if (!camera.is_none()) arguments.camera = ToJson(camera);
            if (!size.is_none()) {
                const py::sequence pair = size.cast<py::sequence>();
                if (pair.size() != 2) throw ApiError("ValueError", "size is (width, height)");
                const std::optional<std::int64_t> width = IntArg(pair[0], "the width");
                const std::optional<std::int64_t> height = IntArg(pair[1], "the height");
                if (!width || !height) throw ApiError("TypeError", "size is (width, height), two integers");
                arguments.size = std::pair{*width, *height};
            }
            arguments.samples = IntArg(samples, "samples");
            arguments.seed = IntArg(seed, "seed");
            if (!preset.is_none()) arguments.preset = ToJson(preset);
            if (stack) arguments.stack = std::pair{stack->texture_set, stack->stack};
            json::Object receipt;
            {
                py::gil_scoped_release release;
                receipt = Capture(arguments);
            }
            return FromJson(receipt);
        },
        py::arg("path"), py::arg("mode"), py::arg("camera") = py::none(), py::arg("size") = py::none(),
        py::arg("samples") = py::none(), py::arg("seed") = py::none(), py::arg("preset") = py::none(),
        py::arg("stack") = py::none(),
        "Captures the committed revision to `path` (a .png; an .exr and a .receipt.json beside it) and returns the "
        "receipt. Modes: painter_viewport (the preview pass, offscreen; needs size), base_color, channel:<name> "
        "(a ChannelType name, or the export's documentMap name), mask:<uid> (texture-space, equal to the export). "
        "painter_iray raises PathTracerUnavailable (P3-PATHTRACER).");
}

}  // namespace uzp::python
