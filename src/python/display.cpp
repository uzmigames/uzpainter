// The display state of the fixed render pipeline (display.h).

#include "python/display.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <optional>
#include <vector>

#include "python/errors.h"
#include "tinyexr.h"
#include "uzp_core/types/errors.h"

namespace uzp::python::display {

namespace {

constexpr const char* kDecision = "decision 038";

// ── The standard (`Render-Comparison-Standard.json`, U-A3D-RENDERSTD-2) ────────────────────────

/// The Painter environment of the v2 block, "Studio White Soft" (an Adobe starter asset, never
/// shipped: used on the owner's machine by hash; the standard's `blender.environment.sha256`).
constexpr const char* kCommonEnvironment = "c2bb3294099b130bfa0f4bdae677efac544ba97ad3afd579a2563333e748c2c3";
/// `presets.ref_match.blender.environment.sha256`: `HDRI/TOS-RefMatch-Skeletal-Mage.exr`.
constexpr const char* kRefMatchEnvironment = "77eeed8de580113581d50258e0ab3dd055aa29fa7d5ab614f2599ce036e0841d";

/// The seed of UzPainter's own sampler is a 32-bit word.
constexpr std::int64_t kMaxSeed = 0xFFFFFFFFll;

json::Array Srgb8(int r, int g, int b) { return {r, g, b}; }

json::Object Rgb(const std::array<int, 3>& c) { return {{"clear_color", true}, {"srgb8", Srgb8(c[0], c[1], c[2])}}; }

struct PresetSpec {
    const char* name;
    const char* block;     // where the standard defines it
    std::int64_t version;  // of that block
    const char* environment;
    bool shadows;
    std::array<int, 3> background;
    std::vector<double> rotations;  // accepted environment rotations
};

const std::vector<PresetSpec>& Specs() {
    // `common`: the v2 top-level block (envRotation 0, shadows off, clear colour on; the
    // background it expects is sRGB8 89,89,89). `ref_match`: `presets.ref_match` v3 (shadows on,
    // clear colour 141,142,148; envRotation 0 for the front view, rotated by the camera yaw for
    // back and side views: 180, and +-90 whose sign is unverified, so both are accepted as given;
    // decision 132).
    static const std::vector<PresetSpec> specs{
        {"common", "painter (v2 common block)", 2, kCommonEnvironment, false, {89, 89, 89}, {0.0}},
        {"ref_match", "presets.ref_match", 3, kRefMatchEnvironment, true, {141, 142, 148}, {0.0, 90.0, -90.0, 180.0, 270.0}},
    };
    return specs;
}

const PresetSpec* FindSpec(const std::string& name) {
    for (const PresetSpec& spec : Specs()) {
        if (name == spec.name) return &spec;
    }
    return nullptr;
}

json::Object DisplayConfiguration() {
    return {{"mode", "ocio"},
            {"config", "substance"},
            {"config_sha256", std::string(kOcioConfigSha256)},
            {"view", "Default - sRGB"},
            {"color_lut", nullptr},
            {"post_effects", false}};
}

json::Object Ground() { return {{"enabled", false}, {"visible_below", false}}; }

json::Object Standard(const PresetSpec& spec) {
    return {{"source", std::string(kStandardSource)},
            {"sha256", std::string(kStandardSha256)},
            {"block", spec.block},
            {"version", spec.version}};
}

json::Object PresetFromSpec(const PresetSpec& spec) {
    return {{"schema", std::string(kPresetSchema)},
            {"name", spec.name},
            {"standard", Standard(spec)},
            {"environment",
             json::Object{{"sha256", spec.environment},
                          {"exposure", 0.0},
                          {"rotation", 0.0},
                          {"opacity", 0.0},
                          {"blur", 0.0},
                          {"dome", "infinite_sphere"},
                          {"color_space", "Linear"},
                          {"shadows", spec.shadows}}},
            {"background", Rgb(spec.background)},
            {"ground", Ground()},
            {"display", DisplayConfiguration()},
            {"cameras", json::Array{}},
            {"samples", std::int64_t{256}},
            {"seed", std::int64_t{0}}};
}

// ── Errors ──────────────────────────────────────────────────────────────────────────────────────

/// `UnsupportedInUzPainter(symbol, reason)`: `setting` = `value` is outside the fixed pipeline.
[[noreturn]] void Unsupported(const std::string& symbol, const std::string& setting, const std::string& value,
                              const std::string& accepted) {
    ApiError error("UnsupportedInUzPainter",
                   symbol + " is not supported in UzPainter: " + setting + " " + value +
                       " is outside the fixed render pipeline; accepted: " + accepted + " (" + kDecision + ")");
    error.symbol = symbol;
    error.reason = setting + " " + value + " is outside the fixed render pipeline; accepted: " + accepted + " (" +
                   kDecision + ")";
    throw error;
}

[[noreturn]] void Invalid(const std::string& message) { throw core::ValueError(message); }

std::string Text(const json::Value& value) {
    if (value.IsString()) return "'" + std::get<std::string>(value.data) + "'";
    return json::WriteCanonical(value);
}

std::string Join(const std::vector<double>& values) {
    std::string text;
    for (const double v : values) text += (text.empty() ? "" : ", ") + json::FormatDouble(v);
    return text;
}

// ── JSON access ─────────────────────────────────────────────────────────────────────────────────

const json::Object& AsObject(const json::Value& value, const std::string& where) {
    if (!value.IsObject()) Invalid(where + " must be an object");
    return std::get<json::Object>(value.data);
}

const json::Value& Need(const json::Object& object, const std::string& key, const std::string& where) {
    const auto it = object.find(key);
    if (it == object.end()) Invalid(where + " has no '" + key + "'");
    return it->second;
}

void OnlyKeys(const json::Object& object, std::initializer_list<const char*> keys, const std::string& where) {
    for (const auto& [key, value] : object) {
        if (std::none_of(keys.begin(), keys.end(), [&](const char* k) { return key == k; })) {
            Invalid(where + " has an unknown key '" + key + "'");
        }
    }
    for (const char* key : keys) Need(object, key, where);
}

double Number(const json::Value& value, const std::string& where) {
    if (value.IsInt()) return static_cast<double>(std::get<std::int64_t>(value.data));
    if (value.IsDouble()) return std::get<double>(value.data);
    Invalid(where + " must be a number");
}

bool Bool(const json::Value& value, const std::string& where) {
    if (!value.IsBool()) Invalid(where + " must be a boolean");
    return std::get<bool>(value.data);
}

const std::string& String(const json::Value& value, const std::string& where) {
    if (!value.IsString()) Invalid(where + " must be a string");
    return std::get<std::string>(value.data);
}

std::array<double, 3> Vector3(const json::Value& value, const std::string& where) {
    if (!value.IsArray() || std::get<json::Array>(value.data).size() != 3) Invalid(where + " must be a list of 3 numbers");
    const json::Array& a = std::get<json::Array>(value.data);
    return {Number(a[0], where), Number(a[1], where), Number(a[2], where)};
}

json::Array Json3(const std::array<double, 3>& v) { return {v[0], v[1], v[2]}; }

bool IsSha256(const std::string& text) {
    return text.size() == 64 &&
           std::all_of(text.begin(), text.end(), [](char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); });
}

// ── The stored state ────────────────────────────────────────────────────────────────────────────
//
// `DisplayState` keeps the environment's resource, rotation, exposure, opacity and blur, the
// shadows, the background, the colour LUT, post effects and cameras in its own fields; the rest
// of a preset lives in `extra` (`preset`, `standard`, `ground`, `display_configuration`, `samples`,
// `seed`) and in `environment.extra` (`dome`, `color_space`).

const PresetSpec* ActiveSpec(const core::Project& project) {
    const auto it = project.display.extra.find("preset");
    if (it == project.display.extra.end() || !it->second.IsString()) return nullptr;
    return FindSpec(std::get<std::string>(it->second.data));
}

/// The active preset, or `UnsupportedInUzPainter` when the display state is not one.
const PresetSpec& RequireSpec(const core::Project& project, const std::string& symbol) {
    const PresetSpec* spec = ActiveSpec(project);
    if (spec == nullptr) {
        Unsupported(symbol, "the display state", "(no preset)",
                    "a state set by apply_preset with the preset 'common' or 'ref_match'");
    }
    return *spec;
}

json::Value Extra(const json::Object& extra, const char* key) {
    const auto it = extra.find(key);
    return it == extra.end() ? json::Value{} : it->second;
}

/// The project's environment entry of `sha256` holds usage ENVIRONMENT.
bool StoresEnvironment(const core::Project& project, const std::string& sha256) {
    const auto it = project.resources.find(sha256);
    if (it == project.resources.end()) return false;
    return std::any_of(it->second.begin(), it->second.end(),
                       [](const core::ResourceMeta& meta) { return meta.usage == kEnvironmentUsage; });
}

void RequireEnvironment(const core::Project& project, const std::string& sha256, const std::string& symbol) {
    if (!StoresEnvironment(project, sha256)) {
        ThrowResourceNotFound(symbol + ": the project stores no environment " + sha256 +
                              " (import its file with resource.import_project_resource(path, Usage.ENVIRONMENT)); "
                              "no substitute is used");
    }
}

void CheckValue(const std::string& symbol, const std::string& setting, double value, const std::vector<double>& accepted) {
    if (std::find(accepted.begin(), accepted.end(), value) == accepted.end()) {
        Unsupported(symbol, setting, json::FormatDouble(value), Join(accepted));
    }
}

// ── Shader ──────────────────────────────────────────────────────────────────────────────────────

constexpr const char* kShaderId = "open-pbr";

// ── Camera ──────────────────────────────────────────────────────────────────────────────────────

constexpr const char* kNoCamera =
    "the project has no camera yet: Painter's default camera of a new project (its framing of the scene) is "
    "unrecorded (decision 132); set a whole camera with uzpainter.display.set_camera";

constexpr double kDegrees = 57.29577951308232;  // 180 / pi, as Python's math.degrees

/// sin and cos of `degrees`, exact at multiples of 90.
void SinCos(double degrees, double& s, double& c) {
    const double r = std::fmod(degrees, 360.0);
    const double turn = r < 0.0 ? r + 360.0 : r;
    if (turn == 0.0) {
        s = 0.0, c = 1.0;
    } else if (turn == 90.0) {
        s = 1.0, c = 0.0;
    } else if (turn == 180.0) {
        s = 0.0, c = -1.0;
    } else if (turn == 270.0) {
        s = -1.0, c = 0.0;
    } else {
        s = std::sin(degrees / kDegrees);
        c = std::cos(degrees / kDegrees);
    }
}

using Matrix = std::array<std::array<double, 3>, 3>;

Matrix Multiply(const Matrix& a, const Matrix& b) {
    Matrix m{};
    for (int i = 0; i < 3; ++i) {
        for (int j = 0; j < 3; ++j) m[i][j] = a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j];
    }
    return m;
}

