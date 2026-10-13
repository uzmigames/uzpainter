"""Link map of `UzPainter.exe` (phase0.6_toolchain-hardware-slice, item 2.8): the render core
and libc++ are linked statically.

Unit tests on synthetic log and map text; the integration test takes the session's fresh verbose
build (`tests/conftest.py`, which builds `painter` from an empty cache), relinks `UzPainter.exe`
with `/MAP` and inspects the map (skipped when zig is not on PATH).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tools.toolchain.link_map import (
    archive_members,
    find_link_command,
    inspect,
    map_build,
    relink_args,
)

if TYPE_CHECKING:
    from tests.conftest import FreshBuild

MAP_SAMPLE = """\
  Address         Publics by Value              Rva+Base               Lib:Object

 0001:00000000       main                       0000000140001000 f   main.obj
 0001:0012bca0       _ZN2uz9GetExeDirEv         000000014012cca0     uzrendercore:paths.obj
 0001:0012c000       _ZN2uz9DX12Device4InitEv   000000014012d000     uzrendercore:dx12_device.obj
 0001:0012c100       _ZN2uz4BeginEv   000000014012d100     uzrendercore:dx12_command_list.obj
 0001:0012c200       _ZN2uz4InitEv    000000014012d200     uzrendercore:shader_compiler.obj
 0001:00167500       _ZNSt12length_errorD1Ev    0000000140168500     c++abi:stdlib_stdexcept.obj
 0001:00168000       _ZNSt3__16chrono12steady_clock3nowEv 0000000140169000     c++:chrono.obj
 0002:00000010       __imp_CreateFileW          0000000140200010     kernel32:KERNEL32.dll
"""


def test_find_link_command_and_relink_args(tmp_path: Path) -> None:
    log = (
        "compile exe UzPainter Debug\n"
        "error: lld-link -lldmingw -NOLOGO -PDB:C:\\c\\o\\1\\other.pdb "
        "-OUT:C:\\c\\o\\1\\other.exe a.obj\n"
        "error: lld-link -lldmingw -NOLOGO -PDB:C:\\c\\o\\2\\UzPainter.pdb "
        "-OUT:C:\\c\\o\\2\\UzPainter.exe -IMPLIB:C:\\c\\o\\2\\UzPainter.lib "
        "C:\\c\\o\\3\\uzrendercore.lib main.obj\n"
    )
    args = find_link_command(log)
    assert args[-2:] == ["C:\\c\\o\\3\\uzrendercore.lib", "main.obj"]
    relinked = relink_args(args, tmp_path, tmp_path / "UzPainter.map")
    assert f"-OUT:{tmp_path / 'UzPainter.exe'}" in relinked
    assert f"-PDB:{tmp_path / 'UzPainter.pdb'}" in relinked
    assert f"-IMPLIB:{tmp_path / 'UzPainter.lib'}" in relinked
    assert relinked[-1] == f"-MAP:{tmp_path / 'UzPainter.map'}"
    with pytest.raises(ValueError, match=r"no lld-link command producing UzPainter\.exe"):
        find_link_command("error: lld-link -OUT:C:\\x\\other.exe a.obj\n")


def test_archive_members_and_inspection() -> None:
    members = archive_members(MAP_SAMPLE)
    assert members["uzrendercore"] == [
        "dx12_command_list.obj",
        "dx12_device.obj",
        "paths.obj",
        "shader_compiler.obj",
    ]
    assert members["c++"] == ["chrono.obj"]
    assert members["c++abi"] == ["stdlib_stdexcept.obj"]
    assert "main.obj" not in str(members)
    assert inspect(MAP_SAMPLE, ["KERNEL32.dll", "d3d12.dll"]) == []


def test_inspection_failures() -> None:
    no_core = "\n".join(line for line in MAP_SAMPLE.splitlines() if "uzrendercore" not in line)
    assert inspect(no_core, []) == ["uzrendercore.lib contributes no object to UzPainter.exe"]
    no_libcxx = "\n".join(line for line in MAP_SAMPLE.splitlines() if " c++:" not in line)
    assert inspect(no_libcxx, []) == [
        "libc++ archive c++.lib contributes no object to UzPainter.exe"
    ]
    assert inspect(MAP_SAMPLE, ["libc++.dll"]) == [
        "UzPainter.exe imports a C++ runtime DLL: libc++.dll"
    ]


def test_link_map_of_the_build(fresh_verbose_build: FreshBuild, tmp_path: Path) -> None:
    """2.8: the linker's own map of a fresh `zig build painter` shows the render core and libc++
    linked statically, and the executable imports no C++ runtime DLL."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH")
    report = map_build(
        fresh_verbose_build.log, fresh_verbose_build.prefix, tmp_path / "linkmap", zig
    )
    assert report.problems == []
    assert "uzrendercore.lib" in report.command_inputs
    assert {"c++.lib", "c++abi.lib"} <= set(report.command_inputs)
    assert len(report.members["uzrendercore"]) >= 10
    assert Path(report.map_path).stat().st_size > 0
