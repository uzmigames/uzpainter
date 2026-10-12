#include "export/cli.h"

#include "export/fixed_names.h"
#include "export/publish.h"
#include "uzp_core/manifest/json.h"

#include <filesystem>

namespace uzp::exporter {

namespace {

namespace fs = std::filesystem;
namespace json = core::json;

constexpr const char* kUsage = "usage: UzPainter.exe export --recover <exportPath> [--fixed-names <dir>]...\n";

json::Value Optional(const std::optional<std::string>& value) {
    return value ? json::Value(*value) : json::Value(nullptr);
}

}  // namespace

bool IsExportCommand(std::string_view verb) { return verb == "export"; }

int RunExportCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err) {
    std::optional<fs::path> exportPath;
    std::vector<fs::path> fixedNames;
    bool recover = false;
    for (size_t i = 1; i < args.size(); ++i) {
        if (args[i] == "--recover" && i + 1 < args.size() && !exportPath) {
            recover = true;
            exportPath = fs::path(args[++i]);
        } else if (args[i] == "--fixed-names" && i + 1 < args.size()) {
            fixedNames.emplace_back(args[++i]);
        } else {
            std::fprintf(err, "%s", kUsage);
            return kCliUsage;
        }
    }
    if (!recover) {
        std::fprintf(err, "%s", kUsage);
        return kCliUsage;
    }
    render::Result<RecoveryReport> report = RecoverExport(*exportPath);
    if (!report) {
        std::fprintf(err, "UzPainter.exe export --recover: %s\n", report.error().reason.c_str());
        return kCliFailed;
    }
    json::Array removed;
    for (const auto& [generation, problem] : report->removed) {
        removed.push_back(json::Object{{"generation", generation}, {"problem", problem}});
    }
    json::Array fixed;
    for (const fs::path& directory : fixedNames) {
        render::Result<std::optional<std::string>> rolled = RecoverFixedNames(*exportPath, directory);
        if (!rolled) {
            std::fprintf(err, "UzPainter.exe export --recover: %s\n", rolled.error().reason.c_str());
            return kCliFailed;
        }
        fixed.push_back(json::Object{{"directory", Utf8String(directory)}, {"rolled_forward", Optional(*rolled)}});
    }
    json::Value damaged = nullptr;
    if (report->damaged) {
        damaged = json::Object{{"generation", report->damaged->first}, {"problem", report->damaged->second}};
    }
    const std::string text = json::WriteCanonical(json::Object{
        {"current_before", Optional(report->currentBefore)},
        {"current_after", Optional(report->currentAfter)},
        {"published", Optional(report->published)},
        {"removed", std::move(removed)},
        {"damaged", damaged},
        {"removed_staging_pointer", report->removedStagingPointer},
        {"fixed_names", std::move(fixed)},
    });
    std::fprintf(out, "%s\n", text.c_str());
    return report->damaged ? kCliFailed : kCliOk;
}

}  // namespace uzp::exporter
