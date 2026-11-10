"""The Unreal Engine 5.6 consumer fixture (phase3.2_unreal-ue56-packed-preset items 2.8, 3.2,
3.3 and 3.5; `docs/architecture/08-export.md` §5.1 row 8).

UE 5.6 imports one published generation of the `Unreal Engine (Packed)` preset headlessly, on
the owner's machine (decision 028), in the owner's fixture project (default
`W:\\UE_Projects\\UzPainterFixture`, `UZP_UE_PROJECT`; the engine at `W:\\UE_5.6`,
`UZP_UE56_ROOT`). The project is created once by `ensure_project` and reused: its `Saved`,
`Intermediate` and `DerivedDataCache` live there (the project's own `UzFixtureDDC` graph keeps
the derived-data cache in the project, Zen is not launched). Nothing else is created outside
the repository.

- **Delivery adapter.** The generation-pinning route of `08-export.md` §5: the pointer
  `current.json` is read once, its receipt and every file are verified by size and SHA-256
  (`tools.consumers.gltf`'s reader), and only those verified bytes are staged into the project
  (`Import/<fixture>/<variant>/<generation>/`, verified again after writing) and imported. A
  fixed-name directory is never read, so an interrupted fixed-name copy cannot reach UE: the
  import consumes one complete generation or fails before UE starts.
- **Import.** `UnrealEditor-Cmd.exe <project> -run=pythonscript
  -script=tools/consumers/unreal_ue.py` (the Python Editor Script Plugin's commandlet),
  `-unattended -nullrhi`. The editor's own asset tools import each file (`AssetImportTask`).
  UE's settings as imported are recorded; then the binding is applied (BaseColor and Emissive
  sRGB, ORM linear, Normal as a DirectX normal map: `TC_Normalmap`, green not flipped), UE
  exports each texture's source through its own exporter, and one material binds BaseColor, the
  ORM's R/G/B to AO/Roughness/Metallic, the Normal and the Emissive with the sampler type each
  binding needs.
- **Judgement** (`judged`). Each texture's bound settings are the binding's; its size is the
  receipt's; the material reads back each link to its texture, output and sampler; for a PNG or
  TGA, UE's exported source equals the published file in decoded values (UE neither converted,
  flipped nor swizzled what it imported). A DDS's exported source is recorded, not judged: UE
  decodes the BC blocks itself.
- **Cook** (`cook`, `cooked_textures`). `-run=cook -targetplatform=Windows` cooks
  `/Game/UzFixture`; the report gives each cooked texture's pixel format, whether a DDS's top-mip
  BC blocks appear unchanged in the cooked data (the `cook` consumer gap: re-encoded or not) and
  the cook's errors.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from tools.consumers.gltf import Published, _json, _published, _read
from tools.parity.feasibility import png

REPO_ROOT = Path(__file__).resolve().parents[2]
UE_SCRIPT = Path(__file__).with_name("unreal_ue.py")
ENGINE_ROOT = Path(os.environ.get("UZP_UE56_ROOT", "W:/UE_5.6"))
PROJECT_DIR = Path(os.environ.get("UZP_UE_PROJECT", "W:/UE_Projects/UzPainterFixture"))
PROJECT_NAME = "UzPainterFixture"
DDC_GRAPH = "UzFixtureDDC"
CONTENT_ROOT = "/Game/UzFixture"
MANIFEST_SCHEMA = "uzpainter/unreal-consumer-fixture/1"
REPORT_SCHEMA = "uzpainter/unreal-consumer-report/1"
ENGINE_VERSION = {"MajorVersion": 5, "MinorVersion": 6}
EDITOR_TIMEOUT_S = 3600
COOK_TIMEOUT_S = 4 * 3600

PROJECT_FILES = {
    f"{PROJECT_NAME}.uproject": json.dumps(
        {
            "FileVersion": 3,
            "EngineAssociation": "5.6",
            "Category": "",
            "Description": "UzPainter UE 5.6 consumer fixture (tools/consumers/unreal.py)",
            "Plugins": [
                {"Name": "PythonScriptPlugin", "Enabled": True},
                {"Name": "EditorScriptingUtilities", "Enabled": True},
            ],
        },
        indent=1,
    )
    + "\n",
    "Config/DefaultEngine.ini": (
        "; The derived-data cache stays in this project (tools/consumers/unreal.py).\n"
        "[Zen]\n"
        "AutoLaunch=false\n"
        "\n"
        f"[{DDC_GRAPH}]\n"
        "Root=(Type=KeyLength, Length=120, Inner=AsyncPut)\n"
        "AsyncPut=(Type=AsyncPut, Inner=Hierarchy)\n"
        "Hierarchy=(Type=Hierarchical, Inner=Local)\n"
        'Local=(Type=FileSystem, Path="%GAMEDIR%DerivedDataCache")\n'
    ),
    "Config/DefaultGame.ini": (
        "[/Script/UnrealEd.ProjectPackagingSettings]\n"
        "bUseZenStore=False\n"
        f'+DirectoriesToAlwaysCook=(Path="{CONTENT_ROOT}")\n'
    ),
}

SLOTS = ("BaseColor", "OcclusionRoughnessMetallic", "Normal", "Emissive")
REQUIRED_SLOTS = SLOTS[:3]
SLOT_OF = re.compile(r"_(BaseColor|OcclusionRoughnessMetallic|Normal|Emissive)(?:_[A-Za-z0-9]+)?$")
# The binding of each map (08-export.md §4 and §5.1 row 8) as UE 5.6 settings and sampler types.
BINDINGS: dict[str, dict[str, dict[str, Any]]] = {
    "png": {
        "BaseColor": {"srgb": True, "compression": "TC_DEFAULT", "sampler": "color"},
        "OcclusionRoughnessMetallic": {
            "srgb": False,
            "compression": "TC_MASKS",
            "sampler": "masks",
        },
        "Normal": {"srgb": False, "compression": "TC_NORMALMAP", "sampler": "normal"},
        "Emissive": {"srgb": True, "compression": "TC_DEFAULT", "sampler": "color"},
    },
    "dds": {
        "BaseColor": {"srgb": True, "compression": "TC_BC7", "sampler": "color"},
        "OcclusionRoughnessMetallic": {
            "srgb": False,
            "compression": "TC_BC7",
            "sampler": "linear_color",
        },
        "Normal": {"srgb": False, "compression": "TC_NORMALMAP", "sampler": "normal"},
        "Emissive": {"srgb": True, "compression": "TC_BC7", "sampler": "color"},
    },
}
LINKS = {
    "BaseColor": [("RGB", "base_color")],
    "OcclusionRoughnessMetallic": [
        ("R", "ambient_occlusion"),
        ("G", "roughness"),
        ("B", "metallic"),
    ],
    "Normal": [("RGB", "normal")],
    "Emissive": [("RGB", "emissive_color")],
}
FORMATS = {"png": ("png", "tga"), "dds": ("dds",)}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


# ── The engine and the project ───────────────────────────────────────────────


def editor_cmd(engine: Path = ENGINE_ROOT) -> Path:
    return engine / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"


def engine_identity(engine: Path = ENGINE_ROOT) -> dict[str, Any]:
    """UE's own build record and the hashes of it and of the command-line editor."""
    version_path = engine / "Engine" / "Build" / "Build.version"
    version = json.loads(_read(version_path))
    if {k: version.get(k) for k in ENGINE_VERSION} != ENGINE_VERSION:
        raise ValueError(f"{engine} is not Unreal Engine 5.6: {version}")
    return {
        "root": engine.as_posix(),
        "version": "{MajorVersion}.{MinorVersion}.{PatchVersion}".format(**version),
        "changelist": version["Changelist"],
        "branch": version["BranchName"],
        "build_version_sha256": _sha(_read(version_path)),
        "editor_cmd_sha256": _sha(editor_cmd(engine).read_bytes()),
    }


