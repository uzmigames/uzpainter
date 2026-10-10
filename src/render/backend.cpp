#include "render/backend.h"

#include <utility>

namespace uzp::render {

std::string_view BackendName(Backend backend) {
    switch (backend) {
        case Backend::Dx12:   return "dx12";
        case Backend::Vulkan: return "vulkan";
    }
    return "unknown";
}

std::optional<Backend> ParseBackend(std::string_view name) {
    if (name == "dx12") return Backend::Dx12;
    if (name == "vulkan") return Backend::Vulkan;
    return std::nullopt;
}

std::string_view WaitStatusName(WaitStatus status) {
    switch (status) {
        case WaitStatus::Signaled:   return "signaled";
        case WaitStatus::Timeout:    return "timeout";
        case WaitStatus::DeviceLost: return "device_lost";
    }
    return "unknown";
}

std::string_view ErrorCodeName(ErrorCode code) {
    switch (code) {
        case ErrorCode::GpuBackendUnavailable:  return "gpu_backend_unavailable";
        case ErrorCode::DeviceRemoved:          return "device_removed";
        case ErrorCode::Timeout:                return "timeout";
        case ErrorCode::KernelCompileFailed:    return "kernel_compile_failed";
        case ErrorCode::ResourceCreationFailed: return "resource_creation_failed";
        case ErrorCode::EngineStopped:          return "engine_stopped";
        case ErrorCode::RequestFailed:          return "request_failed";
    }
    return "unknown";
}

std::string Error::Describe() const {
    std::string text(ErrorCodeName(code));
    text += " {";
    if (backend) {
        text += "backend: ";
        text += BackendName(*backend);
        text += ", ";
    }
    text += "reason: " + reason + "}";
    return text;
}

Unexpected Fail(ErrorCode code, std::optional<Backend> backend, std::string reason) {
    return Unexpected(Error{code, backend, std::move(reason)});
}

std::string_view KernelTargetName(KernelTarget target) {
    switch (target) {
        case KernelTarget::Dxil:  return "dxil";
        case KernelTarget::Spirv: return "spirv";
    }
    return "unknown";
}

}  // namespace uzp::render
