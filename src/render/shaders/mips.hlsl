// Alpha-coverage preservation of mip generation (src/render/mips.h). Integer arithmetic only.
// The state buffer holds the histogram of a level's alpha codes (bins 0..M), the selection
// results, then one word per row of the level (tie counts, then their exclusive prefix).
//
// ClearMain      zeroes g_count entries from g_offset
// CountMain      counts the level-0 texels whose alpha code is >= the cutoff code K
// HistogramMain  histogram of the alpha codes of a filtered level
// SelectMain     one thread: the target count, the boundary code t of the target-th texel in
//                descending alpha order, how many of its texels are covered (r), and the divisor
//                u of the scaling alpha' = min(M, floor(alpha K / u))
// RowCountMain   one thread per row: the row's texels with alpha == t when t is split
// PrefixMain     one thread: exclusive prefix of the row counts
// ApplyMain      one thread per row, texels left to right: scaled alpha, and for a split t the
//                first r texels of t in linear order covered (K), the others not (K - 1; 0 for
//                t = 0)

#include "image_common.hlsli"

#define STATE_COUNT0 65536u
#define STATE_DIVISOR 65537u
#define STATE_TIE 65538u
#define STATE_TIE_COVERED 65539u
#define STATE_TARGET 65540u
#define STATE_ROWS 65544u
#define NO_TIE 0xFFFFFFFFu

cbuffer Params : register(b0) {
    uint g_width;
    uint g_height;
    uint g_enc;
    uint g_srcSrv;
    uint g_dstUav;
    uint g_stateUav;
    uint g_cutoff;      // K, the smallest covered alpha code
    uint g_level0Texels;
    uint g_offset;      // ClearMain
    uint g_count;       // ClearMain
};

uint AlphaCode(int2 p) {
    const float4 texel = LoadTexel(g_srcSrv, p);
    return Codes(texel, g_enc).w;
}

[numthreads(64, 1, 1)]
void ClearMain(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_count) return;
    RWStructuredBuffer<uint> state = ResourceDescriptorHeap[g_stateUav];
    state[g_offset + id.x] = 0u;
}

[numthreads(8, 8, 1)]
void CountMain(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_width || id.y >= g_height) return;
    RWStructuredBuffer<uint> state = ResourceDescriptorHeap[g_stateUav];
    if (AlphaCode(int2(id.xy)) >= g_cutoff) InterlockedAdd(state[STATE_COUNT0], 1u);
}

[numthreads(8, 8, 1)]
void HistogramMain(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_width || id.y >= g_height) return;
    RWStructuredBuffer<uint> state = ResourceDescriptorHeap[g_stateUav];
    InterlockedAdd(state[AlphaCode(int2(id.xy))], 1u);
}

[numthreads(1, 1, 1)]
void SelectMain(uint3 id : SV_DispatchThreadID) {
    RWStructuredBuffer<uint> state = ResourceDescriptorHeap[g_stateUav];
    const uint m = UnormMax(g_enc);
    const uint64_t texels = uint64_t(g_width) * uint64_t(g_height);
    const uint64_t n0 = g_level0Texels;
    // Nearest of count0 N_k / N_0, ties down.
    const uint64_t target = (2 * uint64_t(state[STATE_COUNT0]) * texels + n0 - 1) / (2 * n0);
    uint divisor = m + 1u;
    uint tie = NO_TIE;
    uint covered = 0u;
    if (target > 0) {
        uint64_t above = 0;  // count(alpha > t)
        uint t = m;
        for (;; --t) {
            const uint64_t bin = state[t];
            if (above + bin >= target || t == 0u) break;
            above += bin;
        }
        const uint64_t bin = state[t];
        covered = uint(target - above);
        if (t == 0u || covered < bin) {
            tie = t;
            divisor = max(t, 1u);
        } else {
            // The whole bin is covered: any divisor in (next lower used code, t] separates the
            // covered texels; the one closest to K (K itself leaves alpha unchanged).
            uint lower = 1u;
            for (uint s = t; s > 0u; --s) {
                if (state[s - 1u] != 0u) {
                    lower = s;
                    break;
                }
            }
            divisor = clamp(g_cutoff, lower, t);
        }
    }
    state[STATE_DIVISOR] = divisor;
    state[STATE_TIE] = tie;
    state[STATE_TIE_COVERED] = covered;
    state[STATE_TARGET] = uint(target);
}

[numthreads(64, 1, 1)]
void RowCountMain(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_height) return;
    RWStructuredBuffer<uint> state = ResourceDescriptorHeap[g_stateUav];
    const uint tie = state[STATE_TIE];
    uint count = 0u;
    if (tie != NO_TIE) {
        for (uint x = 0; x < g_width; ++x) count += AlphaCode(int2(x, id.x)) == tie ? 1u : 0u;
    }
    state[STATE_ROWS + id.x] = count;
}

[numthreads(1, 1, 1)]
void PrefixMain(uint3 id : SV_DispatchThreadID) {
    RWStructuredBuffer<uint> state = ResourceDescriptorHeap[g_stateUav];
    uint running = 0u;
    for (uint y = 0; y < g_height; ++y) {
        const uint count = state[STATE_ROWS + y];
        state[STATE_ROWS + y] = running;
        running += count;
    }
}

[numthreads(64, 1, 1)]
void ApplyMain(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_height) return;
    RWStructuredBuffer<uint> state = ResourceDescriptorHeap[g_stateUav];
    const uint m = UnormMax(g_enc);
    const uint divisor = state[STATE_DIVISOR];
    const uint tie = state[STATE_TIE];
    const uint covered = state[STATE_TIE_COVERED];
    uint rank = state[STATE_ROWS + id.x];
    for (uint x = 0; x < g_width; ++x) {
        const int2 p = int2(x, id.x);
        float4 texel = LoadTexel(g_srcSrv, p);
        const uint alpha = Codes(texel, g_enc).w;
        uint adjusted;
        if (alpha == tie) {
            adjusted = rank < covered ? g_cutoff : (tie == 0u ? 0u : g_cutoff - 1u);
            ++rank;
        } else {
            adjusted = min(m, (alpha * g_cutoff) / divisor);
        }
        texel.w = CodeValue(adjusted, g_enc);
        StoreTexel(g_dstUav, p, texel);
    }
}