def _lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def ensure_project(project: Path = PROJECT_DIR) -> dict[str, Any]:
    """The fixture project in `project`, created once: its files are written when absent and must
    otherwise begin with exactly these lines, blank lines aside (UE 5.6 rewrites
    `DefaultEngine.ini` with CRLF and blank lines and appends its own settings, such as a plugin's
    token); a changed file is refused, never overwritten."""
    created = []
    for relative, text in PROJECT_FILES.items():
        path = project / relative
        if path.exists():
            if _lines(path.read_text(encoding="utf-8"))[: len(_lines(text))] != _lines(text):
                raise ValueError(f"{path} is not the fixture's own file; refusing to change it")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        created.append(relative)
    return {"path": project.as_posix(), "created": created}


def _editor(
    engine: Path, project: Path, args: list[str], log: str, env: dict[str, str], timeout: int
) -> dict[str, Any]:
    logs = project / "Saved" / "Logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / f"{log}.log"
    command = [
        str(editor_cmd(engine)),
        str(project / f"{PROJECT_NAME}.uproject"),
        *args,
        "-unattended",
        "-nosplash",
        "-nopause",
        "-nosound",
        f"-ddc={DDC_GRAPH}",
        f"-abslog={log_path}",
    ]
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            env={**os.environ, **env},
            capture_output=True,
            timeout=timeout,
            check=False,
            # Below normal priority (inherited by UE's shader workers): never ahead of other work.
            creationflags=getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"UnrealEditor-Cmd could not complete: {error}") from error
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    return {
        "returncode": proc.returncode,
        "seconds": round(time.monotonic() - started, 1),
        "log": log_path.as_posix(),
        "log_text": text,
        "args": args,
    }


