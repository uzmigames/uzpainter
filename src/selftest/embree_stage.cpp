// Stage `embree`: one ray against one triangle through Embree's C API, checking the hit distance
// and the barycentrics, and one ray that misses.
//
// `embree4.dll` is loaded at run time from the executable's folder (LoadLibraryExW with the
// altered search path, so `tbb12.dll` beside it resolves too) and its C API is resolved by name.
// A missing DLL or a missing dependency of it (for example the Visual C++ runtime the prebuilt
// release imports) is therefore this stage's explicit failure, not a process that cannot start.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "hardware_slice.h"

#include <embree4/rtcore.h>

#include <windows.h>

#include <cmath>
#include <filesystem>
#include <limits>
#include <string>

namespace uzp::selftest {

namespace {

std::string LastErrorText(DWORD code) {
    wchar_t* text = nullptr;
    FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
                       FORMAT_MESSAGE_IGNORE_INSERTS,
                   nullptr, code, MAKELANGID(LANG_ENGLISH, SUBLANG_ENGLISH_US),
                   reinterpret_cast<wchar_t*>(&text), 0, nullptr);
    std::string out = "error " + std::to_string(code);
    if (text) {
        std::wstring wide(text);
        LocalFree(text);
        while (!wide.empty() && (wide.back() == L'\n' || wide.back() == L'\r')) wide.pop_back();
        out += " (";
        for (wchar_t c : wide) out += c < 0x80 ? static_cast<char>(c) : '?';
        out += ")";
    }
    return out;
}

/// The part of Embree's C API the stage uses, resolved from the loaded DLL.
struct EmbreeApi {
    decltype(&::rtcNewDevice) newDevice = nullptr;
    decltype(&::rtcReleaseDevice) releaseDevice = nullptr;
    decltype(&::rtcGetDeviceError) getDeviceError = nullptr;
    decltype(&::rtcGetDeviceProperty) getDeviceProperty = nullptr;
    decltype(&::rtcNewScene) newScene = nullptr;
    decltype(&::rtcReleaseScene) releaseScene = nullptr;
    decltype(&::rtcCommitScene) commitScene = nullptr;
    decltype(&::rtcNewGeometry) newGeometry = nullptr;
    decltype(&::rtcReleaseGeometry) releaseGeometry = nullptr;
    decltype(&::rtcSetNewGeometryBuffer) setNewGeometryBuffer = nullptr;
    decltype(&::rtcCommitGeometry) commitGeometry = nullptr;
    decltype(&::rtcAttachGeometry) attachGeometry = nullptr;
    decltype(&::rtcIntersect1) intersect1 = nullptr;
};

template <typename Fn>
bool Resolve(HMODULE module, const char* name, Fn& fn, std::string& missing) {
    fn = reinterpret_cast<Fn>(reinterpret_cast<void*>(GetProcAddress(module, name)));
    if (!fn) missing += (missing.empty() ? "" : ", ") + std::string(name);
    return fn != nullptr;
}

RTCRayHit MakeRay(float x, float y, float z) {
    RTCRayHit rh{};
    rh.ray.org_x = x;
    rh.ray.org_y = y;
    rh.ray.org_z = z;
    rh.ray.dir_x = 0.0f;
    rh.ray.dir_y = 0.0f;
    rh.ray.dir_z = 1.0f;
    rh.ray.tnear = 0.0f;
    rh.ray.tfar = std::numeric_limits<float>::infinity();
    rh.ray.mask = 0xFFFFFFFFu;
    rh.hit.geomID = RTC_INVALID_GEOMETRY_ID;
    rh.hit.primID = RTC_INVALID_GEOMETRY_ID;
    rh.hit.instID[0] = RTC_INVALID_GEOMETRY_ID;
    return rh;
}

bool Near(float a, float b) { return std::fabs(a - b) <= 1e-6f; }

std::string F(float v) { return std::to_string(v); }

}  // namespace

