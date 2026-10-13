"""The tool registry both MCP transports serve (11-mcp-server.md §1, §2, §4-§6; task
phase2.5_mcp-transport-registry, decisions 158 and 159).

The stdio session and every Streamable HTTP session call the same `Registry`. Its tools are the
supervisor's own (`supervisor_status`, `wait_idle`, the job tools and, in HTTP mode, the lease
tools) and the worker's, whose schemas the worker lists. Every call is checked in this order, and
each refusal comes before admission (no job row, nothing sent to the worker):

1. **Capability.** A worker tool lists the capability-manifest operations it performs
   (`capability: [{symbol, context}]`); while one of them is a `release-gap` in the build's
   `capabilities.json`, or missing from it, the call fails `capability_gap`. The tool stays listed,
   with its status under `_meta["uzpainter/capability"]`, and becomes callable when the manifest
   entry changes, with no change here.
2. **Schema.** The arguments are validated against the tool's public schema (JSON Schema 2020-12:
   types, numeric bounds, enums, required and unknown properties): `invalid_arguments` with each
   failure's argument and rule, never the value given. Then a property marked
   `x-uzpainter-capability {<value>: [ops], "*": [ops]}` adds the operations of the value given
   (`*`: of any value) to the tool's, and a release gap among them fails `capability_gap` naming
   the argument and value; a value the map does not list counts as a gap (phase2.6, decision 164).
3. **Key and precondition.** A mutating call may omit `expected_revision` only together with
   `idempotency_key`; one with a key and no precondition fails `invalid_arguments` (§4, decision
   158; the worker's pipe still decides such a request for direct pipe clients, decision 138).
4. **Object references.** A property marked `x-uzpainter-ref` (`node`, `texture_set`, `stack`) must
   name an object of the committed revision (`snapshot_layer_tree`): `invalid_arguments` with
   `reason: dangling_reference` otherwise.
5. **Roots.** With `--roots`, each path argument is canonicalised and must lie inside the root of
   its kind (roots.py): `path_outside_roots`, naming the argument and the root kind, never the path.
6. **Lease.** In HTTP mode a mutating call needs an owner (`lease_acquire {owner}`):
   `lease_required` otherwise. The stdio session's owner is implicit. Admission (admission.py)
   then takes the lease, refuses `lease_held` and `busy`, and resolves the key and the
   precondition. A project an owner's call opens or creates is leased to that owner when the
   worker switches to it; a session without an owner is admitted `anonymous` and takes no lease
   (decision 243).

Every forwarded call's structured result carries the contract of §2: `revision` (the revision it
was admitted on), `committed_revision` (the project's committed revision after it), `job_id`,
`changed` (modified or removed), `created`, `hidden`, `imported` and `skipped` (from its transaction
result, gathered over the calls a script committed, also when it raised) and `warnings`, besides the
worker's `result` or `error` and the `receipt` (`admission.contract`). The text content is a
one-line summary. Images are content blocks only for `capture` (`IMAGE_TOOLS`): its PNG decoded and
averaged down to at most `IMAGE_EDGE` pixels on the long edge by the supervisor's native helper
(`_uzpainter_image`, decision 165), described by the result's `image {built, ...}`; a capture whose
block cannot be built still answers, with `image {built: false, reason}` and a warning. Every other
result references files. With `--roots`, path-valued fields outside the roots are replaced
(`roots.Roots.scrub`), except a `run_python` result's own (roots never sandbox it).

The supervisor's own tools also include `status`, `capabilities` and `batch` (11 §2; phase2.6,
decision 165): `batch {calls, stop_on_error, idempotency_key?}` runs each call in order through
`call` (every check, its own admission, job and transaction; a long call with `wait`), so a batch is
not atomic; with `stop_on_error` (the default) the calls after the first failure are reported
`not_executed`. With a batch key, a mutating call without its own key gets `<key>/<index>` and the
revision current at its admission, so a retried batch returns each committed call's stored outcome.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import jsonschema

from .admission import CHANGE_LISTS, Admission, Notify, error_reply
from .roots import PathArgument, PathRefused, Roots, path_arguments

log = logging.getLogger("uzpainter.supervisor")

STATUS_TOOL = "supervisor_status"
WAIT_IDLE_TOOL = "wait_idle"
BATCH_TOOL = "batch"
JOB_LIST_LIMIT = 50
CAPABILITY_META_KEY = "uzpainter/capability"
REF_KEYWORD = "x-uzpainter-ref"
VALUE_CAPABILITY_KEYWORD = "x-uzpainter-capability"
IMAGE_TOOLS = frozenset({"capture"})
IMAGE_LIMIT = 4 * 1024 * 1024  # bytes of a PNG attached as an image content block
IMAGE_EDGE = 512  # the long edge of a capture's image block, in pixels (decision 165)
IMAGE_SOURCE_LIMIT = 512 * 1024 * 1024  # the largest capture PNG the helper is given
# The image helper: `(png bytes, max edge) -> png bytes` (`_uzpainter_image.preview_png`).
Thumbnail = Callable[[bytes, int], bytes]
OWNER_PATTERN = re.compile(r"^[A-Za-z0-9._@-][A-Za-z0-9._:@-]{0,127}$")
# The MCP arguments of a mutating tool carry its key and precondition (02 §2); the supervisor
# lifts them into the pipe request, so the worker's own schema does not list them. Both may be
# omitted together; a client that supplies its own key supplies its original precondition with
# it on every attempt (11-mcp-server.md §4).
MUTATION_PROPERTIES: dict[str, Any] = {
    "idempotency_key": {
        "type": "string",
        "minLength": 1,
        "description": "The mutation's idempotency key, kept for every retry of it, always with "
        "its original expected_revision; generated by the supervisor (and returned in the "
        "receipt) when both are omitted.",
    },
    "expected_revision": {
        "type": "integer",
        "minimum": 0,
        "description": "The revision the mutation is based on (its precondition), kept with "
        "the key on every retry; resolved by the supervisor when both are omitted.",
    },
}
WAIT_PROPERTY: dict[str, Any] = {
    "type": "boolean",
    "description": "Wait for the job's end (streaming its progress) instead of returning "
    "{job_id, status} at once.",
}
EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}
JOB_ID_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"job_id": {"type": "string", "minLength": 1}},
    "required": ["job_id"],
    "additionalProperties": False,
}
OWNER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "owner": {
            "type": "string",
            "pattern": OWNER_PATTERN.pattern,
            "description": "The client's lease owner; a client that reconnects names the same "
            "owner to get its lease back.",
        }
    },
    "required": ["owner"],
    "additionalProperties": False,
}
BATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "calls": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "minLength": 1},
                    "arguments": {"type": "object"},
                },
                "required": ["tool"],
                "additionalProperties": False,
            },
            "description": "The calls, run in order, each as a call of its own.",
        },
        "stop_on_error": {
            "type": "boolean",
            "description": "Stop at the first failed call (the default); the calls after it are "
            "reported not_executed.",
        },
        "idempotency_key": {
            "type": "string",
            "minLength": 1,
            "description": "The batch's key: a mutating call without its own key gets "
            "`<key>/<index>`, so a retried batch returns each committed call's stored outcome.",
        },
    },
    "required": ["calls"],
    "additionalProperties": False,
}
# The supervisor's own tools: description, schema, read-only, HTTP mode only.
SUPERVISOR_TOOLS: dict[str, tuple[str, dict[str, Any], bool, bool]] = {
    "status": (
        "UzPainter's versions and compatibility profile, the worker's backend and Python policy, "
        "the open project and its committed revision, the running jobs and the project's lease.",
        EMPTY_SCHEMA,
        True,
        False,
    ),
    "capabilities": (
        "The build's capability manifest summarised: each tool's status (available or release-gap) "
        "with the operations and argument values that are release gaps; uzpainter://capabilities "
        "holds every manifest entry.",
        EMPTY_SCHEMA,
        True,
        False,
    ),
    BATCH_TOOL: (
        "Runs calls in order, each with every check, its own admission and its own transaction (a "
        "batch is not atomic); per-call results; stop_on_error stops at the first failure.",
        BATCH_SCHEMA,
        False,
        False,
    ),
    STATUS_TOOL: (
        "The supervisor's worker: pid, backend, Python policy, project and every recovery with "
        "its cause, minidump and time; the ledger, the project's lease and the running calls.",
        EMPTY_SCHEMA,
        True,
        False,
    ),
    WAIT_IDLE_TOOL: (
        "Waits until no mutating call or long job runs; a timeout is an error.",
        {
            "type": "object",
            "properties": {
                "timeout": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Seconds to wait before failing with `timeout`.",
                }
            },
            "required": ["timeout"],
            "additionalProperties": False,
        },
        True,
        False,
    ),
    "job_status": (
        "A job's status: a running job's progress, message and commit point, or a finished "
        "job's terminal state (succeeded, failed, cancelled or interrupted) and resolution.",
        JOB_ID_SCHEMA,
        True,
        False,
    ),
    "job_result": (
        "A finished job's reply with its receipt, as it was answered.",
        JOB_ID_SCHEMA,
        True,
        False,
    ),
    "job_cancel": (
        "Asks a running long job to stop at its next checkpoint (acknowledged at once); its "
        "receipt then says whether it stopped before or after its commit point.",
        JOB_ID_SCHEMA,
        False,
        False,
    ),
    "job_list": (
        "The ledger's newest jobs, newest first.",
        {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "description": f"The newest jobs to list ({JOB_LIST_LIMIT} when omitted).",
                }
            },
            "additionalProperties": False,
        },
        True,
        False,
    ),
    "lease_acquire": (
        "Takes the open project's mutation lease for `owner` and binds the owner to this "
        "session (HTTP mode); a project the session then opens or creates is leased to the owner "
        "too. Refused with lease_held while another live owner holds it.",
        OWNER_SCHEMA,
        False,
        True,
    ),
    "lease_release": (
        "Ends this session's owner's leases and unbinds it (HTTP mode).",
        EMPTY_SCHEMA,
        False,
        True,
    ),
    "lease_status": (
        "This session's owner and the open project's lease (holder, since, active job).",
        EMPTY_SCHEMA,
        True,
        True,
    ),
}


class Worker(Protocol):
    """What the registry needs of `worker.Supervisor` (besides what admission needs)."""

    project_path: str | None
    project_uuid: str | None
    durable_revision: int | None
    project_epoch: int

    async def wait_ready(self) -> None: ...

    async def request(self, frame: dict[str, Any]) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...


class ManifestError(ValueError):
    """`capabilities.json` is missing, unreadable or malformed."""


@dataclass(frozen=True)
class Manifest:
    """The build's capability manifest: the status of each (symbol, context)."""

    statuses: dict[tuple[str, str], tuple[str, str | None]]
    document: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def load(path: Path) -> Manifest:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ManifestError(f"cannot read the capability manifest {path}: {error}") from None
        return Manifest.from_document(document)

    @staticmethod
    def from_document(document: Any) -> Manifest:
        entries = document.get("entries") if isinstance(document, dict) else None
        if not isinstance(entries, list):
            raise ManifestError("the capability manifest has no entries list")
        statuses: dict[tuple[str, str], tuple[str, str | None]] = {}
        for entry in entries:
            if not isinstance(entry, dict) or not all(
                isinstance(entry.get(field_name), str)
                for field_name in ("symbol", "context", "status")
            ):
                raise ManifestError(f"malformed capability manifest entry {entry!r}")
            pair = (entry["symbol"], entry["context"])
            if pair in statuses:
                raise ManifestError(f"the capability manifest repeats {pair}")
            notes = entry.get("notes")
            statuses[pair] = (entry["status"], notes if isinstance(notes, str) else None)
        return Manifest(statuses, document)

    @property
    def compat_profile(self) -> Any:
        return self.document.get("compat_profile")

    def counts(self) -> dict[str, int]:
        """The number of entries of each status."""
        counts: dict[str, int] = {}
        for status, _ in self.statuses.values():
            counts[status] = counts.get(status, 0) + 1
        return counts

    def operations(self, declared: Any) -> list[dict[str, Any]]:
        """Each declared `{symbol, context}` with its status (`release-gap` when unlisted)."""
        operations = []
        for operation in declared if isinstance(declared, list) else []:
            symbol = str(operation.get("symbol")) if isinstance(operation, dict) else "?"
            context = str(operation.get("context", "any")) if isinstance(operation, dict) else "?"
            status, notes = self.statuses.get((symbol, context), ("release-gap", None))
            operations.append(
                {"symbol": symbol, "context": context, "status": status, "notes": notes}
            )
        return operations


