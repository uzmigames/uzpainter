"""The MCP tool registry (python/uzpainter_supervisor/registry.py; task
phase2.5_mcp-transport-registry items 2.1, 2.4-2.7, 2.9, 3.3, 3.6; decisions 158, 159).

Pure Python: the worker is a stand-in that lists tools and records every frame it is sent, so a
refusal "before admission" is checked as no `tools/call` frame for the tool and no ledger job. The
same checks through `UzPainter.exe --mcp` are in test_supervisor_transports.py.
"""

from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from python.uzpainter_supervisor.admission import Admission, contract
from python.uzpainter_supervisor.ledger import Ledger
from python.uzpainter_supervisor.registry import (
    CAPABILITY_META_KEY,
    Client,
    Manifest,
    ManifestError,
    Registry,
    summary,
)
from python.uzpainter_supervisor.roots import OUTSIDE, Roots

UUID = "6f1c2a6e-0000-4000-8000-000000000002"


def schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


TOOLS: list[dict[str, Any]] = [
    {
        "name": "set_resolution",
        "description": "Sets a texture set's resolution.",
        "inputSchema": schema(
            {
                "texture_set": {"type": "string", "x-uzpainter-ref": "texture_set"},
                "size": {"type": "integer", "minimum": 128, "maximum": 8192},
            },
            ["texture_set", "size"],
        ),
        "mutating": True,
        "long": False,
        "commit_point": None,
        "capability": [{"symbol": "substance_painter.textureset.TextureSet.set_resolution"}],
    },
    {
        "name": "layer_set",
        "description": "Sets a layer's fields.",
        "inputSchema": schema(
            {
                "uid": {"type": "integer", "minimum": 1, "x-uzpainter-ref": "node"},
                "blending": {"type": "string", "enum": ["Normal", "Multiply"]},
                "stack": {"type": "string", "x-uzpainter-ref": "stack"},
            },
            ["uid"],
        ),
        "mutating": True,
        "long": False,
        "commit_point": None,
        "capability": [],
    },
    {
        "name": "project_save",
        "description": "Saves.",
        "inputSchema": schema({"mode": {"type": "string", "enum": ["incremental", "full"]}}, []),
        "mutating": False,
        "long": False,
        "commit_point": None,
        "capability": [{"symbol": "substance_painter.project.save", "context": "any"}],
    },
    {
        "name": "bake_start",
        "description": "A tool whose operation is a release gap.",
        "inputSchema": schema({}, []),
        "mutating": True,
        "long": False,
        "commit_point": None,
        "capability": [{"symbol": "uzpainter.baking.bake_async", "context": "any"}],
    },
    {
        "name": "export",
        "description": "Exports.",
        "inputSchema": schema(
            {
                "config": {
                    "type": ["object", "string"],
                    "x-uzpainter-paths": {"exportPath": "export"},
                },
                "fixed_names": {
                    "type": "array",
                    "items": {"type": "string", "x-uzpainter-root": "export"},
                },
            },
            ["config"],
        ),
        "mutating": False,
        "long": False,
        "commit_point": None,
        "capability": [],
    },
    {
        "name": "project_open",
        "description": "Opens.",
        "inputSchema": schema(
            {"path": {"type": "string", "minLength": 1, "x-uzpainter-root": "project"}}, ["path"]
        ),
        "mutating": False,
        "long": False,
        "commit_point": None,
        "capability": [],
    },
    {
        "name": "run_python",
        "description": "Runs Python.",
        "inputSchema": schema({"code": {"type": "string"}}, ["code"]),
        "mutating": True,
        "long": False,
        "commit_point": None,
        "capability": [],
    },
    {
        "name": "capture",
        "description": "Captures.",
        "inputSchema": schema({}, []),
        "mutating": False,
        "long": False,
        "commit_point": None,
        "capability": [],
    },
    {
        "name": "inspect",
        "description": "A read that returns an image field.",
        "inputSchema": schema({}, []),
        "mutating": False,
        "long": False,
        "commit_point": None,
        "capability": [],
    },
]

