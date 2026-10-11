"""Owen-scrambled Sobol samples under a fixed seed (07 §3.2; Burley 2020).

Burley 2020, *Practical Hash-based Owen Scrambling* (P-BURLEY2020): the first four dimensions of
the Sobol sequence, each Owen-scrambled by the Laine-Karras hash permutation of the
bit-reversed value (`nested_uniform_scramble`), the sample index itself Owen-scrambled per
pixel (a shuffle that keeps the sequence's stratification), and further dimensions padded by
independently shuffled and scrambled copies of the same four dimensions, one seed per
dimension set. Direction numbers: dimension 0 is the van der Corput sequence; dimensions 1-3
follow the primitive polynomials and initial numbers m_i that Burley 2020 and PBRT 4th ed.
§8.7 (P-PBRT) use (Joe and Kuo's table: s = 1, 2, 3; a = 0, 1, 1; m = (1), (1, 3), (1, 3, 1)).

Every value is computed in uint32 arithmetic with wrap-around, so a given (pixel seed, sample
index, dimension set) always yields the same floats on any machine.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

U32 = npt.NDArray[np.uint32]
F64 = npt.NDArray[np.float64]
BITS = 32
POLYNOMIALS = ((1, 0, (1,)), (2, 1, (1, 3)), (3, 1, (1, 3, 1)))
GOLDEN = 0x9E3779B9


def direction_numbers() -> npt.NDArray[np.uint32]:
    """Generator matrices of Sobol dimensions 0-3 as 4 x 32 direction numbers."""
    table = np.zeros((4, BITS), dtype=np.uint64)
    table[0] = [1 << (BITS - 1 - k) for k in range(BITS)]
    for dim, (s, a, m) in enumerate(POLYNOMIALS, start=1):
        v = [0] * (BITS + 1)
        for i in range(1, s + 1):
            v[i] = m[i - 1] << (BITS - i)
        for i in range(s + 1, BITS + 1):
            value = v[i - s] ^ (v[i - s] >> s)
            for k in range(1, s):
                if (a >> (s - 1 - k)) & 1:
                    value ^= v[i - k]
            v[i] = value
        table[dim] = v[1:]
    return table.astype(np.uint32)


DIRECTIONS = direction_numbers()


def reverse_bits(x: U32) -> U32:
    for shift, mask in ((1, 0x55555555), (2, 0x33333333), (4, 0x0F0F0F0F), (8, 0x00FF00FF)):
        m = np.uint32(mask)
        s = np.uint32(shift)
        x = (((x >> s) & m) | ((x & m) << s)).astype(np.uint32)
    return ((x >> np.uint32(16)) | (x << np.uint32(16))).astype(np.uint32)


def laine_karras_permutation(x: U32, seed: U32 | np.uint32) -> U32:
    """Burley 2020 listing 2 (the improved Laine-Karras hash); uint32 wrap-around."""
    x = (x + seed).astype(np.uint32)
    x ^= (x * np.uint32(0x6C50B47C)).astype(np.uint32)
    x ^= (x * np.uint32(0xB82F1E52)).astype(np.uint32)
    x ^= (x * np.uint32(0xC7AFE638)).astype(np.uint32)
    x ^= (x * np.uint32(0x8D22F6E6)).astype(np.uint32)
    return x


def nested_uniform_scramble(x: U32, seed: U32 | np.uint32) -> U32:
    """Owen scrambling of a 32-bit fixed-point value (Burley 2020 listing 3)."""
    return reverse_bits(laine_karras_permutation(reverse_bits(x), seed))


def hash_combine(seed: U32 | np.uint32, value: int) -> U32:
    """Burley 2020's seed combination (boost-style hash_combine), uint32."""
    s = np.asarray(seed, dtype=np.uint32)
    mixed = (np.uint32(value) + np.uint32(GOLDEN) + (s << 6) + (s >> 2)).astype(np.uint32)
    return (s ^ mixed).astype(np.uint32)


def byte_tables() -> npt.NDArray[np.uint32]:
    """For each dimension and index byte, the XOR of the direction numbers its set bits select
    (4 x 4 x 256): the Sobol product computed eight bits at a time."""
    tables = np.zeros((4, 4, 256), dtype=np.uint32)
    for dim in range(4):
        for byte in range(4):
            for value in range(256):
                acc = 0
                for bit in range(8):
                    if (value >> bit) & 1:
                        acc ^= int(DIRECTIONS[dim, byte * 8 + bit])
                tables[dim, byte, value] = acc
    return tables


BYTE_TABLES = byte_tables()


def sobol(index: U32, dim: int) -> U32:
    """Unscrambled Sobol value of dimension `dim` (0-3) for each index."""
    table = BYTE_TABLES[dim]
    result: U32 = table[0][index & np.uint32(0xFF)]
    for byte in range(1, 4):
        result = result ^ table[byte][(index >> np.uint32(8 * byte)) & np.uint32(0xFF)]
    return result.astype(np.uint32)


def pixel_seeds(pixels: npt.NDArray[np.int64], seed: int) -> U32:
    """One scramble seed per pixel index under the render's fixed seed."""
    base = laine_karras_permutation(
        np.asarray(pixels, dtype=np.uint64).astype(np.uint32), np.uint32(seed & 0xFFFFFFFF)
    )
    return laine_karras_permutation(base, np.uint32((seed * 0x2545F491) & 0xFFFFFFFF))


def samples(index: int, seeds: U32, dim_set: int, count: int) -> F64:
    """`count` (1-4) scrambled dimensions of dimension set `dim_set` for sample `index`.

    Shape (len(seeds), count), values in [0, 1)."""
    if not 1 <= count <= 4:
        raise ValueError("a dimension set holds one to four dimensions")
    set_seed = hash_combine(seeds, dim_set)
    shuffled = nested_uniform_scramble(np.full(seeds.shape, index, dtype=np.uint32), set_seed)
    out = np.empty((seeds.shape[0], count), dtype=np.float64)
    for dim in range(count):
        value = nested_uniform_scramble(sobol(shuffled, dim), hash_combine(set_seed, dim))
        out[:, dim] = value.astype(np.float64) * (1.0 / 4294967296.0)
    return out
