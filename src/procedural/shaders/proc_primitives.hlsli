// The HLSL mirror of src/procedural/primitives.{h,cpp}, operation for operation (see the header
// for the rules: one IEEE single operation at a time, `precise`, explicit flush of subnormal
// results, no division, no hardware square root, no transcendental, integer hashing). The
// constants come from the generated `proc_constants.hlsli` (`prim::ConstantsHlsl`).

#include "proc_constants.hlsli"

// ── Arithmetic ───────────────────────────────────────────────────────────────

float Ftz(float x) {
    const uint b = asuint(x);
    return (b & 0x7F800000u) == 0u ? asfloat(b & 0x80000000u) : x;
}

float Add(float a, float b) {
    precise float r = a + b;
    return Ftz(r);
}

float Sub(float a, float b) {
    precise float r = a - b;
    return Ftz(r);
}

float Mul(float a, float b) {
    precise float r = a * b;
    return Ftz(r);
}

float Lerp(float a, float b, float t) { return Add(a, Mul(t, Sub(b, a))); }

float SqrtRn(float x) {
    const uint b = asuint(x);
    const uint e = (b >> 23) & 0xFFu;
    if (e == 0xFFu) return (b & 0x007FFFFFu) != 0u || (b >> 31) == 0u ? x : asfloat(0x7FC00000u);
    if (e == 0u) return asfloat(b & 0x80000000u);
    if ((b >> 31) != 0u) return asfloat(0x7FC00000u);
    uint64_t m = (uint64_t)((b & 0x007FFFFFu) | 0x00800000u);
    int q = int(e) - 150;
    if ((q & 1) != 0) {
        m <<= 1;
        q -= 1;
    } else {
        m <<= 2;
        q -= 2;
    }
    uint64_t n = m << 24;
    uint64_t root = 0;
    uint64_t bit = ((uint64_t)1) << 50;
    while (bit > n) bit >>= 2;
    while (bit != 0) {
        if (n >= root + bit) {
            n -= root + bit;
            root = (root >> 1) + bit;
        } else {
            root >>= 1;
        }
        bit >>= 2;
    }
    uint significand = (uint)(root >> 1);
    if ((root & 1) != 0 && (n != 0 || (significand & 1u) != 0u)) ++significand;
    int exponent = q / 2 + 12 + 127;
    if (significand == 0x01000000u) {
        significand >>= 1;
        ++exponent;
    }
    return asfloat((uint(exponent) << 23) | (significand & 0x007FFFFFu));
}

// ── Hashing ──────────────────────────────────────────────────────────────────

uint3 Pcg3d(uint3 v) {
    v = v * 1664525u + 1013904223u;
    v.x += v.y * v.z;
    v.y += v.z * v.x;
    v.z += v.x * v.y;
    v ^= v >> 16u;
    v.x += v.y * v.z;
    v.y += v.z * v.x;
    v.z += v.x * v.y;
    return v;
}

uint3 SeedOffset(uint seed) { return Pcg3d(uint3(seed, seed ^ 0x5BD1E995u, seed ^ 0x27D4EB2Fu)); }

uint3 CellHash(int i, int j, int k, uint3 offset) { return Pcg3d(uint3(uint(i), uint(j), uint(k)) + offset); }

float Hash24(uint h) { return float(h >> 8); }

// ── Noise ────────────────────────────────────────────────────────────────────

float Dot3(float gx, float gy, float gz, float x, float y, float z) {
    return Add(Add(Mul(gx, x), Mul(gy, y)), Mul(gz, z));
}

float Fade1985(float t) { return Mul(Mul(t, t), Sub(3.0f, Mul(2.0f, t))); }

float Fade2002(float t) { return Mul(Mul(Mul(t, t), t), Add(Mul(t, Sub(Mul(t, 6.0f), 15.0f)), 10.0f)); }

float Grad1985(uint3 h, float x, float y, float z) {
    const float k = asfloat(0x34000000u);  // 2^-23
    const float gx = Sub(Mul(Hash24(h.x), k), 1.0f);
    const float gy = Sub(Mul(Hash24(h.y), k), 1.0f);
    const float gz = Sub(Mul(Hash24(h.z), k), 1.0f);
    return Dot3(gx, gy, gz, x, y, z);
}

float Grad2002(uint hash, float x, float y, float z) {
    const uint h = hash & 15u;
    const float u = h < 8u ? x : y;
    const float v = h < 4u ? y : (h == 12u || h == 14u ? x : z);
    return Add((h & 1u) == 0u ? u : -u, (h & 2u) == 0u ? v : -v);
}

