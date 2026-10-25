// The capability manifest at run time (capabilities.h).

#include "python/capabilities.h"

#include <fstream>
#include <iterator>
#include <optional>

#include <pybind11/eval.h>

#include "python/run.h"
#include "render/kernel_cache.h"
#include "uzp_core/manifest/json.h"

namespace py = pybind11;

namespace uzp::python {

namespace {

namespace json = core::json;

constexpr const char* kUsage = "usage: UzPainter.exe capabilities [--runtime]\n";
/// `capabilities --runtime`: what this build's native host enforces, compiled in (decision 360).
/// A host without it refuses the extra argument (usage, exit 2), so a client probes before a script.
constexpr const char* kRuntimeSchema = "uzpainter/runtime-capabilities/1";

/// The module body: the manifest is read once, on first use, and handed out as copies.
constexpr const char* kModule = R"PY(
import copy as _copy
import json as _json

_cache = None


def profile():
    """The compatibility profile UzPainter reproduces: Painter 12.1, Python API 0.3.7."""
    return _PROFILE


def manifest():
    """The shipped capability manifest (capabilities.json): {schema, compat_profile, documentation,
    entries: [{symbol, context, status, since, tier_evidence, notes, evidence}]}."""
    global _cache
    if _cache is None:
        try:
            with open(_PATH, encoding="utf-8") as stream:
                _cache = _json.load(stream)
        except OSError as error:
            raise RuntimeError(f"the capability manifest is not installed: {_PATH} ({error})") from None
    return _copy.deepcopy(_cache)


def entry(symbol, context="any"):
    """The manifest entry of `symbol` in the operation context `context`, or None."""
    for item in manifest()["entries"]:
        if item["symbol"] == symbol and item["context"] == context:
            return item
    return None
)PY";

void PrintHostError(std::FILE* out, const std::string& message) {
    std::fprintf(out, "%.*s%s\n", static_cast<int>(kJsonPrefix.size()), kJsonPrefix.data(),
                 json::WriteCanonical(json::Object{
                                          {"status", "host_error"},
                                          {"error", json::Object{{"type", "CapabilitiesError"}, {"message", message}}},
                                      })
                     .c_str());
}

}  // namespace

std::filesystem::path CapabilitiesPath() {
    // The executable's folder, where `zig build painter` installs it (as assets/ and the DLLs).
    return render::DefaultDxcompilerPath().parent_path() / "capabilities.json";
}

bool IsCapabilitiesCommand(std::string_view verb) { return verb == "capabilities"; }

int RunCapabilitiesCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err) {
    if (args.size() == 2 && args[1] == "--runtime") {
        std::fprintf(out, "%.*s%s\n", static_cast<int>(kJsonPrefix.size()), kJsonPrefix.data(),
                     json::WriteCanonical(json::Object{{"schema", kRuntimeSchema},
                                                       {"assets3d_production_guard", std::int64_t{1}}})
                         .c_str());
        return kRunOk;
    }
    if (args.size() != 1) {
        std::fprintf(err, "%s", kUsage);
        return kRunUsage;
    }
    const std::filesystem::path path = CapabilitiesPath();
    std::ifstream stream(path, std::ios::binary);
    if (!stream) {
        PrintHostError(out, "the capability manifest is not installed: " + path.generic_string());
        return kRunHostError;
    }
    const std::string text{std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
    std::optional<json::Value> manifest;
    try {
        manifest = json::Parse(text);
    } catch (const json::ParseError& error) {
        PrintHostError(out, path.generic_string() + " is not JSON: " + error.what());
        return kRunHostError;
    }
    std::fprintf(out, "%.*s%s\n", static_cast<int>(kJsonPrefix.size()), kJsonPrefix.data(),
                 json::WriteCanonical(*manifest).c_str());
    return kRunOk;
}

void BindCapabilities(py::module_& m) {
    py::module_ capabilities = m.def_submodule("capabilities", "The capability manifest and the compatibility profile.");
    py::module_::import("sys").attr("modules")["uzpainter.capabilities"] = capabilities;
    const std::u8string path = CapabilitiesPath().u8string();
    capabilities.attr("_PATH") = py::str(reinterpret_cast<const char*>(path.c_str()), path.size());
    capabilities.attr("_PROFILE") = kCompatProfile;
    py::exec(kModule, capabilities.attr("__dict__"));
}

}  // namespace uzp::python
