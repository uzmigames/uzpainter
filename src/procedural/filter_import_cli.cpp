#include "procedural/filter_import_cli.h"

#include <filesystem>
#include <fstream>
#include <map>
#include <optional>
#include <stdexcept>

#include "evaluator/templates.h"
#include "procedural/filter_gate_destination.h"
#include "procedural/filter_gate_host.h"
#include "procedural/filter_gate_request.h"
#include "procedural/filter_observation_source.h"
#include "store/commit.h"
#include "store/filter_observations.h"
#include "uzp_core/manifest/sha256.h"

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

namespace uzp::procedural {
namespace {
namespace fs = std::filesystem;
namespace json = core::json;

struct CommandRefused { ImportRefusal refusal; };
struct StoredReplay { std::string entry_key; std::int64_t revision; };

[[noreturn]] void RefuseCommand(std::string_view reason, std::string_view detail) {
    throw CommandRefused{{std::string(reason), std::string(detail)}};
}

template <typename T>
T Take(std::expected<T, ImportRefusal> result) {
    if (!result) throw CommandRefused{result.error()};
    return std::move(*result);
}

fs::path Path(std::string_view text) { return fs::path(std::u8string(text.begin(), text.end())); }

fs::path RegistryPath() {
    std::wstring buffer(32768, L'\0');
    const DWORD size = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
    if (!size || size >= buffer.size()) RefuseCommand("FILTER_IMPORT_IO", "EXECUTABLE_LOCATION");
    buffer.resize(size);
    return fs::path(buffer).parent_path() / "assets" / "filter-gate" / "registry.json";
}

std::string ReadPublic(const fs::path& path) {
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input) RefuseCommand("FILTER_IMPORT_IO", "PUBLIC_INPUT_UNREADABLE");
    const auto size = input.tellg();
    if (size < 0 || size > 16 * 1024 * 1024) RefuseCommand("FILTER_IMPORT_IO", "PUBLIC_INPUT_SIZE");
    std::string bytes(static_cast<std::size_t>(size), '\0');
    input.seekg(0);
    input.read(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    if (!input || input.peek() != std::char_traits<char>::eof()) RefuseCommand("FILTER_IMPORT_IO", "PUBLIC_INPUT_CHANGED");
    return bytes;
}

void Print(std::FILE* out, const json::Object& report) {
    std::fprintf(out, "UZP_JSON:%s\n", json::WriteCanonical(report).c_str());
}

void RequireRestingFile(const fs::path& project) {
    if (!fs::is_regular_file(project)) RefuseCommand("FILTER_IMPORT_IO", "ORIGINAL_PROJECT_FILE_REQUIRED");
    // Opening a recovering or compacting file could change it even when import later refuses.
    for (const auto suffix : {"-wal", "-shm", "-journal", ".compact", ".vacuum"}) {
        auto companion = project;
        companion += suffix;
        if (fs::exists(companion)) RefuseCommand("FILTER_IMPORT_IO", "PROJECT_RECOVERY_REQUIRED");
    }
}

void CheckReplay(store::Container& reader, const ParsedFilterImportRequest& request,
                 const AdmittedHostCapture& host) {
    const auto uuid = reader.Meta("project_uuid");
    if (!uuid || *uuid != host.Artifacts().CapturedProjectUuid())
        RefuseCommand(kHostSourceStateMismatch, "ORIGINAL_H_PROJECT_UUID");
    const auto operation = request.MutationRequestFor(*uuid);
    const auto revision = store::ReadCurrentRevision(reader);
    const auto decision = store::DecideStored(reader, *uuid, operation, revision);
    if (decision.admission == core::Admission::stored_outcome) {
        if (!decision.record || !decision.record->outcome.IsObject())
            RefuseCommand(kStaleProspectiveView, "STORED_OUTCOME_INVALID");
        const auto& outcome = std::get<json::Object>(decision.record->outcome.data);
        const auto returned = outcome.find("returned");
        if (returned == outcome.end() || !returned->second.IsObject())
            RefuseCommand(kStaleProspectiveView, "STORED_OUTCOME_INVALID");
        const auto& values = std::get<json::Object>(returned->second.data);
        const auto key = values.find("entry_key");
        if (values.size() != 1 || key == values.end() || !key->second.IsString() ||
            !core::IsSha256Hex(std::get<std::string>(key->second.data)))
            RefuseCommand(kStaleProspectiveView, "STORED_OUTCOME_INVALID");
        throw StoredReplay{std::get<std::string>(key->second.data), decision.record->committed_revision};
    }
    if (decision.admission != core::Admission::execute)
        RefuseCommand(kStaleProspectiveView, core::ToString(decision.admission));
}

void CheckObserved(const FilterObservation& actual, std::string_view key, const json::Object& expected) {
    if (actual.entry_key != key || !actual.parameters || !actual.resource_id || !actual.image_outputs)
        RefuseCommand("FILTER_IMPORT_REOPEN", "OBSERVATIONS_UNAVAILABLE");
    json::Array outputs;
    for (const auto& name : *actual.image_outputs) outputs.push_back(name);
    const json::Object observed{{"parameters", *actual.parameters}, {"resource_id", *actual.resource_id},
                                {"image_outputs", std::move(outputs)}};
    if (json::WriteCanonical(observed) != json::WriteCanonical(expected))
        RefuseCommand("FILTER_IMPORT_REOPEN", "OBSERVATIONS_CHANGED");
}
}  // namespace

int FilterImportCommandDriver::Run(const std::vector<std::string>& args, std::FILE* out, std::FILE* err,
                                   const fs::path& registry, const Admission& admit_filter) {
    constexpr const char* usage = "usage: UzPainter.exe assets import-filter-observation <h-store.uzp> "
                                 "--oracle-store <root> --manifest <public-manifest.json> --request <import.json>\n";
    std::map<std::string, fs::path, std::less<>> paths;
    if (args.size() != 9 || args[0] != "assets" || args[1] != "import-filter-observation") {
        std::fputs(usage, err);
        return 2;
    }
    for (std::size_t i = 3; i < args.size(); i += 2) {
        if ((args[i] != "--oracle-store" && args[i] != "--manifest" && args[i] != "--request") ||
            args[i + 1].empty() || !paths.emplace(args[i], Path(args[i + 1])).second) {
            std::fputs(usage, err);
            return 2;
        }
    }
    bool committed = false;
    std::string committed_key;
    try {
        const auto request = Take(ParseFilterImportRequest(ReadPublic(paths.at("--request"))));
        const auto oracle = Take(OracleStoreReader::Open(paths.at("--oracle-store"), registry.empty() ? RegistryPath() : registry));
        const auto host = Take(AdmitHostCapture(request.HostCapture(), oracle));
        const auto capture = Take(admit_filter(ReadPublic(paths.at("--manifest")), request.ManifestRef(), oracle));
        const auto panels = Take(CheckFilterSettingsPanels(capture));
        const auto trace = Take(ValidateFilterTrace(capture, panels));
        const auto settings = Take(DeriveFilterSettings(capture, panels, trace));
        if (const auto failure = ValidateFilterHostBinding(capture, panels, trace, settings, host.Artifacts()))
            throw CommandRefused{*failure};

        const auto project_path = Path(args[2]);
        RequireRestingFile(project_path);
        std::optional<ValidatedFilterDestination> destination;
        store::OpenOptions options;
        options.preflight = [&](const core::Project& base, const auto&) {
            RequireRestingFile(project_path);
            auto reader = store::Container::OpenReadOnly(project_path);
            store::Statement journal(reader, "PRAGMA journal_mode");
            if (!journal.Step() || journal.Text(0) != "delete")
                RefuseCommand("FILTER_IMPORT_IO", "PROJECT_RECOVERY_REQUIRED");
            CheckReplay(reader, request, host);
            destination = Take(ExpectedDestination(capture, panels, trace, settings, host.Artifacts(), base));
        };
        auto opened = store::ProjectStore::Open(project_path, options);
        if (!destination) RefuseCommand(kStaleProspectiveView, "DESTINATION_NOT_VALIDATED");
        core::Document document(std::move(opened.state));
        opened.store->Attach(document);
        const auto templates = evaluator::TemplateLibrary::Load(evaluator::TemplateLibrary::DefaultDirectory());
        const auto imported = CommitAdmittedFilterObservation(*opened.store, document, host, request, *destination, templates);
        // Legacy store/proof details may contain private paths or values; the command reports a code.
        if (!imported) RefuseCommand(imported.error().reason, "NATIVE_COMMIT_REFUSED");
        committed_key = *imported;
        committed = true;
        const auto revision = document.revision();
        opened.store->Save(document);
        opened.store->Close();
        auto reopened = store::ProjectStore::Open(project_path);
        const auto observed = ObservedFilter(*reopened.store, reopened.state.project, destination->FilterEffect().uid);
        if (!observed) RefuseCommand("FILTER_IMPORT_REOPEN", "OBSERVATIONS_UNAVAILABLE");
        CheckObserved(*observed, committed_key, destination->Observations());
        Print(out, {{"status", "ok"}, {"entry_key", committed_key}, {"revision", revision},
                    {"replayed", false}, {"verified_after_reopen", true}});
        return 0;
    } catch (const StoredReplay& replay) {
        Print(out, {{"status", "ok"}, {"entry_key", replay.entry_key}, {"revision", replay.revision},
                    {"replayed", true}, {"verified_after_reopen", false}});
        return 0;
    } catch (const CommandRefused& failure) {
        json::Object report{{"status", committed ? "committed_verification_failed" : "refused"},
                            {"reason", failure.refusal.reason}, {"detail", failure.refusal.detail}};
        if (committed) report["entry_key"] = committed_key;
        Print(out, report);
        return 3;
    } catch (const std::exception&) {
        json::Object report{{"status", committed ? "committed_verification_failed" : "host_error"},
                            {"reason", "FILTER_IMPORT_IO"}, {"detail", "NATIVE_COMMAND_FAILED"}};
        if (committed) report["entry_key"] = committed_key;
        Print(out, report);
        return 3;
    }
}

int RunFilterImportCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err) {
    return FilterImportCommandDriver::Run(args, out, err, {}, AdmitFilterCapture);
}

}  // namespace uzp::procedural
