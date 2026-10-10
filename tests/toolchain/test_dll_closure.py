"""DLL import closure (phase0.6_toolchain-hardware-slice, items 2.9 and 3.4).

Unit tests on synthetic PE32+ images: an unlisted DLL in the import closure fails the check and
names the DLL and its importer; a system DLL in the output folder fails; a Visual C++ runtime DLL
is shipped only as measured. The import parser is also checked against a real binary of this
repository (`thirdparty/dxc/bin/x64/dxil.dll`).
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from pathlib import Path

import pytest

from tools.toolchain.dll_closure import check_folder, is_system, main
from tools.toolchain.pe import PEError, parse_imports, read_imports

REPO_ROOT = Path(__file__).resolve().parents[2]
SECTION_RVA = 0x1000
SECTION_OFFSET = 0x200


def make_pe(imports: Sequence[str], delay: Sequence[str] = (), machine: int = 0x8664) -> bytes:
    """A minimal PE32+ image whose import and delay-load directories name `imports`/`delay`."""
    imp_size = 20 * (len(imports) + 1)
    delay_size = 32 * (len(delay) + 1) if delay else 0
    names = b""
    name_rvas: list[int] = []
    for dll in (*imports, *delay):
        name_rvas.append(SECTION_RVA + imp_size + delay_size + len(names))
        names += dll.encode("ascii") + b"\0"
    data = b"".join(struct.pack("<5I", 0, 0, 0, rva, 0) for rva in name_rvas[: len(imports)])
    data += b"\0" * 20
    if delay:
        data += b"".join(
            struct.pack("<8I", 1, rva, 0, 0, 0, 0, 0, 0) for rva in name_rvas[len(imports) :]
        )
        data += b"\0" * 32
    data += names
    raw_size = (len(data) + 0x1FF) & ~0x1FF

    dos = b"MZ" + b"\0" * 58 + struct.pack("<I", 0x40)
    coff = struct.pack("<HHIIIHH", machine, 1, 0, 0, 0, 240, 0x22)
    optional = bytearray(240)
    struct.pack_into("<H", optional, 0, 0x20B)
    struct.pack_into("<I", optional, 108, 16)
    struct.pack_into("<II", optional, 112 + 8 * 1, SECTION_RVA, imp_size)
    if delay:
        struct.pack_into("<II", optional, 112 + 8 * 13, SECTION_RVA + imp_size, delay_size)
    section = b".idata\0\0" + struct.pack(
        "<IIIIIIHHI", len(data), SECTION_RVA, raw_size, SECTION_OFFSET, 0, 0, 0, 0, 0x40000040
    )
    header = dos + b"PE\0\0" + coff + bytes(optional) + section
    return header.ljust(SECTION_OFFSET, b"\0") + data.ljust(raw_size, b"\0")


def _folder(root: Path, files: dict[str, bytes]) -> Path:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


def test_parse_load_time_and_delay_imports() -> None:
    image = make_pe(["KERNEL32.dll", "d3d12.dll"], delay=["dxgi.dll"])
    parsed = parse_imports(image)
    assert parsed.machine == 0x8664
    assert parsed.load_time == ("KERNEL32.dll", "d3d12.dll")
    assert parsed.delay_load == ("dxgi.dll",)


def test_parse_rejects_non_pe() -> None:
    with pytest.raises(PEError, match="MZ"):
        parse_imports(b"not a binary")
    truncated = make_pe(["KERNEL32.dll"])[:300]
    with pytest.raises(PEError):
        parse_imports(truncated)


def test_parse_real_binary() -> None:
    """The parser reads a real PE32+ DLL of the repository (DXC's validator)."""
    imports = read_imports(REPO_ROOT / "thirdparty/dxc/bin/x64/dxil.dll")
    assert "KERNEL32.dll" in imports.load_time
    assert all(is_system(name) for name in imports.load_time)


def test_allowlisted_folder_passes(tmp_path: Path) -> None:
    folder = _folder(
        tmp_path,
        {
            "UzPainter.exe": make_pe(
                ["KERNEL32.dll", "d3d12.dll", "api-ms-win-crt-heap-l1-1-0.dll"]
            ),
            "D3D12/D3D12Core.dll": make_pe(["ntdll.dll"], delay=["ext-ms-win-dxcore-l1-1-0.dll"]),
            "embree4.dll": make_pe(["tbb12.dll", "MSVCP140.dll", "KERNEL32.dll"]),
            "tbb12.dll": make_pe(["MSVCP140.dll", "KERNEL32.dll"]),
            "msvcp140.dll": make_pe(["KERNEL32.dll"]),
            "UzPainter.pdb": b"not a binary, ignored",
        },
    )
    report = check_folder(folder)
    assert report.problems == []
    assert report.ok and report.clean_machine_ready
    assert report.resolved_in_folder == {
        "msvcp140.dll": ["embree4.dll", "tbb12.dll"],
        "tbb12.dll": ["embree4.dll"],
    }
    assert len(report.binaries) == 5
    assert report.footprint == sum((folder / b.path).stat().st_size for b in report.binaries)


def test_unlisted_dll_in_closure_fails(tmp_path: Path) -> None:
    """3.4: an import that is neither shipped nor a Windows system DLL fails, naming both."""
    folder = _folder(
        tmp_path,
        {
            "UzPainter.exe": make_pe(["KERNEL32.dll", "libfoo.dll"]),
            "dxcompiler.dll": make_pe(["KERNEL32.dll"], delay=["libfoo.dll"]),
        },
    )
    report = check_folder(folder)
    assert not report.ok
    assert len(report.problems) == 1
    assert report.problems[0].startswith("libfoo.dll: imported by UzPainter.exe, dxcompiler.dll")
    assert main([str(folder)]) == 1


def test_system_dll_in_folder_fails(tmp_path: Path) -> None:
    """3.4: a Windows system DLL shipped in the output folder fails."""
    folder = _folder(
        tmp_path,
        {
            "UzPainter.exe": make_pe(["KERNEL32.dll", "dxgi.dll"]),
            "dxgi.dll": make_pe(["KERNEL32.dll"]),
        },
    )
    report = check_folder(folder)
    assert report.problems == [
        "dxgi.dll: Windows system DLL in the output folder (13-engine-integration.md "
        "section 5: system DLLs are never shipped)"
    ]


def test_unlisted_binary_in_folder_fails(tmp_path: Path) -> None:
    folder = _folder(
        tmp_path,
        {"UzPainter.exe": make_pe(["KERNEL32.dll"]), "extra.dll": make_pe(["KERNEL32.dll"])},
    )
    assert check_folder(folder).problems == [
        "extra.dll: binary in the output folder is not on the allowlist of "
        "13-engine-integration.md section 5"
    ]


def test_visual_cpp_runtime_only_as_measured(tmp_path: Path) -> None:
    """An imported runtime DLL that is absent is a clean-machine gap; a shipped runtime DLL that
    nothing imports fails the allowlist."""
    absent = _folder(tmp_path / "absent", {"embree4.dll": make_pe(["VCRUNTIME140.dll"])})
    report = check_folder(absent)
    assert report.ok and not report.clean_machine_ready
    assert report.missing_app_local == {"vcruntime140.dll": ["embree4.dll"]}
    assert main([str(absent)]) == 0
    assert main([str(absent), "--clean-machine"]) == 1

    unused = _folder(
        tmp_path / "unused",
        {"UzPainter.exe": make_pe(["KERNEL32.dll"]), "vcruntime140.dll": make_pe(["KERNEL32.dll"])},
    )
    assert check_folder(unused).problems == [
        "vcruntime140.dll: Visual C++ runtime DLL that no binary in the folder imports "
        "(13-engine-integration.md section 5: only as measured)"
    ]


def test_non_x64_binary_fails(tmp_path: Path) -> None:
    folder = _folder(tmp_path, {"UzPainter.exe": make_pe(["KERNEL32.dll"], machine=0xAA64)})
    assert check_folder(folder).problems == ["UzPainter.exe: machine 0xaa64 is not x64"]