// Perlin's lattice noise: kind 0 is 1985 (Grad1985, Fade1985), kind 1 is 2002.
float LatticeNoise(float3 p, uint seed, uint kind) {
    const float fx = floor(p.x);
    const float fy = floor(p.y);
    const float fz = floor(p.z);
    const int i = int(fx);
    const int j = int(fy);
    const int k = int(fz);
    const float x = Sub(p.x, fx);
    const float y = Sub(p.y, fy);
    const float z = Sub(p.z, fz);
    const float x1 = Sub(x, 1.0f);
    const float y1 = Sub(y, 1.0f);
    const float z1 = Sub(z, 1.0f);
    const uint3 offset = SeedOffset(seed);
    const uint3 h000 = CellHash(i, j, k, offset);
    const uint3 h100 = CellHash(i + 1, j, k, offset);
    const uint3 h010 = CellHash(i, j + 1, k, offset);
    const uint3 h110 = CellHash(i + 1, j + 1, k, offset);
    const uint3 h001 = CellHash(i, j, k + 1, offset);
    const uint3 h101 = CellHash(i + 1, j, k + 1, offset);
    const uint3 h011 = CellHash(i, j + 1, k + 1, offset);
    const uint3 h111 = CellHash(i + 1, j + 1, k + 1, offset);
    float n000, n100, n010, n110, n001, n101, n011, n111, u, v, w;
    if (kind == 0u) {
        n000 = Grad1985(h000, x, y, z);
        n100 = Grad1985(h100, x1, y, z);
        n010 = Grad1985(h010, x, y1, z);
        n110 = Grad1985(h110, x1, y1, z);
        n001 = Grad1985(h001, x, y, z1);
        n101 = Grad1985(h101, x1, y, z1);
        n011 = Grad1985(h011, x, y1, z1);
        n111 = Grad1985(h111, x1, y1, z1);
        u = Fade1985(x);
        v = Fade1985(y);
        w = Fade1985(z);
    } else {
        n000 = Grad2002(h000.x, x, y, z);
        n100 = Grad2002(h100.x, x1, y, z);
        n010 = Grad2002(h010.x, x, y1, z);
        n110 = Grad2002(h110.x, x1, y1, z);
        n001 = Grad2002(h001.x, x, y, z1);
        n101 = Grad2002(h101.x, x1, y, z1);
        n011 = Grad2002(h011.x, x, y1, z1);
        n111 = Grad2002(h111.x, x1, y1, z1);
        u = Fade2002(x);
        v = Fade2002(y);
        w = Fade2002(z);
    }
    const float a = Lerp(Lerp(n000, n100, u), Lerp(n010, n110, u), v);
    const float b = Lerp(Lerp(n001, n101, u), Lerp(n011, n111, u), v);
    return Lerp(a, b, w);
}

float Perlin1985(float3 p, uint seed) { return LatticeNoise(p, seed, 0u); }
float Perlin2002(float3 p, uint seed) { return LatticeNoise(p, seed, 1u); }

static const int3 kEdges[12] = {int3(1, 1, 0),  int3(-1, 1, 0), int3(1, -1, 0), int3(-1, -1, 0),
                                int3(1, 0, 1),  int3(-1, 0, 1), int3(1, 0, -1), int3(-1, 0, -1),
                                int3(0, 1, 1),  int3(0, -1, 1), int3(0, 1, -1), int3(0, -1, -1)};

float SimplexCorner(uint3 hash, float x, float y, float z) {
    const float t = Sub(Sub(Sub(kSimplexR2, Mul(x, x)), Mul(y, y)), Mul(z, z));
    if (t < 0.0f) return 0.0f;
    const int3 g = kEdges[hash.x % 12u];
    const float t2 = Mul(t, t);
    return Mul(Mul(t2, t2), Dot3(float(g.x), float(g.y), float(g.z), x, y, z));
}

