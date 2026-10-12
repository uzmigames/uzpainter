"""UzmiGames pipeline scripts run inside Adobe Substance 3D Painter (decision 099).

The host (`tools.parity.recorder.script_run`) executes this source into a copy of the private
namespace of `painter_side.py`, right after it: the operation below registers into its
`OPERATIONS` (the same dictionary), while the names defined here never replace
`painter_side.py`'s own. No `substance_painter` symbol is used here; the script a step runs makes
its own calls. No private attribute, no shipped Painter source and no community MCP bridge is used.

`run_script` executes one script's exact bytes (base64, checked against their SHA-256) in a fresh
namespace and returns the `result` the script assigned. A script that reads its arguments from a
hard-coded path is given a namespace whose `open` maps exactly that one path to the recorder's
repointed copy of the arguments; every other path passes through to the builtin `open`.
"""

from __future__ import annotations

import base64
import builtins
import hashlib
import json
import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # At run time this name comes from the copy of `painter_side.py`'s namespace.
    from tools.parity.recorder.painter_side import OPERATIONS


def same_path(first: str, second: str) -> bool:
    return os.path.normcase(os.path.normpath(first)) == os.path.normcase(os.path.normpath(second))


def redirected_open(hard_coded: str, copy: str) -> Callable[..., Any]:
    """The builtin `open`, except that the one path `hard_coded` opens `copy` instead."""

    def open_file(file: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(file, (str, os.PathLike)) and same_path(os.fspath(file), hard_coded):
            file = copy
        return builtins.open(file, *args, **kwargs)

    return open_file


def run_script(args: dict[str, Any]) -> dict[str, Any]:
    """Run one script (`source`, base64 of its exact bytes) and return its `result` as JSON."""
    data = base64.b64decode(args["source"])
    if hashlib.sha256(data).hexdigest() != args["sha256"]:
        raise ValueError("the script received differs from its pinned SHA-256")
    namespace: dict[str, Any] = {"__name__": "uzp_pipeline_script", "__builtins__": builtins}
    if args.get("args_path") is not None:
        namespace["open"] = redirected_open(args["args_path"], args["args_copy"])
    exec(compile(data, args["file_name"], "exec", dont_inherit=True), namespace)
    if "result" not in namespace:
        raise RuntimeError(f"{args['file_name']} assigned no `result`")
    return {"result": json.loads(json.dumps(namespace["result"]))}


OPERATIONS["run_script"] = run_script