# ── The delivery adapter and the staging ────────────────────────────────────


def selected(published: Published, variant: str) -> dict[str, str]:
    """The published file of each slot for `variant` (PNG or TGA files, or DDS files)."""
    if variant not in FORMATS:
        raise ValueError(f"unknown variant {variant!r}")
    chosen: dict[str, str] = {}
    for name, entry in published.entries.items():
        if entry.get("format") not in FORMATS[variant]:
            continue
        match = SLOT_OF.search(Path(name).stem)
        if match is None:
            continue
        slot = match.group(1)
        if slot in chosen:
            raise ValueError(f"two published {slot} files: {chosen[slot]}, {name}")
        chosen[slot] = name
    if missing := [s for s in REQUIRED_SLOTS if s not in chosen]:
        raise ValueError(f"the generation has no {missing} file for the {variant} variant")
    return chosen


def stage(
    published: Published, names: dict[str, str], project: Path, fixture: str, variant: str
) -> Path:
    """The verified bytes of `names` written afresh into the project, each read back and checked
    against its receipt hash; the staging directory."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", fixture):
        raise ValueError(f"invalid fixture name {fixture!r}")
    folder = project / "Import" / fixture / variant / published.generation
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    for name in names.values():
        target = folder / Path(name).name
        target.write_bytes(published.files[name])
        if _sha(target.read_bytes()) != published.entries[name]["sha256"]:
            raise ValueError(f"the staged copy of {name} differs from its receipt")
    return folder


def request_of(folder: Path, names: dict[str, str], fixture: str, variant: str) -> dict[str, Any]:
    binding = BINDINGS[variant]
    files = []
    for slot in SLOTS:
        if slot in names:
            files.append(
                {
                    "slot": slot,
                    "path": str(folder / Path(names[slot]).name),
                    "asset": f"T_{slot}",
                    "binding": {
                        "srgb": binding[slot]["srgb"],
                        "compression": binding[slot]["compression"],
                        "flip_green_channel": False,
                    },
                }
            )
    samples = [{"slot": s, "sampler": binding[s]["sampler"]} for s in SLOTS if s in names]
    links = [
        {"slot": s, "output": output, "property": prop}
        for s in SLOTS
        if s in names
        for output, prop in LINKS[s]
    ]
    return {
        "destination": f"{CONTENT_ROOT}/{fixture.replace('-', '_')}/{variant}",
        "files": files,
        "material": {"name": "M_Fixture", "samples": samples, "links": links},
        "export_dir": str(folder / "ue-source-export"),
        "result": str(folder / "result.json"),
    }


def _manifest(path: Path, project: Path, engine: dict[str, Any]) -> tuple[dict[str, Any], str]:
    data = _read(path)
    manifest = _json(data)
    consumer = manifest.get("consumer", {})
    if manifest.get("schema") != MANIFEST_SCHEMA or consumer.get("engine") != "Unreal Engine":
        raise ValueError("unsupported Unreal consumer manifest identity")
    pinned = ("version", "changelist", "branch", "build_version_sha256", "editor_cmd_sha256")
    if any(consumer.get(key) != engine[key] for key in pinned):
        raise ValueError(f"the manifest pins another UE 5.6 build than {engine}")
    if Path(manifest.get("project_folder", "")) != project:
        raise ValueError(f"the manifest's project folder is not {project}")
    return manifest, _sha(data)


# ── The judgement ─────────────────────────────────────────────────────────────


def _decoded(data: bytes, file_format: str) -> np.ndarray:
    if file_format == "png":
        return png.decode(data).astype(np.int64)
    with Image.open(io.BytesIO(data)) as image:
        array = np.asarray(image)
    return (array if array.ndim == 3 else array[:, :, None]).astype(np.int64)


def round_trip(published: bytes, file_format: str, exported: Path) -> dict[str, Any]:
    """UE's exported source against the published file in decoded values: equal when every
    channel of the file equals UE's, and any channel UE adds is opaque alpha. UE stores an
    opaque RGB whose three channels are equal as a grey source (`ue_grey_source`): then each of
    the file's R, G and B must equal that grey."""
    ours = _decoded(published, file_format)
    theirs = _decoded(exported.read_bytes(), "png")
    depth_ours = _bit_depth(published, file_format)
    depth_theirs = _bit_depth(exported.read_bytes(), "png")
    result: dict[str, Any] = {
        "published_shape": list(ours.shape),
        "exported_shape": list(theirs.shape),
        "published_bit_depth": depth_ours,
        "exported_bit_depth": depth_theirs,
    }
    if ours.shape[:2] != theirs.shape[:2] or depth_ours != depth_theirs:
        result["equal"] = False
        return result
    channels = ours.shape[2]
    if theirs.shape[2] == 1 and channels == 3:
        theirs = np.repeat(theirs, 3, axis=2)
        result["ue_grey_source"] = True
    if theirs.shape[2] < channels:
        result["equal"] = False
        return result
    differing = int(np.count_nonzero(ours != theirs[:, :, :channels]))
    extra = theirs[:, :, channels:]
    opaque = int(np.count_nonzero(extra != (1 << depth_theirs) - 1))
    result.update(differing_samples=differing, non_opaque_added=opaque)
    result["equal"] = differing == 0 and opaque == 0
    return result


