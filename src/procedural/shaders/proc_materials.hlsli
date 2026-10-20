// The kernel functions of UzPainter's material family (src/procedural/materials.h, decision 334),
// written once for both lanes. This text is compiled twice:
//
// - as HLSL, after the HLSL host's wrapper and the primitive library (materials.cpp's kernel
//   body adds `MParam`, `MFloor`, `MInput` and `ProcTexel`);
// - as C++, inside `uzp::procedural::material_kernel` (materials.cpp's prelude defines `uint`,
//   `uint3`, `float4`, `asfloat`, `asuint`, `Hash24`, `SeedOffset`, `CellHash`, `MParam`,
//   `MFloor`, `MInput` and takes `Add`, `Sub`, `Mul`, `Lerp`, `Fade2002` and `SqrtRn` from the
//   primitive library), the CPU reference.
//
// So the text keeps to a subset that means the same in both languages:
// - every float operation is a flushed single operation of the primitive library (`Add`, `Sub`,
//   `Mul`, `Lerp`), never a bare `+`, `-` or `*` on floats, and there is no division and no
//   transcendental (the host computes every derived constant, `MaterialWords`);
// - every float literal is a dyadic fraction, exact in float32 whatever the parser;
// - comparisons, unary minus, `MFloor`, int-float conversions of small integers and integer
//   arithmetic are exact in both;
// - no vector arithmetic, no swizzle beyond `.x .y .z .w`, no arrays, no out parameters.
//
// Parameter words (`MParam(i)`; floats as their bits):

static const uint kMatKind = 0u;      // 0 felt, 1 burlap, 2 leather grain, 3 leather pattern
static const uint kMatOutput = 1u;    // 0 basecolor ... 5 ambient_occlusion, 6 the fields pass
static const uint kMatTiling = 2u;    // whole repeats across the texture
static const uint kMatUnit = 3u;      // tiling / resolution
static const uint kMatSalt = 4u;      // added to the request seed
static const uint kMatColour = 5u;    // 5, 6, 7: the colour (sRGB-encoded values)
static const uint kMatColourVariation = 8u;
static const uint kMatRoughness = 9u;
static const uint kMatRoughnessVariation = 10u;
static const uint kMatNormalGain = 11u;  // normal_intensity x resolution / 256
static const uint kMatAoIntensity = 12u;
static const uint kMatAoStep = 13u;   // resolution / 512 texels (an integer)
static const uint kMatA = 14u;        // per kind, see each material
static const uint kMatB = 15u;
static const uint kMatC = 16u;
static const uint kMatTable = 17u;    // felt: 16 (cos, sin) fibre directions
static const uint kMatFieldsOutput = 6u;

float MW(uint i) { return asfloat(MParam(i)); }

// NaN and -0 give +0.
float MClamp01(float v) { return v > 0.0f ? (v < 1.0f ? v : 1.0f) : 0.0f; }
float MAbs(float v) { return v < 0.0f ? -v : v; }
float MMax(float a, float b) { return b > a ? b : a; }
float MFract(float v) { return Sub(v, MFloor(v)); }
// The triangle wave |2 fract(v) - 1|: period 1, continuous.
float MTri(float v) { return MAbs(Sub(Mul(MFract(v), 2.0f), 1.0f)); }
int MWrap(int i, int n) { return ((i % n) + n) % n; }
// The high 24 bits of a hash in [0, 1).
float MUnit(uint h) { return Mul(Hash24(h), asfloat(0x33800000u)); }

// The coordinate of texel x on a lattice of `cells` x tiling cells across the texture:
// (x + 1/2) x (tiling / R) x cells, exact in float32 inside the domain (R a power of two, and
// (2x + 1) x tiling x cells below 2^24), so the lattice wraps bit for bit.
float MCoord(int x, int cells) { return Mul(Mul(Add(float(x), 0.5f), MW(kMatUnit)), float(cells)); }

// The hash of cell (i, j) of a lattice of period p: the index taken modulo the period
// (Lagae et al. 2010), so the texture tiles.
uint3 MHash(int i, int j, int p, uint3 offset) { return CellHash(MWrap(i, p), MWrap(j, p), 0, offset); }

