#include "procedural/snapshot_cli.h"

#include "procedural/admission.h"
#include "procedural/snapshot_recording.h"
#include "procedural/snapshot_backend.h"
#include "python/interpreter.h"
#include "uzp_core/manifest/sha256.h"

#include <Python.h>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <memory>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

namespace uzp::procedural {
namespace {
namespace fs = std::filesystem;
namespace json = core::json;

std::string Utf8(const fs::path& path) {
    const auto text = path.generic_u8string();
    return std::string(text.begin(), text.end());
}

fs::path Path(std::string_view text) { return fs::path(std::u8string(text.begin(), text.end())); }

struct ReleasePython {
    void operator()(PyObject* object) const { Py_XDECREF(object); }
};
using PythonObject = std::unique_ptr<PyObject, ReleasePython>;

std::runtime_error PythonError() {
    PythonObject error(PyErr_GetRaisedException());
    PythonObject message(error ? PyObject_Str(error.get()) : nullptr);
    const char* text = message ? PyUnicode_AsUTF8(message.get()) : nullptr;
    return std::runtime_error(text ? text : "Painter snapshot bridge failed");
}

void RunBridge(const fs::path& work) {
    const std::string error = python::Start();
    if (!error.empty()) throw std::runtime_error(error);
    struct Stop { ~Stop() { python::Stop(); } } stop;
    PythonObject module(PyImport_ImportModule("uzpainter_snapshot.bridge"));
    if (!module) throw PythonError();
    PythonObject function(PyObject_GetAttrString(module.get(), "main"));
    PythonObject args(PyList_New(0));
    if (!function || !args) throw PythonError();
    for (const fs::path& path : {work / "context.json", work / "request.json", work}) {
        const std::wstring value = path.wstring();
        PythonObject item(PyUnicode_FromWideChar(value.data(), static_cast<Py_ssize_t>(value.size())));
        if (!item || PyList_Append(args.get(), item.get()) != 0) throw PythonError();
    }
    PythonObject result(PyObject_CallFunctionObjArgs(function.get(), args.get(), nullptr));
    if (!result) throw PythonError();
    if (PyLong_AsLong(result.get()) != 0 || PyErr_Occurred()) throw PythonError();
}

std::string Read(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw std::runtime_error("cannot read " + Utf8(path));
    std::ostringstream text;
    text << stream.rdbuf();
    if (stream.bad()) throw std::runtime_error("cannot finish reading " + Utf8(path));
    return text.str();
}

void Write(const fs::path& path, std::string_view text) {
    std::ofstream stream(path, std::ios::binary);
    stream.write(text.data(), static_cast<std::streamsize>(text.size()));
    stream.close();
    if (!stream) throw std::runtime_error("cannot write " + Utf8(path));
}

const json::Object& Object(const json::Value& value) { return std::get<json::Object>(value.data); }
std::string String(const json::Object& value, std::string_view key) {
    return std::get<std::string>(value.at(std::string(key)).data);
}

fs::path BinaryDirectory() {
    std::wstring value(32768, L'\0');
    const DWORD size = GetModuleFileNameW(nullptr, value.data(), static_cast<DWORD>(value.size()));
    if (size == 0 || size == value.size()) throw std::runtime_error("cannot locate installed recorder");
    value.resize(size);
    return fs::path(value).parent_path();
}

void CheckCaptureDomain(const core::Project& project, std::string_view mesh, std::string_view plane) {
    const auto& settings = project.settings;
    const auto& colour = settings.color_management;
    if (!project.mesh || mesh != plane || project.mesh->resource != core::Sha256Hex(mesh)) {
        throw std::runtime_error("snapshot recording requires the exact shipped full-UV plane mesh");
    }
    if (settings.normal_map_format != core::NormalMapFormat::OpenGL ||
        settings.tangent_space != core::TangentSpace::PerVertex || settings.mesh_unit_scale != 1.0 ||
        settings.workflow != core::ProjectWorkflow::Default || (!colour.mode.empty() && colour.mode != "legacy") ||
        !colour.config_hash.empty() || !colour.working_space.empty() || !colour.io_rules.empty()) {
        throw std::runtime_error("snapshot recording requires Legacy, OpenGL, PerVertex, default workflow and mesh scale 1");
    }
}

void Print(std::FILE* out, const json::Object& report) {
    std::fprintf(out, "UZP_JSON:%s\n", json::WriteCanonical(report).c_str());
}
}  // namespace

int RunSnapshotCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err) {
    if (args.size() != 5 || args[0] != "assets" || args[1] != "snapshot" || args[3] != "--request") {
        std::fputs("usage: UzPainter.exe assets snapshot <file.uzp> --request <request.json>\n", err);
        return 2;
    }
    fs::path work;
    try {
        const fs::path bin = BinaryDirectory();
        const fs::path bridge = bin / "python" / "uzpainter_snapshot" / "bridge.py";
        const std::string bridgeHash = core::Sha256Hex(Read(bridge));
        const fs::path painterSide = bridge.parent_path() / "painter_side.py";
        const std::string painterSideHash = core::Sha256Hex(Read(painterSide));
        const json::Value requested = json::Parse(Read(Path(args[4])));
        const auto& requestObject = Object(requested);
        if (requestObject.size() != 2 || !requestObject.contains("parameters")) {
            throw std::runtime_error("request requires exactly resource and parameters");
        }
        const std::string resource = String(requestObject, "resource");
        auto opened = store::ProjectStore::Open(Path(args[2]));
        core::Document document(std::move(opened.state));
        opened.store->Attach(document);
        const auto state = document.snapshot();
        const auto& project = *state.project;
        if (!project.mesh) throw std::runtime_error("snapshot recording requires an imported plane mesh");
        const std::string mesh = opened.store->ReadResource(project.mesh->resource);
        CheckCaptureDomain(project, mesh, Read(bin / "assets" / "snapshot" / "plane.obj"));
        const wchar_t* local = _wgetenv(L"LOCALAPPDATA");
        if (local == nullptr || *local == L'\0') throw std::runtime_error("LOCALAPPDATA is not set");
        const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
        work = fs::path(local) / "UzPainter" / "snapshot-recordings" /
               (std::to_string(GetCurrentProcessId()) + "-" + std::to_string(stamp));
        if (!fs::create_directories(work)) throw std::runtime_error("snapshot work directory already exists");
        Write(work / "mesh.obj", mesh);
        Write(work / "request.json", json::WriteCanonical(requested));
        json::Object settings;
        for (const auto& [name, value] : EvaluationSettings(project)) settings[name] = ParamJson(value);
        const json::Object context{{"project_uuid", opened.store->project_uuid()},
                                   {"revision", document.revision()}, {"settings", settings},
                                   {"mesh_path", Utf8(work / "mesh.obj")}, {"bridge_sha256", bridgeHash},
                                   {"painter_side_sha256", painterSideHash}};
        Write(work / "context.json", json::WriteCanonical(context));
        RunBridge(work);
        if (core::Sha256Hex(Read(bridge)) != bridgeHash || core::Sha256Hex(Read(painterSide)) != painterSideHash) {
            throw std::runtime_error("installed recorder changed during capture");
        }
        const json::Value capture = json::Parse(Read(work / "capture.json"));
        const auto& receipt = Object(capture);
        if (String(receipt, "schema") != "uzpainter/procedural-capture/1" ||
            String(receipt, "project_uuid") != opened.store->project_uuid() ||
            std::get<int64_t>(receipt.at("revision").data) != document.revision() ||
            String(receipt, "resource") != resource) throw std::runtime_error("capture identity differs from request");
        const auto parsed = RequestFromSignature(receipt.at("signature"));
        if (!parsed) throw std::runtime_error(parsed.error());
        const ProceduralRequest& request = *parsed;
        if (core::FormatAssetUrl(request.asset) != "uzasset://snapshot/" + core::Sha256Hex(resource) + "@1" ||
            request.output != RasterSpec{128, ChannelFormat::F32, "raw", 1} || request.preset ||
            !request.inputs.empty() || request.meshClass != "quad" || request.uvTiles != 1 || request.outputId.empty()) {
            throw std::runtime_error("capture signature lies outside the supported domain");
        }
        // Only the receipt's explicit, paired readback gives the observations; nothing is inferred.
        const auto observed = ReceiptSourceMetadata(capture, resource, request);
        if (!observed) throw std::runtime_error("capture observations: " + observed.error());
        std::string scalarExport;
        std::string scalarTexels;
        const auto& hashes = Object(receipt.at("files"));
        for (int repeat = 1; repeat <= 2; ++repeat) {
            for (int channel = 0; channel <= 1; ++channel) {
                const std::string name = "export" + std::to_string(repeat) + "/user" + std::to_string(channel) + ".exr";
                const std::string bytes = Read(work / name);
                if (core::Sha256Hex(bytes) != String(hashes, name)) throw std::runtime_error("capture file hash differs");
                RasterSpec spec = request.output;
                spec.channels = channel == 0 ? 1 : 3;
                const auto texels = SnapshotExportTexels(bytes, spec);
                if (!texels) throw std::runtime_error(texels.error());
                if (repeat == 1 && channel == 0) { scalarExport = bytes; scalarTexels = *texels; }
                for (size_t pixel = 0; pixel < size_t{128 * 128}; ++pixel) {
                    for (uint32_t component = 0; component < spec.channels; ++component) {
                        if (texels->compare((pixel * spec.channels + component) * 4, 4, scalarTexels, pixel * 4, 4) != 0) {
                            throw std::runtime_error("paired scalar/RGB or repeated capture differs at native float32 precision");
                        }
                    }
                }
            }
        }
        const auto outcome = RecordSnapshotExport(*opened.store, document, request, scalarExport,
                                                  opened.store->project_uuid(), document.revision(), *observed);
        if (!outcome) throw std::runtime_error(outcome.error());
        if (!outcome->result || outcome->result->status != core::ResultStatus::committed) {
            throw std::runtime_error("snapshot transaction did not commit");
        }
        opened.store->Save(document);
        const int64_t recordedRevision = document.revision();
        opened.store->Close();
        auto reopened = store::ProjectStore::Open(Path(args[2]));
        const auto backend = SnapshotBackend::Load(*reopened.store, reopened.state.project);
        if (!backend) throw std::runtime_error("saved snapshot backend did not reload: " + backend.error());
        const auto stored = backend->Stored(request);
        if (!stored || (*stored)->bytes != scalarTexels) {
            throw std::runtime_error("saved snapshot did not serve the captured texels exactly after reopen");
        }
        const auto storedObservations = backend->Metadata(request);
        if (!storedObservations || *storedObservations != *observed) {
            throw std::runtime_error("saved snapshot did not keep the captured observations after reopen");
        }
        Print(out, {{"status", "ok"}, {"asset", core::FormatAssetUrl(request.asset)},
                    {"signature_sha256", SignatureHash(request)}, {"revision", recordedRevision},
                    {"verified_after_reopen", true},
                    {"receipt", Utf8(work / "capture.json")}});
        return 0;
    } catch (const std::exception& error) {
        Print(out, {{"status", "host_error"}, {"error", error.what()}, {"work", Utf8(work)}});
        return 3;
    }
}
}  // namespace uzp::procedural
