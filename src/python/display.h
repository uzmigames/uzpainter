#pragma once

// The display state of the fixed render pipeline (task phase2.1_preview-display-presets;
// decisions 038, 042 and 132; `docs/architecture/07-preview-and-render-parity.md` §3.4, §7;
// `03-project-model.md` §1, §3). The bindings (`bind_display.cpp`) and the worker's MCP tools
// (`src/supervisor/worker.cpp`) share it. Nothing here touches Python.
//
// - A display preset is serialisable JSON (`kPresetSchema`): the environment {sha256, exposure,
//   rotation, opacity, blur, dome, colour space, shadows}, background, ground, display
//   configuration, cameras, samples and seed. Only the Assets3D render comparison standard's two
//   presets exist (`U-A3D-RENDERSTD-2`): `common` (the v2 block) and `ref_match` (v3). A preset
//   names its environment by SHA-256; applying one whose environment the project does not store
//   raises `ResourceNotFoundError` and changes nothing.
// - Every value the standard does not vary is pinned. Setters accept the pinned value, or a value
//   the active preset varies (the environment, the `ref_match` per-view rotation, the camera), and
//   raise `UnsupportedInUzPainter` naming the setting, the accepted values and decision 038
//   for anything else. A refused call changes nothing.
// - The display configuration is OCIO with Painter's substance config (by SHA-256) and the view
//   `Default - sRGB`; the colour LUT is none and post effects are off. Tone mapping does not apply
//   to a colour-managed project (`RuntimeError`, as Painter documents) and is unsupported on a
//   Legacy one.
// - The shader is the default `open-pbr` instance at its read-back defaults (`ShaderDefaults`).
// - A camera is Painter's documented camera in its Y-up scene space (`CameraFromJson`), with
//   conversion to and from Blender's convention per the standard's `coordinate_contract`.

#include <array>
#include <string>
#include <string_view>

#include "uzp_core/manifest/json.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/project.h"