// Perlin 2002's gradient on the z = 0 plane: u is x for h < 8, else y; v is y for h < 4, x for
// h 12 or 14, else z (0 here, so its term is left out); signs from bits 0 and 1.
float MGrad(uint hash, float x, float y) {
    const uint h = hash & 15u;
    const float u = h < 8u ? x : y;
    const float su = (h & 1u) == 0u ? u : -u;
    if (h >= 4u && h != 12u && h != 14u) return su;
    const float v = h < 4u ? y : x;
    return Add(su, (h & 2u) == 0u ? v : -v);
}

// Periodic Perlin 2002 gradient noise, period p cells.
float MNoise(float x, float y, int p, uint3 offset) {
    const float fx = MFloor(x);
    const float fy = MFloor(y);
    const int i = int(fx);
    const int j = int(fy);
    const float u = Sub(x, fx);
    const float v = Sub(y, fy);
    const float u1 = Sub(u, 1.0f);
    const float v1 = Sub(v, 1.0f);
    const float n00 = MGrad(MHash(i, j, p, offset).x, u, v);
    const float n10 = MGrad(MHash(i + 1, j, p, offset).x, u1, v);
    const float n01 = MGrad(MHash(i, j + 1, p, offset).x, u, v1);
    const float n11 = MGrad(MHash(i + 1, j + 1, p, offset).x, u1, v1);
    const float a = Fade2002(u);
    const float b = Fade2002(v);
    return Lerp(Lerp(n00, n10, a), Lerp(n01, n11, a), b);
}

// fBm of `MNoise` (Musgrave): lacunarity 2 (each octave doubles the coordinate and the period),
// gain 1/2, octave k seeded seed + k; ridged sums (1 - |n|)^2 per octave.
float MFbm(float x, float y, int p, uint octaves, uint seed, bool ridged) {
    float sum = 0.0f;
    float amplitude = 1.0f;
    for (uint k = 0u; k < octaves; ++k) {
        float n = MNoise(x, y, p, SeedOffset(seed + k));
        if (ridged) {
            const float r = Sub(1.0f, MAbs(n));
            n = Mul(r, r);
        }
        sum = Add(sum, Mul(amplitude, n));
        x = Mul(x, 2.0f);
        y = Mul(y, 2.0f);
        p = p * 2;
        amplitude = Mul(amplitude, 0.5f);
    }
    return sum;
}

// ── Felt ─────────────────────────────────────────────────────────────────────
// A: the keep probability of a fibre (0.35 + 0.6 fibre_density); B: fibre_density; the table:
// 16 directions spanning (1 - fibre_alignment) x 180 degrees.

// Straight fibres (Kallmes and Corte 1960): per cell and layer one segment of half length 7/8
// cell and width 1/16 cell, its centre and direction from the cell hash, kept with probability
// A; the brightest wins. The second layer doubles the lattice.
float MFibres(float x, float y, int p, uint seed) {
    const float keep = MW(kMatA);
    const float reach = 0.875f;
    float best = 0.0f;
    for (uint k = 0u; k < 2u; ++k) {
        const uint3 offset = SeedOffset(seed + k);
        const float fx = MFloor(x);
        const float fy = MFloor(y);
        const int i = int(fx);
        const int j = int(fy);
        const float u = Sub(x, fx);
        const float v = Sub(y, fy);
        for (int dy = -1; dy <= 1; ++dy) {
            for (int dx = -1; dx <= 1; ++dx) {
                const uint3 h = MHash(i + dx, j + dy, p, offset);
                if (!(MUnit(h.z) < keep)) continue;
                const float cx = Add(float(dx), MUnit(h.x));
                const float cy = Add(float(dy), MUnit(h.y));
                const uint d = kMatTable + 2u * (h.y & 15u);
                const float c = MW(d);
                const float s = MW(d + 1u);
                const float rx = Sub(u, cx);
                const float ry = Sub(v, cy);
                const float along = Add(Mul(rx, c), Mul(ry, s));
                const float across = Sub(Mul(ry, c), Mul(rx, s));
                const float clamped = along < -reach ? -reach : (along > reach ? reach : along);
                const float beyond = Sub(along, clamped);
                const float t = Mul(Add(Mul(beyond, beyond), Mul(across, across)), 256.0f);
                if (!(t < 1.0f)) continue;
                const float taper = Sub(1.0f, Mul(Mul(clamped, clamped), 1.25f));
                const float profile = Sub(1.0f, t);
                const float shade = Add(0.5f, Mul(0.5f, MUnit(h.x ^ h.y)));
                best = MMax(best, Mul(Mul(Mul(profile, profile), taper), shade));
            }
        }
        x = Mul(x, 2.0f);
        y = Mul(y, 2.0f);
        p = p * 2;
    }
    return best;
}

