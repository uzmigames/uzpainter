## ADDED Requirements

### Requirement: Deterministic BC Encoding
The BC encoder adapter SHALL produce identical bytes for the same input image, format and settings, independent of run and worker-thread count.

#### Scenario: Thread count does not change bytes
Given an authored RGBA16 test image and the BC7 sRGB format
When it is encoded once with one worker thread and once with the maximum thread count
Then both outputs have the same SHA-256

### Requirement: Mip Policy Per Map Class
The `.uztexture` writer MUST generate full mip chains with sRGB-aware filtering for colour maps, renormalised vectors for normal maps and alpha-coverage preservation for masked albedo.

#### Scenario: Normal mips stay unit length
Given an authored hemisphere normal map exported to `<set>_normal`
When its mip chain is generated
Then every texel of every mip level decodes to a unit-length vector within the storage precision

#### Scenario: Colour mips filter in linear space
Given an authored sRGB ramp exported to `<set>_albedo`
When its mip chain is generated
Then each level equals the declared filter applied to linear values and re-encoded to sRGB

### Requirement: Negative-Z Normals Never Silently Reconstructed
The exporter MUST detect normal texels with negative Z before BC5 encoding and SHALL either fail the export or route the map to an RGB format, recording the choice in the receipt.

#### Scenario: Negative-Z texel blocks BC5
Given a normal map containing one texel with negative Z and the plan option set to fail
When the UzEngine preset exports it
Then the export fails before publication with the texel count in the error and no `.uztexture` is written for that map

### Requirement: Format-Definition-Conformant uztexture Files
UzPainter SHALL write `.uztexture` files with its own code from the vendored format definition only, with explicit format, colour space, binding and mip metadata, and SHALL NOT link or call UzEngine code.

#### Scenario: Header matches the format definition
Given a BC4 height texture written by UzPainter
When the test reader parses it against the constants of the vendored `uztexture_format.h`
Then the header fields, mip offsets and sizes match and the format metadata states BC4 linear

### Requirement: Lossy-Derivative Error Reported Separately
The decoded error of every BC derivative against its canonical map SHALL be reported as a lossy-derivative contract and MUST NOT be reported as authoring equality.

#### Scenario: Compression error published as numbers
Given a canonical 16-bit ORM map and its BC7 derivative
When the comparison runs
Then the report lists max, mean and p99 decoded error for the derivative under the lossy-derivative heading only