Matrix Rx(double d) {
    double s, c;
    SinCos(d, s, c);
    return {{{1, 0, 0}, {0, c, -s}, {0, s, c}}};
}
Matrix Ry(double d) {
    double s, c;
    SinCos(d, s, c);
    return {{{c, 0, s}, {0, 1, 0}, {-s, 0, c}}};
}
Matrix Rz(double d) {
    double s, c;
    SinCos(d, s, c);
    return {{{c, -s, 0}, {s, c, 0}, {0, 0, 1}}};
}

/// `(x, y, z) -> (x, -z, y)`: Painter's Y-up scene space to Blender's Z-up world.
const Matrix kToBlender{{{1, 0, 0}, {0, 0, -1}, {0, 1, 0}}};
const Matrix kFromBlender{{{1, 0, 0}, {0, 0, 1}, {0, -1, 0}}};

/// An angle from `std::atan2` / `std::asin` in degrees, with -0 as 0 and -180 as 180 (the
/// canonical branch (-180, 180]).
double Angle(double radians) {
    double d = radians * kDegrees + 0.0;
    if (d == -180.0) d = 180.0;
    return d;
}

double Clamp1(double v) { return std::max(-1.0, std::min(1.0, v)); }

/// Blender's XYZ Euler angles of `m` = Rz(z) @ Ry(y) @ Rx(x), y in [-90, 90].
std::array<double, 3> EulerXYZ(const Matrix& m) {
    const double y = Angle(std::asin(Clamp1(-m[2][0])));
    if (m[2][0] == 1.0 || m[2][0] == -1.0) return {0.0, y, Angle(std::atan2(-m[0][1], m[1][1]))};
    return {Angle(std::atan2(m[2][1], m[2][2])), y, Angle(std::atan2(m[1][0], m[0][0]))};
}