MANIFEST = {
    "entries": [
        {
            "symbol": "substance_painter.textureset.TextureSet.set_resolution",
            "context": "any",
            "status": "supported",
        },
        {"symbol": "substance_painter.project.save", "context": "any", "status": "supported"},
        {
            "symbol": "uzpainter.baking.bake_async",
            "context": "any",
            "status": "release-gap",
            "notes": "owner phase3.4_baker-ao",
        },
    ]
}

SNAPSHOT = {
    "schema": "x",
    "revision": 5,
    "stacks": [
        {"texture_set": 1, "texture_set_name": "body", "stack": 2, "stack_name": ""},
        {"texture_set": 3, "texture_set_name": "head", "stack": 4, "stack_name": "hair"},
    ],
    "nodes": [{"uid": 10, "node": "layer"}, {"uid": 11, "node": "effect"}],
}

TRANSACTION = {
    "status": "committed",
    "returned": {},
    "created": [21],
    "hidden": [],
    "imported": ["res://a"],
    "modified": [10],
    "removed": [12],
    "skipped": [],
}


class FakeWorker:
    """Holds project `UUID` at revision 5 (or none); records every frame."""

    def __init__(self, open_project: bool = True) -> None:
        self.project_path: str | None = "C:/p/plane.uzp" if open_project else None
        self.project_uuid: str | None = UUID if open_project else None
        self.durable_revision: int | None = 5 if open_project else None
        self.project_epoch = 1
        self.frames: list[dict[str, Any]] = []
        self.tools = copy.deepcopy(TOOLS)
        self.reply: dict[str, Any] | None = None  # the next tools/call reply, when set

    async def wait_ready(self) -> None:
        return None

    def status(self) -> dict[str, Any]:
        return {"project": self.project_path, "crash_dir": "C:/Temp/crashes"}

    async def request(self, frame: dict[str, Any]) -> dict[str, Any]:
        self.frames.append(frame)
        method = frame["method"]
        if method == "tools/list":
            return {"id": "x", "result": {"tools": copy.deepcopy(self.tools)}}
        if method == "worker/operations":
            return {
                "id": "x",
                "result": {
                    "project_uuid": UUID,
                    "current_revision": 5,
                    "horizon_revision": 0,
                    "operations": [],
                    "unreadable": [],
                },
            }
        if frame["name"] == "snapshot_layer_tree":
            return {"id": "x", "result": copy.deepcopy(SNAPSHOT), "committed_revision": 5}
        if self.reply is not None:
            reply, self.reply = self.reply, None
            return {"id": "x", **reply}
        if "idempotency_key" in frame:
            assert self.durable_revision is not None
            self.durable_revision += 1
            return {
                "id": "x",
                "result": {**TRANSACTION, "revision": self.durable_revision},
                "committed_revision": self.durable_revision,
                "admission": "executed",
                "request_hash": "h",
            }
        return {"id": "x", "result": {"arguments": frame["arguments"]}}


def tool_calls(worker: FakeWorker, name: str | None = None) -> list[dict[str, Any]]:
    return [
        frame
        for frame in worker.frames
        if frame["method"] == "tools/call"
        and frame["name"] != "snapshot_layer_tree"
        and (name is None or frame["name"] == name)
    ]


def jobs(ledger: Ledger) -> int:
    with sqlite3.connect(ledger.path) as db:
        count = db.execute("SELECT count(*) FROM job").fetchone()[0]
    db.close()
    assert isinstance(count, int)
    return count


def make(
    tmp_path: Path,
    *,
    open_project: bool = True,
    http: bool = False,
    roots: Roots | None = None,
    manifest: dict[str, Any] | None = None,
) -> tuple[FakeWorker, Ledger, Registry]:
    worker = FakeWorker(open_project)
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    admission = Admission(worker, ledger)
    registry = Registry(
        worker,
        admission,
        Manifest.from_document(manifest or MANIFEST),
        roots=roots,
        http=http,
    )
    return worker, ledger, registry


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


STDIO = Client("stdio")


