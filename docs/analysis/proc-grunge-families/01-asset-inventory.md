# Grunge and noise asset inventory (phase3.2_proc-grunge-families item 2.1)

The grunge, dirt, spots, scratches, rust, humidity and cracks procedurals that the UzmiGames recipes reference, plus `fabric_linen`, each with the UzPainter asset that will reproduce it and the parameter sets the recipes record. Written 2026-10-20 from the recipe files of `E:\UzmiGames\Assets3D` (read only). The family is implemented in `src/procedural/grunges.h` (item 2.3) and the domains are declared in `assets/procedural/records/grunge.*@1.json` (item 2.6).

## Sources read

| Recipe | File and key | What it records |
|---|---|---|
| Body v3 | `Creatures/Undead/Skeletal Mage/Models3D/00-Corpo/report.json` → `painting_v3.smart_layers` (Cranio, Tronco, Membros) | grunge masks by Painter name, their projection scale (`tiling`) and the Levels of the mask (`levels`); no source parameter and no seed |
| Hat | `Creatures/Undead/Skeletal Mage/Models3D/10-Chapeu/report.json` → `painter_recipe.node_details` | every procedural source with its parameters and `$randomseed`, read back through the documented `SourceSubstance.get_parameters` |
| Bracer v1, belt v1 | `22-Bracal-Direito/report.json` → `painting.stack_top_to_bottom["CRAQ Couro craquelado"]`; `23-Cinto/report.json` → same key | the cracks grunge (no crack grunge is in the body or hat recipes) |
| Sash v1 | `25-Faixa-Cintura/report.json` → `painting.stack_top_to_bottom["TRAMA Fios claros"]` | `fabric_linen` as a light-thread mask |

Assumptions:
- The "cracks" row of `05-procedural-content.md` §3 is `cracks_leather`. The body and hat recipes use no crack grunge: their cracks are the Edge Dirty Cracks smart mask, which is the smart-mask family. The bracer and belt recipes are its only users. The locked bracer recipe r9 does not use it: round r3 replaced it with a 3D mask (`painting_r3.fine_crackle`).
- `fabric_linen` is inventoried as the sash recipe uses it: a single-channel thread pattern under a Levels effect. The tunic recipe uses it as a full material (`18-Tunica/report.json`). That use belongs to the materials family (`phase3.2_proc-material-families`).
- A recipe's `tiling`, `scale` or triplanar scale is the fill's projection (`uv_transformation.scale`, the triplanar scale), not a parameter of the asset. The body recipe's 3.5 is not an integer, which confirms it. The projection belongs to the fill effect, and these assets output one tile of the texture.
- The `levels` triples (input min, input max, gamma) belong to a Levels effect over the mask, not to the asset.

## Assets

Every asset is `uzasset://grunge/<id>@1`, usage `PROCEDURAL`, status `unavailable`. The Painter column is the name the alias will carry once the asset is `exact`. No alias is registered now: decision 324 lets an alias name only an `exact` asset.

| UzPainter asset | UzPainter name | Painter asset (future alias) | Used by |
|---|---|---|---|
| `grunge/rock` | UzPainter Rock Grunge | `grunge_rock` | body (3 sets) |
| `grunge/stone-details` | UzPainter Stone Details Grunge | `grunge_stone_details` | body (3 sets) |
| `grunge/dirt-large` | UzPainter Large Dirt Grunge | `grunge_dirt_large` | body (3 sets) |
| `grunge/dirt-spots-small` | UzPainter Small Dense Dirt Spots | `dirt_spots_dense_small` | body (3 sets) |
| `grunge/spots-bw-a` | UzPainter Black and White Spots A | `bnw_spots_2` | body (3 sets), hat |
| `grunge/spots-bw-b` | UzPainter Black and White Spots B | `bnw_spots_3` (ratio variant) | hat |
| `grunge/dirt-a` | UzPainter Dirt A | `dirt_1` (ratio variant) | hat |
| `grunge/scratches-fine` | UzPainter Fine Scratches | `grunge_scratches_fine` | body (3 sets) |
| `grunge/scratches` | UzPainter Scratches | `grunge_scratches` | hat |
| `grunge/scratches-dirty` | UzPainter Dirty Scratches | `grunge_scratches_dirty` | hat |
| `grunge/rust-fine` | UzPainter Fine Rust | `grunge_rust_fine` | hat |
| `grunge/humidity` | UzPainter Humidity | `grunge_humidity` | hat |
| `grunge/map-a` | UzPainter Grunge Map A | Grunge Map 009 (ratio variant) | hat |
| `grunge/map-b` | UzPainter Grunge Map B | Grunge Map 012 (ratio variant) | hat (2 uses) |
| `grunge/spots-soft` | UzPainter Soft Spots | `gaussian_spots_2` | hat |
| `grunge/cracks-leather` | UzPainter Leather Cracks | `cracks_leather` | bracer v1, belt v1 |
| `grunge/linen` | UzPainter Linen Weave | `fabric_linen` | sash v1 |

## Recorded parameter sets

The UzPainter parameter set of every asset is `balance`, `contrast`, `invert` and `tiling`, plus the extras named below (`src/procedural/grunges.h`). Painter's parameter names, ranges and labels are not discovered yet (item 2.2). The mapping below is by name only. It says which UzPainter parameter a recorded value would set; it does not claim the two have the same meaning. Item 2.2 confirms or replaces it, and calibration (item 2.4) fits it. A recorded parameter with no UzPainter counterpart is listed as such. A request that carries it is refused as outside the domain until the domain is revised.

