"""The instruction-sequence vocabulary, read from `painter_side.py` without importing it.

`painter_side.py` runs only inside Painter (it imports `substance_painter`), so the host reads its
literal top-level constants from the source to share one definition of the vocabulary.
"""

from __future__ import annotations

import ast
from functools import cache
from typing import Any

from tools.parity.recorder.session import PAINTER_SIDE


@cache
def painter_side_constants() -> dict[str, Any]:
    tree = ast.parse(PAINTER_SIDE.read_text(encoding="utf-8"))
    constants: dict[str, Any] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id.isupper()
        ):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    return constants


CONSTANTS = painter_side_constants()

CREATE: str = CONSTANTS["CREATE"]
INSERT_FILL: str = CONSTANTS["INSERT_FILL"]
SET_SOURCE: str = CONSTANTS["SET_SOURCE"]
SET_ACTIVE_CHANNELS: str = CONSTANTS["SET_ACTIVE_CHANNELS"]
SET_BLENDING_MODE: str = CONSTANTS["SET_BLENDING_MODE"]
SET_OPACITY: str = CONSTANTS["SET_OPACITY"]
SET_RESOLUTIONS: str = CONSTANTS["SET_RESOLUTIONS"]
CAMERA: str = CONSTANTS["CAMERA"]
CAMERA_PROPERTIES: tuple[str, ...] = CONSTANTS["CAMERA_PROPERTIES"]
SET_ENVIRONMENT: str = CONSTANTS["SET_ENVIRONMENT"]
SET_TONE_MAPPING: str = CONSTANTS["SET_TONE_MAPPING"]
GET_SOURCE: str = CONSTANTS["GET_SOURCE"]
GET_ACTIVE_CHANNELS: str = CONSTANTS["GET_ACTIVE_CHANNELS"]
GET_BLENDING_MODE: str = CONSTANTS["GET_BLENDING_MODE"]
GET_OPACITY: str = CONSTANTS["GET_OPACITY"]
GET_RESOLUTION: str = CONSTANTS["GET_RESOLUTION"]