def _bit_depth(data: bytes, file_format: str) -> int:
    if file_format == "png":
        return int(data[24])
    return 8


def judged(
    result: dict[str, Any],
    published: Published,
    names: dict[str, str],
    variant: str,
) -> dict[str, Any]:
    """The checks of the module's docstring over UE's result; `failures` lists every miss."""
    failures: list[str] = []
    if result.get("status") == "refused":
        refused = [
            {"slot": slot, "file": result["textures"][slot]["file"]} for slot in result["refused"]
        ]
        failures = [f"{r['slot']}: UE 5.6 imported nothing from {r['file']}" for r in refused]
        return {"failures": failures, "textures": {}, "refused": refused}
    if result.get("status") != "imported":
        return {"failures": [f"UE import failed: {result.get('error')}"], "textures": {}}
    textures: dict[str, Any] = {}
    material_links = {link["property"]: link for link in result["material"]["links"]}
    for slot, name in names.items():
        entry = result["textures"][slot]
        expected = BINDINGS[variant][slot]
        bound = entry["as_bound"]
        checks = {
            "srgb": bound["srgb"] == expected["srgb"],
            "compression": bound["compression"] == expected["compression"],
            "green_not_flipped": bound["flip_green_channel"] is False,
            "size": bound["size"] == published.entries[name]["size"],
            "texture_class": bound["class"] == "Texture2D",
        }
        texture_path = entry["imported_object_paths"][0].split(".")[0]
        for output, prop in LINKS[slot]:
            link = material_links.get(prop, {})
            checks[f"material_{prop}"] = (
                str(link.get("texture", "")).split(".")[0] == texture_path
                and link.get("output") == output
                and link.get("sampler") == f"SAMPLERTYPE_{expected['sampler'].upper()}"
            )
        file_format = published.entries[name]["format"]
        exported = entry.get("source_export")
        trip: dict[str, Any] | None = None
        if exported and Path(exported).is_file():
            trip = round_trip(published.files[name], file_format, Path(exported))
        if file_format != "dds":
            checks["source_equals_published"] = bool(trip and trip["equal"])
        failures += [f"{slot}: {check}" for check, ok in checks.items() if not ok]
        textures[slot] = {
            "file": Path(name).name,
            "sha256": published.entries[name]["sha256"],
            "format": file_format,
            "receipt_colour_space": published.entries[name].get("colour_space"),
            "as_imported": entry["as_imported"],
            "as_bound": bound,
            "checks": checks,
            "source_round_trip": trip,
        }
    return {"failures": failures, "textures": textures, "material": result["material"]}


