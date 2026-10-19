#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "bake/embree_api.h"

#include <windows.h>

#include <filesystem>
#include <mutex>

namespace uzp::bake {

namespace {

template <typename Fn>
void Resolve(HMODULE module, const char* name, Fn& fn, std::string& missing) {
    fn = reinterpret_cast<Fn>(reinterpret_cast<void*>(GetProcAddress(module, name)));
    if (!fn) missing += (missing.empty() ? "" : ", ") + std::string(name);
}

std::filesystem::path ExecutableDir() {
    std::wstring buffer(MAX_PATH, L'\0');
    for (;;) {
        const DWORD length =
            GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
        if (length == 0) return {};
        if (length < buffer.size()) {
            buffer.resize(length);
            return std::filesystem::path(buffer).parent_path();
        }
        buffer.resize(buffer.size() * 2);
    }
}

struct Loaded {
    EmbreeApi api;
    std::string error;
    bool ok = false;
};

Loaded LoadOnce() {
    Loaded loaded;
    const std::filesystem::path dll = ExecutableDir() / "embree4.dll";
    // The altered search path lets tbb12.dll and the Visual C++ runtime beside it resolve.
    HMODULE module = LoadLibraryExW(dll.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!module) {
        loaded.error = "embree4.dll failed to load from " + dll.string() + " (Windows error " +
                       std::to_string(GetLastError()) +
                       "; it needs tbb12.dll, msvcp140.dll and vcruntime140*.dll beside it)";
        return loaded;
    }
    EmbreeApi& api = loaded.api;
    std::string missing;
    Resolve(module, "rtcNewDevice", api.newDevice, missing);
    Resolve(module, "rtcReleaseDevice", api.releaseDevice, missing);
    Resolve(module, "rtcGetDeviceError", api.getDeviceError, missing);
    Resolve(module, "rtcGetDeviceLastErrorMessage", api.getDeviceLastErrorMessage, missing);
    Resolve(module, "rtcGetDeviceProperty", api.getDeviceProperty, missing);
    Resolve(module, "rtcNewScene", api.newScene, missing);
    Resolve(module, "rtcReleaseScene", api.releaseScene, missing);
    Resolve(module, "rtcSetSceneFlags", api.setSceneFlags, missing);
    Resolve(module, "rtcSetSceneBuildQuality", api.setSceneBuildQuality, missing);
    Resolve(module, "rtcCommitScene", api.commitScene, missing);
    Resolve(module, "rtcNewGeometry", api.newGeometry, missing);
    Resolve(module, "rtcReleaseGeometry", api.releaseGeometry, missing);
    Resolve(module, "rtcSetNewGeometryBuffer", api.setNewGeometryBuffer, missing);
    Resolve(module, "rtcCommitGeometry", api.commitGeometry, missing);
    Resolve(module, "rtcAttachGeometryByID", api.attachGeometryByID, missing);
    Resolve(module, "rtcIntersect1", api.intersect1, missing);
    if (!missing.empty()) {
        loaded.error = "embree4.dll does not export " + missing;
        return loaded;
    }
    loaded.ok = true;
    return loaded;
}

}  // namespace

const EmbreeApi* LoadEmbree(std::string& error) {
    static std::once_flag once;
    static Loaded loaded;
    std::call_once(once, [] { loaded = LoadOnce(); });
    if (!loaded.ok) {
        error = loaded.error;
        return nullptr;
    }
    return &loaded.api;
}

}  // namespace uzp::bake
