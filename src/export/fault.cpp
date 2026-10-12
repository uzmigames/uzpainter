// Test-only fault hooks (see fault.h). Compiles to nothing unless `UZP_EXPORT_FAULT_HOOKS` is
// defined.

#include "export/fault.h"

#if defined(UZP_EXPORT_FAULT_HOOKS)

#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include <array>
#include <stdexcept>
#include <string>
#include <utility>

namespace uzp::exporter::fault {
namespace {

Point g_point = Point::none;
std::size_t g_index = 0;

constexpr std::array<std::pair<std::string_view, Point>, 9> kNames{{
    {"fail_encode", Point::fail_encode},
    {"fail_write", Point::fail_write},
    {"kill_after_file", Point::kill_after_file},
    {"kill_after_plan", Point::kill_after_plan},
    {"kill_after_receipt", Point::kill_after_receipt},
    {"kill_before_pointer_rename", Point::kill_before_pointer_rename},
    {"kill_after_pointer_rename", Point::kill_after_pointer_rename},
    {"kill_before_fixed_rename", Point::kill_before_fixed_rename},
    {"kill_after_fixed_rename", Point::kill_after_fixed_rename},
}};

}  // namespace

void Arm(Point point, std::size_t index) {
    g_point = point;
    g_index = index;
}

void Arm(std::string_view spec) {
    const size_t colon = spec.find(':');
    const std::string_view name = spec.substr(0, colon);
    const std::size_t index = colon == std::string_view::npos ? 0 : std::stoul(std::string(spec.substr(colon + 1)));
    for (const auto& [known, point] : kNames) {
        if (known == name) return Arm(point, index);
    }
    throw std::invalid_argument("unknown export fault point: " + std::string(name));
}

bool Fails(Point point, std::size_t index) { return g_point == point && g_index == index; }

void Reach(Point point, std::size_t index) {
    if (!Fails(point, index)) return;
    TerminateProcess(GetCurrentProcess(), kKillExitCode);
    ExitProcess(kKillExitCode);
}

}  // namespace uzp::exporter::fault

#endif