def run_fixture(
    export_root: Path,
    fixture: str,
    variant: str,
    manifest_path: Path,
    *,
    project: Path = PROJECT_DIR,
    engine: Path = ENGINE_ROOT,
) -> dict[str, Any]:
    """Pin, verify, stage and import one generation's `variant` files into UE 5.6; the report.
    Invalid input raises ValueError before UE starts."""
    identity = engine_identity(engine)
    manifest, manifest_sha = _manifest(manifest_path, project, identity)
    published = _published(export_root)
    names = selected(published, variant)
    gaps = [
        gap
        for entry in published.entries.values()
        for gap in entry.get("consumer_gaps", [])
        if entry.get("format") in FORMATS[variant]
    ]
    skipped_emissive = [
        s for s in published.skipped if "emissive" in str(s.get("file_name", "")).lower()
    ]
    if "Emissive" not in names and not skipped_emissive:
        raise ValueError("no Emissive file and the receipt does not report it skipped")
    project_state = ensure_project(project)
    folder = stage(published, names, project, fixture, variant)
    request = request_of(folder, names, fixture, variant)
    request_path = folder / "request.json"
    _write_json(request_path, request)
    run = _editor(
        engine,
        project,
        ["-run=pythonscript", f"-script={UE_SCRIPT}", "-nullrhi"],
        f"uzfixture-{fixture}-{variant}",
        {"UZP_UE_REQUEST": str(request_path)},
        EDITOR_TIMEOUT_S,
    )
    result_path = Path(request["result"])
    result = _json(_read(result_path)) if result_path.is_file() else {"status": "no result"}
    verdict = judged(result, published, names, variant)
    if run["returncode"] != 0:
        verdict["failures"].append(f"UnrealEditor-Cmd exited {run['returncode']}")
    report = {
        "schema": REPORT_SCHEMA,
        "fixture": fixture,
        "variant": variant,
        "status": "pass" if not verdict["failures"] else "fail",
        "failures": verdict["failures"],
        "engine": identity,
        "ue_engine_version": result.get("engine_version"),
        "manifest_sha256": manifest_sha,
        "manifest_fixture": manifest.get("fixture"),
        "project": project_state,
        "generation": published.generation,
        "receipt_sha256": published.receipt_sha256,
        "staged": folder.as_posix(),
        "destination": request["destination"],
        "import_method": "UnrealEditor-Cmd -run=pythonscript (AssetImportTask, automated)",
        "editor_seconds": run["seconds"],
        "editor_log": run["log"],
        "textures": verdict["textures"],
        "material": verdict.get("material"),
        "consumer_gaps": gaps,
        "skipped": [dict(s) for s in published.skipped],
        "runner_sha256": {
            "tools/consumers/unreal.py": _sha(Path(__file__).read_bytes()),
            "tools/consumers/unreal_ue.py": _sha(UE_SCRIPT.read_bytes()),
        },
    }
    if result.get("error"):
        report["ue_error"] = result["error"]
    if verdict.get("refused"):
        report["refused"] = verdict["refused"]
        report["ue_log_errors"] = sorted(
            {
                line[line.index("Error:") :].strip()
                for line in run["log_text"].splitlines()
                if "Error:" in line
            }
        )
    return report


