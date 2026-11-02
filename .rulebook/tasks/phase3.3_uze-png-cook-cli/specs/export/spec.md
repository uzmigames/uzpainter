## ADDED Requirements

### Requirement: UzEngine PNG Cook Through The Preset's Code
UzPainter SHALL provide `UzPainter.exe cook-uzengine`, which cooks a texture set exported as 8- or 16-bit PNG into the UzEngine preset's `.uztexture` set and `.uzmat` through the same derivative cook, mip, BC and material code as the native preset, with the targets of the shipped `uzengine` preset.

#### Scenario: Native canonical maps give the native bytes
Given a native UzEngine export of an authored texture set
When its canonical PNG 16 maps are cooked by `cook-uzengine` with the DirectX convention
Then every `.uztexture` and the `.uzmat` equal the export's files byte for byte

#### Scenario: Equal decoded inputs give equal bytes
Given an 8-bit set and the same images as 16-bit codes * 257, with the normal's green mirrored and the DirectX convention, or the ORM as three grey maps
When both are cooked
Then every written file is byte-identical, and two runs of one input are identical with the same receipt

### Requirement: Pinned Input Contract
The verb MUST refuse, before writing anything, a missing or unreadable map, a non-PNG, palette, sub-8-bit or tRNS image, maps of different sizes, a size that is not a power of two on both sides, a non-opaque alpha outside the albedo, a non-grey AO, roughness, metallic, height or SpecularWeight map, a grey normal map, a normal texel with negative Z, and an unsafe set name; the normal convention MUST be stated.

#### Scenario: Refusal writes nothing
Given an input set that violates the contract
When `cook-uzengine` runs
Then it exits 1 with a message naming the violation, and the output directory is not created

### Requirement: Receipt
The verb SHALL print a canonical JSON receipt listing each input (hash, bit depth, channels, colour space, decoded-image hash, normal convention) and each written file (sha256, size, format, colour space, mips, mip filter, encoder and its settings, consumer gaps; the `.uzmat`'s blend and opacity source).

#### Scenario: Missing alpha is opacity 1
Given a BaseColor PNG without alpha
When it is cooked
Then the `.uzmat` blends Opaque and the receipt states that the opacity is 1 because the PNG has no alpha
