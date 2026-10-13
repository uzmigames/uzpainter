"""The MCP resources and prompts of the supervisor (`docs/architecture/11-mcp-server.md` §2; task
phase2.6_mcp-typed-tool-families, decision 165).

Resources are JSON documents (`application/json`) read through the registry, so each read follows
the tools' rules: a project resource is a read of the committed revision (no lease), its paths are
scrubbed under `--roots`, and it names its project (`project_uuid`) and `revision`. Reading a
project resource with no project open fails (MCP error -32002), as does an unknown URI.

- `uzpainter://capabilities`: the capability manifest (`compat_profile`, every entry) and each
  tool's status with its gaps (`Registry.capability_table`);
- `uzpainter://project/manifest`: the committed revision's project manifest (pipe method
  `worker/manifest`);
- `uzpainter://project/recipe`, `.../layers`, `.../resources`: its recipe dump (`project_recipe`),
  layer-tree snapshot (`snapshot_layer_tree`) and resource entries (`resource_list`);
- `uzpainter://assets/parity`: the asset library with each asset's parity status: none yet, and
  `uzpainter.assets.search` is a release gap until the procedural families land;
- `uzpainter://jobs/{job_id}` (the resource template): a ledger job (`job_status`);
- `uzpainter://ledger`: the ledger's newest jobs (`job_list`).

The prompts are UzmiGames-authored templates (`PROMPTS`): the stack JSON of `sync_stack`, the
smart-material configuration of `apply_smart`, a baking preset of `bake_apply_preset` and an export
`json_config` of `export`. Each takes no argument and returns one user message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .registry import Client, Registry

RESOURCE_NOT_FOUND = -32002
JSON = "application/json"
JOBS_PREFIX = "uzpainter://jobs/"
LEDGER_LIMIT = 50


class ResourceError(Exception):
    """A read that cannot be answered: an unknown URI, no project open, or a failed read."""

    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.data = data


@dataclass(frozen=True)
class Listed:
    uri: str
    name: str
    description: str


RESOURCES = (
    Listed(
        "uzpainter://capabilities",
        "capabilities",
        "The capability manifest (every symbol's status) and each tool's status with its gaps.",
    ),
    Listed(
        "uzpainter://project/manifest",
        "project-manifest",
        "The open project's manifest at its committed revision.",
    ),
    Listed(
        "uzpainter://project/recipe",
        "project-recipe",
        "The recipe dump of the committed revision: every output-determining field and its digest.",
    ),
    Listed(
        "uzpainter://project/layers",
        "project-layers",
        "The layer-tree snapshot of the committed revision (every node's uid, kind, name, place).",
    ),
    Listed(
        "uzpainter://project/resources",
        "project-resources",
        "The project's resource entries: name, SHA-256, URL, usage, group and whether bound.",
    ),
    Listed(
        "uzpainter://assets/parity",
        "assets-parity",
        "The UzPainter asset library with each asset's parity status.",
    ),
    Listed("uzpainter://ledger", "ledger", "The ledger's newest jobs with their receipts' state."),
)
JOB_TEMPLATE = Listed(
    "uzpainter://jobs/{job_id}", "job", "One ledger job: its status, progress or terminal state."
)
# The project resources and the read-only worker tool behind each.
PROJECT_TOOLS = {
    "uzpainter://project/recipe": "project_recipe",
    "uzpainter://project/layers": "snapshot_layer_tree",
    "uzpainter://project/resources": "resource_list",
}

STACK_TEMPLATE = {
    "title": "<root group name: sync_stack rebuilds the root group of this name>",
    "groups": [
        {"key": "base", "name": "Base", "mask": None},
        {"key": "detail", "name": "Detail", "mask": "<mask image name>", "replace_height": False},
    ],
    "layers": [
        {
            "group": "base",
            "name": "Base colour",
            "base": [0.5, 0.5, 0.5],
            "rough": 0.6,
            "metal": 0.0,
        },
        {
            "group": "detail",
            "name": "Worn edges",
            "mask": "<mask image name>",
            "base_tex": "<image name>",
            "height": 0.02,
            "op": 1.0,
        },
    ],
}
SMART_TEMPLATE = {
    "layers": [
        {
            "name": "<layer name>",
            "color": [0.5, 0.5, 0.5],
            "rough": 0.6,
            "height": 0.0,
            "op": 1.0,
            "blend": "Normal",
            "mask": {
                "type": "smart_mask",
                "name": "<smart mask name>",
                "tiling": 1.0,
                "params": {},
                "levels": [0.0, 1.0, 1.0],
            },
        }
    ]
}
BAKING_TEMPLATE = {
    "texture_set": "<texture set name>",
    "enabled": True,
    "bakers": ["<mesh map usage, e.g. Normal, AO, Curvature, ID>"],
    "uv_tiles": [1001],
    "curvature_method": "<curvature method>",
    "common": {"<common baking parameter>": "<value>"},
    "per_baker": {"<mesh map usage>": {"<baker parameter>": "<value>"}},
}
EXPORT_TEMPLATE = {
    "exportPath": "<folder inside the export root>",
    "defaultExportPreset": "<shipped preset id (export_presets_list)>",
    "exportList": [{"rootPath": "<texture set name>"}],
    "exportParameters": [
        {
            "parameters": {
                "fileFormat": "png",
                "bitDepth": "16",
                "sizeLog2": 11,
                "paddingAlgorithm": "infinite",
            }
        }
    ],
}


@dataclass(frozen=True)
class Prompt:
    name: str
    description: str
    text: str


def _prompt(intro: str, template: dict[str, Any], notes: str) -> str:
    return f"{intro}\n\n```json\n{json.dumps(template, indent=2)}\n```\n\n{notes}"


PROMPTS = (
    Prompt(
        "stack_json_template",
        "The stack JSON sync_stack rebuilds a root group from.",
        _prompt(
            "Write the stack JSON for `sync_stack` (the `painter_layer_stack.py sync` format).",
            STACK_TEMPLATE,
            "Groups and the layers of a group are listed bottom to top. Each layer is a fill layer "
            "whose active channels are the ones it names: `base` (sRGB, 0-1, or 0-255 when any "
            "component is above 1) or `base_tex` (an image name), `rough`, `metal`, `spec`, "
            "`height`, and `op` (the BaseColor opacity, 1 when absent). A `mask` names a PNG "
            "image `<name>.png` of `masks_dir`; `replace_height` blends a group's Height as "
            "Normal. Other root groups are hidden, never deleted, unless `keep_visible` names a "
            "prefix of theirs.",
        ),
    ),
    Prompt(
        "smart_json_template",
        "The smart-material configuration apply_smart takes (a release gap of this build).",
        _prompt(
            "Write the smart-material configuration for `apply_smart` (the `painter_layer_stack.py "
            "smart` format).",
            SMART_TEMPLATE,
            "`mask.type` is `smart_mask` or `grunge`; `levels` is [in_min, in_max, gamma]. Smart "
            "materials and masks are a release gap of this build (phase3.6_smart-presets-"
            "projections): `apply_smart` answers capability_gap until they land.",
        ),
    ),
    Prompt(
        "baking_preset_template",
        "A baking preset for bake_configure and bake_apply_preset (a release gap of this build).",
        _prompt(
            "Write a baking preset for `bake_configure` / `bake_apply_preset`.",
            BAKING_TEMPLATE,
            "Bakers are mesh map usages; `common` and `per_baker` hold the baking parameters by "
            "their documented names. Native baking is a release gap of this build "
            "(phase3.5_embree-bakers): the baking tools answer capability_gap until it lands.",
        ),
    ),
    Prompt(
        "export_config_template",
        "An export json_config for the export tool.",
        _prompt(
            "Write Painter's export `json_config` for the `export` tool (or call it with `preset` "
            "and `output_dir`).",
            EXPORT_TEMPLATE,
            "`exportList[].rootPath` is a texture set (or `<texture set>/<stack>`); "
            "`exportParameters` rules apply in order, the last matching one winning. "
            "`dry_run: true` returns the plan and the files without writing.",
        ),
    ),
)


class Resources:
    """The resources and prompts of one supervisor, over its registry."""

    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    async def read(self, uri: str, client: Client) -> dict[str, Any]:
        """The JSON document of `uri`; `ResourceError` when it cannot be read."""
        registry = self.registry
        if uri == "uzpainter://capabilities":
            return {
                "compat_profile": registry.manifest.compat_profile,
                "tools": await registry.capability_table(),
                "entries": registry.manifest.document.get("entries", []),
            }
        if uri == "uzpainter://assets/parity":
            operations = registry.manifest.operations(
                [{"symbol": "uzpainter.assets.search", "context": "any"}]
            )
            return {"assets": [], "status": operations[0]["status"], "operations": operations}
        if uri == "uzpainter://ledger":
            jobs: dict[str, Any] = registry.admission.job_list(LEDGER_LIMIT)["result"]
            return jobs
        if uri.startswith(JOBS_PREFIX):
            job_id = uri[len(JOBS_PREFIX) :]
            body = registry.admission.job_status(job_id)
            if "error" in body:
                raise ResourceError(f"no job {job_id}", {"uri": uri})
            result: dict[str, Any] = body["result"]
            return result
        if uri == "uzpainter://project/manifest":
            worker = registry.worker
            await worker.wait_ready()
            reply = await worker.request({"method": "worker/manifest"})
            document = reply.get("result")
            if not isinstance(document, dict) or document.get("project_uuid") is None:
                raise ResourceError("no project is open", {"uri": uri})
            scrubbed: dict[str, Any] = (
                registry.roots.scrub(document) if registry.roots is not None else document
            )
            return scrubbed
        tool = PROJECT_TOOLS.get(uri)
        if tool is None:
            raise ResourceError(f"unknown resource {uri}", {"uri": uri})
        reply_body = (await registry.call(tool, {}, client, None)).body
        error = reply_body.get("error")
        if isinstance(error, dict):
            raise ResourceError(str(error.get("message")), {"uri": uri, "code": error.get("code")})
        receipt = reply_body.get("receipt") or {}
        return {
            "project_uuid": receipt.get("project_uuid"),
            "revision": reply_body.get("committed_revision"),
            "content": reply_body.get("result"),
        }

    @staticmethod
    def prompt(name: str) -> Prompt:
        for prompt in PROMPTS:
            if prompt.name == name:
                return prompt
        raise ResourceError(f"unknown prompt {name}", {"name": name})
