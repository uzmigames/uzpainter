"""Project store: `inspect`, `export-bundle` with the bundle import, and the size census.

Task `phase1.7_store-inspect-census`. `uzp-store-inspect-tests.exe` (`tests/store/inspect_test.cpp`,
`zig build uzp-store-inspect-tests`) holds the native cases: every field of
`docs/architecture/09-project-file-format.md` §6, inspect while a child process holds the project's
lock, project-file versus external dependency bytes, `--verify` on a broken plane binding and on
missing blobs, the bundle round trip through `ProjectStore::Open` of the bundle directory, the PNG
and OpenEXR codecs, and the census instrumentation on a scripted edit sequence. This driver also
checks the ZIP form with `zipfile` and the PNG reader against PNGs that Python's zlib compressed
(fixed and dynamic Huffman blocks, every scanline filter). No GPU is involved: everything runs on
the hosted CPU lane.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import zipfile
import zlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

NATIVE_CASES = (
    "inspect_fields",  # 3.1
    "inspect_while_locked",  # 3.1
    "inspect_external_dependencies",  # 3.1
    "verify_failures",  # 3.2
    "bundle_round_trip",  # 3.3
    "codec_formats",  # 3.3
    "census_sequence",  # 3.4
)


@pytest.fixture(scope="session")
def inspect_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-store-inspect-tests.exe` of a fresh `zig build uzp-store-inspect-tests`."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; `zig build uzp-store-inspect-tests` cannot run")
    prefix = tmp_path_factory.mktemp("uzp-store-inspect-tests")
    build = subprocess.run(
        [zig, "build", "uzp-store-inspect-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-store-inspect-tests.exe"


def run(exe: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([str(exe), *args], capture_output=True, timeout=900, check=False)


@pytest.mark.parametrize("case", NATIVE_CASES)
def test_native_case(inspect_tests: Path, case: str) -> None:
    proc = run(inspect_tests, "run", case)
    assert proc.returncode == 0, proc.stdout.decode() + proc.stderr.decode()
    assert f"PASS {case}".encode() in proc.stdout


def test_native_case_list_is_complete(inspect_tests: Path) -> None:
    proc = run(inspect_tests, "run")
    assert proc.returncode == 0, proc.stdout.decode() + proc.stderr.decode()
    ran = [line.split()[1] for line in proc.stdout.decode().splitlines() if line.startswith("PASS")]
    assert tuple(ran) == NATIVE_CASES


def test_zip_bundle_holds_the_directory_bundle(inspect_tests: Path, tmp_path: Path) -> None:
    assert run(inspect_tests, "fixture", str(tmp_path)).returncode == 0
    project = tmp_path / "fixture.uzp"
    directory = tmp_path / "bundle"
    archive = tmp_path / "bundle.zip"
    for target in (directory, archive):
        proc = run(inspect_tests, "cli", "export-bundle", str(project), str(target))
        assert proc.returncode == 0, proc.stderr.decode()
        assert json.loads(proc.stdout)["planes"] == 2
    files = {
        p.relative_to(directory).as_posix(): p.read_bytes()
        for p in directory.rglob("*")
        if p.is_file()
    }
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert all(info.compress_type == zipfile.ZIP_STORED for info in bundle.infolist())
        entries = {name: bundle.read(name) for name in bundle.namelist()}
    assert entries == files
    index = json.loads(files["bundle.json"])
    assert index["schema"] == "uzpainter/bundle/1"
    assert {p["file"].split("/")[0] for p in index["planes"]} == {"planes"}
    assert sorted(p["file"].rsplit(".", 1)[1] for p in index["planes"]) == ["exr", "png"]
    assert any(name.startswith("meshmaps/") for name in files)
    assert any(name.startswith("res/") for name in files)


def test_inspect_cli_without_a_recipe_host_reports_the_digest_unavailable(
    inspect_tests: Path, tmp_path: Path
) -> None:
    """The store's own executable resolves no template base values, so it names the host that
    reports the digest (`UzPainter.exe inspect`, tests/python/test_pyapi_cli.py)."""
    assert run(inspect_tests, "fixture", str(tmp_path)).returncode == 0
    proc = run(inspect_tests, "cli", "inspect", str(tmp_path / "fixture.uzp"))
    assert proc.returncode == 0, proc.stderr.decode()
    report = json.loads(proc.stdout)
    assert report["recipe_digest"]["available"] is False
    assert "UzPainter.exe inspect" in report["recipe_digest"]["reason"]


def _png(
    width: int, height: int, bits: int, channels: int, rows: list[bytes], level: int, strategy: int
) -> bytes:
    """A PNG whose scanlines use filters 0..4 in turn, compressed by Python's zlib."""
    bpp = channels * bits // 8
    raw = bytearray()
    previous = bytes(len(rows[0]))
    for y, row in enumerate(rows):
        kind = y % 5
        out = bytearray()
        for i, x in enumerate(row):
            a = row[i - bpp] if i >= bpp else 0
            b = previous[i]
            c = previous[i - bpp] if i >= bpp else 0
            if kind == 0:
                pred = 0
            elif kind == 1:
                pred = a
            elif kind == 2:
                pred = b
            elif kind == 3:
                pred = (a + b) // 2
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
            out.append((x - pred) & 0xFF)
        raw += bytes([kind]) + out
        previous = row
    compressor = zlib.compressobj(level, zlib.DEFLATED, zlib.MAX_WBITS, 9, strategy)
    data = compressor.compress(bytes(raw)) + compressor.flush()

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body)
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    colour = 0 if channels == 1 else 2
    header = struct.pack(">IIBBBBB", width, height, bits, colour, 0, 0, 0)
    half = len(data) // 2  # two IDAT chunks
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"tEXt", b"Comment\x00ancillary chunks are skipped")
        + chunk(b"IDAT", data[:half])
        + chunk(b"IDAT", data[half:])
        + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize(
    ("fmt", "bits", "channels", "level", "strategy"),
    [
        ("RGB16", 16, 3, 9, zlib.Z_DEFAULT_STRATEGY),
        ("L8", 8, 1, 6, zlib.Z_DEFAULT_STRATEGY),
        ("RGB8", 8, 3, 1, zlib.Z_FIXED),
        ("L16", 16, 1, 9, zlib.Z_HUFFMAN_ONLY),
    ],
)
def test_png_reader_inflates_zlib_streams(
    inspect_tests: Path,
    tmp_path: Path,
    fmt: str,
    bits: int,
    channels: int,
    level: int,
    strategy: int,
) -> None:
    width, height = 61, 23
    stride = width * channels * bits // 8
    rows = [
        bytes(((x * 7 + y * 13) ^ (x * y)) & 0xFF for x in range(stride)) for y in range(height)
    ]
    png = tmp_path / "image.png"
    png.write_bytes(_png(width, height, bits, channels, rows, level, strategy))
    out = tmp_path / "texels.bin"
    proc = run(inspect_tests, "png-decode", str(png), fmt, str(out))
    assert proc.returncode == 0, proc.stderr.decode()
    expected = b"".join(rows)
    if bits == 16:  # PNG samples are big-endian, plane texels little-endian
        swapped = bytearray(expected)
        swapped[0::2], swapped[1::2] = expected[1::2], expected[0::2]
        expected = bytes(swapped)
    assert out.read_bytes() == expected
