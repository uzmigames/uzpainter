# Tunic v10 input inventory (phase2.10 items 2.6 and 2.7)

Bounded verification on 2026-10-23, using only the sources already identified in decisions 194, 215 and 300. Assets3D was read only. No drive, recycle-bin or worktree sweep was repeated. This record contains identities and status, not oracle pixels or private input bytes.

## Preserved inputs

All ten files below are present in the documented `Creatures/Undead/Skeletal Mage/Models3D/18-Tunica/` folder. Each file's SHA-256 was recomputed and its private content-addressed blob was compared byte for byte. All match. The SPP also matches the piece manifest's verified pin; the older report SPP pin is not substituted.

| File | SHA-256 |
|---|---|
| `18-Tunica-v10.spp` | `c43db46a2f2d4d935fa33cd62956ce7b4d097f00b45c93798ef9f498b27153a6` |
| `18-Tunica-v10.blend` | `f6243a577f673c2b00e5803c256cebfbe933187810b7446f81d56827f0d92cb9` |
| `report.json` | `7829b2add3961e6916bfba32fdea470c3736c2f060636fd8a03b0272a982af5f` |
| `Export/18-Tunica-v10.fbx` | `ad7ef061e244a52f51a5f99af7df028ac4e7f7f80d5f0b68fee06dc374230e0a` |
| `Export/18-Tunica-v10.glb` | `4b5e0d652275646bb3e670c4f1cf7803d31f02b41c3f5012b8a7d178cd68fdd1` |
| `Textures/DefaultMaterial_BaseColor_sRGB.png` | `6526ac1658c96599837b5d71dbf3673175d0a544f3b7e2b48e90ceb01f04f21b` |
| `Textures/DefaultMaterial_Displacement_Raw.png` | `86c9f07fde9493a03a9f6cc0628d74504d11ab8d8cbb916426f7a7268e71f567` |
| `Textures/DefaultMaterial_Metallic_Raw.png` | `d915331ab8750d70eed2630ced1cd2f9b6ed2adc11b1fdc5da7d9a720e799853` |
| `Textures/DefaultMaterial_Normal_Raw.png` | `87ffb58b3da22fbcacf1ec3e12787e2b20e1bc23dc2707a5f070a368549eab37` |
| `Textures/DefaultMaterial_Roughness_Raw.png` | `35f034252deb9d3a31fc67aa85e8ef9e211ffc42664ffe8fd4ef3c9f6fe86d60` |

The eight recovered masks and Normal named by `tools/parity/recorder/tunic.py` (`RECOVERED`, `NORMAL`) are also available in the private store. Their SHA-256 pins were recomputed, their SHA-1 values match the report's resource versions, and each version occurs in decision 215's admitted private readback:

| Binding | Verified SHA-1 / resource version |
|---|---|
| `M_band` | `45203ad9bd2f92154972c1ea65dc681060ea33fb` |
| `M_embro` | `ee39f50a2363c2255926937c2446307205e38250` |
| `M_hemband` | `53e97a5427f3ead643798e1ade87dca678df4c85` |
| `M_lacerings` | `8f29b7fe1b4eb7d7337ed487524b3e000da30b62` |
| `M_laceholes` | `d3be1b18a8715fc0a2737893cf80d6037219ebb8` |
| `M_hemline` | `00326e6cdcc1a235f955d3b534238a6b3d5acb27` |
| `M_piping` (C07) | `68ac4eba0a92fd6a6f83a0fc3cc921a151d79ff5` |
| `M_piping_lining_v9` (F03) | `ccf4857c52a839ba7829bae5a0cad4ae2a0a8019` |
| `Normal` | `a5de3314c3cd418bea85372801e771e668437b92` |

## Missing originals

Each documented `_tmp/claude/<name>.png` path remains absent. These known SHA-1 versions come from decision 215's admitted readback and are recovery requirements, not recovered files. Original SHA-256 values remain unknown here.

