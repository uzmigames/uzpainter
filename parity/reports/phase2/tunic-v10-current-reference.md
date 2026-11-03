# Tunic v10 current reference against the migration golden

`python -m tools.parity.tier1.current_reference` (decision 300 item 7), run once on 2026-11-03 against the admitted `phase2/tier1/tunic-v10` migration golden and the admitted `phase2/tier1/tunic-v10-current` round. The comparator's full JSON report (SHA-256 `61b38a4fede40bba91863b0f9288615a101835f36f281d0226be176e9adab249`) is kept in the private oracle work area beside the run, because no public schema covers it; this summary carries its aggregate figures. It holds identifiers, hashes, shapes and counts only, never a pixel, coordinate or map hash.

**Outcome: `different`.** One of the five maps is byte-identical.

| Map | Bytes equal | Values equal | Differing values | Max abs diff (16-bit) |
|---|---|---|---:|---:|
| BaseColor_sRGB | no | no | 3,301,154 | 1,884 |
| Normal_Raw | no | no | 3,423,291 | 128 |
| Metallic_Raw | yes | yes | 0 | 0 |
| Roughness_Raw | no | no | 4,479 | 257 |
| Displacement_Raw | no | no | 284,649 | 3 |

Each map is 4096 × 4096 × 3, PNG 16-bit, on both sides.

- **Stability.** Both sides are stable: `r1`, `r1-repeat` and `r2` are byte-identical within each side, for all five maps.
- **Structure.** There are no structural differences: the same maps, storage formats and shapes.
- **Envelope.** The two environment records `match`.
- **Problems.** None.

**Sides.**
- The current round: record `3165bacb…2d1e`, manifest `e3b69e54…129d`, request `7364fafe…93a7`, recorded after the recorder's named-import fix `52a182da`.
- The migration golden: record `59ef801e…01bf`, manifest `ce702ddf…de31`.

**What this does not establish.**
- The current round runs on current-round substitutes: 9 masks, the AO behind them, and a low exported now. Only the 8 preserved masks and the Normal are originals. The historical inputs stay missing, so `historical_input_identity_established` is false. Equal outputs would not prove input identity either.
- The admitted record observes the create's slots and the Normal's identity, not the layer stack. The supplementary record below observes the stack.
- No baseline is changed or promotable, no exception is recorded, and no gate or acceptance item is completed. Using the current round as phase2.10's changed baseline is the owner's decision (decision 300 item 8).

## Supplementary state-qualified record (2026-11-03)

This record is separate from the admission above. It is content-addressed evidence, not a second golden record: the admitted manifest, its private records and the comparison above are unchanged.

- **Run.** The same request `7364fafe…93a7`, recorded again after the recorder's state readback (`bf2d57bb`). Record `7663d8ac374637d40a88c7b694a5b6055103f0a354f51a74b254ab5e01aca1df`. It is kept in the private store with its run manifest and every blob it names, each re-hashed after storing, because the write-once store refuses a second record under the admitted manifest's record id.
- **Maps.** All five maps of `r1`, `r1-repeat` and `r2` are byte-identical to the admitted record `3165bacb…2d1e`, so the comparison above holds for this record unchanged.
- **Observed layer stack**, read back from Painter in `r1` (after the save) and in `r2` (after the reopen), before each export, and checked against the pinned stack and the sync's reply:
  - 21 mask bindings onto 17 distinct resources, every one in colour space Data, each URL equal to the sync's, version included;
  - F03 and C07 on distinct resources;
  - height blends: Forro Normal, Tecido externo LinearDodge, and the titled group LinearDodge;
  - exactly one hidden default layer (`Layer 1`) beside the synced group;
  - the staged mesh as the last imported mesh.
  `r2` equals `r1` once project contexts are renumbered and the project file path is checked.
- **Environment.** It differs from the admitted record's only in the recorder version.