def consume_generation(
    export_root: Path,
    fixture: str,
    manifest_path: Path,
    *,
    project: Path = PROJECT_DIR,
    engine: Path = ENGINE_ROOT,
) -> dict[str, Any]:
    """Item 3.5: UE imports every PNG of the selected generation through the pinning adapter, no
    binding applied; `files` maps each receipt path to the SHA-256 UE was given, and every
    imported texture's source, exported back by UE, equals its file in decoded values. A
    generation that does not verify raises ValueError before anything is staged."""
    identity = engine_identity(engine)
    _manifest(manifest_path, project, identity)
    published = _published(export_root)
    names = {n: n for n, e in published.entries.items() if e.get("format") == "png"}
    if len({Path(n).name.casefold() for n in names}) != len(names):
        raise ValueError("two published files share a base name")
    ensure_project(project)
    folder = stage(published, names, project, fixture, "any")
    request: dict[str, Any] = {
        "destination": f"{CONTENT_ROOT}/{fixture.replace('-', '_')}",
        "files": [
            {"slot": name, "path": str(folder / Path(name).name), "asset": f"T_{index}"}
            for index, name in enumerate(sorted(names))
        ],
        "export_dir": str(folder / "ue-source-export"),
        "result": str(folder / "result.json"),
    }
    request_path = folder / "request.json"
    _write_json(request_path, request)
    run = _editor(
        engine,
        project,
        ["-run=pythonscript", f"-script={UE_SCRIPT}", "-nullrhi"],
        f"uzfixture-{fixture}",
        {"UZP_UE_REQUEST": str(request_path)},
        EDITOR_TIMEOUT_S,
    )
    result_path = Path(request["result"])
    result: dict[str, Any] = (
        _json(_read(result_path)) if result_path.is_file() else {"status": "no result"}
    )
    failures = [] if run["returncode"] == 0 else [f"UnrealEditor-Cmd exited {run['returncode']}"]
    for name in names:
        entry = result.get("textures", {}).get(name)
        exported = entry.get("source_export") if entry else None
        if not exported or not Path(exported).is_file():
            failures.append(f"{name}: not imported")
        elif not round_trip(published.files[name], "png", Path(exported))["equal"]:
            failures.append(f"{name}: UE's source differs from the published file")
    status = result.get("status") if not failures else "fail"
    return {
        "status": status,
        "failures": failures,
        "generation": published.generation,
        "files": {name: published.entries[name]["sha256"] for name in sorted(names)},
        "staged": folder.as_posix(),
        "editor_seconds": run["seconds"],
        "ue_error": result.get("error"),
    }