@dataclass
class Client:
    """One MCP session: its transport and, in HTTP mode, the lease owner it acquired."""

    transport: str  # "stdio" or "http"
    owner: str | None = None


def _value_operations(
    schema: Any, value: Any, pointer: str = ""
) -> list[tuple[str, str, list[Any]]]:
    """The `(argument, value, operations)` of each `x-uzpainter-capability` property `value`
    gives: the map's entry of a string value (`*` for any value); an unlisted value declares an
    operation no manifest lists, so it is a gap (fail closed)."""
    found: list[tuple[str, str, list[Any]]] = []
    if not isinstance(schema, dict) or value is None:
        return found
    mapping = schema.get(VALUE_CAPABILITY_KEYWORD)
    if isinstance(mapping, dict):
        if "*" in mapping:
            found.append((pointer or "/", "*", list(mapping["*"])))
        elif isinstance(value, str):
            declared = mapping.get(value)
            if not isinstance(declared, list):
                declared = [{"symbol": f"<unlisted value of {pointer or '/'}>", "context": "any"}]
            found.append((pointer or "/", value, declared))
    properties = schema.get("properties")
    additional = schema.get("additionalProperties")
    if isinstance(value, dict):
        for name, item in value.items():
            if isinstance(properties, dict) and name in properties:
                found += _value_operations(properties[name], item, f"{pointer}/{name}")
            elif isinstance(additional, dict):
                found += _value_operations(additional, item, f"{pointer}/{name}")
    items = schema.get("items")
    if isinstance(value, list) and isinstance(items, dict):
        for index, item in enumerate(value):
            found += _value_operations(items, item, f"{pointer}/{index}")
    return found


