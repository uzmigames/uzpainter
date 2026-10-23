# Sash v5 input inventory (phase2.9 item 2.6)

One bounded inventory of the Sash v5 (`25-Faixa-Cintura` v5) round inputs, taken on 2026-10-20 at Assets3D `a6eaf6a5`. It reuses the searches of decisions 192 and 260 and adds only the sources named below. Assets3D was read, never written. This page holds paths, numbers and hashes only: no input bytes and no Painter pixels.

**Result: the original Tier 1 request still cannot be written.** All 22 paths the request generator needs are missing. Four more bindings (mesh, MTL, Normal, AO) are unresolved because only the lost create arguments name them. Every file that survives is in the private store, and its hash checks out.

## Sources checked

| # | Source | Result |
|---|---|---|
| 1 | Round folder `_tmp/claude/cintura-v5/` | present, empty (last modified 2026-10-12) |
| 2 | Piece folder `Creatures/Undead/Skeletal Mage/Models3D/25-Faixa-Cintura/`, with `Textures/Swatches/` | the 20 files of decision 260 are present, with the same hashes as their stored copies; the two swatch originals are absent |
| 3 | `_tmp/astra/paint-swatches/` | absent (this was the Belt's swatch folder; the sash's swatches were in the piece's `Textures/Swatches/`) |
| 4 | Assets3D git history, all refs, for both swatches and `_tmp/claude/cintura-v5/` | no commit; `Textures/` is git-ignored (`.gitignore:30`) |
| 5 | Assets3D working tree and its 20 agent worktrees (`.claude/worktrees/`), searched by name: `painter_create_args.json`, `painter_export_args.json`, `*_low.obj`, `T_sash*`, `T_belt*`, `masks-sash`, `masks-belt`, `cintura-v5`, `paint-swatches`, `M_hem*.png` | no sash file; the only hits are other rounds' committed arguments files and Lich masks |
| 6 | `E:/UzmiGames/Assets3D-Arquivo` | absent |
| 7 | Private store, inputs | 90 entries; the sash's 29 are listed below. None of them is a mask, `T_sash`, a swatch, an arguments file, the mesh or the AO |
| 8 | Private store, corpora | no `phase2/tier1/sash-v5*` record. The only phase2 golden is `phase2/tier1/tunic-v10` |
| 9 | Oracle work `resource-export-qual/` | no run yet (decision 300's qualification is still pending) |

Not repeated, because no new source was found: the drive search of C to G and the recycle bin check (decisions 192 and 260).

## Request generator

`python -m tools.parity.recorder.script_run manifest --pilot sash --assets-root E:/UzmiGames/Assets3D --out <scratch>` exits 2 and lists 22 missing paths, all under `_tmp/claude/cintura-v5/`:

- `painter_create_args.json` and `painter_export_args.json`;
- `paint/masks-sash/`: `M_band`, `M_band_seam`, `M_band_stitch`, `M_band_top`, `M_beltgrime`, `M_cav`, `M_crest`, `M_dust`, `M_fibers`, `M_hem`, `M_hem_crack`, `M_hem_grain`, `M_hem_grime`, `M_hem_top`, `M_inner`, `M_seam`, `M_tab_edge`, `M_tab_var`, `M_weave` (19 masks) and `T_sash` (all `.png`).

Unresolved bindings: the mesh, its MTL, the Normal and the AO. Only the lost create arguments name them, so they cannot be listed until that file is restored.

## Inputs present and stored

The SHA-256 below is the full value, given also as its first 12 hex digits. Each disk file equals its stored copy. "v5.json" means the file equals the hash that the piece manifest `manifests/v5.json` pins for it.

| Path (Assets3D) | SHA-256 | SHA-1 | Bytes | Identity |
|---|---|---|---|---|
| `25-Faixa-Cintura/25-Faixa-Cintura-v5.spp` | `0691cc120714` | `3fd342a8aab5` | 74,544,892 | v5.json, report.json |
| `25-Faixa-Cintura/25-Faixa-Cintura-v5.blend` | `4c770d1dcf1f` | `22d9556ef6d4` | 9,748,913 | v5.json; **not** report.json (see check 1) |
| `25-Faixa-Cintura/Export/25-Faixa-Cintura-v5.fbx` | `3ed923e0b327` | `ee6f675d5222` | 152,124 | v5.json, report.json |
| `25-Faixa-Cintura/Export/25-Faixa-Cintura-v5.glb` | `5f7057e29182` | `7b6a94bc3ec9` | 21,081,964 | v5.json, report.json |
| `Textures/25-Faixa-Cintura_BaseColor_v5.png` | `3240a374d662` | `ee63d180c6fe` | 8,233,716 | v5.json, report.json |
| `Textures/25-Faixa-Cintura_Normal_v5.png` | `4d1dd8ebd3bd` | `bd7a8d8e83d9` | 12,169,186 | v5.json, report.json |
| `Textures/25-Faixa-Cintura_Roughness_v5.png` | `f55183b682b8` | `8f819ba7a44c` | 327,910 | v5.json, report.json |
| `Textures/25-Faixa-Cintura_Metallic_v5.png` | `537c59bf6206` | `685fddc36da8` | 8,243 | v5.json, report.json |
| `Textures/25-Faixa-Cintura_Height_v5.png` | `996ce6147ed8` | `7bd94f0e6de1` | 2,316,204 | v5.json, report.json |
| `Textures/25-Faixa-Cintura_Normal_OpenGL_bake_v5.png` | `ec05be82d5c5` | `a32d7cb0b6f8` | 11,167,163 | v5.json, report.json `normal_bake.png_sha256` |
| `Textures/Swatches/ref-sash-cloth.png` | `3e36acc9ab7d` | `7d3b0f9b3cad` | 745,050 | stored by decision 260; v5.json does not pin it |
| `Textures/Swatches/ref-hem-tabs.png` | `c30033a744f9` | `7d8c1e673747` | 360,550 | stored by decision 260; v5.json does not pin it |
| `25-Faixa-Cintura/report.json` | `d0692a382f9a` | `0cd795205aab` | 144,121 | **not** v5.json (see check 4) |
| `25-Faixa-Cintura/manifests/v5.json` | `fb6fe0204dba` | `43bbdd172f04` | 25,401 | stored |
| `25-Faixa-Cintura/manifests/v5.input.json` | `959162cb7fc6` | `7e8ea06dbae7` | 14,835 | stored |
| `Pipeline/retopology/waist-v5/painter_create.py` | `f3e01482efaa` | `daddafcbd71d` | 1,897 | same as at its first commit `83e9f43` |
| `Pipeline/retopology/waist-v5/painter_export.py` | `48c294a43cbc` | `7c38632548ce` | 1,822 | same as at its first commit `83e9f43` |
| `Pipeline/retopology/waist-v5/stack-sash.json` | `567e918f97ab` | `5b7a14d56271` | 3,977 | v5.json |
| `Pipeline/painting/painter_layer_stack.py` (decision 260 copy) | `d3eebe58b98b` | `acea5cee66c4` | 21,255 | matches no committed version (see check 3) |
| `Pipeline/production/run.py` (decision 260 copy) | `4a9ef77672b4` | `35e0b2a08d4e` | 115,192 | matches no committed version (see check 3) |
| `Pipeline/retopology/waist-v5/waist_masks.py` | `959eca0bc3e2` | `5fa8e4b30253` | 19,989 | v5.json; stored by item 2.7 |
| `Pipeline/retopology/waist-v5/waist_gen.py` | `15cf7cb9831d` | `ac7b4a9d9a02` | 33,517 | v5.json, report.json `generator.sha256_at_gate`; item 2.7 |
| `Pipeline/retopology/waist-v5/low_gen.py` | `d1153afbbba9` | `ffc3c708c963` | 11,836 | v5.json; item 2.7 |
| `Pipeline/retopology/waist-v5/history/waist_gen_v4b.py` | `64d0d55e26f9` | `b8c4b41fd769` | 22,175 | v5.json; item 2.7 |
| `Pipeline/retopology/waist-v5/swatch-prompts.txt` | `ed63842fbfb3` | `d4377b4ff0dc` | 2,405 | v5.json; item 2.7 |
| `Pipeline/retopology/waist-v5/README.md` | `bce19f5dc298` | `6b70d3a27072` | 3,549 | v5.json; item 2.7 |
| `Pipeline/retopology/waist-v5/round.sh` | `e848dc891289` | `0b90716d5fda` | 2,452 | HEAD `a6eaf6a5`; item 2.7 |
| `Pipeline/retopology/waist-v5/sashchain.sh` | `70ee17308d97` | `67b7fa52a93a` | 2,933 | HEAD `a6eaf6a5`; item 2.7 |
| `Equipment/Skeletal-Mage-25-Vestivel-Faixa-Cintura.png` (the sash's reference) | `29e0b7e1a0e4` | `65bbc453a1ee` | 2,015,585 | v5.json `ref-isolada`; git-ignored; item 2.7 |

In this table, `25-Faixa-Cintura/` and `Textures/` stand for paths under `Creatures/Undead/Skeletal Mage/Models3D/`, and `Equipment/` for `Creatures/Undead/Skeletal Mage/Equipment/`.

Present but not a v5 input: `Textures/25-Faixa-Cintura_Displacement.png` (last modified 2026-10-07, before the v5 round). Neither v5 manifest lists it.

## Missing inputs and what is known about them

| Input | Known identity |
|---|---|
| 19 masks `M_*.png` | No hash was ever recorded. `report.json` `v5.painting.masks` records, at 2048 px over 1,810,564 texels, each mask's mean coverage (for example `M_hem` 0.40632, `M_weave` 0.44819). These are numbers that can corroborate a recovered file, not prove its identity. Inside the `.spp` they are PROJECT resources named `v5f_<name>_<SHA-1[:6]>` (decision 300). Their SHA-1 versions can only be read through a Painter readback. |
| `T_sash.png` (the `base_tex` bitmap of S01 and H01) | Same as the masks. Its recorded mean RGB is [0.172, 0.125, 0.0981]. |
| `Textures/Swatches/sash-cloth-BaseColor-v1.png` | SHA-256 `5ab8cdf3edefbac2f35613bae9b2fbe49fea2754da2c1e8ca8bf5fa32bd518a9` (v5.json `amostra-pano`) |
| `Textures/Swatches/hem-leather-BaseColor-v1.png` | SHA-256 `546bba43d7291d29a70ac2bf26f234f62802feeb8be47d8f1c99a6719a80c5b7` (v5.json `amostra-couro-abas`) |
| `painter_create_args.json`, `painter_export_args.json` | unknown |
| low OBJ and its MTL | File hashes unknown. v5.json names the low object as `25-Faixa-Cintura-v5-Low-Game` in `blend-v5` (4,038 triangles, `UVMap`). `report.json` `v5.low_uv.validation_512` records `geometry_sha256` `e9b68549f4b0…` and `uv_sha256` `aa3b4c9b3909…`. Those are validation digests, not file hashes. |
| Normal mesh map, as imported | It is the `.spp` resource `<name>_Normal_v5`. The candidate copy is `Textures/25-Faixa-Cintura_Normal_OpenGL_bake_v5.png` (SHA-1 `a32d7cb0b6f8…`), which equals the bake's recorded `png_sha256`. It counts as the imported file only if a readback version equals that SHA-1. |
| AO mesh map | unknown; it is the `.spp` resource `<name>_AO_v5` |
| `_tmp/claude/cintura-v5/waist-v5.blend` (the round's geometry gate) | SHA-256 `d9c6de784280dd4403142706e94ae917f68c4c01e8bd513b61ae36a395f45d0b` (`report.json` `v5.geometry.gate_blend`) |
| `Assembly/Skeletal-Mage-TunicCoverage-v1.blend` (the round's base) | SHA-256 `38bed369d18e23681b75ff80b33ad6e175d119e18848bcf0713de2bf5849b0cd` (v5.json `suporte-bancada`); `report.json` gives the prefix `710f2b40`. The two disagree. |

## Unresolved identity checks

1. **The `.blend` changed after the round.** `report.json` `v5.files_sha256` (2026-10-09) records `ecc807202fa9…`. The file on disk, its stored copy and v5.json (revision 6, 2026-10-11) are all `4c770d1dcf1f…`, and the file was last modified on 2026-10-11 at 06:25. Decision 300 item 7 exports the low mesh from the stored `.blend`, so that export comes from a file saved after the round.
2. **The round's script copies are unproven.** The round ran from `_tmp/claude/cintura-v5/` copies; the `.spp` was last modified on 2026-10-09 at 05:06. The waist-v5 scripts were first committed later, at `83e9f43` (2026-10-09 22:10). Since that commit, `painter_create.py`, `painter_export.py` and `stack-sash.json` are unchanged. `waist_masks.py` changed (`ef311abe…` became `959eca0b…`), and so did `round.sh` (`4574278f…` became `e848dc89…`). Nothing proves that the round's copies equal any commit.
3. **The layer-stack and production scripts drift.** The last commit before the round is `aab929b`, where the layer-stack script was at `Docs/Pipeline/Pintura/painter_layer_stack.py` (LF form `dbcc526f…`). The stored copies (`d3eebe58…` for the sash, `bf7006e2…` for the Wand, `4a9ef776…` for `run.py`) match none of the 19 committed versions of those paths, in LF or CRLF form. HEAD is now `1c9a312` (2026-10-20); its working copies are `62702cb3…` and `79afd1ce…`. The generator pins whatever HEAD holds when it runs.
4. **`report.json` was rewritten.** v5.json pins `3aeab8f6…`, but the file on disk (modified 2026-10-12 22:25) and its stored copy are `d0692a38…`.
5. **The Normal and AO bindings, and every mask's and `T_sash`'s resource version, need a readback.** That means a Sash migration readback of a hash-checked private copy of the `.spp` (decision 300 item 6). It is Painter work.

## Owner decision package (item 2.8)

The question is already pending, so it is linked here rather than asked again. Decision 300 item 8 holds it, and so does the supervision file's `owner_decisions` entry "Sash v5". It is one yes/no question, asked once decision 300's qualification has a verdict: **may Sash v5's G2 evidence use a changed baseline, because the original round inputs are lost?** Restoring the originals needs no decision.

| Route | What it gives | What stays missing or changed | Needs |
|---|---|---|---|
| Restore `_tmp/claude/cintura-v5/` or name a backup | the original request (`--pilot sash --store`), then the Tier 1 golden `phase2/tier1/sash-v5` | nothing | the owner's restore; no decision |
| Recover resources from the stored `.spp` (decision 300 item 6, after an `EXACT` or `PARTIAL` qualification) | the 19 masks, `T_sash`, Normal and AO, each accepted only if its SHA-1 equals the readback's version | both arguments files, the low OBJ and its MTL (they are not resources), so the original request still cannot be written | the qualification run and a Sash migration readback (Painter); no decision |
| Pinned current round `phase2/tier1/sash-v5-current` (decision 300 item 7) | a script golden with every input stored first | the low comes from the stored `.blend`, which was saved after the round (check 1). The arguments files are re-authored from the project. Masks not recovered come from today's `waist_masks.py`, which changed after the round (check 2). `T_sash` needs the lost swatches unless it is recovered, so a new `T_sash` would be a named substitute | **the owner's yes** for the changed baseline |
| Migration golden from the stored `.spp` (decision 194 route) | the delivered project's export | it tests the delivered project, not a fresh pipeline run; the rebuild still lacks the arguments files, mesh, AO and masks | the owner's choice (supervision `owner_decisions`) |
| Replace the pilot or exclude it | none | decision 260 found no Skeletal Mage piece with complete inputs | the owner's choice |

No route is chosen here. Missing inputs and the unanswered question never count as a parity pass.

2026-10-23 evidence update: decision 300's first qualification retry is `RE_ENCODED`, with no qualified forms. Twelve cases write re-encoded files in A and B; the 2048 grey case writes none. The conditional original-resource recovery row above therefore remains unavailable. Nine cases preserve decoded texels, but equality of texels does not establish original file bytes. The documented BaseMesh control (`base-mesh-export-control.md`, commit `416916ac`) is a separate effective-geometry investigation with measured losses; it does not restore the low OBJ, MTL or arguments-file identity. The Tunic inventory now carries the linked item 2.8 package with the same scope boundary. Rulebook lists no separate open question for either pilot, so this update reuses decision 300 item 8 without creating a duplicate or recording an answer. No new-reference comparison has yet been produced for approval.