/// Painter's Euler angles of `m` = Rx(x) @ Ry(y) @ Rz(z), y in [-90, 90].
std::array<double, 3> EulerPainter(const Matrix& m) {
    const double y = Angle(std::asin(Clamp1(m[0][2])));
    if (m[0][2] == 1.0 || m[0][2] == -1.0) return {0.0, y, Angle(std::atan2(m[1][0], m[1][1]))};
    return {Angle(std::atan2(-m[1][2], m[2][2])), y, Angle(std::atan2(-m[0][1], m[0][0]))};
}

}  // namespace

// ── Presets ─────────────────────────────────────────────────────────────────────────────────────

json::Array StandardPresets() {
    json::Array presets;
    for (const PresetSpec& spec : Specs()) presets.push_back(PresetFromSpec(spec));
    return presets;
}

json::Object StandardPreset(const std::string& name) {
    const PresetSpec* spec = FindSpec(name);
    if (spec == nullptr) Unsupported("uzpainter.render.display.preset", "preset", "'" + name + "'", "'common', 'ref_match'");
    return PresetFromSpec(*spec);
}

void InitialiseNewProject(core::Project& project) {
    core::DisplayState& d = project.display;
    d = core::DisplayState{};
    const PresetSpec& common = Specs().front();
    d.environment.resource.reset();
    d.environment.rotation = 0.0;
    d.environment.exposure = 0.0;
    d.environment.opacity = 0.0;
    d.environment.blur = 0.0;
    d.environment.extra = {{"dome", "infinite_sphere"}, {"color_space", "Linear"}};
    d.shadows = common.shadows;
    d.background = Rgb(common.background);
    d.extra = {{"preset", common.name},
               {"standard", Standard(common)},
               {"ground", Ground()},
               {"display_configuration", DisplayConfiguration()},
               {"samples", std::int64_t{256}},
               {"seed", std::int64_t{0}}};
    d.shader.id = kShaderId;
    d.shader.parameters = ShaderDefaults();
}