StageOutcome RunEmbree(SelftestContext& context) {
    const std::filesystem::path dll = context.exeDir / "embree4.dll";
    Details details = {{"embree4", dll.string()}};
    HMODULE module = LoadLibraryExW(dll.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!module) {
        return StageOutcome::Fail("embree4.dll failed to load from " + dll.string() + ": " +
                                      LastErrorText(GetLastError()) +
                                      " (it needs tbb12.dll beside it and the Visual C++ runtime "
                                      "MSVCP140.dll, VCRUNTIME140.dll)",
                                  details);
    }
    EmbreeApi api;
    std::string missing;
    Resolve(module, "rtcNewDevice", api.newDevice, missing);
    Resolve(module, "rtcReleaseDevice", api.releaseDevice, missing);
    Resolve(module, "rtcGetDeviceError", api.getDeviceError, missing);
    Resolve(module, "rtcGetDeviceProperty", api.getDeviceProperty, missing);
    Resolve(module, "rtcNewScene", api.newScene, missing);
    Resolve(module, "rtcReleaseScene", api.releaseScene, missing);
    Resolve(module, "rtcCommitScene", api.commitScene, missing);
    Resolve(module, "rtcNewGeometry", api.newGeometry, missing);
    Resolve(module, "rtcReleaseGeometry", api.releaseGeometry, missing);
    Resolve(module, "rtcSetNewGeometryBuffer", api.setNewGeometryBuffer, missing);
    Resolve(module, "rtcCommitGeometry", api.commitGeometry, missing);
    Resolve(module, "rtcAttachGeometry", api.attachGeometry, missing);
    Resolve(module, "rtcIntersect1", api.intersect1, missing);
    if (!missing.empty()) {
        return StageOutcome::Fail("embree4.dll does not export " + missing, details);
    }

    RTCDevice device = api.newDevice(nullptr);
    if (!device) return StageOutcome::Fail("rtcNewDevice returned null", details);
    const ssize_t version = api.getDeviceProperty(device, RTC_DEVICE_PROPERTY_VERSION);
    const ssize_t tasking = api.getDeviceProperty(device, RTC_DEVICE_PROPERTY_TASKING_SYSTEM);
    details.emplace_back("embree_version", std::to_string(version / 10000) + "." +
                                               std::to_string(version / 100 % 100) + "." +
                                               std::to_string(version % 100));
    details.emplace_back("tasking_system", tasking == 0   ? "internal"
                                           : tasking == 1 ? "TBB"
                                           : tasking == 2 ? "PPL"
                                                          : std::to_string(tasking));

    // Triangle (0,0,0) (1,0,0) (0,1,0) in the plane z = 0.
    RTCScene scene = api.newScene(device);
    RTCGeometry triangle = api.newGeometry(device, RTC_GEOMETRY_TYPE_TRIANGLE);
    auto* vertices = static_cast<float*>(api.setNewGeometryBuffer(
        triangle, RTC_BUFFER_TYPE_VERTEX, 0, RTC_FORMAT_FLOAT3, 3 * sizeof(float), 3));
    auto* indices = static_cast<unsigned*>(api.setNewGeometryBuffer(
        triangle, RTC_BUFFER_TYPE_INDEX, 0, RTC_FORMAT_UINT3, 3 * sizeof(unsigned), 1));
    if (vertices && indices) {
        const float v[9] = {0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f};
        for (int i = 0; i < 9; ++i) vertices[i] = v[i];
        indices[0] = 0;
        indices[1] = 1;
        indices[2] = 2;
    }
    api.commitGeometry(triangle);
    const unsigned geomId = api.attachGeometry(scene, triangle);
    api.releaseGeometry(triangle);
    api.commitScene(scene);

    // Hit: from (0.2, 0.3, -2) along +z, t = 2, barycentrics u = 0.2, v = 0.3.
    RTCRayHit hit = MakeRay(0.2f, 0.3f, -2.0f);
    api.intersect1(scene, &hit, nullptr);
    // Miss: (0.8, 0.8) lies outside the triangle (u + v > 1).
    RTCRayHit miss = MakeRay(0.8f, 0.8f, -2.0f);
    api.intersect1(scene, &miss, nullptr);
    const RTCError error = api.getDeviceError(device);
    api.releaseScene(scene);
    api.releaseDevice(device);

    details.emplace_back("hit_t", F(hit.ray.tfar));
    details.emplace_back("hit_u", F(hit.hit.u));
    details.emplace_back("hit_v", F(hit.hit.v));
    details.emplace_back("hit_geom_id", std::to_string(hit.hit.geomID));
    details.emplace_back("miss_geom_id", std::to_string(miss.hit.geomID));
    if (!vertices || !indices || error != RTC_ERROR_NONE) {
        return StageOutcome::Fail("Embree reported error " + std::to_string(error), details);
    }
    if (hit.hit.geomID != geomId || hit.hit.primID != 0 || !Near(hit.ray.tfar, 2.0f) ||
        !Near(hit.hit.u, 0.2f) || !Near(hit.hit.v, 0.3f)) {
        return StageOutcome::Fail("the ray did not hit the triangle at t = 2 with u = 0.2, "
                                  "v = 0.3",
                                  details);
    }
    if (miss.hit.geomID != RTC_INVALID_GEOMETRY_ID || !std::isinf(miss.ray.tfar)) {
        return StageOutcome::Fail("the ray outside the triangle reported a hit", details);
    }
    return StageOutcome::Pass(std::move(details));
}

}  // namespace uzp::selftest