| Missing mask | Required SHA-1 / resource version |
|---|---|
| `M_pores` | `ca318d8c888a8246dcfc2ee95f7698e228505369` |
| `M_fiber` | `81ddd3abac874483f2fd3cbe872bd60115f24381` |
| `M_dyeinv` | `d76b451425e273a49c7ac754ed4d0aea46dfc1b6` |
| `M_stains` | `1804df372e7bfee68d5e96759adcbdacb702d1ad` |
| `M_fray` | `ecd61cfa9ef786d7f899afe6c6d94874edba2b09` |
| `M_hem` | `e5b4689bc3c3f2b117bccc95e60aa611a47f3a11` |
| `M_cav` | `e1860edfbb356a7987797e137b9e0fb940c9d243` |
| `M_ridgewear` | `b0dd141864f992fc3894ab7329580c7d752ff4fd` |
| `M_lining` | `61f509bc8c93a53328f70d35bb3f4740c843ba3b` |

The readback's `_tmp/astra-tunica/normalized_low.obj` path also remains absent; its original hash is unknown. The preserved FBX and blend are available sources, but this inventory proves neither original OBJ identity nor geometry/UV equivalence. No new source justifies another disk sweep.

## Request, reference and scope

The admitted manifests retain the authored request's inputs, instruction sequence and export configuration. `parity/fixtures/tier1/tunic-v10/export-config.json` remains pinned by SHA-256 `7167a93ec10baf82f6d394efff7ea91d3f525b747ed1a71b47dc5bc75b846de8`. `store verify` passes all 17 private record references in each of:

- `parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/phase2/tier1/tunic-v10.json`: golden record `afa1309ace69d4a82b1c4e37eb0e6d9072b3c7d2359b300f314f540525803670`.
- `parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/manifests/phase2/tier1/tunic-v10.json`: golden record prefix `59ef801eaf67`.

Both oracle environment records are available. All five golden map hashes are unchanged between these envelopes and remain identical across r1, r1-repeat and r2. Delivered maps remain a cross-check; four delivered hashes differ from the golden, so they cannot silently replace it.

Double-sided scope is already settled by decision 196's SUP-030 amendment: preserve the state across save/reopen, with render parity false while enabled and exported maps unchanged. The old unresolved-scope note is historical.

Inventory and preservation do not complete recovery or authorize a changed reference. Decision 300's first qualification retry is `RE_ENCODED`, with no qualified forms: twelve cases re-encode in both conditions and the 2048 grey case writes no file. Nine cases preserve decoded texels, three change them; neither result recovers original file bytes. Nine original masks and original mesh identity remain blockers. Item 2.8, the rebuild, infinite-padding equality and acceptance stay open.

## Owner decision package (item 2.8)

This updates the existing scope question in decision 300 item 8 and the Sash inventory's owner package; it does not create a second request or choose a route. Rulebook's question lists for both pilot tasks contain no separate open question as of 2026-10-23. The pending scope question remains: **may a separately identified current reference be used for a pilot's gate if its original inputs cannot be restored, while retaining the existing approved reference?** The answer must name the pilot; approval for one does not change the other.

| Route | Concrete evidence and work | Scope boundary |
|---|---|---|
| Restore originals | Nine masks must match the SHA-1 versions above; original OBJ identity remains unknown. No new backup location has been supplied. | Restoration needs no new scope decision; current evidence does not complete it. |
| Export original resource files | The 13-case qualification is `RE_ENCODED`; none of the measured forms qualifies. | No missing pilot mask may be accepted through this route. Pixel equality is insufficient. |
| Compare effective mesh through BaseMesh | The documented control in `base-mesh-export-control.md`, commit `416916ac`, completed 18 exports on authored meshes. A separate SPP-versus-delivered-FBX comparison is being prepared. Position/normal changes occur in the control, and the admitted Tunic readback does not record mesh unit scale or project projection settings. | Investigation continues; no claim that an export restores original OBJ bytes or that the delivered FBX is equivalent. |
| Record `phase2/tier1/tunic-v10-current` | Decision 300 item 7 specifies unchanged sync, the F03 override, preserved inputs and named regenerated substitutes for unrecovered masks. Compare every new map with the retained migration golden and list differences. | Technical recording does not authorize using the result as a changed G2 baseline. The owner's explicit recorded approval is required for that use. |
| Retain the current gate, replace or exclude the pilot | Retaining the gate leaves input recovery and parity open. Replacement or exclusion changes the required evidence. | Replacement or exclusion requires an explicit scope decision; no route is selected here. |

The existing migration golden and all five map hashes remain unchanged. Double-sided scope is already settled by decision 196; this question does not reopen it. Item 2.8 remains open until restored identity or the required explicit scope decision is recorded. A concrete new-reference comparison has not yet been produced, so this package is preparation, not a request to approve unseen results.