def test_schema_violations_are_rejected_before_admission(tmp_path: Path) -> None:
    """3.3, 2.4: out-of-bound numbers, unknown enum members, wrong types and unknown arguments
    fail `invalid_arguments` with the argument and the rule, never the value, and reach neither the
    worker nor the ledger."""
    worker, ledger, registry = make(tmp_path)

    async def scenario() -> None:
        for arguments, rule in (
            ({"texture_set": "body", "size": 64, "expected_revision": 5}, "minimum"),
            ({"texture_set": "body", "size": 9000}, "maximum"),
            ({"texture_set": "body", "size": "big"}, "type"),
            ({"texture_set": "body", "size": 512, "bogus": 1}, "additionalProperties"),
            ({"texture_set": "body"}, "required"),
            ({"texture_set": "body", "size": 512, "expected_revision": -1}, "minimum"),
        ):
            reply = await registry.call("set_resolution", arguments, STDIO, None)
            error = reply.body["error"]
            assert error["code"] == "invalid_arguments", reply.body
            assert [e["rule"] for e in error["details"]["errors"]] == [rule], error
            assert "9000" not in json.dumps(error) and "big" not in json.dumps(error)
            assert reply.body["receipt"]["job_id"] is None
        enum = await registry.call("project_save", {"mode": "bogus"}, STDIO, None)
        assert enum.body["error"]["details"]["errors"][0]["argument"] == "/mode"
        assert enum.body["error"]["details"]["errors"][0]["rule"] == "enum"
        assert "bogus" not in json.dumps(enum.body["error"])
        limit = await registry.call("job_list", {"limit": 0}, STDIO, None)
        assert limit.body["error"]["code"] == "invalid_arguments"
        timeout = await registry.call("wait_idle", {}, STDIO, None)
        assert timeout.body["error"]["details"]["errors"][0]["rule"] == "required"
        ok = await registry.call(
            "set_resolution", {"texture_set": "body", "size": 8192}, STDIO, None
        )
        assert ok.body["result"]["status"] == "committed"

    run(scenario())
    assert len(tool_calls(worker)) == 1 and jobs(ledger) == 1


def test_dangling_object_references_are_rejected_before_admission(tmp_path: Path) -> None:
    """3.3, 2.4: a uid, texture set or stack that names nothing in the committed revision fails
    `invalid_arguments` (`dangling_reference`); with no project open every reference dangles."""
    worker, ledger, registry = make(tmp_path)

    async def scenario() -> None:
        for arguments, argument in (
            ({"uid": 99}, "/uid"),
            ({"uid": 10, "stack": "nope"}, "/stack"),
        ):
            reply = await registry.call("layer_set", arguments, STDIO, None)
            [error] = reply.body["error"]["details"]["errors"]
            assert error["argument"] == argument and error["reason"] == "dangling_reference"
        missing = await registry.call(
            "set_resolution", {"texture_set": "legs", "size": 512}, STDIO, None
        )
        assert missing.body["error"]["details"]["errors"][0]["argument"] == "/texture_set"
        assert tool_calls(worker) == []
        for arguments in ({"uid": 11}, {"uid": 10, "stack": "hair"}):
            assert "result" in (await registry.call("layer_set", arguments, STDIO, None)).body

    run(scenario())
    assert len(tool_calls(worker, "layer_set")) == 2 and jobs(ledger) == 2
    # The snapshot is read once per project, revision and epoch.
    snapshots = [f for f in worker.frames if f.get("name") == "snapshot_layer_tree"]
    assert len(snapshots) == 2  # revision 5, then 6 after the first commit

    closed_worker, closed_ledger, closed = make(tmp_path / "closed", open_project=False)
    reply = run(closed.call("layer_set", {"uid": 10}, STDIO, None))
    assert "no project is open" in reply.body["error"]["details"]["errors"][0]["message"]
    assert tool_calls(closed_worker) == [] and jobs(closed_ledger) == 0