json::Object PresetOf(const core::Project& project) {
    const core::DisplayState& d = project.display;
    json::Object configuration;
    if (const json::Value stored = Extra(d.extra, "display_configuration"); stored.IsObject()) {
        configuration = std::get<json::Object>(stored.data);
    }
    configuration["color_lut"] = d.color_lut ? json::Value(*d.color_lut) : json::Value{};
    configuration["post_effects"] = !d.post_effects.empty();
    return {{"schema", std::string(kPresetSchema)},
            {"name", Extra(d.extra, "preset")},
            {"standard", Extra(d.extra, "standard")},
            {"environment",
             json::Object{{"sha256", d.environment.resource ? json::Value(*d.environment.resource) : json::Value{}},
                          {"exposure", d.environment.exposure},
                          {"rotation", d.environment.rotation},
                          {"opacity", d.environment.opacity},
                          {"blur", d.environment.blur},
                          {"dome", Extra(d.environment.extra, "dome")},
                          {"color_space", Extra(d.environment.extra, "color_space")},
                          {"shadows", d.shadows}}},
            {"background", d.background},
            {"ground", Extra(d.extra, "ground")},
            {"display", std::move(configuration)},
            {"cameras", d.cameras},
            {"samples", Extra(d.extra, "samples")},
            {"seed", Extra(d.extra, "seed")}};
}

json::Object State(const core::Project& project) {
    json::Object state = PresetOf(project);
    const PresetSpec* spec = ActiveSpec(project);
    const auto& resource = project.display.environment.resource;
    state["parity"] = spec != nullptr && resource && *resource == spec->environment;
    state["shader"] = Shader(project);
    return state;
}

void ApplyPreset(core::Edit& edit, const json::Value& value) { ApplyPreset(edit.project(), value); }