Seeds are the recorded `$randomseed`. "Not recorded" means the recipe file holds none.

### Body v3 (all three texture sets)

The body recipe records no source parameter and no seed. Its parameter set is the asset defaults. Projection scales and mask Levels are listed for the recipe's own replay.

| Asset | Projection scale | Mask Levels (in min, in max, gamma) |
|---|---|---|
| `grunge/rock` | 2.0 | 0.3, 0.8, 1.0 |
| `grunge/stone-details` | 6.0 | 0.3, 0.8, 1.0 |
| `grunge/dirt-large` | 3.5 | 0.55, 0.9, 1.0 |
| `grunge/dirt-spots-small` | 8.0 | none |
| `grunge/spots-bw-a` | 10.0 | 0.55, 0.85, 1.0 |
| `grunge/scratches-fine` | 4.0 | 0.65, 0.95, 1.0 |

### Hat (`painter_recipe.node_details`)

| Asset | Node (uid) | Seed | Recorded parameters → UzPainter parameters | No counterpart |
|---|---|---|---|---|
| `grunge/spots-bw-b` | Mask Editor (2591) input `texture` | 30095 | `histogram_position` 0.5 → `balance`; `historgram_contrast` 0.0 → `contrast`; `invert` 0 → `invert`; `Disorder` 0.0 → `disorder` | `tile_by_ratio` 0 |
| `grunge/dirt-a` | Mask Editor (2591) input `texture_sec` | 13110 | `histogram_position` 0.5 → `balance`; `historgram_contrast` 0.0 → `contrast`; `invert` 0 → `invert`; `Disorder` 0.0 → `disorder` | `tile_by_ratio` 0 |
| `grunge/rust-fine` | Mask Editor (2106) input `texture` | 0 | `balance` 0.5; `Contrast` 0.0 → `contrast`; `invert` 0 | — |
| `grunge/map-a` | Grunge Map 009 (703), UV scale 5 | 11538 | `balance` 0.6; `contrast` 0.5; `invert` 0 | `tile_ratio` 0, `brush_pattern` 0.0 |
| `grunge/map-b` | Grunge Map 012 (637), triplanar scale 4 | 0 | `balance` 0.5; `contrast` 0.5; `invert` 1 | `tile_ratio` 0, `brush_pattern` 0.0 |
| `grunge/map-b` | Fill (490), roughness channel, triplanar scale 3, rotation 45 | 27210 | `balance` 0.3; `contrast` 0.5; `invert` 1 | `tile_ratio` 0, `brush_pattern` 0.0 |
| `grunge/spots-soft` | gaussian_spots_2 (630), triplanar scale 8 | 0 | `Disorder` 0.0 → `disorder` | — |
| `grunge/spots-bw-a` | BnW Spots 2 (514), UV scale 3 | 24464 | `Disorder` 0.0 → `disorder` | — |
| `grunge/scratches` | Mask Editor (911) input `texture` | 0 | `balance` 0.2; `contrast` 0.5; `invert` 0; `rotation_variation` 360.0 | `brush_pattern` 0.0, `random_mode` 0 |
| `grunge/scratches-dirty` | Mask Editor (911) input `texture_sec` | 0 | `balance` 0.41; `Contrast` 0.83 → `contrast`; `invert` 0 | — |
| `grunge/humidity` | Umidade irregular - projecao continua (2732), triplanar scale 1 | 19 | `Balance` 0.54 → `balance`; `Contrast` 0.62 → `contrast`; `Invert` 0 → `invert`; `Flip_Horizontal` 0 → `flip_horizontal`; `Flip_Vertical` 0 → `flip_vertical`; `tiling_amount` 1 → `tiling` | `rotate_by_45_degrees` 0 |

Values are as recorded (float32 read back as doubles, e.g. 0.6000000238418579 for 0.6); the table rounds them.

### Bracer v1 and belt v1 (`cracks_leather`)

| Recipe | Projection | Seed | Recorded parameters → UzPainter parameters | Mask Levels |
|---|---|---|---|---|
| Bracer v1 | triplanar, scale 8 | not recorded | `hardness` 0.8; `shape` 0.75; `invert` 0 | 0.42, 0.6, 1.0 |
| Belt v1 | tiling 24 | not recorded | `hardness` 0.8; `invert` 0 | 0.55, 0.8, 1.0 |

### Sash v1 (`fabric_linen`)

| Recipe | Projection | Seed | Recorded parameters | Mask Levels |
|---|---|---|---|---|
| Sash v1 | tiling 3.0 | not recorded | none (`params: {}`): the defaults | 0.6, 0.8, 1.0 |

## What this inventory does not settle

- Painter's parameter names, ranges, labels and defaults (item 2.2). The UzPainter domains in `assets/procedural/records/grunge.*@1.json` use UzPainter's own names and ranges until then.
- Whether a "ratio" variant (`ratio_bnw_spots_3`, `ratio_dirt_1`, `ratio_grunge_map_009`, `ratio_grunge_map_012`) differs from the plain asset. Only the ratio variants are recorded, and the inventory names one UzPainter asset for each.
- The aliases themselves. They are registered in `assets/procedural/aliases.json` only when the asset is `exact` (decision 324).