def test_the_omission_rule_at_the_mcp_boundary(tmp_path: Path) -> None:
    """3.6, 2.5, decision 158: without key and precondition the supervisor generates the key and
    resolves the precondition, returned in the receipt for retries; with a precondition only it
    generates the key; a key without its precondition is refused before admission."""
    worker, ledger, registry = make(tmp_path)

    async def scenario() -> None:
        generated = (await registry.call("layer_set", {"uid": 10}, STDIO, None)).body
        receipt = generated["receipt"]
        assert receipt["key_source"] == "supervisor" and receipt["idempotency_key"].startswith(
            "sup-"
        )
        assert receipt["expected_revision"] == 5
        [frame] = tool_calls(worker)
        assert frame["idempotency_key"] == receipt["idempotency_key"]
        assert frame["expected_revision"] == 5
        only = (
            await registry.call("layer_set", {"uid": 10, "expected_revision": 6}, STDIO, None)
        ).body
        assert (
            only["receipt"]["key_source"] == "supervisor"
            and only["receipt"]["expected_revision"] == 6
        )
        refused = (
            await registry.call("layer_set", {"uid": 10, "idempotency_key": "k-1"}, STDIO, None)
        ).body
        assert refused["error"]["code"] == "invalid_arguments"
        assert refused["error"]["details"]["errors"][0]["argument"] == "/expected_revision"
        assert "idempotency_key" not in refused["receipt"] and refused["receipt"]["job_id"] is None
        keyed = (
            await registry.call(
                "layer_set",
                {"uid": 10, "idempotency_key": "k-1", "expected_revision": 7},
                STDIO,
                None,
            )
        ).body
        assert keyed["receipt"]["key_source"] == "client"

    run(scenario())
    assert [frame.get("idempotency_key") for frame in tool_calls(worker)][2] == "k-1"
    assert len(tool_calls(worker)) == 3 and jobs(ledger) == 3


def test_release_gap_operations_fail_with_capability_gap(tmp_path: Path) -> None:
    """2.9: a tool whose declared operation is a release gap (or missing from the manifest) fails
    `capability_gap` before admission and stays listed with its status; the same tool becomes
    callable when the manifest entry changes, with no registry change."""
    worker, ledger, registry = make(tmp_path)
    listed = {tool["name"]: tool for tool in run(registry.list_tools())}
    assert listed["bake_start"]["meta"][CAPABILITY_META_KEY]["status"] == "release-gap"
    assert listed["project_save"]["meta"][CAPABILITY_META_KEY]["status"] == "available"
    assert listed["layer_set"]["meta"] is None
    reply = run(registry.call("bake_start", {}, STDIO, None)).body
    assert reply["error"]["code"] == "capability_gap"
    [operation] = reply["error"]["details"]["operations"]
    assert operation["symbol"] == "uzpainter.baking.bake_async"
    assert operation["notes"] == "owner phase3.4_baker-ao"
    assert tool_calls(worker) == [] and jobs(ledger) == 0

    landed = copy.deepcopy(MANIFEST)
    landed["entries"][2]["status"] = "pending-evidence"
    worker2, _, registry2 = make(tmp_path / "landed", manifest=landed)
    assert (
        run(registry2.call("bake_start", {}, STDIO, None)).body["result"]["status"] == "committed"
    )
    assert len(tool_calls(worker2, "bake_start")) == 1

    unlisted = {"entries": [e for e in MANIFEST["entries"] if "set_resolution" not in e["symbol"]]}
    worker3, _, registry3 = make(tmp_path / "unlisted", manifest=unlisted)
    reply = run(registry3.call("set_resolution", {"texture_set": "body", "size": 512}, STDIO, None))
    assert reply.body["error"]["code"] == "capability_gap"  # fails closed
    assert tool_calls(worker3) == []


def test_a_malformed_manifest_is_refused(tmp_path: Path) -> None:
    """2.9: the manifest is the build's; a missing, unreadable or malformed one is an error."""
    with pytest.raises(ManifestError):
        Manifest.load(tmp_path / "missing.json")
    documents: list[Any] = [
        [],
        {"entries": [{"symbol": "a", "context": "any"}]},
        {"entries": [{"symbol": "a", "context": "any", "status": "supported"}] * 2},
    ]
    for document in documents:
        with pytest.raises(ManifestError):
            Manifest.from_document(document)