// Fibres over fBm clouds: the clouds weigh 1/2, the fibres 1/4 + 3/8 fibre_density.
float4 MFelt(int x, int y, uint seed) {
    const int t = int(MParam(kMatTiling));
    const float fibres = MFibres(MCoord(x, 32), MCoord(y, 32), 32 * t, seed);
    const float sum = MFbm(MCoord(x, 4), MCoord(y, 4), 4 * t, 4u, seed + 100u, false);
    const float clouds = MClamp01(Add(Mul(sum, 0.4375f), 0.5f));
    const float weight = Add(0.25f, Mul(MW(kMatB), 0.375f));
    const float height = MClamp01(Add(Mul(clouds, 0.5f), Mul(fibres, weight)));
    return float4(height, Lerp(clouds, fibres, 0.375f), 0.0f, 0.0f);
}

// ── Burlap ───────────────────────────────────────────────────────────────────
// A: 1 / the yarn's half width (1/2 (1 - gap)); B: irregularity; C: fuzz / 4.

// A yarn's profile across its width: 1 - ((w - 1/2) / half width)^2, 0 in the gap.
float MYarn(float w, float inverseHalfWidth) {
    const float a = Mul(Sub(w, 0.5f), inverseHalfWidth);
    return MClamp01(Sub(1.0f, Mul(a, a)));
}

// A plain weave (Peachey) of 2 x tiling yarns each way: the warp runs along v and lies on top
// where i + j is even, the weft along u. Each yarn's thickness varies by irregularity; slanted
// twist ridges run along it (Irawan and Marschner 2012), a triangle wave of period 1/4 cell; a
// fuzz of fBm covers the weave. The tone is the uppermost yarn's own shade.
float4 MBurlap(int x, int y, uint seed) {
    const int t = int(MParam(kMatTiling));
    const int p = 2 * t;
    const float wx = MCoord(x, 2);
    const float wy = MCoord(y, 2);
    const float fx = MFloor(wx);
    const float fy = MFloor(wy);
    const int i = MWrap(int(fx), p);
    const int j = MWrap(int(fy), p);
    const float u = Sub(wx, fx);
    const float v = Sub(wy, fy);
    const uint3 offset = SeedOffset(seed);
    const float inverseHalfWidth = MW(kMatA);
    const float irregularity = MW(kMatB);
    const bool warpOnTop = ((i + j) & 1) == 0;
    const float warpThickness = Add(1.0f, Mul(irregularity, Sub(MUnit(CellHash(i, 0, 1, offset).x), 0.5f)));
    const float weftThickness = Add(1.0f, Mul(irregularity, Sub(MUnit(CellHash(0, j, 2, offset).x), 0.5f)));
    const float acrossWarp = MYarn(u, inverseHalfWidth);
    const float acrossWeft = MYarn(v, inverseHalfWidth);
    const float twistWarp = Lerp(1.0f, MTri(Add(Mul(v, 4.0f), Mul(u, 2.0f))), 0.375f);
    const float twistWeft = Lerp(1.0f, MTri(Add(Mul(u, 4.0f), Mul(v, 2.0f))), 0.375f);
    const float warpLift = warpOnTop ? Add(0.625f, Mul(0.375f, acrossWeft)) : Mul(0.375f, Sub(1.0f, acrossWeft));
    const float weftLift = warpOnTop ? Mul(0.375f, Sub(1.0f, acrossWarp)) : Add(0.625f, Mul(0.375f, acrossWarp));
    const float warp = Mul(Mul(Mul(acrossWarp, warpThickness), warpLift), twistWarp);
    const float weft = Mul(Mul(Mul(acrossWeft, weftThickness), weftLift), twistWeft);
    const float fuzz = MFbm(MCoord(x, 16), MCoord(y, 16), 16 * t, 3u, seed + 200u, false);
    const float height = MClamp01(Add(MMax(warp, weft), Mul(fuzz, MW(kMatC))));
    const float tone = warp > weft ? MUnit(CellHash(i, 0, 3, offset).x) : MUnit(CellHash(0, j, 4, offset).x);
    return float4(height, MClamp01(Lerp(height, tone, 0.375f)), 0.0f, 0.0f);
}

