#include "export/cli.h"

#include "export/fixed_names.h"
#include "export/project_export.h"
#include "export/publish.h"
#include "store/container.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/types/errors.h"

#include <filesystem>
#include <fstream>
#include <iterator>

namespace uzp::exporter {

namespace {

namespace fs = std::filesystem;
namespace json = core::json;

constexpr const char* kUsage =
    "usage: UzPainter.exe export <file.uzp> --config <config.json> --app-version <version> --build <id>\n"
    "       UzPainter.exe export --recover <exportPath> [--fixed-names <dir>]...\n";

json::Value Optional(const std::optional<std::string>& value) {
    return value ? json::Value(*value) : json::Value(nullptr);
}

/// `export <file.uzp> --config ... --app-version ... --build ...` (args without the verb).
int RunProjectExport(const std::vector<std::string>& args, std::FILE* out, std::FILE* err) {
    ProjectExportRequest request;
    std::optional<fs::path> configPath;
    request.project = fs::path(args.front());
    for (size_t i = 1; i < args.size(); ++i) {
        if (i + 1 >= args.size()) {
            std::fprintf(err, "%s", kUsage);
            return kCliUsage;
        }
        if (args[i] == "--config" && !configPath) {
            configPath = fs::path(args[++i]);
        } else if (args[i] == "--app-version" && request.identity.appVersion.empty()) {
            request.identity.appVersion = args[++i];
        } else if (args[i] == "--build" && request.identity.build.empty()) {
            request.identity.build = args[++i];
        } else {
            std::fprintf(err, "%s", kUsage);
            return kCliUsage;
        }
    }
    if (!configPath || request.identity.appVersion.empty() || request.identity.build.empty()) {
        std::fprintf(err, "%s", kUsage);
        return kCliUsage;
    }
    std::ifstream stream(*configPath, std::ios::binary);
    if (!stream) {
        std::fprintf(err, "UzPainter.exe export: cannot read %s\n", Utf8String(*configPath).c_str());
        return kCliFailed;
    }
    request.config.assign(std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>());
    try {
        render::Result<Publication> published = ExportProject(request);
        if (!published) {
            std::fprintf(err, "UzPainter.exe export: %s\n", published.error().reason.c_str());
            return kCliFailed;
        }
        json::Array files;
        for (const WrittenFile& f : published->files) {
            files.push_back(json::Object{{"root_path", f.rootPath},
                                         {"path", f.relativePath},
                                         {"size", static_cast<std::int64_t>(f.size)},
                                         {"sha256", f.sha256}});
        }
        const std::string text = json::WriteCanonical(json::Object{
            {"generation", published->generation},
            {"receipt", Utf8String(published->receipt)},
            {"receipt_sha256", published->receiptSha256},
            {"files", std::move(files)},
        });
        std::fprintf(out, "%s\n", text.c_str());
        return kCliOk;
    } catch (const core::ValueError& e) {
        std::fprintf(err, "UzPainter.exe export: ValueError: %s\n", e.what());
    } catch (const core::NotYetSupported& e) {
        std::fprintf(err, "UzPainter.exe export: NotYetSupported: %s\n", e.what());
    } catch (const store::StoreError& e) {
        std::fprintf(err, "UzPainter.exe export: %s\n", e.what());
    }
    return kCliFailed;
}

}  // namespace

bool IsExportCommand(std::string_view verb) { return verb == "export"; }

int RunExportCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err) {
    if (args.size() >= 2 && !args[1].starts_with("--")) return RunProjectExport({args.begin() + 1, args.end()}, out, err);
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