def test_results_carry_the_contract_fields_and_a_one_line_summary(tmp_path: Path) -> None:
    """2.5, 2.4: every forwarded result carries revision, committed_revision, job_id, changed,
    created, hidden, imported, skipped and warnings; a raising script's committed calls are its
    partial changes; the text is a one-line summary."""
    worker, _, registry = make(tmp_path)
    reply = run(registry.call("layer_set", {"uid": 10}, STDIO, None))
    body = reply.body
    assert body["revision"] == 5 and body["committed_revision"] == 6
    assert body["job_id"] == body["receipt"]["job_id"] is not None
    assert body["changed"] == [10, 12] and body["created"] == [21]
    assert body["imported"] == ["res://a"] and body["hidden"] == body["skipped"] == []
    assert body["warnings"] == []
    assert reply.summary == (
        f"layer_set: committed; revision 5 -> 6; changed 2, created 1, imported 1; "
        f"job {body['job_id']}"
    )

    worker.reply = {
        "error": {
            "code": "script_failed",
            "message": "the script raised",
            "details": {
                "committed": [
                    {**TRANSACTION, "created": [30], "modified": [], "removed": []},
                    {**TRANSACTION, "created": [31], "modified": [30], "removed": []},
                ],
                "last_committed_revision": 8,
            },
        },
        "committed_revision": 8,
    }
    failed = run(registry.call("run_python", {"code": "raise"}, STDIO, None))
    assert failed.body["created"] == [30, 31] and failed.body["changed"] == [30]
    assert failed.body["committed_revision"] == 8
    assert failed.summary == "run_python: error script_failed: the script raised"

    read = run(registry.call("project_save", {}, STDIO, None)).body
    assert read["job_id"] is None and read["created"] == [] and read["revision"] == 6
    warned = contract({"result": {"warnings": ["w"]}, "receipt": {"revision": 1}})
    assert warned["warnings"] == ["w"] and warned["committed_revision"] is None
    assert summary("x", {"result": {}}) == "x: ok"


def test_images_are_content_blocks_only_for_capture(tmp_path: Path) -> None:
    """2.4: `capture`'s image becomes an image content block; another tool's never does."""
    worker, _, registry = make(tmp_path)
    image = {"mimeType": "image/png", "data": "iVBORw0KGgo="}
    worker.reply = {"result": {"receipt": "r", "image": image}}
    captured = run(registry.call("capture", {}, STDIO, None))
    assert captured.images == [image] and "image" not in captured.body["result"]
    worker.reply = {"result": {"image": image}}
    other = run(registry.call("inspect", {}, STDIO, None))
    assert other.images == [] and other.body["result"]["image"] == image


def test_http_lease_is_explicit_and_survives_a_reconnect(tmp_path: Path) -> None:
    """2.6, 3.2 (lease part), decision 159: in HTTP mode a mutating call needs the session's owner;
    `lease_acquire` binds it and takes the lease; another owner is refused `lease_held`; a client
    that reconnects names its owner again and keeps its lease; `lease_release` ends it."""
    worker, ledger, registry = make(tmp_path, http=True)
    names = {tool["name"] for tool in run(registry.list_tools())}
    assert {"lease_acquire", "lease_release", "lease_status"} <= names
    _, _, stdio = make(tmp_path / "stdio")
    assert "lease_acquire" not in {tool["name"] for tool in run(stdio.list_tools())}

    async def scenario() -> None:
        a, b = Client("http"), Client("http")
        unowned = (await registry.call("layer_set", {"uid": 10}, a, None)).body
        assert unowned["error"]["code"] == "lease_required" and tool_calls(worker) == []
        reserved = (await registry.call("lease_acquire", {"owner": "stdio:1"}, a, None)).body
        assert reserved["error"]["code"] == "invalid_arguments"
        bad = (await registry.call("lease_acquire", {"owner": "a b"}, a, None)).body
        assert bad["error"]["details"]["errors"][0]["rule"] == "pattern"
        taken = (await registry.call("lease_acquire", {"owner": "agent-a"}, a, None)).body
        assert taken["result"]["owner"] == "agent-a"
        assert taken["result"]["lease"]["holder"] == "agent-a"
        assert "result" in (await registry.call("layer_set", {"uid": 10}, a, None)).body
        held = (await registry.call("lease_acquire", {"owner": "agent-b"}, b, None)).body
        assert held["error"]["code"] == "lease_held"
        assert held["error"]["details"]["holder"] == "agent-a"
        assert b.owner is None
        # agent-a reconnects: a new session, the same owner.
        again = Client("http")
        status = (await registry.call("lease_status", {}, again, None)).body["result"]
        assert status["owner"] is None and status["lease"]["holder"] == "agent-a"
        assert (
            "result"
            in (await registry.call("lease_acquire", {"owner": "agent-a"}, again, None)).body
        )
        assert "result" in (await registry.call("layer_set", {"uid": 10}, again, None)).body
        released = (await registry.call("lease_release", {}, again, None)).body
        assert released["result"] == {"released": "agent-a"} and again.owner is None
        assert (
            "result" in (await registry.call("lease_acquire", {"owner": "agent-b"}, b, None)).body
        )
        assert (await registry.call("lease_release", {}, a, None)).body["result"][
            "released"
        ] == "agent-a"

    run(scenario())
    assert len(tool_calls(worker, "layer_set")) == 2
    registry.close()
    assert ledger.lease(UUID) is None


