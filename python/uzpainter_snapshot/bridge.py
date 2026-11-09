"""Local Painter bridge; exports stay in the native command's private work directory.

A request of exactly `resource` and `parameters` captures a scalar, input-free, single-output
source on the authored full-UV plane; the native caller compares decoded L/RGB and repeat
exports before committing any project change. A request that also names `preset` and `inputs`
(decision 412 §3) captures every listed output of that state, each through the same paired
L32F and RGB32F channels, with the state's presets and its single and multiple output contexts.
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


def capture_inputs(value: Any) -> dict[str, dict[str, Any]]:
    """Image-input plugs: a working-space colour, an existing bitmap file or Painter's removal."""
    if not isinstance(value, dict):
        raise ValueError("inputs must be an object")
    result: dict[str, dict[str, Any]] = {}
    for name, plug in value.items():
        if not isinstance(name, str) or not name or not isinstance(plug, dict) or len(plug) != 1:
            raise ValueError("each input is named and plugged with exactly color, bitmap or remove")
        if "color" in plug:
            color = plug["color"]
            if (
                not isinstance(color, list)
                or len(color) != 3
                or any(isinstance(c, bool) or not isinstance(c, (int, float)) for c in color)
                or not all(math.isfinite(c) for c in color)
            ):
                raise ValueError(f"input {name}: color must be three finite numbers")
            result[name] = {"color": [float(c) for c in color]}
        elif "bitmap" in plug:
            path = plug["bitmap"]
            if not isinstance(path, str) or not (Path(path).is_absolute() and Path(path).is_file()):
                raise ValueError(f"input {name}: bitmap must be an absolute path to a file")
            result[name] = {"bitmap": path}
        elif plug.get("remove") is True:
            result[name] = {"remove": True}
        else:
            raise ValueError(f"input {name}: plug with exactly color, bitmap or remove")
    return result


def capture_request(value: Any) -> dict[str, Any]:
    """Accept one explicitly versioned ResourceID and scalar parameter overrides, and for a
    multi-output capture a preset name (or null) and image-input plugs (possibly none)."""
    multi = isinstance(value, dict) and set(value) == {"resource", "parameters", "preset", "inputs"}
    if not isinstance(value, dict) or (set(value) != {"resource", "parameters"} and not multi):
        raise ValueError("request requires exactly resource and parameters (and preset and inputs)")
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
    result: dict[str, Any] = {
        "resource": resource,
        "parameters": scalar_parameters(value["parameters"]),
    }
    if multi:
        preset = value["preset"]
        if preset is not None and (not isinstance(preset, str) or not preset):
            raise ValueError("preset must be null or a nonempty preset name")
        if preset is not None and result["parameters"]:
            # Painter's preset sets parameters itself: overrides beside it would be ambiguous.
            raise ValueError("a preset capture takes no parameter overrides")
        result["preset"] = preset
        result["inputs"] = capture_inputs(value["inputs"])
    return result


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