def _value_maps(schema: Any, pointer: str = "") -> list[tuple[str, dict[str, Any]]]:
    """The `(argument, map)` of every `x-uzpainter-capability` property of a schema (`*` stands
    for any member or item)."""
    found: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(schema, dict):
        return found
    mapping = schema.get(VALUE_CAPABILITY_KEYWORD)
    if isinstance(mapping, dict):
        found.append((pointer or "/", mapping))
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, item in properties.items():
            found += _value_maps(item, f"{pointer}/{name}")
    for key in ("additionalProperties", "items"):
        if isinstance(schema.get(key), dict):
            found += _value_maps(schema[key], f"{pointer}/*")
    return found


def _png_size(data: bytes) -> tuple[int, int]:
    """The width and height of a PNG (its IHDR)."""
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


@dataclass
class Reply:
    """A tool call's structured content and its image blocks (`capture` only)."""

    body: dict[str, Any]
    images: list[dict[str, str]] = field(default_factory=list)
    summary: str = ""


def public_schema(tool: dict[str, Any]) -> dict[str, Any]:
    """The MCP input schema of a worker tool; a mutating one takes its key and precondition too,
    a long one `wait`."""
    schema: dict[str, Any] = copy.deepcopy(tool["inputSchema"])
    if tool["mutating"]:
        schema.setdefault("properties", {}).update(copy.deepcopy(MUTATION_PROPERTIES))
    if tool.get("long"):
        schema.setdefault("properties", {})["wait"] = copy.deepcopy(WAIT_PROPERTY)
    return schema


