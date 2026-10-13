#pragma once

// The worker's tool definitions (src/supervisor/SUPERVISOR.md, Worker): what a tool is, how a call
// fails, the schema builders and the argument readers the worker (worker.cpp) and the typed tool
// families (typed_tools.cpp; task phase2.6_mcp-typed-tool-families, decision 164) share.

#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "python/jobs.h"
#include "python/session.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/project.h"

namespace uzp::supervisor {

namespace json = core::json;

/// A failed call: the reply's `error`.
struct CallError {
    std::string code;
    std::string message;
    json::Object details;
};

/// Whether an API error class is a release gap: `NotYetSupported` and its subclasses
/// `UnsupportedProcedural`, `ReleaseGap` and `PathTracerUnavailable`.
bool IsGapClass(std::string_view cls);

/// Whether an API error class is a `ProjectError`: the class itself and the mesh refusals that
/// subclass it, `MeshParseError`, `UnsupportedFormat`, `DuplicateMaterialNames`, `UVOutsideTile`
/// and `MaterialMappingError`.
bool IsProjectErrorClass(std::string_view cls);

/// A release gap met by `tool`: `capability_gap {tool, type, reason, operations}`, the fields the
/// supervisor's capability gate gives too (decision 242). `operations` are the release-gap
/// manifest operations of a gap family; empty when the native code refused the call.
CallError GapError(const std::string& tool, const std::string& reason, const std::string& type,
                   json::Array operations = {});

struct Tool {
    std::string name;
    std::string description;
    json::Object input_schema;
    bool mutating = false;
    bool gpu = false;
    /// The call is refused before it runs when the device is unavailable (`gpu`); a tool whose
    /// mode decides whether it uses the GPU (`capture`) checks the device itself.
    bool gpu_gate = true;
    /// The capability-manifest operations the tool performs (`[{symbol, context}]`): the supervisor
    /// refuses the call with `capability_gap` while one of them is a `release-gap` (phase2.5). A
    /// schema property may add the operations of the value it is given (`x-uzpainter-capability`,
    /// `CapabilityByValue`).
    json::Array capability = {};
};

using Handler = std::function<json::Object(const json::Object& arguments)>;
/// A long tool's handler: the job body of its arguments (checked before the job starts).
using JobHandler = std::function<python::JobBody(const json::Object& arguments)>;

/// One tool of a family: a call handler, or a job handler for a long tool with its commit point
/// (`revision`, `publication` or none).
struct ToolDefinition {
    Tool tool;
    Handler handler;
    JobHandler job;
    std::optional<std::string> commit_point;
};

// ── Schemas ────────────────────────────────────────────────────────────────────────────────────

json::Object Schema(json::Object properties, json::Array required);
json::Object StringProperty(const char* description);
/// A path argument: the supervisor's `--roots` confine it to the root of kind `root` (`project`,
/// `mesh`, `bake_mesh`, `resource` or `export`; 11-mcp-server.md §5) and hand over its canonical
/// absolute form.
json::Object PathProperty(const char* description, const char* root);
/// A node of the committed revision (a layer or an effect), by uid: the supervisor rejects a uid
/// that names no node before admission (`x-uzpainter-ref`, phase2.5).
json::Object UidProperty(const char* description);
/// The capability-manifest operation `symbol` in the context `any`.
json::Array Operation(const char* symbol);
/// `property` with the operations each of its values performs (`x-uzpainter-capability`): the
/// supervisor adds the operations of the value a call gives to the tool's own; a value the map
/// does not list is a capability gap (decision 164).
json::Object CapabilityByValue(json::Object property, std::vector<std::pair<std::string, const char*>> operations);

// ── Arguments ──────────────────────────────────────────────────────────────────────────────────

const json::Value* Field(const json::Object& object, std::string_view key);
std::optional<std::string> StringField(const json::Object& object, std::string_view key);

/// The texture set and stack a call names by `texture_set` and `stack`: the active texture set,
/// and its active or first stack, when omitted. `invalid_arguments` for a name that is not there.
std::pair<const core::TextureSet*, const core::Stack*> NamedStack(const core::Project& project,
                                                                  const python::OpenProject& open,
                                                                  const json::Object& arguments);

/// The refusal of a mutating call the stored operation rows decided not to run (`09-...` §4), or
/// nothing for `execute` and `stored_outcome`.
std::optional<CallError> AdmissionRefusal(const core::AdmissionDecision& decision, const std::string& key);

}  // namespace uzp::supervisor