// ── Worley cells ─────────────────────────────────────────────────────────────

// Worley 1996 on a periodic lattice of p cells: one feature point per cell at
// 1/2 + jitter (hash - 1/2), searched over the 3 x 3 cells around the point; x is F1^2, y is F2^2
// and z the nearest cell's hash in [0, 1).
float4 MWorley(float x, float y, int p, float jitter, uint3 offset) {
    const float fx = MFloor(x);
    const float fy = MFloor(y);
    const int i = int(fx);
    const int j = int(fy);
    const float u = Sub(x, fx);
    const float v = Sub(y, fy);
    float d1 = asfloat(0x7F800000u);
    float d2 = asfloat(0x7F800000u);
    float nearest = 0.0f;
    for (int dy = -1; dy <= 1; ++dy) {
        for (int dx = -1; dx <= 1; ++dx) {
            const uint3 h = MHash(i + dx, j + dy, p, offset);
            const float ox = Sub(Add(float(dx), Add(0.5f, Mul(jitter, Sub(MUnit(h.x), 0.5f)))), u);
            const float oy = Sub(Add(float(dy), Add(0.5f, Mul(jitter, Sub(MUnit(h.y), 0.5f)))), v);
            const float d = Add(Mul(ox, ox), Mul(oy, oy));
            if (d < d1) {
                d2 = d1;
                d1 = d;
                nearest = MUnit(h.z);
            } else if (d < d2) {
                d2 = d;
            }
        }
    }
    return float4(d1, d2, nearest, 0.0f);
}

// The cell border F2 - F1 of a Worley result, scaled by `gain` and clamped: 0 on the border.
float MBorder(float4 cell, float gain) { return MClamp01(Mul(Sub(SqrtRn(cell.y), SqrtRn(cell.x)), gain)); }

// ── Leather grain ────────────────────────────────────────────────────────────
// A: the feature points' jitter (1/2 + irregularity / 2); B: 1 / the groove width
// (0.04 + 0.16 groove_width cell); C: pore_amount / 2.

// Pebbled grain on 12 x tiling cells: a dome per cell (1 - 3/2 F1^2) inside grooves at the cell
// borders; pores from a 48 x tiling lattice darken the relief. The tone mixes in the cell's own
// shade.
float4 MLeatherGrain(int x, int y, uint seed) {
    const int t = int(MParam(kMatTiling));
    const float4 cell = MWorley(MCoord(x, 12), MCoord(y, 12), 12 * t, MW(kMatA), SeedOffset(seed));
    const float groove = MBorder(cell, MW(kMatB));
    const float dome = MClamp01(Sub(1.0f, Mul(cell.x, 1.5f)));
    const float relief = Mul(groove, Add(0.5625f, Mul(0.4375f, dome)));
    const float4 pores = MWorley(MCoord(x, 48), MCoord(y, 48), 48 * t, 1.0f, SeedOffset(seed + 300u));
    const float pore = MClamp01(Mul(SqrtRn(pores.x), 6.0f));
    const float height = Mul(relief, Lerp(1.0f, pore, MW(kMatC)));
    return float4(height, MClamp01(Lerp(height, cell.z, 0.375f)), 0.0f, 0.0f);
}

// ── Leather pattern ──────────────────────────────────────────────────────────
// A: crease_depth; B: wrinkles; C: grain_amount.

// Deep creases at the borders of 4 x tiling cells, ridged-fBm wrinkles (Musgrave's ridged
// multifractal, four octaves on 6 x tiling cells, normalised by 17/32) and a fine grain of
// 24 x tiling cells, each mixed in by its parameter. The tone follows the wrinkles.
float4 MLeatherPattern(int x, int y, uint seed) {
    const int t = int(MParam(kMatTiling));
    const float4 creases = MWorley(MCoord(x, 4), MCoord(y, 4), 4 * t, 1.0f, SeedOffset(seed));
    const float crease = MBorder(creases, 8.0f);
    const float ridges = MFbm(MCoord(x, 6), MCoord(y, 6), 6 * t, 4u, seed + 400u, true);
    const float wrinkles = MClamp01(Mul(ridges, 0.53125f));
    const float4 cells = MWorley(MCoord(x, 24), MCoord(y, 24), 24 * t, 0.75f, SeedOffset(seed + 500u));
    const float grain = MBorder(cells, 6.0f);
    const float relief = Mul(Lerp(1.0f, crease, MW(kMatA)), Lerp(1.0f, wrinkles, MW(kMatB)));
    const float height = MClamp01(Mul(relief, Lerp(1.0f, grain, MW(kMatC))));
    return float4(height, MClamp01(Lerp(height, wrinkles, 0.25f)), 0.0f, 0.0f);
}