float Simplex3(float3 p, uint seed) {
    const float s = Mul(Add(Add(p.x, p.y), p.z), kSimplexF3);
    const float fi = floor(Add(p.x, s));
    const float fj = floor(Add(p.y, s));
    const float fk = floor(Add(p.z, s));
    const float t = Mul(Add(Add(fi, fj), fk), kSimplexG3);
    const float x0 = Sub(p.x, Sub(fi, t));
    const float y0 = Sub(p.y, Sub(fj, t));
    const float z0 = Sub(p.z, Sub(fk, t));
    int i1, j1, k1, i2, j2, k2;
    if (x0 >= y0) {
        if (y0 >= z0) {
            i1 = 1; j1 = 0; k1 = 0; i2 = 1; j2 = 1; k2 = 0;
        } else if (x0 >= z0) {
            i1 = 1; j1 = 0; k1 = 0; i2 = 1; j2 = 0; k2 = 1;
        } else {
            i1 = 0; j1 = 0; k1 = 1; i2 = 1; j2 = 0; k2 = 1;
        }
    } else {
        if (y0 < z0) {
            i1 = 0; j1 = 0; k1 = 1; i2 = 0; j2 = 1; k2 = 1;
        } else if (x0 < z0) {
            i1 = 0; j1 = 1; k1 = 0; i2 = 0; j2 = 1; k2 = 1;
        } else {
            i1 = 0; j1 = 1; k1 = 0; i2 = 1; j2 = 1; k2 = 0;
        }
    }
    const float x1 = Add(Sub(x0, float(i1)), kSimplexG3);
    const float y1 = Add(Sub(y0, float(j1)), kSimplexG3);
    const float z1 = Add(Sub(z0, float(k1)), kSimplexG3);
    const float x2 = Add(Sub(x0, float(i2)), kSimplexG3x2);
    const float y2 = Add(Sub(y0, float(j2)), kSimplexG3x2);
    const float z2 = Add(Sub(z0, float(k2)), kSimplexG3x2);
    const float x3 = Add(Sub(x0, 1.0f), kSimplexG3x3);
    const float y3 = Add(Sub(y0, 1.0f), kSimplexG3x3);
    const float z3 = Add(Sub(z0, 1.0f), kSimplexG3x3);
    const int i = int(fi);
    const int j = int(fj);
    const int k = int(fk);
    const uint3 offset = SeedOffset(seed);
    const float n0 = SimplexCorner(CellHash(i, j, k, offset), x0, y0, z0);
    const float n1 = SimplexCorner(CellHash(i + i1, j + j1, k + k1, offset), x1, y1, z1);
    const float n2 = SimplexCorner(CellHash(i + i2, j + j2, k + k2, offset), x2, y2, z2);
    const float n3 = SimplexCorner(CellHash(i + 1, j + 1, k + 1, offset), x3, y3, z3);
    return Mul(kSimplexScale, Add(Add(Add(n0, n1), n2), n3));
}

#define WORLEY_EUCLIDEAN 0u
#define WORLEY_MANHATTAN 1u
#define WORLEY_CHEBYSHEV 2u

struct WorleyResult {
    float f1;
    float f2;
    uint cell;
};

WorleyResult Worley3(float3 p, uint seed, uint metric) {
    const float fx = floor(p.x);
    const float fy = floor(p.y);
    const float fz = floor(p.z);
    const int i = int(fx);
    const int j = int(fy);
    const int k = int(fz);
    const uint3 offset = SeedOffset(seed);
    const float unit = asfloat(0x33800000u);  // 2^-24
    WorleyResult r;
    r.f1 = asfloat(0x7F800000u);
    r.f2 = asfloat(0x7F800000u);
    r.cell = 0u;
    for (int dz = -1; dz <= 1; ++dz) {
        for (int dy = -1; dy <= 1; ++dy) {
            for (int dx = -1; dx <= 1; ++dx) {
                const uint3 h = CellHash(i + dx, j + dy, k + dz, offset);
                const float px = Add(float(i + dx), Mul(Hash24(h.x), unit));
                const float py = Add(float(j + dy), Mul(Hash24(h.y), unit));
                const float pz = Add(float(k + dz), Mul(Hash24(h.z), unit));
                const float ox = Sub(px, p.x);
                const float oy = Sub(py, p.y);
                const float oz = Sub(pz, p.z);
                float d;
                if (metric == WORLEY_EUCLIDEAN) {
                    d = Add(Add(Mul(ox, ox), Mul(oy, oy)), Mul(oz, oz));
                } else {
                    const float ax = abs(ox);
                    const float ay = abs(oy);
                    const float az = abs(oz);
                    if (metric == WORLEY_MANHATTAN) {
                        d = Add(Add(ax, ay), az);
                    } else {
                        const float axy = ay > ax ? ay : ax;
                        d = az > axy ? az : axy;
                    }
                }
                if (d < r.f1) {
                    r.f2 = r.f1;
                    r.f1 = d;
                    r.cell = h.x;
                } else if (d < r.f2) {
                    r.f2 = d;
                }
            }
        }
    }
    if (metric == WORLEY_EUCLIDEAN) {
        r.f1 = SqrtRn(r.f1);
        r.f2 = SqrtRn(r.f2);
    }
    return r;
}

