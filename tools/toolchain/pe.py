"""Import tables of Windows PE32+ binaries (`13-engine-integration.md` §5).

Reads the DLL names a binary imports through its import directory (load-time imports) and its
delay-load import directory, straight from the file; no Windows SDK tool is needed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

PE32_PLUS = 0x20B
MACHINE_AMD64 = 0x8664
IMPORT_DIRECTORY = 1
DELAY_IMPORT_DIRECTORY = 13
BINARY_SUFFIXES = (".exe", ".dll", ".pyd")


class PEError(ValueError):
    """The file is not a well-formed PE32+ image."""


@dataclass(frozen=True)
class Section:
    virtual_address: int
    virtual_size: int
    raw_offset: int
    raw_size: int


@dataclass(frozen=True)
class Imports:
    """The DLL names (as spelled in the file) a binary imports at load time and delay-loads."""

    machine: int
    load_time: tuple[str, ...]
    delay_load: tuple[str, ...]


def _u16(data: bytes, offset: int) -> int:
    return int(struct.unpack_from("<H", data, offset)[0])


def _u32(data: bytes, offset: int) -> int:
    return int(struct.unpack_from("<I", data, offset)[0])


def _rva_to_offset(rva: int, sections: list[Section]) -> int:
    for s in sections:
        size = max(s.virtual_size, s.raw_size)
        if s.virtual_address <= rva < s.virtual_address + size:
            offset = rva - s.virtual_address + s.raw_offset
            if offset >= s.raw_offset + s.raw_size:
                break
            return offset
    raise PEError(f"RVA 0x{rva:x} is outside every section's file data")


def _c_string(data: bytes, offset: int) -> str:
    end = data.find(b"\0", offset)
    if end < 0:
        raise PEError(f"unterminated name at file offset 0x{offset:x}")
    return data[offset:end].decode("ascii")


def parse_imports(data: bytes) -> Imports:
    """Load-time and delay-load DLL names of a PE32+ image."""
    try:
        if data[:2] != b"MZ":
            raise PEError("no MZ header")
        pe = _u32(data, 0x3C)
        if data[pe : pe + 4] != b"PE\0\0":
            raise PEError("no PE signature")
        coff = pe + 4
        machine = _u16(data, coff)
        section_count = _u16(data, coff + 2)
        optional_size = _u16(data, coff + 16)
        optional = coff + 20
        if _u16(data, optional) != PE32_PLUS:
            raise PEError("not a PE32+ (64-bit) image")
        directory_count = _u32(data, optional + 108)
        directories = optional + 112
        table = optional + optional_size
        sections = [
            Section(
                virtual_size=_u32(data, table + 40 * i + 8),
                virtual_address=_u32(data, table + 40 * i + 12),
                raw_size=_u32(data, table + 40 * i + 16),
                raw_offset=_u32(data, table + 40 * i + 20),
            )
            for i in range(section_count)
        ]

        def directory(index: int) -> tuple[int, int]:
            if index >= directory_count:
                return 0, 0
            return _u32(data, directories + 8 * index), _u32(data, directories + 8 * index + 4)

        load_time: list[str] = []
        rva, size = directory(IMPORT_DIRECTORY)
        if rva and size:
            offset = _rva_to_offset(rva, sections)
            while True:
                descriptor = data[offset : offset + 20]
                if len(descriptor) < 20 or descriptor == b"\0" * 20:
                    break
                load_time.append(_c_string(data, _rva_to_offset(_u32(data, offset + 12), sections)))
                offset += 20

        delay_load: list[str] = []
        rva, size = directory(DELAY_IMPORT_DIRECTORY)
        if rva and size:
            offset = _rva_to_offset(rva, sections)
            while True:
                descriptor = data[offset : offset + 32]
                if len(descriptor) < 32 or descriptor == b"\0" * 32:
                    break
                name_rva = _u32(data, offset + 4)
                delay_load.append(_c_string(data, _rva_to_offset(name_rva, sections)))
                offset += 32
    except struct.error as error:
        raise PEError(f"truncated image: {error}") from error
    return Imports(machine, tuple(load_time), tuple(delay_load))


def read_imports(path: Path) -> Imports:
    try:
        return parse_imports(path.read_bytes())
    except PEError as error:
        raise PEError(f"{path}: {error}") from error