void ApplyPreset(core::Project& project, const json::Value& value) {
    const std::string symbol = "uzpainter.render.display.apply_preset";
    const json::Object& preset = AsObject(value, "the preset");
    OnlyKeys(preset,
             {"schema", "name", "standard", "environment", "background", "ground", "display", "cameras", "samples", "seed"},
             "the preset");
    if (String(Need(preset, "schema", "the preset"), "the preset's schema") != kPresetSchema) {
        Invalid("the preset's schema must be '" + std::string(kPresetSchema) + "'");
    }
    const std::string& name = String(Need(preset, "name", "the preset"), "the preset's name");
    const PresetSpec* spec = FindSpec(name);
    if (spec == nullptr) Unsupported(symbol, "preset", "'" + name + "'", "'common', 'ref_match'");
    const json::Object pinned = PresetFromSpec(*spec);
    const auto pin = [&](const char* key) {
        const json::Value& given = Need(preset, key, "the preset");
        if (!(given == pinned.at(key))) Unsupported(symbol, std::string(key), Text(given), Text(pinned.at(key)));
    };
    pin("standard");
    pin("background");
    pin("ground");
    pin("display");
    pin("samples");

    const json::Object& environment = AsObject(Need(preset, "environment", "the preset"), "environment");
    OnlyKeys(environment, {"sha256", "exposure", "rotation", "opacity", "blur", "dome", "color_space", "shadows"},
             "environment");
    const json::Object& pinned_environment = std::get<json::Object>(pinned.at("environment").data);
    for (const char* key : {"exposure", "opacity", "blur", "dome", "color_space", "shadows"}) {
        const json::Value& given = environment.at(key);
        const json::Value& want = pinned_environment.at(key);
        const bool same = given.IsNumber() && want.IsNumber() ? Number(given, key) == Number(want, key) : given == want;
        if (!same) Unsupported(symbol, std::string("environment.") + key, Text(given), Text(want));
    }
    const double rotation = Number(environment.at("rotation"), "environment.rotation") + 0.0;
    CheckValue(symbol, "environment.rotation", rotation, spec->rotations);
    std::optional<std::string> sha256;
    if (const json::Value& given = environment.at("sha256"); !given.IsNull()) {
        sha256 = String(given, "environment.sha256");
        if (!IsSha256(*sha256)) Invalid("environment.sha256 must be a lowercase SHA-256 or null");
    }

    const json::Value& cameras_value = Need(preset, "cameras", "the preset");
    if (!cameras_value.IsArray()) Invalid("cameras must be a list");
    json::Array cameras;
    for (const json::Value& camera : std::get<json::Array>(cameras_value.data)) cameras.push_back(CameraFromJson(camera, symbol));
    if (cameras.size() > 1) Unsupported(symbol, "cameras", "(" + std::to_string(cameras.size()) + " cameras)", "none or one (the default camera)");

    const json::Value& seed = Need(preset, "seed", "the preset");
    if (!seed.IsInt() || std::get<std::int64_t>(seed.data) < 0 || std::get<std::int64_t>(seed.data) > kMaxSeed) {
        Invalid("seed must be an integer in 0.." + std::to_string(kMaxSeed) + " (UzPainter's own sampler)");
    }
    // Everything is valid; the environment must be stored before anything changes.
    if (sha256) RequireEnvironment(project, *sha256, symbol);

    core::DisplayState& d = project.display;
    d.environment.resource = sha256;
    d.environment.rotation = rotation;
    d.environment.exposure = 0.0;
    d.environment.opacity = 0.0;
    d.environment.blur = 0.0;
    d.environment.extra["dome"] = environment.at("dome");
    d.environment.extra["color_space"] = environment.at("color_space");
    d.shadows = spec->shadows;
    d.background = std::get<json::Object>(pinned.at("background").data);
    d.color_lut.reset();
    d.post_effects.clear();
    d.cameras = std::move(cameras);
    d.extra["preset"] = spec->name;
    d.extra["standard"] = pinned.at("standard");
    d.extra["ground"] = pinned.at("ground");
    json::Object configuration = std::get<json::Object>(pinned.at("display").data);
    configuration.erase("color_lut");
    configuration.erase("post_effects");
    d.extra["display_configuration"] = std::move(configuration);
    d.extra["samples"] = pinned.at("samples");
    d.extra["seed"] = seed;
}

void SetValue(core::Edit& edit, const std::string& symbol, const std::string& key, const json::Value& value) {
    const PresetSpec& spec = RequireSpec(edit.project(), symbol);
    core::DisplayState& d = edit.project().display;
    if (key == "exposure" || key == "opacity" || key == "blur") {
        CheckValue(symbol, "environment " + key, Number(value, key), {0.0});
        (key == "exposure" ? d.environment.exposure : key == "opacity" ? d.environment.opacity : d.environment.blur) = 0.0;
    } else if (key == "rotation") {
        const double rotation = Number(value, key) + 0.0;
        CheckValue(symbol, "environment rotation (preset '" + std::string(spec.name) + "')", rotation, spec.rotations);
        d.environment.rotation = rotation;
    } else if (key == "shadows") {
        const bool shadows = Bool(value, key);
        if (shadows != spec.shadows) {
            Unsupported(symbol, "shadows (preset '" + std::string(spec.name) + "')", shadows ? "True" : "False",
                        spec.shadows ? "True" : "False");
        }
    } else if (key == "background") {
        const std::array<double, 3> rgb = Vector3(value, "the background (sRGB8 [r, g, b])");
        const std::array<double, 3> want{static_cast<double>(spec.background[0]), static_cast<double>(spec.background[1]),
                                         static_cast<double>(spec.background[2])};
        if (rgb != want) {
            Unsupported(symbol, "the clear colour (preset '" + std::string(spec.name) + "')", Text(value),
                        Text(Srgb8(spec.background[0], spec.background[1], spec.background[2])));
        }
    } else {
        Invalid("unknown display value '" + key + "'");
    }
}