def stage_bitmaps(request: dict[str, Any], root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    """The Painter-side request with each bitmap copied privately, and SHA-256 by staged path."""
    staged = dict(request)
    staged["inputs"] = {}
    hashes: dict[str, str] = {}
    copies: dict[Path, Path] = {}
    for name, plug in sorted(request["inputs"].items()):
        if "bitmap" not in plug:
            staged["inputs"][name] = plug
            continue
        original = Path(plug["bitmap"])
        if original not in copies:
            data = original.read_bytes()
            directory = root / "inputs"
            directory.mkdir(exist_ok=True)
            copy = directory / f"{len(copies)}{original.suffix.lower()}"
            copy.write_bytes(data)
            copies[original] = copy
            hashes[copy.as_posix()] = hashlib.sha256(data).hexdigest()
        staged["inputs"][name] = {"bitmap": copies[original].as_posix()}
    return staged, hashes


def signature_inputs(
    source: dict[str, Any], staged: dict[str, Any], readback: dict[str, Any], hashes: dict[str, str]
) -> dict[str, Any]:
    """The signature's plugged inputs (decision 412 §3), from what Painter read back: a bitmap by
    the SHA-256 of its file and its colour space, a colour by its working value; an unplugged
    input (its `get_source` raised) is absent. Each read-back source must be the requested plug."""
    observed = source["input_sources"]
    if set(observed) != set(source["inputs"]) or set(staged["inputs"]) - set(observed):
        raise ValueError("requested image inputs are not the source's image inputs")
    urls = {url: path for path, url in readback["bitmaps"].items()}
    result: dict[str, Any] = {}
    for name, value in observed.items():
        plug = staged["inputs"].get(name)
        # Unplugged: `get_source` raised, or returned a bitmap whose `resource_id` raises.
        unplugged = set(value) == {"raised"} or (
            value.get("class") == "SourceBitmap" and "resource_id" in value
        )
        if plug is None:
            if not unplugged:
                raise ValueError(f"input {name} is plugged; the request leaves it unplugged")
            continue
        if "color" in plug or "remove" in plug:
            if value.get("class") != "SourceUniformColor":
                raise ValueError(f"input {name} does not read back a uniform colour")
            working = value["working"]
            if "color" in plug and canonical_state(working) != canonical_state(plug["color"]):
                raise ValueError(f"input {name} reads back another working colour than requested")
            result[name] = {"working_colour": working}
        else:
            path = urls.get(value.get("resource"))
            if value.get("class") != "SourceBitmap" or path != plug["bitmap"] or unplugged:
                raise ValueError(f"input {name} does not read back the requested bitmap")
            result[name] = {"bitmap_sha256": hashes[path], "colour_space": value["colour_space"]}
    return result


def validate_multi(readback: Any, request: dict[str, Any]) -> dict[str, Any]:
    """The multi-output state: the isolated paired layer of the legacy capture, sources naming
    the requested resource with at least one output, and the requested overrides effective."""
    if readback["channel_formats"] != {"User0": "L32F", "User1": "RGB32F"}:
        raise ValueError("capture channels changed native precision")
    if (
        readback["source_mode"] != "Split"
        or readback["projection_mode"] != "UV"
        or readback["active_channels"] != ["User0", "User1"]
        or readback["projection"]
        != {
            "filtering": "Nearest",
            "wrapping": "RepeatNone",
            "scale_mode": "Factors",
            "scale": [1, 1],
            "rotation": 0,
            "offset": [0, 0],
        }
    ):
        raise ValueError("capture layer is not the isolated split User0/User1 layer")
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
    identifier = source.get("resource_id")
    if (
        source["resource"] != request["resource"]
        or not source["outputs"]
        or source["active_output"] not in source["outputs"]
        or source["opacity"] != 1
        or source["blending"] != "Normal"
        or source["resolution"]["mode"] != "Auto"
        or source["resolution"]["log2_offset"] != 0
        or not isinstance(identifier, dict)
        or set(identifier) != {"url", "context", "name", "version"}
        or any(not isinstance(v, str) or not v for v in identifier.values())
        or identifier["url"] != source["resource"]
    ):
        raise ValueError("source lies outside the multi-output capture domain")
    if request["preset"] is not None and request["preset"] not in source["presets"]:
        raise ValueError("the requested preset is not in the source's preset list")
    effective = scalar_parameters(source["parameters"])
    if canonical_state(effective) != canonical_state(source["parameters"]):
        raise ValueError("effective parameters must retain observed scalar types")
    if any(effective.get(key) != value for key, value in request["parameters"].items()):
        raise ValueError("effective parameters differ from requested overrides")
    return source


def without_output(readback: dict[str, Any]) -> str:
    """A readback with its sources' active output left out, canonically."""
    copy = json.loads(json.dumps(readback))
    for source in copy["sources"]:
        source.pop("active_output")
    return canonical_state(copy)


def check_contexts(
    contexts: Any, source: dict[str, Any], presets: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The preset parameters (paired, scalar, typed) and the contexts' consistency with the
    captured state: the material source reads the same parameters and input sources."""
    # The remote endpoint's JSON need not keep the presets' order: compared as names.
    if not isinstance(presets, dict) or sorted(presets) != sorted(source["presets"]):
        raise ValueError("preset parameters were not read for exactly the source's presets")
    observed: dict[str, Any] = {}
    for name, pair in presets.items():
        if len(pair) != 2 or canonical_state(pair[0]) != canonical_state(pair[1]):
            raise ValueError(f"paired sources read different parameters after preset {name}")
        if canonical_state(scalar_parameters(pair[0])) != canonical_state(pair[0]):
            raise ValueError(f"preset {name} gives parameters outside the scalar typed domain")
        observed[name] = pair[0]
    material = contexts["material"]
    if canonical_state(material["parameters"]) != canonical_state(source["parameters"]) or (
        canonical_state(material["input_sources"]) != canonical_state(source["input_sources"])
    ):
        raise ValueError("the material source of the same state reads another state")
    if not all(value in source["outputs"] for value in material["output_mapping"].values()):
        raise ValueError("the material output mapping names an output the source does not list")
    return observed, contexts


def record_outputs(
    context: dict[str, Any], request: dict[str, Any], root: Path, remote: Remote
) -> dict[str, Any]:
    """Every listed output of one state, inside the owned project; see `record_multi`."""
    staged, hashes = stage_bitmaps(request, root)
    remote.call("configure", staged)
    remote.wait("ready")
    readback = remote.call("readback")
    source = validate_multi(readback, request)
    inputs = signature_inputs(source, staged, readback, hashes)
    base = without_output(readback)
    seed = source["parameters"].get("$randomseed", 0)
    if not isinstance(seed, int):
        raise ValueError("effective random seed is not an integer")
    pin = hashlib.sha256(source["resource"].encode("utf-8")).hexdigest()
    captures = []
    exports = []
    for index, output in enumerate(source["outputs"]):
        remote.call("set_output", {"output": output})
        remote.wait("ready")
        observed = remote.call("readback")
        if without_output(observed) != base or any(
            s["active_output"] != output for s in observed["sources"]
        ):
            raise RuntimeError("selecting an output changed the captured state")
        for repeat in (1, 2):
            directory = root / f"output{index}-export{repeat}"
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
            exports.append({"output": output, "config": config, "result": status})
        for channels, name in ((1, "user0"), (3, "user1")):
            captures.append(
                {
                    "output": output,
                    "file": f"output{index}-export1/{name}.exr",
                    "repeat": f"output{index}-export2/{name}.exr",
                    "signature": {
                        "asset": "uzasset://snapshot/" + pin,
                        "version": "1",
                        "params": source["parameters"],
                        "preset": request["preset"],
                        "seed": seed,
                        "output": {
                            "id": output,
                            "resolution": 128,
                            "format": "f32",
                            "colour_space": "raw",
                            "channels": channels,
                        },
                        "inputs": inputs,
                        "mesh": {"class": "quad", "uv_tiles": 1},
                        "settings": context["settings"],
                    },
                }
            )
    remote.call("set_output", {"output": source["active_output"]})
    remote.wait("ready")
    if canonical_state(remote.call("readback")) != canonical_state(readback):
        raise RuntimeError("restoring the active output did not restore the captured state")
    presets = remote.call("preset_parameters")
    remote.wait("ready")
    if canonical_state(remote.call("readback")) != canonical_state(readback):
        raise RuntimeError("reading the presets did not restore the captured state")
    contexts = remote.call("contexts", staged)
    remote.wait("ready")
    if canonical_state(remote.call("readback")) != canonical_state(readback):
        raise RuntimeError("reading the output contexts changed the captured state")
    preset_parameters, observed_contexts = check_contexts(contexts, source, presets)
    return {
        "schema": "uzpainter/procedural-capture/2",
        "request": request,
        "readback": readback,
        "exports": exports,
        "captures": captures,
        "preset_parameters": preset_parameters,
        "contexts": observed_contexts,
        "bitmaps": hashes,
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
    if "inputs" in request:
        # A multi-output source is a Substance material (decision 412: a fill's material source),
        # which need not carry the PROCEDURAL usage.
        if [{k: m[k] for k in ("url", "type")} for m in matched] != [
            {"url": request["resource"], "type": "SUBSTANCE"}
        ]:
            raise ValueError("exact Substance ResourceID is absent or ambiguous")
    elif matched != [{"url": request["resource"], "type": "SUBSTANCE", "procedural": True}]:
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
        if "inputs" in request:
            report = record_outputs(context, request, root, remote)
            if not still_owned():
                raise RuntimeError("Painter capture project ownership changed")
            report.update(
                {
                    "recorder": {
                        key: context.get(key) for key in ("bridge_sha256", "painter_side_sha256")
                    },
                    "identity": identity,
                    "resource": request["resource"],
                    "project_uuid": context["project_uuid"],
                    "revision": context["revision"],
                }
            )
            return report
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
    if "captures" in report:
        names = [c[key] for c in report["captures"] for key in ("file", "repeat")]
    else:
        names = [f"export{i}/{name}.exr" for i in (1, 2) for name in ("user0", "user1")]
    report["files"] = {n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in names}
    (root / "capture.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
