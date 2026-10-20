#include "procedural/cli.h"

#include "procedural/asset_library.h"

#include "uzp_core/manifest/json.h"

#include <filesystem>
#include <optional>

namespace uzp::procedural {

namespace {

namespace json = core::json;

constexpr int kOk = 0;
constexpr int kUsage = 2;
constexpr int kHostError = 3;
constexpr std::string_view kPrefix = "UZP_JSON:";
constexpr const char* kUsageText = "usage: UzPainter.exe assets list [--parity] [--library <dir>]\n";

void Print(std::FILE* out, const json::Value& document) {
    std::fprintf(out, "%.*s%s\n", static_cast<int>(kPrefix.size()), kPrefix.data(),
                 json::WriteCanonical(document).c_str());
}

std::string Utf8(const std::filesystem::path& path) {
    const std::u8string text = path.generic_u8string();
    return std::string(reinterpret_cast<const char*>(text.data()), text.size());
}

json::Value Parity(const AssetRecord& record) {
    json::Object parity{{"status", std::string(KindName(record.status.kind))}};
    if (record.status.kind == ParityStatus::Kind::Calibrated) {
        json::Array residuals;
        for (const Residual& r : record.status.residuals) {
            residuals.push_back(json::Object{{"unit", r.unit},
                                             {"max", static_cast<std::int64_t>(r.max)},
                                             {"sum", static_cast<std::int64_t>(r.sum)},
                                             {"count", static_cast<std::int64_t>(r.count)},
                                             {"mean", r.Mean()},
                                             {"p99", static_cast<std::int64_t>(r.p99)}});
        }
        parity["residuals"] = std::move(residuals);
    }
    if (record.status.kind == ParityStatus::Kind::Unavailable) parity["reason"] = record.status.reason;
    if (!record.status.corpusIds.empty()) {
        parity["corpus_ids"] = json::Array(record.status.corpusIds.begin(), record.status.corpusIds.end());
    }
    if (!record.report.empty()) parity["report"] = record.report;
    return parity;
}

}  // namespace

bool IsAssetsCommand(std::string_view verb) { return verb == "assets"; }

int RunAssetsCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err) {
    bool parity = false;
    std::optional<std::filesystem::path> root;
    if (args.size() < 2 || args[1] != "list") {
        std::fputs(kUsageText, err);
        return kUsage;
    }
    for (size_t i = 2; i < args.size(); ++i) {
        if (args[i] == "--parity" && !parity) {
            parity = true;
        } else if (args[i] == "--library" && !root && i + 1 < args.size()) {
            root = std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(args[i + 1].data()),
                                                       args[i + 1].size()));
            ++i;
        } else {
            std::fputs(kUsageText, err);
            return kUsage;
        }
    }
    const std::filesystem::path library = root.value_or(DefaultLibraryRoot());
    const std::expected<AssetLibrary, std::string> loaded = AssetLibrary::Load(library);
    if (!loaded) {
        Print(out, json::Object{{"status", "host_error"},
                                {"error", json::Object{{"type", "AssetLibraryError"}, {"message", loaded.error()}}}});
        return kHostError;
    }
    json::Array assets;
    for (const AssetRecord& record : loaded->records()) {
        json::Object entry{{"asset", core::FormatAssetUrl(record.asset)}, {"name", record.name}, {"usage", record.usage}};
        if (parity) {
            entry["parity"] = Parity(record);
            const json::Object& document = std::get<json::Object>(record.json.data);
            entry["domain"] = document.at("domain");
            // A material's outputs and physical size belong to its declaration (05 §6).
            for (const std::string_view key : {"outputs", "physical_size_cm"}) {
                if (const auto it = document.find(key); it != document.end()) entry[std::string(key)] = it->second;
            }
        }
        assets.push_back(std::move(entry));
    }
    Print(out, json::Object{{"status", "ok"}, {"library", Utf8(library)}, {"assets", std::move(assets)}});
    return kOk;
}

}  // namespace uzp::procedural