void SetEnvironment(core::Edit& edit, const std::string& symbol, const json::Value& sha256) {
    RequireSpec(edit.project(), symbol);
    if (sha256.IsNull()) {
        edit.project().display.environment.resource.reset();
        return;
    }
    const std::string& hash = String(sha256, "the environment");
    RequireEnvironment(edit.project(), hash, symbol);
    edit.project().display.environment.resource = hash;
}

void SetColorLut(core::Edit& edit, const std::string& symbol, const json::Value& sha256) {
    if (!sha256.IsNull()) Unsupported(symbol, "the colour LUT", Text(sha256), "None (no colour LUT)");
    edit.project().display.color_lut.reset();
}

void RefuseToneMapping(const core::Project& project, const std::string& symbol) {
    const std::string& mode = project.settings.color_management.mode;
    if (!mode.empty() && mode != "legacy") {
        throw ApiError("RuntimeError", "The project is color managed: tone mapping is not available (" + symbol + ")");
    }
    ApiError error("UnsupportedInUzPainter",
                   symbol + " is not supported in UzPainter: tone mapping applies to a Legacy project's display, and "
                            "the only supported display transform is OCIO 'Default - sRGB' (" +
                       kDecision + "); accepted: none");
    error.symbol = symbol;
    error.reason = std::string("tone mapping applies to a Legacy project's display, and the only supported display "
                               "transform is OCIO 'Default - sRGB' (") +
                   kDecision + "); accepted: none";
    throw error;
}

// ── Shader ──────────────────────────────────────────────────────────────────────────────────────

json::Object ShaderDefaults() {
    // Painter 12.1.5's default `open-pbr` instance ("Main shader"), decision 042 and the OCIO
    // read-back of `parity/reports/phase0/iray-references.md` §5. Identifier -> panel setting:
    // diffuse_roughness_enabled (diffuse roughness), anisotropy_enabled (anisotropy),
    // specular_ior (IOR), specular_color_enabled (specular colour), transmission_enabled,
    // subsurface_enabled, coat_enabled, fuzz_enabled, thin_film_enabled (each section's enable),
    // emission_luminance (Emission / Luminance), displacement_enabled (Displacement &
    // Tessellation / Enable), displacement_source_channel, displacement_scale_unit,
    // displacement_scale (Displacement / Source Channel, Scale unit, Scale amount),
    // tessellation_mode, tessellation_subdivisions (Tessellation / Subdivision Mode, Count),
    // alpha_test_enabled, alpha_blending_enabled, double_sided (Opacity / Enable alpha test,
    // Enable alpha blending, Double sided).
    return {{"diffuse_roughness_enabled", false},
            {"anisotropy_enabled", false},
            {"specular_ior", 1.5},
            {"specular_color_enabled", false},
            {"transmission_enabled", false},
            {"subsurface_enabled", false},
            {"coat_enabled", false},
            {"fuzz_enabled", false},
            {"thin_film_enabled", false},
            {"emission_luminance", 0.0},
            {"displacement_enabled", true},
            {"displacement_source_channel", "Height"},
            {"displacement_scale_unit", "Normalized"},
            {"displacement_scale", 0.0},
            {"tessellation_mode", "Uniform"},
            {"tessellation_subdivisions", std::int64_t{1}},
            {"alpha_test_enabled", false},
            {"alpha_blending_enabled", false},
            {"double_sided", false}};
}

json::Object Shader(const core::Project& project) {
    return {{"shader", project.display.shader.id}, {"parameters", project.display.shader.parameters}};
}

