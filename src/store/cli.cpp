#include "store/cli.h"

#include <algorithm>
#include <charconv>
#include <exception>
#include <filesystem>
#include <fstream>
#include <map>
#include <optional>
#include <sstream>

#include "store/bundle.h"
#include "store/census.h"
#include "store/inspect.h"

namespace uzp::store {

using core::json::Object;
using core::json::Value;
namespace fs = std::filesystem;

namespace {

constexpr const char* kUsage =
    "usage: UzPainter.exe inspect <file.uzp> [--revision N] [--verify | --recipe]\n"
    "       UzPainter.exe export-bundle <file.uzp> <dir|file.zip> [--revision N]\n"
    "       UzPainter.exe store-census --inputs <inputs.json> --assets-root <dir> --work <dir> --out <report.json> "
    "[--edits N]\n";

struct UsageError {
    std::string message;
};

std::int64_t Number(const std::string& text, const char* option) {
    std::int64_t value = 0;
    const auto [end, error] = std::from_chars(text.data(), text.data() + text.size(), value);
    if (error != std::errc() || end != text.data() + text.size() || value < 0) {
        throw UsageError{std::string(option) + " needs a non-negative integer, not '" + text + "'"};
    }
    return value;
}

/// Positional arguments and `--name value` / `--flag` options.
struct Parsed {
    std::vector<std::string> positional;
    std::optional<std::int64_t> revision;
    bool verify = false;
    bool recipe = false;
    std::map<std::string, std::string> values;
};

Parsed Parse(const std::vector<std::string>& args, const std::vector<std::string>& valued, bool allow_flags) {
    Parsed parsed;
    for (std::size_t i = 1; i < args.size(); ++i) {
        const std::string& arg = args[i];
        if (arg == "--verify" && allow_flags) {
            parsed.verify = true;
        } else if (arg == "--recipe" && allow_flags) {
            parsed.recipe = true;
        } else if (arg.rfind("--", 0) == 0) {
            if (std::find(valued.begin(), valued.end(), arg) == valued.end()) throw UsageError{"unknown option " + arg};
            if (i + 1 >= args.size()) throw UsageError{arg + " needs a value"};
            if (arg == "--revision") {
                parsed.revision = Number(args[++i], "--revision");
            } else {
                parsed.values[arg] = args[++i];
            }
        } else {
            parsed.positional.push_back(arg);
        }
    }
    return parsed;
}

std::string Required(const Parsed& parsed, const char* option) {
    const auto it = parsed.values.find(option);
    if (it == parsed.values.end()) throw UsageError{std::string(option) + " is required"};
    return it->second;
}

int Inspect(const std::vector<std::string>& args, std::FILE* out, const core::RecipeHost* recipe) {
    const Parsed parsed = Parse(args, {"--revision"}, true);
    if (parsed.positional.size() != 1) throw UsageError{"inspect takes one project file"};
    if (parsed.recipe) {
        if (parsed.verify) throw UsageError{"inspect takes --verify or --recipe, not both"};
        if (recipe == nullptr) throw std::runtime_error(std::string(kRecipeHostMissing));
        const Object dump = InspectRecipe(fs::path(parsed.positional[0]), parsed.revision, *recipe);
        std::fputs(WriteIndented(Value(dump)).c_str(), out);
        return kCliOk;
    }
    const Value report =
        store::Inspect(fs::path(parsed.positional[0]), InspectOptions{parsed.revision, parsed.verify, recipe});
    std::fputs(WriteIndented(report).c_str(), out);
    if (parsed.verify) {
        const auto& verify = std::get<Object>(std::get<Object>(report.data).at("verify").data);
        if (!std::get<bool>(verify.at("ok").data)) return kCliFailed;
    }
    return kCliOk;
}

int ExportBundleCommand(const std::vector<std::string>& args, std::FILE* out) {
    const Parsed parsed = Parse(args, {"--revision"}, false);
    if (parsed.positional.size() != 2) throw UsageError{"export-bundle takes a project file and a target"};
    const BundleSummary summary = ExportBundle(fs::path(parsed.positional[0]), fs::path(parsed.positional[1]), parsed.revision);
    std::fputs(WriteIndented(Object{{"target", parsed.positional[1]},
                                    {"revision", summary.revision},
                                    {"manifest_sha256", summary.manifest_sha256},
                                    {"resources", summary.resources},
                                    {"mesh_maps", summary.mesh_maps},
                                    {"planes", summary.planes}})
                   .c_str(),
               out);
    return kCliOk;
}

int Census(const std::vector<std::string>& args, std::FILE* out) {
    const Parsed parsed = Parse(args, {"--inputs", "--assets-root", "--work", "--out", "--edits"}, false);
    if (!parsed.positional.empty()) throw UsageError{"store-census takes options only"};
    const fs::path inputs_path(Required(parsed, "--inputs"));
    std::ifstream file(inputs_path, std::ios::binary);
    if (!file) throw StoreError(StoreError::Code::io, "cannot read " + inputs_path.string());
    std::ostringstream text;
    text << file.rdbuf();
    CensusOptions options;
    options.work_dir = fs::path(Required(parsed, "--work"));
    if (const auto it = parsed.values.find("--edits"); it != parsed.values.end()) {
        options.one_parameter_edits = static_cast<int>(Number(it->second, "--edits"));
    }
    const std::vector<CensusProjectInput> inputs =
        ReadCensusInputs(core::json::Parse(text.str()), fs::path(Required(parsed, "--assets-root")));
    const Value report = RunCensus(inputs, options);
    const fs::path out_path(Required(parsed, "--out"));
    std::ofstream report_file(out_path, std::ios::binary | std::ios::trunc);
    const std::string body = WriteIndented(report);
    report_file.write(body.data(), static_cast<std::streamsize>(body.size()));
    report_file.close();
    if (!report_file) throw StoreError(StoreError::Code::io, "cannot write " + out_path.string());
    std::fprintf(out, "store-census: %zu projects, report %s\n", inputs.size(), out_path.string().c_str());
    return kCliOk;
}

}  // namespace

bool IsStoreCommand(std::string_view verb) {
    return verb == "inspect" || verb == "export-bundle" || verb == "store-census";
}

int RunStoreCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err, const core::RecipeHost* recipe) {
    try {
        if (args.empty()) throw UsageError{"no command"};
        if (args[0] == "inspect") return Inspect(args, out, recipe);
        if (args[0] == "export-bundle") return ExportBundleCommand(args, out);
        if (args[0] == "store-census") return Census(args, out);
        throw UsageError{"unknown command " + args[0]};
    } catch (const UsageError& error) {
        std::fprintf(err, "%s\n%s", error.message.c_str(), kUsage);
        return kCliUsage;
    } catch (const std::exception& error) {
        std::fprintf(err, "%s: %s\n", args[0].c_str(), error.what());
        return kCliFailed;
    }
}

}  // namespace uzp::store