// ── The outputs ──────────────────────────────────────────────────────────────

// The fields of texel (x, y): x the height, y the tone.
float4 MFields(int x, int y, uint seed) {
    const uint kind = MParam(kMatKind);
    if (kind == 0u) return MFelt(x, y, seed);
    if (kind == 1u) return MBurlap(x, y, seed);
    if (kind == 2u) return MLeatherGrain(x, y, seed);
    return MLeatherPattern(x, y, seed);
}

// 1 / sqrt(a) for a >= 1 (Lomont 2003): the estimate 0x5F375A86 - (bits >> 1), then four Newton
// steps r (3/2 - a/2 r^2).
float MRsqrt(float a) {
    float r = asfloat(0x5F375A86u - (asuint(a) >> 1u));
    const float halfA = Mul(a, 0.5f);
    for (uint k = 0u; k < 4u; ++k) r = Mul(r, Sub(1.5f, Mul(halfA, Mul(r, r))));
    return r;
}

// The output of texel (x, y). The normal and the occlusion read the fields pass (`MInput`, the
// texture wrapping); every other output computes the fields itself.
float4 MaterialTexel(int x, int y, uint requestSeed) {
    const uint output = MParam(kMatOutput);
    if (output == 1u || output == 5u) {
        const int d = output == 1u ? 1 : int(MParam(kMatAoStep));
        const float left = MInput(x - d, y).x;
        const float right = MInput(x + d, y).x;
        const float up = MInput(x, y - d).x;
        const float down = MInput(x, y + d).x;
        if (output == 1u) {
            // Blinn 1978: n = (-dh/du, -dh/dv, 1) normalised; rows run down, so -dh/dv is
            // down - up.
            const float gain = MW(kMatNormalGain);
            const float nx = Mul(Sub(left, right), gain);
            const float ny = Mul(Sub(down, up), gain);
            const float r = MRsqrt(Add(Add(Mul(nx, nx), Mul(ny, ny)), 1.0f));
            return float4(Add(0.5f, Mul(0.5f, Mul(nx, r))), Add(0.5f, Mul(0.5f, Mul(ny, r))),
                          Add(0.5f, Mul(0.5f, r)), 0.0f);
        }
        // Luft et al. 2006: the local mean of the height minus the height marks a crevice.
        const float mean = Mul(Add(Add(left, right), Add(up, down)), 0.25f);
        const float crevice = MClamp01(Mul(Sub(mean, MInput(x, y).x), 4.0f));
        return float4(Sub(1.0f, Mul(MW(kMatAoIntensity), crevice)), 0.0f, 0.0f, 0.0f);
    }
    const float4 f = MFields(x, y, requestSeed + MParam(kMatSalt));
    if (output == kMatFieldsOutput) return f;
    if (output == 0u) {
        const float shade = Add(1.0f, Mul(MW(kMatColourVariation), Sub(Mul(f.y, 2.0f), 1.0f)));
        return float4(MClamp01(Mul(MW(kMatColour), shade)), MClamp01(Mul(MW(kMatColour + 1u), shade)),
                      MClamp01(Mul(MW(kMatColour + 2u), shade)), 0.0f);
    }
    if (output == 2u) {
        const float rough = Add(MW(kMatRoughness), Mul(MW(kMatRoughnessVariation), Sub(0.5f, f.x)));
        return float4(MClamp01(rough), 0.0f, 0.0f, 0.0f);
    }
    if (output == 4u) return float4(f.x, 0.0f, 0.0f, 0.0f);
    return float4(0.0f, 0.0f, 0.0f, 0.0f);  // metallic: a dielectric
}
