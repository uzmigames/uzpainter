#pragma once

// Embree 4.4.1's C API (`thirdparty/embree/`, prebuilt x64 Windows release with TBB tasking),
// resolved by name from `embree4.dll` beside the executable, as the `selftest` embree stage
// loads it (`src/selftest/embree_stage.cpp`): no import library is vendored.

#include <embree4/rtcore.h>

#include <string>

namespace uzp::bake {

struct EmbreeApi {
    decltype(&::rtcNewDevice) newDevice = nullptr;
    decltype(&::rtcReleaseDevice) releaseDevice = nullptr;
    decltype(&::rtcGetDeviceError) getDeviceError = nullptr;
    decltype(&::rtcGetDeviceLastErrorMessage) getDeviceLastErrorMessage = nullptr;
    decltype(&::rtcGetDeviceProperty) getDeviceProperty = nullptr;
    decltype(&::rtcNewScene) newScene = nullptr;
    decltype(&::rtcReleaseScene) releaseScene = nullptr;
    decltype(&::rtcSetSceneFlags) setSceneFlags = nullptr;
    decltype(&::rtcSetSceneBuildQuality) setSceneBuildQuality = nullptr;
    decltype(&::rtcCommitScene) commitScene = nullptr;
    decltype(&::rtcNewGeometry) newGeometry = nullptr;
    decltype(&::rtcReleaseGeometry) releaseGeometry = nullptr;
    decltype(&::rtcSetNewGeometryBuffer) setNewGeometryBuffer = nullptr;
    decltype(&::rtcCommitGeometry) commitGeometry = nullptr;
    decltype(&::rtcAttachGeometryByID) attachGeometryByID = nullptr;
    decltype(&::rtcIntersect1) intersect1 = nullptr;
};

/// The process-wide API of `embree4.dll` in the executable's folder, loaded on first use and
/// never unloaded. Null with `error` set when the DLL or one of its exports is missing.
const EmbreeApi* LoadEmbree(std::string& error);

}  // namespace uzp::bake