# ── The cook ──────────────────────────────────────────────────────────────────


def dds_top_mip(data: bytes) -> bytes:
    """The top mip's BC blocks of a DX10 BC5/BC7 DDS (docs/DDS.md)."""
    if data[:4] != b"DDS " or data[84:88] != b"DX10":
        raise ValueError("not a DX10 DDS")
    height, width = int.from_bytes(data[12:16], "little"), int.from_bytes(data[16:20], "little")
    size = ((width + 3) // 4) * ((height + 3) // 4) * 16
    return data[148 : 148 + size]


PIXEL_FORMAT = re.compile(rb"PF_[A-Za-z0-9_]+")


def cook(
    *, project: Path = PROJECT_DIR, engine: Path = ENGINE_ROOT, log: str = "uzfixture-cook"
) -> dict[str, Any]:
    """Cook the project for Windows (`-run=cook -targetplatform=Windows`, every package under
    `/Game/UzFixture` by the project's `DirectoriesToAlwaysCook`); the cook's exit code, its
    summary line and every error line naming the fixture's content."""
    run = _editor(
        engine,
        project,
        ["-run=cook", "-targetplatform=Windows", "-nullrhi"],
        log,
        {},
        COOK_TIMEOUT_S,
    )
    errors = [
        line.strip()
        for line in run["log_text"].splitlines()
        if re.search(r"\bError:", line) and "UzFixture" in line
    ]
    summary = re.findall(r"Success - (\d+) error\(s\), (\d+) warning\(s\)", run["log_text"])
    return {
        "returncode": run["returncode"],
        "seconds": run["seconds"],
        "log": run["log"],
        "summary": [list(s) for s in summary],
        "uzfixture_errors": errors,
    }


def cooked_textures(report: dict[str, Any], *, project: Path = PROJECT_DIR) -> dict[str, Any]:
    """Per texture of a `run_fixture` report (`T_<slot>` under its destination), after `cook`: its
    cooked files, the pixel formats they name and, for a DDS, whether its top mip's BC blocks
    appear unchanged in the cooked data."""
    relative = str(report["destination"]).removeprefix("/Game/")
    cooked_dir = project / "Saved" / "Cooked" / "Windows" / PROJECT_NAME / "Content" / relative
    textures: dict[str, Any] = {}
    for slot, texture in report["textures"].items():
        files = sorted(cooked_dir.glob(f"T_{slot}.*")) if cooked_dir.is_dir() else []
        blob = b"".join(p.read_bytes() for p in files)
        entry: dict[str, Any] = {
            "files": {p.name: p.stat().st_size for p in files},
            "pixel_formats": sorted({m.decode() for m in PIXEL_FORMAT.findall(blob)}),
        }
        if texture["format"] == "dds":
            top = dds_top_mip((Path(report["staged"]) / texture["file"]).read_bytes())
            entry["dds_top_mip_bytes"] = len(top)
            entry["dds_top_mip_unchanged_in_cook"] = bool(files) and top in blob
        textures[slot] = entry
    return {"cooked_dir": cooked_dir.as_posix(), "textures": textures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="import one published generation")
    imp.add_argument("--export-root", type=Path, required=True)
    imp.add_argument("--fixture", required=True)
    imp.add_argument("--variant", choices=sorted(BINDINGS), required=True)
    imp.add_argument("--manifest", type=Path, required=True)
    imp.add_argument("--report", type=Path)
    sub.add_parser("project", help="create or check the fixture project")
    args = parser.parse_args()
    try:
        if args.command == "project":
            print(json.dumps(ensure_project()))
            return 0
        report = run_fixture(args.export_root, args.fixture, args.variant, args.manifest)
    except (ValueError, OSError, KeyError) as error:
        print(json.dumps({"error": str(error)}))
        return 1
    if args.report:
        _write_json(args.report, report)
    print(json.dumps({k: report[k] for k in ("status", "failures", "generation")}))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
