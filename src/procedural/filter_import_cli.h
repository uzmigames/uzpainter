#pragma once

#include <cstdio>
#include <filesystem>
#include <functional>
#include <string>
#include <vector>

#include "procedural/filter_gate_admission.h"

namespace uzp::procedural {

/// Native admitted-evidence import into the original H project; no diagnostic-fixture route.
int RunFilterImportCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err);

/// Production callers can only enter through the compiled-pin command. The existing test friend
/// exercises this same driver using C1 admission under authored pins, without private machine data.
class FilterImportCommandDriver {
private:
    using Admission = std::function<std::expected<AdmittedFilterCapture, ImportRefusal>(
        std::string_view, const core::json::Object&, const OracleStoreReader&)>;
    static int Run(const std::vector<std::string>& args, std::FILE* out, std::FILE* err,
                   const std::filesystem::path& registry, const Admission& admit_filter);
    friend int RunFilterImportCommand(const std::vector<std::string>&, std::FILE*, std::FILE*);
    friend struct FilterGateTestAccess;
};

}  // namespace uzp::procedural