void SetShaderParameters(core::Edit& edit, const std::string& symbol, const json::Value& parameters) {
    const json::Object& given = AsObject(parameters, "the shader parameters");
    const json::Object defaults = ShaderDefaults();
    for (const auto& [key, value] : given) {
        const auto known = defaults.find(key);
        if (known == defaults.end()) {
            std::string names;
            for (const auto& [name, v] : defaults) names += (names.empty() ? "" : ", ") + name;
            Unsupported(symbol, "the shader parameter '" + key + "'", "(unknown)", "the default open-pbr instance's parameters " + names);
        }
        const json::Value& want = known->second;
        const bool same = value.IsNumber() && want.IsNumber() ? Number(value, key) == Number(want, key) : value == want;
        if (!same) Unsupported(symbol, "the shader parameter '" + key + "'", Text(value), Text(want) + " (open-pbr default)");
    }
    core::ShaderState& shader = edit.project().display.shader;
    shader.id = kShaderId;
    shader.parameters = defaults;
}

// ── Cameras ─────────────────────────────────────────────────────────────────────────────────────

json::Object CameraFromJson(const json::Value& value, const std::string& symbol) {
    const json::Object& camera = AsObject(value, "the camera");
    OnlyKeys(camera,
             {"position", "rotation", "projection_type", "field_of_view", "focal_length", "focus_distance", "aperture",
              "orthographic_height"},
             "the camera");
    const std::string& projection = String(camera.at("projection_type"), "projection_type");
    if (projection != "Perspective" && projection != "Orthographic") {
        Invalid("projection_type must be 'Perspective' or 'Orthographic', not '" + projection + "'");
    }
    const double fov = Number(camera.at("field_of_view"), "field_of_view");
    const double focal = Number(camera.at("focal_length"), "focal_length");
    const double focus = Number(camera.at("focus_distance"), "focus_distance");
    const double aperture = Number(camera.at("aperture"), "aperture");
    const double height = Number(camera.at("orthographic_height"), "orthographic_height");
    if (fov < 3.0 || fov > 179.0) Invalid("field_of_view " + json::FormatDouble(fov) + " is outside 3..179 degrees");
    if (focal < 1.0 || focal > 500.0) Invalid("focal_length " + json::FormatDouble(focal) + " is outside 1..500 mm");
    if (focus < 0.0) Invalid("focus_distance must not be negative");
    if (!(height > 0.0)) Invalid("orthographic_height must be positive");
    if (aperture != 0.0) Unsupported(symbol, "the camera aperture", json::FormatDouble(aperture), "0 (no depth of field)");
    return {{"position", Json3(Vector3(camera.at("position"), "position"))},
            {"rotation", Json3(Vector3(camera.at("rotation"), "rotation"))},
            {"projection_type", projection},
            {"field_of_view", fov},
            {"focal_length", focal},
            {"focus_distance", focus},
            {"aperture", 0.0},
            {"orthographic_height", height}};
}

json::Value DefaultCamera(const core::Project& project) {
    if (project.display.cameras.empty()) return nullptr;
    return project.display.cameras.front();
}

void SetCamera(core::Edit& edit, const json::Value& camera, const std::string& symbol) {
    json::Object record = CameraFromJson(camera, symbol);
    json::Array& cameras = edit.project().display.cameras;
    if (cameras.empty()) {
        cameras.push_back(std::move(record));
    } else {
        cameras.front() = std::move(record);
    }
}

void SetCameraProperty(core::Edit& edit, const std::string& property, const json::Value& value) {
    const std::string symbol = "uzpainter.display.Camera." + property;
    if (property == "field_of_view" || property == "focal_length") {
        ThrowNotYetSupported(symbol +
                             ": Painter changes the focal length with the field of view (and back) through a sensor "
                             "size that is unrecorded (decision 132); set a whole camera with uzpainter.display.set_camera");
    }
    json::Array& cameras = edit.project().display.cameras;
    if (cameras.empty()) ThrowNotYetSupported(symbol + ": " + kNoCamera);
    json::Object record = std::get<json::Object>(cameras.front().data);
    record[property] = value;
    cameras.front() = CameraFromJson(record, symbol);
}

json::Value CameraProperty(const core::Project& project, const std::string& property) {
    if (project.display.cameras.empty()) ThrowNotYetSupported("uzpainter.display.Camera." + property + ": " + kNoCamera);
    const json::Object& record = std::get<json::Object>(project.display.cameras.front().data);
    const auto it = record.find(property);
    if (it == record.end()) Invalid("the camera has no property '" + property + "'");
    return it->second;
}