#define FBM_PERLIN1985 0u
#define FBM_PERLIN2002 1u
#define FBM_SIMPLEX3 2u
#define FBM_WORLEY_F1 3u

float Fbm(uint basis, float3 p, uint seed, uint octaves, float lacunarity, float gain) {
    float sum = 0.0f;
    float amplitude = 1.0f;
    float3 q = p;
    for (uint octave = 0u; octave < octaves; ++octave) {
        const uint s = seed + octave;
        float n = 0.0f;
        if (basis == FBM_PERLIN1985) n = Perlin1985(q, s);
        else if (basis == FBM_PERLIN2002) n = Perlin2002(q, s);
        else if (basis == FBM_SIMPLEX3) n = Simplex3(q, s);
        else n = Worley3(q, s, WORLEY_EUCLIDEAN).f1;
        sum = Add(sum, Mul(amplitude, n));
        q = float3(Mul(q.x, lacunarity), Mul(q.y, lacunarity), Mul(q.z, lacunarity));
        amplitude = Mul(amplitude, gain);
    }
    return sum;
}

// ── Image operators (over the host's input slots, `ProcInput`) ───────────────

#define BORDER_WRAP 0u
#define BORDER_CLAMP 1u
#define FOOTPRINT_SQUARE 0u
#define FOOTPRINT_DISK 1u

float4 Ftz4(float4 v) { return float4(Ftz(v.x), Ftz(v.y), Ftz(v.z), Ftz(v.w)); }

// The texel of input `slot` at (x, y) after the border rule, flushed.
float4 Texel(uint slot, int x, int y, uint border) {
    const uint2 size = ProcInputSize(slot);
    const int w = int(size.x);
    const int h = int(size.y);
    if (border == BORDER_WRAP) {
        x = ((x % w) + w) % w;
        y = ((y % h) + h) % h;
    } else {
        x = x < 0 ? 0 : (x >= w ? w - 1 : x);
        y = y < 0 ? 0 : (y >= h ? h - 1 : y);
    }
    return Ftz4(ProcInput(slot, int2(x, y)));
}

float Pick(bool dilate, float v, float best) { return (dilate ? v > best : v < best) ? v : best; }

float4 Morph(uint slot, int2 p, int radius, uint footprint, uint border, bool dilate) {
    float4 best = Texel(slot, p.x, p.y, border);
    for (int dy = -radius; dy <= radius; ++dy) {
        for (int dx = -radius; dx <= radius; ++dx) {
            if (footprint == FOOTPRINT_DISK && dx * dx + dy * dy > radius * radius) continue;
            const float4 v = Texel(slot, p.x + dx, p.y + dy, border);
            best = float4(Pick(dilate, v.x, best.x), Pick(dilate, v.y, best.y),
                          Pick(dilate, v.z, best.z), Pick(dilate, v.w, best.w));
        }
    }
    return best;
}

float4 Dilate(uint slot, int2 p, int radius, uint footprint, uint border) {
    return Morph(slot, p, radius, footprint, border, true);
}

float4 Erode(uint slot, int2 p, int radius, uint footprint, uint border) {
    return Morph(slot, p, radius, footprint, border, false);
}

// One pass of the separable convolution: `taps` weights from parameter word `firstWeight`
// (float bits), centred, along x (horizontal) or y.
float4 BlurPass(uint slot, int2 p, uint firstWeight, uint taps, bool horizontal, uint border) {
    const int r = int(taps / 2u);
    float4 sum = float4(0.0f, 0.0f, 0.0f, 0.0f);
    for (int k = 0; k <= 2 * r; ++k) {
        const float w = asfloat(ProcParam(firstWeight + uint(k)));
        const int tx = horizontal ? p.x + k - r : p.x;
        const int ty = horizontal ? p.y : p.y + k - r;
        const float4 v = Texel(slot, tx, ty, border);
        sum = float4(Add(sum.x, Mul(w, v.x)), Add(sum.y, Mul(w, v.y)), Add(sum.z, Mul(w, v.z)),
                     Add(sum.w, Mul(w, v.w)));
    }
    return sum;
}
