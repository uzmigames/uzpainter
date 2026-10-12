# `phase1.20_pyapi-facade`: local run on the owner's machine

This task is a child of `phase1.24_python-api-facade` (P1-PYAPI; `docs/architecture/10-python-api.md` §0, §1, §3, §4; OWN-04, ARC-03, ARC-13, PRJ-05, LAY-01, INT-01). Under decision 028 its Tier 0 comparison runs locally against the private oracle store. This report is its evidence for `phase1.24_python-api-facade`.

- Run on 2026-10-12, branch `wt/phase1.20-facade`, on main `26f12d7`, current envelope `painter-12.1.5_js-api.1.1.20`.
- Decisions 107 and 108. Implementation: `python/` (`python/FACADE.md`).

## Result

### `tests/python/test_pyapi_facade_tier0.py` (items 3.1, 3.6, 3.7): 9 of 9 pass

The recorder's own Painter-side code runs inside UzPainter's interpreter against the facade. It replays every probe as the recorder records it, and compares outputs exactly with both recordings: readbacks, raised errors (class and message), the effective defaults of inserted nodes, and exported maps on every texel. Normalisations: resource contexts are compared up to the session offset (decision 107 §4), and Painter's empty "Layer 1" is removed from structure readbacks (decision 105).

| Golden | Exact | Excluded (owner) |
|---|---|---|
| `active-channel-reset`, `-superset`, `-order-control` | Every readback and default. The reset reads BaseColor (0.8, 0.8, 0.8) and Height 0, and the control keeps the values. | The exported BaseColor PNG16 (phase1.25_pilot-wand item 2.6, R-090, decision 103). The Height PNG, written (h + 1) / 2 since phase1.18 (decision 103), is compared. |
| `set-source-none-multichannel` | `EditionContextException` "Only valid in mono channel context" on the fill layer. Implicit activation keeps BaseColor. | The content-stack fill effect of s5 and its steps (phase3.2_proc-filter-families). |
| `mask-stack` | Every `None`-rule error: `EditionContextException` "Channel 0 isn't valid in this context", "Only valid in multi channel context", and the `ValueError` blending messages. Also mask defaults, the source, opacity and blending. | The mask-stack levels of s13 and its readbacks (phase4.2_remaining-nodes); BaseColor PNG16 (phase1.25_pilot-wand item 2.6, decision 103). |
| `insert-positions` | Every insertion error whose position exists (s11, s13-s17, s19, s20, s22), plus the groups and sub-layers. | The steps on the refused content fill effects, mask levels and compare mask (s5, s7-s9, s12, s18, s21, s23-s26, s28, s29; decision 081). |
| `fill-layer-readback` (3.7) | Working-space colours s5-s8 and s30-s33, including the sRGB conversion 0.8 to 0.6038274. Available colour spaces s43. Resource ids (SHA-1 version, context). Every other readback. | The exported BaseColor PNG16 (phase1.25_pilot-wand item 2.6, decision 103); the Height PNG is compared. |
| `textureset-project-readback` (3.7) | Everything, including resource ids, `probe.spp`, and `needs_saving` after re-binding a mesh map. | — |
| `export-ocio-encode-legacy` readbacks (3.6) | Implicit sRGB and Raw by channel, sRGB/none/Raw uniforms, bitmap spaces and lists on BaseColor and in a mask, both recordings. | `readback/get_source/29/BaseColor`: the sRGB decode of 70/255, 2 ulp (decision 107 §3, recording P20-B). Its maps are compositor fits (decision 108). |

### `tests/python/test_pyapi_facade.py` (items 3.2-3.8, every lane): 9 of 9 pass

- **Provenance.** 828 public symbols, each documented in the inventory. `_version` is the only private module, and `sp._private_helper` raises `AttributeError`.
- **Desktop-only symbols.** 15 symbols raise `UnsupportedInUzPainter` naming the symbol, the reason and an alternative. The revision is unchanged.
- **Inert state.** Selection, selection type, collapsed groups, the active stack and the UI mode each read back what was set, and `RuntimeError` is raised inside a `ScopedModification`. The exports are byte-identical.
- **`js.evaluate`.** The whitelist maps to native calls. Non-whitelisted expressions and non-literal arguments raise `UnsupportedInUzPainter` with the revision unchanged.
- **Colour.** The implicit space per channel holds and conversions work. The default profile round-trips through save and reopen. An OCIO configuration fails before evaluation and nothing is written.
- **`ScopedModification`.** The calls committed before an exception are kept.
- **Plugins.** A startup module starts, and `close_plugin` runs its `close_plugin()`.
- **Quirks on supported nodes**, matching the native LAY-01 behaviour.

### Other affected tests

- `tests/python/test_pyapi_native.py` and `test_pyapi_tier0.py`: 16 of 16 pass.
- `tests/capabilities` and `tests/parity/recorder/test_provenance.py`: 43 of 43 pass.
- Native evaluator case `not-yet-supported` (`zig build evaluator-tests`, CPU): all 5 checks pass after the refusals were re-owned (decision 108).

## Open

- **Item 1.1.** `phase1.18_export-engine` has not been accepted.
- **Recordings P20-A and P20-B** (decision 107): unrecorded fill-channel defaults and bitmap spaces, and the dense sRGB decode. Owner: phase1.14_compositor-core.