def test_roots_canonicalise_path_arguments_and_scrub_results(tmp_path: Path) -> None:
    """2.7: path arguments reach the worker in canonical absolute form under their root, a path
    outside is refused without echoing it, and path fields outside the roots are scrubbed from
    results (`run_python`'s own result is exempt)."""
    project, export = tmp_path / "projects", tmp_path / "exports"
    project.mkdir()
    export.mkdir()
    roots = Roots.parse(f"project={project};export={export}")
    worker, _, registry = make(tmp_path, roots=roots)

    async def scenario() -> None:
        opened = (await registry.call("project_open", {"path": "sub/../a.uzp"}, STDIO, None)).body
        assert opened["result"]["arguments"]["path"] == str(project.resolve() / "a.uzp")
        outside = str(tmp_path / "elsewhere.uzp")
        refused = (await registry.call("project_open", {"path": outside}, STDIO, None)).body
        assert refused["error"]["code"] == "path_outside_roots"
        assert refused["error"]["details"] == {
            "argument": "/path",
            "root": "project",
            "reason": "the path lies outside the project root",
        }
        assert "elsewhere" not in json.dumps(refused)
        config = {"exportPath": "out", "exportList": []}
        exported = (
            await registry.call("export", {"config": config, "fixed_names": ["fixed"]}, STDIO, None)
        ).body["result"]["arguments"]
        assert exported["config"]["exportPath"] == str(export.resolve() / "out")
        assert exported["fixed_names"] == [str(export.resolve() / "fixed")]
        as_text = (await registry.call("export", {"config": json.dumps(config)}, STDIO, None)).body[
            "result"
        ]["arguments"]
        assert json.loads(as_text["config"])["exportPath"] == str(export.resolve() / "out")
        escape = {"exportPath": "..\\..\\Windows"}
        refused = (await registry.call("export", {"config": escape}, STDIO, None)).body
        assert refused["error"]["details"]["argument"] == "/config/exportPath"
        assert "Windows" not in json.dumps(refused)
        worker.reply = {"result": {"path": "C:\\Windows\\x", "directory": str(export / "d")}}
        scrubbed = (await registry.call("inspect", {}, STDIO, None)).body
        assert scrubbed["result"] == {"path": OUTSIDE, "directory": str(export / "d")}
        assert scrubbed["receipt"]["project"] == OUTSIDE  # C:/p/plane.uzp
        status = (await registry.call("supervisor_status", {}, STDIO, None)).body["result"]
        assert status["crash_dir"] == OUTSIDE and status["ledger"] == OUTSIDE
        worker.reply = {"result": {"result": {"path": "C:\\Windows"}, "stdout": "C:\\Windows"}}
        script = (await registry.call("run_python", {"code": "1"}, STDIO, None)).body
        assert script["result"]["result"] == {"path": "C:\\Windows"}
        assert script["receipt"]["project"] == OUTSIDE

    run(scenario())
    assert [frame["name"] for frame in tool_calls(worker)].count("project_open") == 1