namespace uzp::python::display {

namespace json = core::json;

inline constexpr std::string_view kPresetSchema = "uzpainter/display-preset/1";
/// The approved source and SHA-256 of `Render-Comparison-Standard.json` (decision 038).
inline constexpr std::string_view kStandardSource = "U-A3D-RENDERSTD-2";
inline constexpr std::string_view kStandardSha256 = "2ec4281f7a1414c836eb59aec4fa895db0706c2fc9c4e19433325939a6525be5";
/// Painter's `resources/ocio/substance/config.ocio` (`parity/reports/phase0/iray-capture-procedure.md`).
inline constexpr std::string_view kOcioConfigSha256 = "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4";
/// The resource usage of an environment map.
inline constexpr std::string_view kEnvironmentUsage = "ENVIRONMENT";

/// The standard's presets, `common` then `ref_match`, each with no camera and seed 0.
json::Array StandardPresets();
/// The standard preset `name`; `UnsupportedInUzPainter` for any other name.
json::Object StandardPreset(const std::string& name);

/// Sets the display of a new project: the `common` preset with no environment, and the default
/// `open-pbr` shader.
void InitialiseNewProject(core::Project& project);

/// The display state as a preset (round-trips through `ApplyPreset`). A project whose display
/// was never set by this API (a file older than decision 132) has `name` null.
json::Object PresetOf(const core::Project& project);
/// `PresetOf` plus `parity` (the environment is the preset's standard environment, so the state
/// is the comparison standard's; any other is a non-parity preview), `environment_default` (the
/// project names no environment, so `painter_viewport` lights it with the installation's default,
/// decision 212) and the shader.
json::Object State(const core::Project& project);
/// Validates `preset` whole, then sets it. `ValueError` for a malformed preset,
/// `UnsupportedInUzPainter` for a value outside the fixed pipeline, `ResourceNotFoundError` for an
/// environment the project does not store.
void ApplyPreset(core::Edit& edit, const json::Value& preset);
/// `ApplyPreset` on `project` itself (a capture's in-memory copy, never committed).
void ApplyPreset(core::Project& project, const json::Value& preset);

/// One display value (`symbol` names the call in the error): `exposure`, `rotation`, `opacity`,
/// `blur`, `shadows` or `background` (sRGB8 `[r, g, b]`), checked against the active preset.
void SetValue(core::Edit& edit, const std::string& symbol, const std::string& key, const json::Value& value);
/// The environment by SHA-256 (null: none); `ResourceNotFoundError` when the project stores no
/// environment of that hash.
void SetEnvironment(core::Edit& edit, const std::string& symbol, const json::Value& sha256);
/// The colour LUT: only null (no LUT) is accepted.
void SetColorLut(core::Edit& edit, const std::string& symbol, const json::Value& sha256);
/// `get_tone_mapping` / `set_tone_mapping`: always raises (`RuntimeError` on a colour-managed
/// project, `UnsupportedInUzPainter` on a Legacy one).
[[noreturn]] void RefuseToneMapping(const core::Project& project, const std::string& symbol);

/// The default `open-pbr` instance's parameters (decision 042; read back under OCIO,
/// `parity/reports/phase0/iray-references.md` §5).
json::Object ShaderDefaults();
/// `{shader, parameters}` of the project.
json::Object Shader(const core::Project& project);
/// Accepts only known identifiers at their default value; anything else raises
/// `UnsupportedInUzPainter` (decision 042 §5).
void SetShaderParameters(core::Edit& edit, const std::string& symbol, const json::Value& parameters);

/// A validated camera record (Painter's convention): `position`, `rotation` (Euler degrees, X
/// then Y then Z), `projection_type` (`Perspective` | `Orthographic`), `field_of_view` (3-179
/// degrees), `focal_length` (1-500 mm), `focus_distance` (>= 0), `aperture` (pinned to 0) and
/// `orthographic_height` (> 0). `ValueError` for a malformed or out-of-range record,
/// `UnsupportedInUzPainter` for an aperture other than 0.
json::Object CameraFromJson(const json::Value& camera, const std::string& symbol);
/// The default camera, or null when none is set.
json::Value DefaultCamera(const core::Project& project);
/// Sets the default camera (a full record).
void SetCamera(core::Edit& edit, const json::Value& camera, const std::string& symbol);
/// One property of the default camera. `NotYetSupported` when no camera is set (Painter's default
/// framing is unrecorded) and for `field_of_view` / `focal_length`, which Painter couples through
/// an unrecorded sensor size (decision 132).
void SetCameraProperty(core::Edit& edit, const std::string& property, const json::Value& value);
/// The default camera's property; `NotYetSupported` when no camera is set.
json::Value CameraProperty(const core::Project& project, const std::string& property);

/// A camera in Blender's convention (`location`, `rotation_euler_degrees` XYZ, `type`
/// `PERSP` | `ORTHO`, `angle_degrees`, `lens_mm`, `ortho_scale`, `focus_distance`,
/// `aperture_radius`): position `(x, y, z) -> (x, -z, y)`, rotation `B @ Rx @ Ry @ Rz` with `B`
/// that basis change, decomposed into Blender's XYZ Euler angles; lens values unchanged.
json::Object CameraToBlender(const json::Value& camera);
/// The inverse of `CameraToBlender`.
json::Object CameraFromBlender(const json::Value& blender);
/// The rotation of a camera record (validated as `CameraFromJson`): `Rx @ Ry @ Rz` of its Euler
/// angles, rows first. Its columns are the camera's right, up and backward axes in Painter's
/// Y-up scene space (the camera looks along `-column 2`).
std::array<std::array<double, 3>, 3> CameraRotation(const json::Value& camera, const std::string& symbol);

/// Whether `bytes` are an OpenEXR image a display environment can be: a single-part scanline or
/// tiled file whose data window is twice as wide as it is high (an equirectangular map). The
/// reason when not.
std::string EnvironmentProblem(const std::string& bytes);

}  // namespace uzp::python::display