json::Object CameraToBlender(const json::Value& value) {
    const json::Object camera = CameraFromJson(value, "uzpainter.display.camera_to_blender");
    const std::array<double, 3> p = Vector3(camera.at("position"), "position");
    const std::array<double, 3> r = Vector3(camera.at("rotation"), "rotation");
    const Matrix m = Multiply(kToBlender, Multiply(Rx(r[0]), Multiply(Ry(r[1]), Rz(r[2]))));
    const bool perspective = std::get<std::string>(camera.at("projection_type").data) == "Perspective";
    return {{"location", json::Array{p[0], -p[2] + 0.0, p[1]}},
            {"rotation_euler_degrees", Json3(EulerXYZ(m))},
            {"type", perspective ? "PERSP" : "ORTHO"},
            {"angle_degrees", camera.at("field_of_view")},
            {"lens_mm", camera.at("focal_length")},
            {"ortho_scale", camera.at("orthographic_height")},
            {"focus_distance", camera.at("focus_distance")},
            {"aperture_radius", camera.at("aperture")}};
}

std::array<std::array<double, 3>, 3> CameraRotation(const json::Value& value, const std::string& symbol) {
    const json::Object camera = CameraFromJson(value, symbol);
    const std::array<double, 3> r = Vector3(camera.at("rotation"), "rotation");
    return Multiply(Rx(r[0]), Multiply(Ry(r[1]), Rz(r[2])));
}

json::Object CameraFromBlender(const json::Value& value) {
    const json::Object& blender = AsObject(value, "the Blender camera");
    OnlyKeys(blender,
             {"location", "rotation_euler_degrees", "type", "angle_degrees", "lens_mm", "ortho_scale", "focus_distance",
              "aperture_radius"},
             "the Blender camera");
    const std::array<double, 3> l = Vector3(blender.at("location"), "location");
    const std::array<double, 3> e = Vector3(blender.at("rotation_euler_degrees"), "rotation_euler_degrees");
    const std::string& type = String(blender.at("type"), "type");
    if (type != "PERSP" && type != "ORTHO") Invalid("type must be 'PERSP' or 'ORTHO', not '" + type + "'");
    const Matrix m = Multiply(kFromBlender, Multiply(Rz(e[2]), Multiply(Ry(e[1]), Rx(e[0]))));
    const json::Object camera{{"position", json::Array{l[0], l[2], -l[1] + 0.0}},
                              {"rotation", Json3(EulerPainter(m))},
                              {"projection_type", type == "PERSP" ? "Perspective" : "Orthographic"},
                              {"field_of_view", blender.at("angle_degrees")},
                              {"focal_length", blender.at("lens_mm")},
                              {"focus_distance", blender.at("focus_distance")},
                              {"aperture", blender.at("aperture_radius")},
                              {"orthographic_height", blender.at("ortho_scale")}};
    return CameraFromJson(camera, "uzpainter.display.camera_from_blender");
}

// ── Environment files ───────────────────────────────────────────────────────────────────────────

std::string EnvironmentProblem(const std::string& bytes) {
    const auto* data = reinterpret_cast<const unsigned char*>(bytes.data());
    EXRVersion version;
    if (ParseEXRVersionFromMemory(&version, data, bytes.size()) != TINYEXR_SUCCESS) return "not an OpenEXR file";
    if (version.multipart || version.non_image) return "a multi-part or deep OpenEXR file";
    EXRHeader header;
    InitEXRHeader(&header);
    const char* error = nullptr;
    if (ParseEXRHeaderFromMemory(&header, &version, data, bytes.size(), &error) != TINYEXR_SUCCESS) {
        std::string reason = "an unreadable OpenEXR header";
        if (error) {
            reason += std::string(": ") + error;
            FreeEXRErrorMessage(error);
        }
        return reason;
    }
    const long long width = static_cast<long long>(header.data_window.max_x) - header.data_window.min_x + 1;
    const long long height = static_cast<long long>(header.data_window.max_y) - header.data_window.min_y + 1;
    FreeEXRHeader(&header);
    if (height <= 0 || width != 2 * height) {
        return "an OpenEXR image of " + std::to_string(width) + "x" + std::to_string(height) +
               ", not an equirectangular map (width = 2 x height)";
    }
    return {};
}

}  // namespace uzp::python::display
