"""Local Painter bridge; exports stay in the native command's private work directory.

Only a scalar, input-free source on the authored full-UV plane is admitted. The native
caller compares decoded L/RGB and repeat exports before committing any project change.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import math
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit


def scalar_parameters(value: Any) -> dict[str, int | float | str]:
    """Refuse parameter shapes outside the observed scalar capture domain."""
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValueError("parameters must be an object")
    result: dict[str, int | float | str] = {}
    for key, item in value.items():
        if isinstance(item, bool):
            result[key] = int(item)
        elif (
            (isinstance(item, int) and -(1 << 63) <= item < (1 << 63))
            or (isinstance(item, float) and math.isfinite(item))
            or isinstance(item, str)
        ):
            result[key] = item
        else:
            raise ValueError(f"parameter {key}: only finite scalar values are supported")
    return result


def capture_request(value: Any) -> dict[str, Any]:
    """Accept one explicitly versioned ResourceID and scalar parameter overrides."""
    if not isinstance(value, dict) or set(value) != {"resource", "parameters"}:
        raise ValueError("request requires exactly resource and parameters")
    resource = value["resource"]
    if not isinstance(resource, str):
        raise ValueError("resource must be a versioned resource:// URL")
    parsed = urlsplit(resource)
    query = parse_qs(parsed.query, strict_parsing=True)
    if (
        parsed.scheme != "resource"
        or not parsed.netloc
        or not parsed.path
        or parsed.fragment
        or set(query) != {"version"}
        or len(query["version"]) != 1
        or not query["version"][0]
    ):
        raise ValueError("resource must be an exact versioned ResourceID")
    return {"resource": resource, "parameters": scalar_parameters(value["parameters"])}


class Remote:
    """Painter's documented localhost /run.json protocol; no arbitrary host option."""

    def __init__(self) -> None:
        self.initialized = False

    def call(self, operation: str, args: dict[str, Any] | None = None) -> Any:
        if not self.initialized:
            source = Path(__file__).with_name("painter_side.py").read_text(encoding="utf-8")
            self.send("q_snapshot = {}; exec(" + repr(source) + ", q_snapshot)")
            self.initialized = True
        return self.send(
            "q_snapshot['dispatch'](" + repr(operation) + ", " + repr(args or {}) + ")"
        )

    def send(self, source: str) -> Any:
        connection = http.client.HTTPConnection("localhost", 60041, timeout=120)
        try:
            body = json.dumps({"python": base64.b64encode(source.encode()).decode("ascii")})
            connection.request("POST", "/run.json", body, {"Content-Type": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                raise RuntimeError(f"Painter remote HTTP {response.status}")
            data = response.read()
            result = json.loads(data) if data.strip() else None
            if isinstance(result, dict) and "error" in result:
                raise RuntimeError(f"Painter remote: {result['error']}")
            return result
        finally:
            connection.close()

    def wait(self, operation: str, timeout: float = 120) -> None:
        deadline = time.monotonic() + timeout
        while not self.call(operation):
            if time.monotonic() >= deadline:
                raise RuntimeError("Painter readiness deadline exceeded")
            time.sleep(0.2)


def canonical_state(value: Any) -> str:
    """Compare observations without conflating integers, doubles or signed zero."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_readback(readback: Any, request: dict[str, Any]) -> dict[str, Any]:
    """Every capture assumption is checked against the actual source and layer."""
    if readback["channel_formats"] != {"User0": "L32F", "User1": "RGB32F"}:
        raise ValueError("capture channels changed native precision")
    if (
        readback["source_mode"] != "Split"
        or readback["projection_mode"] != "UV"
        or readback["active_channels"] != ["User0", "User1"]
    ):
        raise ValueError("capture layer is not the isolated split User0/User1 layer")
    if readback["projection"] != {
        "filtering": "Nearest",
        "wrapping": "RepeatNone",
        "scale_mode": "Factors",
        "scale": [1, 1],
        "rotation": 0,
        "offset": [0, 0],
    }:
        raise ValueError("capture projection changed")
    tree = readback["isolated_tree"]
    if tree != {
        "roots": [tree["fill"]],
        "fill": tree["fill"],
        "visible": True,
        "mask": False,
        "content_effects": [],
        "mask_effects": [],
    }:
        raise ValueError("capture layer tree is not isolated")
    if readback["sets"] != [{"name": "uzp_plane", "resolution": [128, 128], "has_uv_tiles": False}]:
        raise ValueError("capture texture set or resolution changed")
    sources = readback["sources"]
    if len(sources) != 2 or canonical_state(sources[0]) != canonical_state(sources[1]):
        raise ValueError("paired source state differs")
    source: dict[str, Any] = sources[0]
    if (
        source["resource"] != request["resource"]
        or source["inputs"] != []
        or source["outputs"] != [source["active_output"]]
        or not source["active_output"]
        or source["opacity"] != 1
        or source["blending"] != "Normal"
        or source["resolution"]["mode"] != "Auto"
        or source["resolution"]["log2_offset"] != 0
    ):
        raise ValueError("source lies outside the input-free scalar capture domain")
    if "resource_id" in source:
        identifier = source["resource_id"]
        if (
            not isinstance(identifier, dict)
            or set(identifier) != {"url", "context", "name", "version"}
            or any(not isinstance(value, str) or not value for value in identifier.values())
            or identifier["url"] != source["resource"]
        ):
            raise ValueError(
                "observed ResourceID must be complete and match the requested resource"
            )
    effective = scalar_parameters(source["parameters"])
    if canonical_state(effective) != canonical_state(source["parameters"]):
        raise ValueError("effective parameters must retain observed scalar types")
    if any(effective.get(key) != value for key, value in request["parameters"].items()):
        raise ValueError("effective parameters differ from requested overrides")
    source["parameters"] = effective
    return source


def export_config(directory: Path) -> dict[str, Any]:
    """Two raw document maps with no padding, dithering or precision conversion."""
    maps = []
    for name, channels in (("user0", "L"), ("user1", "RGB")):
        maps.append(
            {
                "fileName": name,
                "channels": [
                    {
                        "destChannel": c,
                        "srcChannel": c,
                        "srcMapType": "documentMap",
                        "srcMapName": name,
                    }
                    for c in channels
                ],
            }
        )
    return {
        "exportPath": directory.as_posix(),
        "exportShaderParams": False,
        "defaultExportPreset": "uzp_snapshot",
        "exportPresets": [{"name": "uzp_snapshot", "maps": maps}],
        "exportList": [{"rootPath": "uzp_plane"}],
        "exportParameters": [
            {
                "parameters": {
                    "fileFormat": "exr",
                    "bitDepth": "32f",
                    "dithering": False,
                    "paddingAlgorithm": "passthrough",
                }
            }
        ],
    }


def record(context: dict[str, Any], request: dict[str, Any], root: Path) -> dict[str, Any]:
    """Own one disposable project; never close a project present on connection."""
    remote = Remote()
    identity = remote.call("identity")
    if identity["project_open"]:
        raise RuntimeError("Painter already has an open project; close it before recording")
    if identity["OCIO"] or identity["PAINTER_ACE_CONFIG"]:
        raise RuntimeError("snapshot capture currently requires Painter Legacy colour management")
    remote.call("refresh")
    remote.wait("catalog_ready")
    matched = remote.call("lookup", request)
    if matched != [{"url": request["resource"], "type": "SUBSTANCE", "procedural": True}]:
        raise ValueError("exact procedural ResourceID is absent or ambiguous")
    owner = {key: identity[key] for key in ("pid", "version")}
    owned = False

    def still_owned() -> bool:
        observed = remote.call("identity")
        return bool(
            all(observed[k] == v for k, v in owner.items())
            and isinstance(observed["mesh"], str)
            and Path(observed["mesh"]).resolve() == Path(context["mesh_path"]).resolve()
        )

    try:
        owned = True
        remote.call("create", {"mesh_path": context["mesh_path"]})
        remote.wait("ready")
        if not still_owned():
            raise RuntimeError("Painter capture project ownership changed")
        remote.call("configure", request)
        remote.wait("ready")
        readback = remote.call("readback")
        source = validate_readback(readback, request)
        exports = []
        for index in (1, 2):
            if not still_owned():
                raise RuntimeError("Painter capture project ownership changed")
            directory = root / f"export{index}"
            directory.mkdir()
            config = export_config(directory)
            status = remote.call("export", config)
            if status["status"] != "Success":
                raise RuntimeError(f"Painter export failed: {status}")
            expected = {directory / "user0.exr", directory / "user1.exr"}
            reported = {Path(p) for p in status["files"]}
            if reported != expected or set(directory.iterdir()) != expected:
                raise RuntimeError("Painter reported unexpected export files")
            if any(p.is_symlink() or not p.is_file() for p in expected):
                raise RuntimeError("Painter export is not a regular private file")
            exports.append({"config": config, "result": status})
        if not still_owned() or canonical_state(remote.call("readback")) != canonical_state(
            readback
        ):
            raise RuntimeError("source state changed during capture")
        seed = source["parameters"].get("$randomseed", 0)
        if not isinstance(seed, int):
            raise ValueError("effective random seed is not an integer")
        pin = hashlib.sha256(source["resource"].encode("utf-8")).hexdigest()
        return {
            "schema": "uzpainter/procedural-capture/1",
            "recorder": {key: context.get(key) for key in ("bridge_sha256", "painter_side_sha256")},
            "identity": identity,
            "resource": source["resource"],
            "readback": readback,
            "exports": exports,
            "project_uuid": context["project_uuid"],
            "revision": context["revision"],
            "signature": {
                "asset": "uzasset://snapshot/" + pin,
                "version": "1",
                "params": source["parameters"],
                "preset": None,
                "seed": seed,
                "output": {
                    "id": source["active_output"],
                    "resolution": 128,
                    "format": "f32",
                    "colour_space": "raw",
                    "channels": 1,
                },
                "inputs": {},
                "mesh": {"class": "quad", "uv_tiles": 1},
                "settings": context["settings"],
            },
        }
    finally:
        if owned and still_owned():
            remote.wait("idle")
            if still_owned():
                remote.call("close", {"pid": owner["pid"], "mesh": context["mesh_path"]})


def main(argv: list[str]) -> int:
    """Native caller supplies private context, request and fresh output directory."""
    if len(argv) != 3:
        raise ValueError("bridge requires context.json request.json private-directory")
    context = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    request = capture_request(json.loads(Path(argv[1]).read_text(encoding="utf-8")))
    root = Path(argv[2]).resolve(strict=True)
    report = record(context, request, root)
    report["files"] = {
        f"export{i}/{name}.exr": hashlib.sha256(
            (root / f"export{i}/{name}.exr").read_bytes()
        ).hexdigest()
        for i in (1, 2)
        for name in ("user0", "user1")
    }
    (root / "capture.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
