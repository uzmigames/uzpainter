# Export resource qualification (decision 300)

Painter build `12.2.0+js-api.1.1.20`, colour management `ocio`, run `2026-10-23T09:38:26.214867+00:00`.

**Verdict: RE_ENCODED** (no case is exact: re-encoded files are written, and every other case wrote nothing or offered no enabled menu item). Qualified forms: none. Exact format classes: none. Pilot forms exact: no. Unresolved cases: none. Fresh process for B: yes; every source verified absent: yes.

| Case | Class | Version = SHA-1 at import | A (source present) | B (source removed) | Version stable | Fields that differ |
|---|---|---|---|---|---|---|
| `png8-rgb-srgb` | png | no | re-encoded | re-encoded | yes | bytes |
| `png8-grey-linear` | png | no | re-encoded | re-encoded | yes | bytes |
| `png8-rgba-plain` | png | no | re-encoded | re-encoded | yes | bytes |
| `png16-rgb-linear` | png | no | re-encoded | re-encoded | yes | bytes |
| `png16-rgb-blender` | png | no | re-encoded | re-encoded | yes | bytes |
| `png16-grey-pillow` | png | no | re-encoded | re-encoded | yes | bytes |
| `png16-grey-2048` | png | no | no-file | no-file | yes | - |
| `png8-rgb-pillow` | png | no | re-encoded | re-encoded | yes | bytes |
| `tga8-rgb-raw` | tga | no | re-encoded | re-encoded | yes | bytes, container |
| `tga8-rgba-rle` | tga | no | re-encoded | re-encoded | yes | bytes, container |
| `exr-half-rgb-zip` | exr | no | re-encoded | re-encoded | yes | bytes |
| `exr-float-rgba-none` | exr | no | re-encoded | re-encoded | yes | bytes |
| `jpeg-rgb-srgb` | jpeg | no | re-encoded | re-encoded | yes | bytes, container |

Originals (SHA-256) and exports (SHA-256) per condition:

- `png8-rgb-srgb` `bf38651e89044b20850a6b2e2427c2b27062bdc5db81ef041a12ce8dc99833fb`: A `257d4a52723b51fd8b884b79781a1ecd5a6235bbd1b6206c9827b952307d7712`; B `257d4a52723b51fd8b884b79781a1ecd5a6235bbd1b6206c9827b952307d7712`
- `png8-grey-linear` `8a0e81f502deb27148308a8e5f43d0e366de2fdedb1b3ab6e5f74085c72d07d2`: A `5aab413d87013b9c0aee91e7558dea13333ceb9bd67fabc381910804c144f5dd`; B `5aab413d87013b9c0aee91e7558dea13333ceb9bd67fabc381910804c144f5dd`
- `png8-rgba-plain` `2944dca9b5f03c3c53556aaa36b0d14f4473193e9460cd4f23ad41964604b0d3`: A `eac2f08aa0c59c99b518acc605ba3947f68a44d399b9266307c3522bb70f3dd9`; B `eac2f08aa0c59c99b518acc605ba3947f68a44d399b9266307c3522bb70f3dd9`
- `png16-rgb-linear` `21860f9eff6b970edb592a0e88816eb28451bfb55dd07389aa3f65b6bbc677fc`: A `e6e771096092e3ce741aa26943c9ec33dfa5264b300ee9439385457bcc85f93c`; B `e6e771096092e3ce741aa26943c9ec33dfa5264b300ee9439385457bcc85f93c`
- `png16-rgb-blender` `57ea96ac93acab5155719b913b1dd23f9d2b9043daeb2a3e658256599407b701`: A `e033d562ec187d9fb41134c34d8e112cb05a72cd545c9ea05a6c52a37fa21f69`; B `e033d562ec187d9fb41134c34d8e112cb05a72cd545c9ea05a6c52a37fa21f69`
- `png16-grey-pillow` `3ea0661a98fd77a4cd81d8a9ce33d7136da3fa6c1e68d4c6ec01c264cb61ef2e`: A `d049210c6c44c218fe752ad8bbf54a3680244cc1c1af11ac45099c6c81a3dac2`; B `d049210c6c44c218fe752ad8bbf54a3680244cc1c1af11ac45099c6c81a3dac2`
- `png16-grey-2048` `f710f70a51ba732e05ce6b0a87d9443b42935263027674da02bf19b837e0d7d5`: A none; B none
- `png8-rgb-pillow` `de4050c23a7ea3da17fe1ef729a96593493ab6d0412e6cf644350e99006eda6f`: A `06939e5444cac72a372f070c5cfc50c8c101cde45dccd58761474765b92c6f94`; B `06939e5444cac72a372f070c5cfc50c8c101cde45dccd58761474765b92c6f94`
- `tga8-rgb-raw` `61dc7f3d4a7b70456569788f2be324652079f35a7df6f77409a058239269a64b`: A `82b80d72d42dc3e6eda40462fa0887aaba723943b5ce6aa7d35b27def8ebe1ad`; B `82b80d72d42dc3e6eda40462fa0887aaba723943b5ce6aa7d35b27def8ebe1ad`
- `tga8-rgba-rle` `2be8cb5cb73f14d81ad320d0992a341c4ec9b755d03cd68e758dcc036a0c88af`: A `b765d3ce3c1a0110447eb6fa830e24b8844c528180c61d513d94deee5b62df72`; B `b765d3ce3c1a0110447eb6fa830e24b8844c528180c61d513d94deee5b62df72`
- `exr-half-rgb-zip` `77c751ebb61eae17ef98fe8e3866ad2e3eaff8e4c11ac850956b0527a5a20dd4`: A `7d09de3ed624e0f15440a13a2fcf3bd0e8c881c4436df206b70d499859b15d66`; B `7d09de3ed624e0f15440a13a2fcf3bd0e8c881c4436df206b70d499859b15d66`
- `exr-float-rgba-none` `589df2cb27832626f7665e8ebd5444a0a96fb7d569f986c213007510a0f5eb19`: A `8f9af43b37067d8213725ab90f038dcbafcbc85421453fe1fa7df09e25af5304`; B `8f9af43b37067d8213725ab90f038dcbafcbc85421453fe1fa7df09e25af5304`
- `jpeg-rgb-srgb` `ce5324eff6594c81aba1084da9cd2616209b4e2a9829fe8e2c68acbc0a9af968`: A `41a8f6d5abfb08bb88ed58348c3ecdf8c43b73220648dfccb2cc7d1e9ff70dd4`; B `41a8f6d5abfb08bb88ed58348c3ecdf8c43b73220648dfccb2cc7d1e9ff70dd4`
