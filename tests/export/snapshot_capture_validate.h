#pragma once

// Test-only H diagnostic `uzp-export-tests.exe snapshot-capture-validate --input-stdin`: validates
// the six artifacts of one paired scalar/RGB snapshot capture with
// `procedural::ValidateHostCaptureArtifacts` and prints the report
// `tools/parity/store/snapshot_validator.py` reads (`snapshot_contract.parse_validation_report`).

#include <string>

/// The SHA-256 of the validator's sources, framed and embedded at build time (decision 147): the
/// domain `uzpainter/snapshot-capture-validator-sources/1` and a NUL, then for each of the eight
/// files in order its UTF-8 name and its raw bytes, each preceded by its uint64 little-endian
/// length. Compiled dependencies beyond these files are covered by the binary's own hash.
std::string SnapshotCaptureValidatorCodeSha256();

/// Reads the input (UTF-8 JSON, at most 65536 bytes) from stdin. Exit 0 prints exactly one report;
/// exit 2 prints none and names only a value-free reason on stderr. Nothing is written to disk.
int RunSnapshotCaptureValidate();
