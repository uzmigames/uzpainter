"""`substance_painter.js.evaluate`: the documented `alg.*` whitelist (10 §3; decision 107;
`python/FACADE.md` §6).

UzPainter has no JavaScript engine. `evaluate(js_code)` accepts exactly one whitelisted `alg.*`
expression: a property read or a call whose arguments are JSON literals, with an optional
trailing semicolon. It is parsed into a typed native call and returns the call's value, as
Painter returns the evaluation's JSON. Anything else (another `alg` member, several statements,
operators, identifiers or JavaScript-only literals as arguments) raises `UnsupportedInUzPainter`
before any native call, so nothing changes. A whitelisted call given the wrong arguments raises
`RuntimeError`, Painter's documented error for a failed evaluation.

- `alg.version.painter`: `uzpainter.application.version()`.
- `alg.project.isOpen()`, `alg.project.name()`: `uzpainter.project.is_open()`, `.name()`.
- `alg.project.saveAndClose([mode])`: the facade's `project.save(mode)`, then `close()`.
- `alg.shaders.instances()`, `parameters(id[, group])`, `setParameters(id, params[, options])`,
  `updateShaderInstance(id, url)`: `uzpainter.render.shader`, NotYetSupported until
  phase2.3_realtime-preview.
- `alg.mapexport.channelIdentifiers()`, `convertedMapIdentifiers()`, `meshMapIdentifiers()`:
  the identifier lists of the JavaScript API documentation.
- `alg.mapexport.save`, `saveChannelMap`, `saveMeshMap`, `saveConvertedMap`: NotYetSupported, as
  no golden records a JavaScript export (decision 107).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import uzpainter

EXPRESSION = re.compile(
    r"\s*(?P<path>alg(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\s*(?:\((?P<args>.*)\))?\s*;?\s*", re.DOTALL
)

# The channel, converted-map and mesh-map identifiers of the JavaScript API documentation.
CHANNEL_IDENTIFIERS = [
    "basecolor", "height", "specular", "opacity", "emissive", "displacement", "glossiness",
    "roughness", "anisotropylevel", "anisotropyangle", "transmissive", "scattering",
    "reflection", "ior", "metallic", "normal", "ambientOcclusion", "diffuse", "specularlevel",
    "blendingmask",
]  # fmt: skip
CONVERTED_MAP_IDENTIFIERS = [
    "1/ior", "ao_mixed", "diffuse", "f0", "glossiness", "glossiness2", "normal",
    "normal_directx", "reflection", "specular", "unity4diff", "unity4gloss",
]  # fmt: skip
MESH_MAP_IDENTIFIERS = [
    "normal_base", "world_space_normals", "id", "ambient_occlusion", "curvature", "position",
    "thickness",
]  # fmt: skip


def _save_and_close(mode: str = "Incremental") -> None:
    modes = {"Incremental": uzpainter.project.ProjectSaveMode.Incremental,
             "Full": uzpainter.project.ProjectSaveMode.Full}  # fmt: skip
    if mode not in modes:
        raise RuntimeError(f"alg.project.saveAndClose: unknown save mode {mode!r}")
    from uzpainter_facade import project

    project.save(modes[mode])
    project.close()


def _export_gap(name: str) -> Callable[..., Any]:
    def call(*args: Any) -> Any:
        raise uzpainter.NotYetSupported(
            f"alg.mapexport.{name}: no Tier 0 golden records a JavaScript map export, so its "
            "MapInfo semantics are unproven; use substance_painter.export.export_project_textures "
            "(decision 107)"
        )

    return call


def _identifiers(values: list[str]) -> Callable[..., Any]:
    def call(*context: Any) -> Any:
        if context:
            raise uzpainter.NotYetSupported(
                "the identifiers of one texture set or stack are not recorded; call it without "
                "arguments (decision 107)"
            )
        return list(values)

    return call


# (minimum, maximum) argument counts and the typed call of each whitelisted expression; None for
# a property read.
WHITELIST: dict[str, tuple[tuple[int, int] | None, Callable[..., Any]]] = {
    "alg.version.painter": (None, lambda: uzpainter.application.version()),
    "alg.project.isOpen": ((0, 0), lambda: uzpainter.project.is_open()),
    "alg.project.name": ((0, 0), lambda: uzpainter.project.name()),
    "alg.project.saveAndClose": ((0, 1), _save_and_close),
    "alg.shaders.instances": ((0, 0), lambda: uzpainter.render.shader.parameters()),
    "alg.shaders.parameters": ((1, 2), lambda *a: uzpainter.render.shader.parameters(*a)),
    "alg.shaders.setParameters": ((2, 3), lambda *a: uzpainter.render.shader.set_parameters(*a)),
    "alg.shaders.updateShaderInstance": (
        (2, 2),
        lambda *a: uzpainter.render.shader.set_parameters(*a),
    ),
    "alg.mapexport.save": ((2, 3), _export_gap("save")),
    "alg.mapexport.saveChannelMap": ((3, 4), _export_gap("saveChannelMap")),
    "alg.mapexport.saveMeshMap": ((3, 4), _export_gap("saveMeshMap")),
    "alg.mapexport.saveConvertedMap": ((3, 4), _export_gap("saveConvertedMap")),
    "alg.mapexport.channelIdentifiers": ((0, 1), _identifiers(CHANNEL_IDENTIFIERS)),
    "alg.mapexport.convertedMapIdentifiers": ((0, 0), _identifiers(CONVERTED_MAP_IDENTIFIERS)),
    "alg.mapexport.meshMapIdentifiers": ((0, 1), _identifiers(MESH_MAP_IDENTIFIERS)),
}


def _unsupported(js_code: str, reason: str) -> Exception:
    error: Exception = uzpainter.UnsupportedInUzPainter(
        "substance_painter.js.evaluate",
        f"{reason}: {js_code!r}; UzPainter evaluates only the documented alg.* whitelist with "
        "JSON-literal arguments",
        "the substance_painter Python API, or uzpainter.export and uzpainter.render",
    )
    return error


def evaluate(js_code: str) -> Any:
    """Evaluate one whitelisted `alg.*` expression (see the module documentation)."""
    match = EXPRESSION.fullmatch(js_code)
    if match is None:
        raise _unsupported(js_code, "not a single alg.* property or call")
    path, text = match.group("path"), match.group("args")
    if path not in WHITELIST:
        raise _unsupported(js_code, f"{path} is not in the whitelist")
    arity, call = WHITELIST[path]
    if arity is None:
        if text is not None:
            raise _unsupported(js_code, f"{path} is a property, not a function")
        return call()
    if text is None:
        raise _unsupported(js_code, f"{path} is a function: call it")
    try:
        args = json.loads(f"[{text}]") if text.strip() else []
    except json.JSONDecodeError as error:
        raise _unsupported(js_code, f"the arguments are not JSON literals ({error.msg})") from None
    low, high = arity
    if not low <= len(args) <= high:
        raise RuntimeError(f"{path}: expected {low} to {high} arguments, got {len(args)}")
    return call(*args)