def _invalid(message: str, errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return error_reply("invalid_arguments", message, {"errors": errors or []})


def _schema_errors(schema: dict[str, Any], arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """Each failure as `{argument, rule, message}`; a message never repeats the value given (it
    may be a path outside the roots)."""
    validator = jsonschema.Draft202012Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(arguments), key=lambda e: list(e.absolute_path)):
        pointer = "/" + "/".join(str(part) for part in error.absolute_path)
        rule = str(error.validator)
        if rule in ("required", "additionalProperties"):
            message = error.message  # names the properties, never their values
        elif rule in (
            "type",
            "enum",
            "minimum",
            "maximum",
            "exclusiveMinimum",
            "exclusiveMaximum",
            "minLength",
            "maxLength",
            "minItems",
            "maxItems",
            "pattern",
            "const",
            "multipleOf",
        ):
            message = f"{pointer} fails {rule} {json.dumps(error.validator_value)}"
        else:
            message = f"{pointer} fails {rule}"
        errors.append({"argument": pointer, "rule": rule, "message": message})
    return errors


def _references(schema: Any, value: Any, pointer: str = "") -> list[tuple[str, str, Any]]:
    """The `(pointer, kind, value)` of each object reference in `value`."""
    found: list[tuple[str, str, Any]] = []
    if not isinstance(schema, dict):
        return found
    kind = schema.get(REF_KEYWORD)
    if isinstance(kind, str):
        found.append((pointer or "/", kind, value))
    properties = schema.get("properties")
    if isinstance(value, dict) and isinstance(properties, dict):
        for name, item in value.items():
            if name in properties:
                found += _references(properties[name], item, f"{pointer}/{name}")
    items = schema.get("items")
    if isinstance(value, list) and isinstance(items, dict):
        for index, item in enumerate(value):
            found += _references(items, item, f"{pointer}/{index}")
    return found


def summary(tool: str, body: dict[str, Any]) -> str:
    """The one-line text of a result: `<tool>: <status>[; revision a -> b][; <counts>][; job j]`,
    or `<tool>: error <code>: <message>`."""
    error = body.get("error")
    if isinstance(error, dict):
        message = str(error.get("message", ""))
        if len(message) > 200:
            message = message[:197] + "..."
        return f"{tool}: error {error.get('code')}: {message}"
    result = body.get("result")
    status = result.get("status") if isinstance(result, dict) else None
    parts = [f"{tool}: {status if isinstance(status, str) else 'ok'}"]
    if body.get("revision") is not None or body.get("committed_revision") is not None:
        parts.append(f"revision {body.get('revision')} -> {body.get('committed_revision')}")
    counts = [
        f"{name} {len(body[name])}"
        for name in ("changed", *CHANGE_LISTS)
        if isinstance(body.get(name), list) and body[name]
    ]
    if counts:
        parts.append(", ".join(counts))
    if body.get("job_id"):
        parts.append(f"job {body['job_id']}")
    return "; ".join(parts)


class Registry:
    """The tools of one supervisor, shared by its transports."""

    def __init__(
        self,
        worker: Worker,
        admission: Admission,
        manifest: Manifest,
        *,
        roots: Roots | None = None,
        http: bool = False,
        thumbnail: Thumbnail | None = None,
        build: str = "",
        protocol: str = "",
    ) -> None:
        self.worker = worker
        self.admission = admission
        self.manifest = manifest
        self.roots = roots
        self.http = http
        self.thumbnail = thumbnail
        self.build = build
        self.protocol = protocol
        self.known: dict[str, dict[str, Any]] = {}
        # The owners HTTP sessions acquired (their leases end when the supervisor does).
        self.owners: set[str] = set()
        self._snapshot: tuple[tuple[str | None, int | None, int], dict[str, Any] | None] | None = (
            None
        )

    def close(self) -> None:
        for owner in self.owners:
            self.admission.ledger.release(owner)

    # ── Listing ─────────────────────────────────────────────────────────────────────────────

    async def worker_tools(self) -> list[dict[str, Any]]:
        reply = await self.worker.request({"method": "tools/list"})
        if "error" in reply:  # the worker died while listing: ask the relaunched one
            reply = await self.worker.request({"method": "tools/list"})
        listed: list[dict[str, Any]] = reply.get("result", {}).get("tools", [])
        self.known = {tool["name"]: tool for tool in listed}
        return listed

    async def list_tools(self) -> list[dict[str, Any]]:
        """`[{name, description, inputSchema, readOnly, meta}]`, the supervisor's tools first."""
        tools = [
            {
                "name": name,
                "description": description,
                "inputSchema": copy.deepcopy(schema),
                "readOnly": read_only,
                "meta": None,
            }
            for name, (description, schema, read_only, http_only) in SUPERVISOR_TOOLS.items()
            if self.http or not http_only
        ]
        for tool in await self.worker_tools():
            capability = self._capability(tool)
            tools.append(
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "inputSchema": public_schema(tool),
                    "readOnly": not tool["mutating"],
                    "meta": {CAPABILITY_META_KEY: capability} if capability else None,
                }
            )
        return tools

    def _capability(self, tool: dict[str, Any]) -> dict[str, Any] | None:
        """`{status, operations, values}` of a worker tool, or None when it declares nothing:
        `values` lists the status of each argument value an `x-uzpainter-capability` map names."""
        operations = self.manifest.operations(tool.get("capability"))
        values = []
        for argument, mapping in _value_maps(tool.get("inputSchema")):
            for value, declared in mapping.items():
                listed = self.manifest.operations(declared)
                gap = any(operation["status"] == "release-gap" for operation in listed)
                values.append(
                    {
                        "argument": argument,
                        "value": value,
                        "status": "release-gap" if gap else "available",
                        "operations": listed,
                    }
                )
        if not operations and not values:
            return None
        gap = any(operation["status"] == "release-gap" for operation in operations)
        return {
            "status": "release-gap" if gap else "available",
            "operations": operations,
            "values": values,
        }

    async def capability_table(self) -> list[dict[str, Any]]:
        """Every worker tool's capability status (`capabilities`, `uzpainter://capabilities`):
        `{tool, status, gaps, value_gaps}`, the operations and argument values that are gaps."""
        table = []
        for tool in await self.worker_tools():
            capability = self._capability(tool) or {
                "status": "available",
                "operations": [],
                "values": [],
            }
            table.append(
                {
                    "tool": tool["name"],
                    "status": capability["status"],
                    "gaps": [
                        operation
                        for operation in capability["operations"]
                        if operation["status"] == "release-gap"
                    ],
                    "value_gaps": [
                        {"argument": value["argument"], "value": value["value"]}
                        for value in capability["values"]
                        if value["status"] == "release-gap"
                    ],
                }
            )
        return table

    # ── Calls ───────────────────────────────────────────────────────────────────────────────

    async def call(
        self, name: str, arguments: dict[str, Any], client: Client, notify: Notify | None
    ) -> Reply:
        """Checks, admits and forwards one tool call."""
        arguments = dict(arguments)
        own = SUPERVISOR_TOOLS.get(name)
        if own is not None and (self.http or not own[3]):
            errors = _schema_errors(own[1], arguments)
            body = (
                _invalid(f"{name}: invalid arguments", errors)
                if errors
                else await self._own(name, arguments, client)
            )
            return self._reply(name, body, scrub=name != BATCH_TOOL)
        if name not in self.known:
            await self.worker_tools()
        tool = self.known.get(name)
        if tool is None:
            # The worker answers an unknown tool (`unknown_tool`) and `run_python` without
            # --allow-python (`python_disabled`) at its own boundary.
            body = await self.admission.call(name, arguments, False, self._owner(client))
            return self._reply(name, body, scrub=True)
        refused = await self._check(name, tool, arguments, client)
        if refused is not None:
            refused = self.admission.refused(name, refused)
            return self._reply(name, refused, scrub=True)
        body = await self.admission.call(
            name,
            arguments,
            bool(tool.get("mutating")),
            self._owner(client),
            long=bool(tool.get("long")),
            commit_point=tool.get("commit_point"),
            notify=notify,
            anonymous=self.http and client.owner is None,
        )
        images = await self._images(name, body)
        return self._reply(name, body, scrub=name != "run_python", images=images)

    def _owner(self, client: Client) -> str:
        """The lease owner of `client`'s calls: its acquired owner, or the stdio session's (an
        HTTP session without an owner has none: its calls are admitted `anonymous`)."""
        return client.owner or self.admission.stdio_owner()

    async def _check(
        self, name: str, tool: dict[str, Any], arguments: dict[str, Any], client: Client
    ) -> dict[str, Any] | None:
        """The refusal of a call before admission, or None; canonicalises its path arguments in
        place."""
        operations = self.manifest.operations(tool.get("capability"))
        gaps = [operation for operation in operations if operation["status"] == "release-gap"]
        if gaps:
            return error_reply(
                "capability_gap",
                f"{name} needs an operation that is a release gap of this build",
                {"tool": name, "operations": gaps},
            )
        schema = public_schema(tool)
        errors = _schema_errors(schema, arguments)
        if errors:
            return _invalid(f"{name}: invalid arguments", errors)
        value_gaps = []
        for argument, value, declared in _value_operations(schema, arguments):
            for operation in self.manifest.operations(declared):
                if operation["status"] == "release-gap":
                    value_gaps.append({**operation, "argument": argument, "value": value})
        if value_gaps:
            return error_reply(
                "capability_gap",
                f"{name}: an argument value needs an operation that is a release gap of this build",
                {"tool": name, "operations": value_gaps},
            )
        mutating = bool(tool.get("mutating"))
        if mutating and "idempotency_key" in arguments and "expected_revision" not in arguments:
            return _invalid(
                "a call that supplies idempotency_key supplies its original expected_revision",
                [
                    {
                        "argument": "/expected_revision",
                        "rule": "dependentRequired",
                        "message": "idempotency_key needs expected_revision",
                    }
                ],
            )
        busy = (mutating or bool(tool.get("long"))) and (
            (self.worker.project_uuid or "") in self.admission.running
        )
        if not busy:  # a busy call is refused by admission without waiting for the long job
            dangling = await self._dangling(schema, arguments)
            if dangling:
                return _invalid(f"{name}: dangling object reference", dangling)
        if self.roots is not None:
            refusal = await asyncio.to_thread(self._canonicalise, schema, arguments)
            if refusal is not None:
                return refusal
        if self.http and mutating and client.owner is None:
            return error_reply(
                "lease_required",
                "a mutating call in HTTP mode needs the session's owner: call lease_acquire first",
                {},
            )
        return None

    async def _dangling(
        self, schema: dict[str, Any], arguments: dict[str, Any]
    ) -> list[dict[str, Any]]:
        references = _references(schema, arguments)
        if not references:
            return []
        snapshot = await self._layer_tree()
        nodes = {node.get("uid") for node in (snapshot or {}).get("nodes", [])}
        stacks = [
            (stack.get("texture_set_name"), stack.get("stack_name"))
            for stack in (snapshot or {}).get("stacks", [])
        ]
        texture_set = arguments.get("texture_set")
        dangling = []
        for pointer, kind, value in references:
            if kind == "node":
                found = value in nodes
            elif kind == "texture_set":
                found = any(name == value for name, _ in stacks)
            elif kind == "stack":
                found = any(
                    stack == value and (texture_set is None or name == texture_set)
                    for name, stack in stacks
                )
            else:
                found = False
            if not found:
                reason = "no project is open" if snapshot is None else f"no such {kind}"
                dangling.append(
                    {
                        "argument": pointer,
                        "rule": REF_KEYWORD,
                        "reason": "dangling_reference",
                        "message": f"{pointer} names no {kind} of the committed revision "
                        f"({reason})",
                    }
                )
        return dangling

    async def _layer_tree(self) -> dict[str, Any] | None:
        """The committed revision's layer tree (cached per project, revision and epoch); None
        when no project is open."""
        worker = self.worker
        await worker.wait_ready()
        key = (worker.project_uuid, worker.durable_revision, worker.project_epoch)
        if self._snapshot is not None and self._snapshot[0] == key:
            return self._snapshot[1]
        snapshot = None
        if worker.project_uuid is not None:
            reply = await worker.request(
                {"method": "tools/call", "name": "snapshot_layer_tree", "arguments": {}}
            )
            result = reply.get("result")
            snapshot = result if isinstance(result, dict) else None
        self._snapshot = (key, snapshot)
        return snapshot

    def _canonicalise(
        self, schema: dict[str, Any], arguments: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Replaces each path argument by its canonical form; the refusal of the first one outside
        its root. Runs in the default executor (filesystem lookups)."""
        assert self.roots is not None
        try:
            for argument in list(path_arguments(schema, arguments)):
                self._canonicalise_one(arguments, argument)
        except PathRefused as refused:
            return error_reply(
                "path_outside_roots",
                str(refused),
                {"argument": refused.pointer, "root": refused.root, "reason": refused.reason},
            )
        return None

    def _canonicalise_one(self, arguments: dict[str, Any], argument: PathArgument) -> None:
        assert self.roots is not None
        parts = [part for part in argument.pointer.split("/") if part]
        container: Any = arguments
        for part in parts[:-1]:
            container = container[int(part)] if isinstance(container, list) else container[part]
        last: Any = int(parts[-1]) if isinstance(container, list) else parts[-1]
        value = container[last]
        if argument.members is None:
            container[last] = self.roots.canonical(value, argument.root, argument.pointer)
            return
        as_text = isinstance(value, str)
        try:
            members = json.loads(value) if as_text else value
        except ValueError:
            return  # not JSON text: the worker refuses it
        if not isinstance(members, dict):
            return
        for member, root in argument.members.items():
            if isinstance(members.get(member), str):
                members[member] = self.roots.canonical(
                    members[member], root, f"{argument.pointer}/{member}"
                )
        container[last] = json.dumps(members) if as_text else members

    async def _own(self, name: str, arguments: dict[str, Any], client: Client) -> dict[str, Any]:
        admission = self.admission
        if name == STATUS_TOOL:
            return {"result": {**self.worker.status(), **admission.status()}}
        if name == "status":
            return {"result": await self._status()}
        if name == "capabilities":
            table = await self.capability_table()
            return {
                "result": {
                    "compat_profile": self.manifest.compat_profile,
                    "entries": self.manifest.counts(),
                    "tools": table,
                    "gaps": [row["tool"] for row in table if row["status"] == "release-gap"],
                }
            }
        if name == BATCH_TOOL:
            return await self._batch(arguments, client)
        if name == WAIT_IDLE_TOOL:
            return await admission.wait_idle(float(arguments["timeout"]))
        if name == "job_list":
            return admission.job_list(int(arguments.get("limit", JOB_LIST_LIMIT)))
        if name == "job_status":
            return admission.job_status(arguments["job_id"])
        if name == "job_result":
            return admission.job_result(arguments["job_id"])
        if name == "job_cancel":
            return await admission.cancel(arguments["job_id"])
        return await self._lease(name, arguments, client)

    async def _status(self) -> dict[str, Any]:
        """`status`: versions, profile, open project, revision, busy jobs and the lease."""
        await self.worker.wait_ready()
        worker = self.worker.status()
        admission = self.admission.status()
        return {
            "versions": {
                "worker_build": worker.get("build"),
                "supervisor_build": self.build,
                "protocol": self.protocol,
            },
            "compat_profile": self.manifest.compat_profile,
            "gpu_backend": worker.get("gpu_backend"),
            "gpu_status": worker.get("gpu_status"),
            "python": worker.get("python"),
            "project": {
                "path": worker.get("project"),
                "project_uuid": worker.get("project_uuid"),
                "untitled": worker.get("untitled"),
            },
            "revision": worker.get("revision"),
            "busy": [
                {"project_uuid": scope or None, "job_id": job_id}
                for scope, job_id in admission["running"].items()
            ],
            "lease": admission["lease"],
        }

    async def _batch(self, arguments: dict[str, Any], client: Client) -> dict[str, Any]:
        """`batch`: each call through `call`, in order (see the module comment)."""
        calls: list[dict[str, Any]] = arguments["calls"]
        stop = arguments.get("stop_on_error", True) is not False
        key = arguments.get("idempotency_key")
        results: list[dict[str, Any]] = []
        stopped = False
        for index, entry in enumerate(calls):
            name = str(entry["tool"])
            if stopped:
                results.append({"index": index, "tool": name, "status": "not_executed"})
                continue
            call_arguments = dict(entry.get("arguments") or {})
            if name == BATCH_TOOL:
                body = _invalid("a batch cannot hold a batch")
                reply = self._reply(name, body, scrub=True)
            else:
                if name not in self.known and name not in SUPERVISOR_TOOLS:
                    await self.worker_tools()
                tool = self.known.get(name)
                if tool is not None and tool.get("long"):
                    call_arguments["wait"] = True  # a batch's long call runs to its end
                if (
                    key is not None
                    and tool is not None
                    and tool.get("mutating")
                    and "idempotency_key" not in call_arguments
                ):
                    call_arguments["idempotency_key"] = f"{key}/{index}"
                    if "expected_revision" not in call_arguments:
                        await self.worker.wait_ready()
                        call_arguments["expected_revision"] = self.worker.durable_revision or 0
                reply = await self.call(name, call_arguments, client, None)
            failed = "error" in reply.body
            results.append(
                {
                    "index": index,
                    "tool": name,
                    "status": "failed" if failed else "succeeded",
                    "summary": reply.summary,
                    "body": reply.body,
                }
            )
            if failed and stop:
                stopped = True
        executed = [row for row in results if row["status"] != "not_executed"]
        failures = [row for row in executed if row["status"] == "failed"]
        if stopped and len(executed) < len(results):
            status = "stopped"
        elif failures:
            status = "completed_with_errors"
        else:
            status = "completed"
        return {
            "result": {
                "status": status,
                "executed": len(executed),
                "failed": len(failures),
                "results": results,
            },
            "committed_revision": self.worker.durable_revision,
        }

    async def _lease(self, name: str, arguments: dict[str, Any], client: Client) -> dict[str, Any]:
        """`lease_acquire`, `lease_release` and `lease_status` (HTTP mode, 11 §4, decision 159)."""
        admission = self.admission
        await self.worker.wait_ready()
        project_uuid = self.worker.project_uuid
        if name == "lease_acquire":
            owner = str(arguments["owner"])
            if owner.startswith("stdio:"):
                return _invalid("owners starting with stdio: are reserved")
            lease = None
            if project_uuid is not None:
                refused = admission.check_lease(project_uuid, owner)
                if refused is not None:
                    return refused
                lease = admission.ledger.lease(project_uuid)
            client.owner = owner
            self.owners.add(owner)
            return {"result": self._lease_status(client, project_uuid, lease)}
        if name == "lease_release":
            bound = client.owner
            if bound is None:
                return error_reply("lease_required", "this session holds no owner", {})
            held = admission.ledger.lease(project_uuid) if project_uuid else None
            if held is not None and held.holder == bound and held.active_job is not None:
                return error_reply(
                    "busy",
                    "the owner's job is running; the lease is kept",
                    {"job_id": held.active_job},
                )
            admission.ledger.release(bound)
            self.owners.discard(bound)
            client.owner = None
            return {"result": {"released": bound}}
        lease = admission.ledger.lease(project_uuid) if project_uuid else None
        return {"result": self._lease_status(client, project_uuid, lease)}

    @staticmethod
    def _lease_status(client: Client, project_uuid: str | None, lease: Any) -> dict[str, Any]:
        return {
            "owner": client.owner,
            "project_uuid": project_uuid,
            "lease": None if lease is None else lease.to_json(),
        }

    def _reply(
        self,
        name: str,
        body: dict[str, Any],
        *,
        scrub: bool,
        images: list[dict[str, str]] | None = None,
    ) -> Reply:
        error = body.get("error")
        log.info(
            "call %s: %s (job %s)",
            name,
            f"error {error.get('code')}" if isinstance(error, dict) else "ok",
            (body.get("receipt") or {}).get("job_id"),
        )
        if self.roots is not None:
            if scrub:
                body = self.roots.scrub(body)
            elif isinstance(body.get("receipt"), dict):
                body = {**body, "receipt": self.roots.scrub(body["receipt"])}
        return Reply(body, images or [], summary(name, body))

    async def _images(self, name: str, body: dict[str, Any]) -> list[dict[str, str]]:
        """`capture`'s image block: its receipt's `files.png` downscaled by the image helper in
        the executor (decision 165), described by `body["image"]`. A block that cannot be built is
        `image {built: false, reason}` with a warning; the capture's files stay as they are."""
        result = body.get("result")
        files = result.get("files") if isinstance(result, dict) else None
        png = files.get("png") if isinstance(files, dict) else None
        if name not in IMAGE_TOOLS or not isinstance(png, str):
            return []

        def unbuilt(reason: str) -> list[dict[str, str]]:
            body["image"] = {"built": False, "reason": reason}
            body["warnings"].append(
                f"the capture's image block was not built: {reason}; read files.png"
            )
            return []

        if self.thumbnail is None:
            return unbuilt("this supervisor has no image helper")
        try:
            preview, source_sha256 = await asyncio.to_thread(self._preview, png)
        except OSError as error:
            return unbuilt(f"the capture image could not be read: {error.strerror}")
        except ValueError as error:
            return unbuilt(str(error))
        if len(preview) > IMAGE_LIMIT:
            return unbuilt(f"the downscaled image is over the {IMAGE_LIMIT}-byte limit")
        width, height = _png_size(preview)
        body["image"] = {
            "built": True,
            "mime_type": "image/png",
            "width": width,
            "height": height,
            "max_edge": IMAGE_EDGE,
            "sha256": hashlib.sha256(preview).hexdigest(),
            "source_sha256": source_sha256,
        }
        return [{"data": base64.b64encode(preview).decode("ascii"), "mimeType": "image/png"}]

    def _preview(self, png: str) -> tuple[bytes, str]:
        """The downscaled PNG of the capture `png` and the source's SHA-256 (in the executor)."""
        assert self.thumbnail is not None
        path = Path(png)
        if path.stat().st_size > IMAGE_SOURCE_LIMIT:
            raise ValueError(f"the capture image is over the {IMAGE_SOURCE_LIMIT}-byte limit")
        source = path.read_bytes()
        return self.thumbnail(source, IMAGE_EDGE), hashlib.sha256(source).hexdigest()
