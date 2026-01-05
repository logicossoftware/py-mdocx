# MarkDown Open Container eXchange (MDOCX) File Format
## RFC: Draft Specification v1.0 (with Optional Payload Compression)

**Author:** MHJ Wiggers  
**Filename extension:** `.mdocx`  
**Primary purpose:** A single-file container holding one or more Markdown documents plus referenced binary media (images/audio/video/other), suitable for exchange, archival, and transport.  
**Primary implementation target:** Go (Golang), using `encoding/gob` for payload serialization.

---

## 1. Status of This Memo

This document defines the **MDOCX** file format, version **1**.

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**, **SHOULD**, **SHOULD NOT**, **RECOMMENDED**, **MAY**, and **OPTIONAL** in this document are to be interpreted as described in RFC 2119 and RFC 8174.

---

## 2. Design Goals

1. **Containerization:** Bundle multiple Markdown files and associated media in one file.
2. **Self-contained references:** Markdown can reference media by stable IDs and/or container paths.
3. **Efficient parsing:** Deterministic header and length-delimited sections.
4. **Extensibility:** Forward-compatible via versioning, flags, and gob field evolution.
5. **Golang-native encoding:** Document and media payloads are encoded using Go `encoding/gob`.
6. **Optional compression:** Support per-section compression (Markdown and/or Media) using ZIP and other efficient codecs.

---

## 3. High-Level File Layout

An MDOCX file is composed of:

1. **Fixed-format header** (magic, version, flags, metadata length).
2. **Optional metadata block** (UTF-8 JSON).
3. **Markdown bundle section** (length-delimited; gob bytes, optionally compressed).
4. **Media bundle section** (length-delimited; gob bytes, optionally compressed; MAY be empty).

The sections MUST appear in this order.

```
+--------------------+
| Fixed Header       |
+--------------------+
| Metadata (optional)|
+--------------------+
| Section 1: Markdown|
|  - section header  |
|  - payload         |
+--------------------+
| Section 2: Media   |
|  - section header  |
|  - payload         |
+--------------------+
```

---

## 4. Fixed Header

### 4.1 Header Encoding

All integer fields in the fixed header are **little-endian**. The fixed header size is **32 bytes**.

### 4.2 Header Fields

| Offset | Size | Name              | Type     | Description |
|-------:|-----:|-------------------|----------|-------------|
| 0      | 8    | Magic             | [8]byte  | Unique file signature |
| 8      | 2    | Version           | uint16   | Format version (MUST be 1 for this spec) |
| 10     | 2    | HeaderFlags       | uint16   | Flags for header behavior |
| 12     | 4    | FixedHeaderSize   | uint32   | MUST be 32 |
| 16     | 4    | MetadataLength    | uint32   | Length in bytes of metadata block |
| 20     | 4    | Reserved0         | uint32   | MUST be 0 for v1 |
| 24     | 8    | Reserved1         | uint64   | MUST be 0 for v1 |

### 4.3 Magic Value

The `Magic` field MUST be exactly:

- ASCII: `"MDOCX\r\n"` followed by `0x1A`
- Hex: `4D 44 4F 43 58 0D 0A 1A`

### 4.4 HeaderFlags (v1)

`HeaderFlags` is a bitmask:

- Bit 0 (0x0001): `METADATA_JSON`  
  If set, metadata block MUST be UTF-8 JSON.
- All other bits are RESERVED in v1 and MUST be 0 when writing. Readers MUST ignore unknown bits.

### 4.5 Metadata Block

If `MetadataLength` is greater than 0, the metadata block immediately follows the fixed header and MUST be exactly `MetadataLength` bytes.

For v1:
- Metadata MUST be **UTF-8 JSON** text when `METADATA_JSON` is set.
- The JSON value MUST be an object at the top level.

Recommended metadata keys (non-exhaustive):
- `title` (string)
- `description` (string)
- `creator` (string)
- `created_at` (string; RFC3339 timestamp)
- `root` (string; container path of the primary Markdown file, e.g. `"docs/index.md"`)
- `tags` (array of strings)

Readers MUST tolerate unknown keys.

---

## 5. Section Framing

Two sections MUST follow the metadata block:

1. Markdown bundle section (SectionType = 1)
2. Media bundle section (SectionType = 2)

Each section uses a deterministic framing header to allow skipping and bounded reads.

### 5.1 Section Header (16 bytes)

All fields are little-endian.

| Offset | Size | Name        | Type    | Description |
|-------:|-----:|-------------|---------|-------------|
| 0      | 2    | SectionType | uint16  | 1 = Markdown, 2 = Media |
| 2      | 2    | SectionFlags| uint16  | See §5.2 |
| 4      | 8    | PayloadLen  | uint64  | Length in bytes of the section payload |
| 12     | 4    | Reserved    | uint32  | MUST be 0 for v1 |

Immediately after the section header, exactly `PayloadLen` bytes follow as the section payload.

### 5.2 SectionFlags (v1)

`SectionFlags` is a bitmask.

#### 5.2.1 Compression Algorithm (bits 0..3)

Bits 0..3 encode the compression method:

- `0x0` = `COMP_NONE`  (payload is raw gob bytes; no prefix)
- `0x1` = `COMP_ZIP`   (payload is ZIP container; see §6.3)
- `0x2` = `COMP_ZSTD`  (payload is Zstandard-compressed stream; see §6.4)
- `0x3` = `COMP_LZ4`   (payload is LZ4-compressed stream; see §6.5)
- `0x4` = `COMP_BR`    (payload is Brotli-compressed stream; see §6.6)

All other values are RESERVED. Writers MUST NOT emit reserved values. Readers MUST reject unknown compression values unless operating in a best-effort mode that can safely skip the section.

#### 5.2.2 Compression Prefix Present (bit 4)

- Bit 4 (0x0010): `HAS_UNCOMPRESSED_LEN`
  - If set, the section payload begins with an 8-byte `UncompressedLen` (uint64 LE) prefix, followed by the compressed bytes.
  - If `COMP_NONE` is used, this bit MUST be 0.

For all compressed algorithms (`COMP_*` other than `COMP_NONE`), writers MUST set `HAS_UNCOMPRESSED_LEN`. Readers MUST require it.

#### 5.2.3 Reserved Bits

All other bits are RESERVED in v1 and MUST be 0 when writing. Readers MUST ignore unknown reserved bits if they do not affect safe parsing.

---

## 6. Section Payload Semantics

### 6.1 Uncompressed Payload Format (COMP_NONE)

If `SectionFlags` indicates `COMP_NONE`, the payload is exactly the gob encoding of the corresponding bundle struct (see §7).

### 6.2 Compressed Payload Envelope

If `SectionFlags` indicates a compressed algorithm, the payload MUST be:

```
UncompressedLen (uint64 LE) || CompressedBytes
```

Where:
- `UncompressedLen` is the length in bytes of the *decompressed* gob payload.
- `CompressedBytes` is the compressed representation of the gob payload.

Decoders MUST:
- Enforce a configured maximum allowed `UncompressedLen` before allocating.
- Decompress into a bounded reader/writer so that output cannot exceed `UncompressedLen`.

### 6.3 ZIP Compression (COMP_ZIP)

For `COMP_ZIP`, `CompressedBytes` MUST be a standard ZIP archive satisfying all of the following:
- It MUST contain exactly **one** file entry.
- The entry name MUST be `payload.gob`.
- The entry’s uncompressed size MUST equal `UncompressedLen`.
- The entry’s content bytes MUST be the gob payload.

Writers SHOULD use the ZIP DEFLATE method for maximum interoperability.

Readers MUST reject archives that contain:
- More than one entry,
- An entry name other than `payload.gob`,
- Or an entry that expands beyond `UncompressedLen`.

### 6.4 Zstandard Compression (COMP_ZSTD)

For `COMP_ZSTD`, `CompressedBytes` MUST be a Zstandard-compressed stream of the gob payload.

Writers SHOULD choose Zstandard as the default compression due to its favorable speed/ratio trade-offs.

### 6.5 LZ4 Compression (COMP_LZ4)

For `COMP_LZ4`, `CompressedBytes` MUST be an LZ4-compressed stream of the gob payload.

Writers MAY choose LZ4 when decode/encode speed is prioritized over compression ratio.

### 6.6 Brotli Compression (COMP_BR)

For `COMP_BR`, `CompressedBytes` MUST be a Brotli-compressed stream of the gob payload.

Writers MAY choose Brotli when maximizing compression ratio is prioritized and CPU cost is acceptable.

---

## 7. Gob Payload Semantics

MDOCX v1 defines canonical Go structs for gob encoding. Implementations MUST use semantically equivalent structs compatible with gob decoding.

### 7.1 Markdown Bundle (SectionType = 1)

```go
type MarkdownBundle struct {
    BundleVersion uint16            // MUST be 1 for this spec
    RootPath      string            // OPTIONAL: primary markdown path (overrides metadata.root if non-empty)
    Files         []MarkdownFile     // One or more Markdown files
}

type MarkdownFile struct {
    Path        string              // Container path, e.g. "docs/readme.md" (MUST be unique within bundle)
    Content     []byte              // UTF-8 Markdown bytes
    MediaRefs   []string            // OPTIONAL: referenced media IDs (see MediaItem.ID)
    Attributes  map[string]string   // OPTIONAL: arbitrary per-file attributes
}
```

Normative requirements:
- `BundleVersion` MUST be `1`.
- `Files` MUST contain at least one entry.
- Each `MarkdownFile.Path` MUST be non-empty and MUST be unique within `Files`.
- `MarkdownFile.Content` SHOULD be valid UTF-8; decoders MAY reject invalid UTF-8.
- Paths SHOULD use forward slashes (`/`). Paths MUST NOT be absolute (no leading `/`) and MUST NOT contain `..` segments.

### 7.2 Media Bundle (SectionType = 2)

```go
type MediaBundle struct {
    BundleVersion uint16         // MUST be 1 for this spec
    Items         []MediaItem     // Zero or more media items
}

type MediaItem struct {
    ID          string            // Stable identifier, MUST be unique within Items
    Path        string            // OPTIONAL: container path, e.g. "assets/logo.png"
    MIMEType    string            // e.g. "image/png", "audio/mpeg"
    Data        []byte            // Raw bytes
    SHA256      [32]byte          // OPTIONAL but RECOMMENDED: integrity hash of Data
    Attributes  map[string]string // OPTIONAL: e.g. "alt":"Logo"
}
```

Normative requirements:
- `BundleVersion` MUST be `1`.
- Each `MediaItem.ID` MUST be non-empty and unique.
- `MIMEType` SHOULD be present and SHOULD be a valid media type string.
- If `SHA256` is non-zero, it MUST equal the SHA-256 of `Data`.

---

## 8. Referencing Media from Markdown

MDOCX does not mandate a single URI scheme, but this spec RECOMMENDS the following conventions:

- By ID: `mdocx://media/<ID>`
  - Example: `![Logo](mdocx://media/logo_png)`
- By container path (if `MediaItem.Path` is set): relative paths like `assets/logo.png`

Implementations SHOULD support both:
- Resolving `mdocx://media/<ID>` against `MediaItem.ID`
- Resolving relative references against `MediaItem.Path`

If both can apply, ID resolution SHOULD take precedence for `mdocx://` URIs.

---

## 9. Decoding Procedure (Normative)

A conforming MDOCX v1 reader MUST:

1. Read first 32 bytes; validate:
   - `Magic` matches exactly.
   - `FixedHeaderSize` equals 32.
   - `Version` equals 1 (or if higher, MAY attempt best-effort forward parsing; at minimum MUST fail safely).
2. Read `MetadataLength` bytes; if > 0:
   - If `HeaderFlags & METADATA_JSON != 0`, parse as UTF-8 JSON object.
3. Read Section 1 header (16 bytes):
   - Validate `SectionType == 1` and `Reserved == 0`.
   - Read exactly `PayloadLen` bytes as section payload.
   - Decode payload per §6:
     - If `COMP_NONE`: gob-decode into `MarkdownBundle`.
     - Else: read `UncompressedLen` prefix, decompress exactly `UncompressedLen` bytes, gob-decode.
4. Read Section 2 header (16 bytes):
   - Validate `SectionType == 2` and `Reserved == 0`.
   - Read exactly `PayloadLen` bytes and decode per §6:
     - If `PayloadLen == 0`: treat as empty `MediaBundle` (per local policy), otherwise decode as above.
5. Apply constraints:
   - Unique `MarkdownFile.Path`
   - Unique `MediaItem.ID`
   - Path normalization checks
   - OPTIONAL hash verification (`SHA256`)
6. Expose the bundle to the application.

Readers SHOULD provide configurable limits for:
- Metadata length,
- PayloadLen per section,
- UncompressedLen for compressed payloads,
- Number of files/items,
- Per-file/per-item sizes.

---

## 10. Encoding Procedure (Normative)

A conforming MDOCX v1 writer MUST:

1. Construct `MarkdownBundle` with `BundleVersion = 1`.
2. Construct `MediaBundle` with `BundleVersion = 1` (may be empty).
3. Serialize metadata JSON (optional). Set `HeaderFlags` bit `METADATA_JSON` if metadata exists.
4. Emit fixed header.
5. Emit metadata bytes (if present).
6. Emit Section 1:
   - Choose compression method (or none).
   - Serialize gob payload bytes for MarkdownBundle.
   - If compressed: prepend `UncompressedLen` and compress gob bytes; set `HAS_UNCOMPRESSED_LEN` and algorithm bits.
   - Write section header and payload.
7. Emit Section 2:
   - Same process, using MediaBundle.
8. Writers SHOULD populate `SHA256` for each `MediaItem`.

Compression selection guidance (non-normative):
- Default: `COMP_ZSTD`
- Interop-centric: `COMP_ZIP`
- Max speed: `COMP_LZ4`
- Max ratio: `COMP_BR`

---

## 11. Security and Robustness Considerations

MDOCX files may be untrusted input. Implementations MUST protect against:

- **Oversized allocations:** Validate `MetadataLength`, `PayloadLen`, and (if compressed) `UncompressedLen` against configured maximums.
- **Decompression bombs:** Enforce strict bounds during decompression (output MUST NOT exceed `UncompressedLen`).
- **Gob decoding hazards:** Use `io.LimitReader` and enforce maximum counts/sizes.
- **ZIP traversal hazards:** For `COMP_ZIP`, readers MUST ignore or reject any path elements in the ZIP entry name; only `payload.gob` is permitted.

Recommended default maxima (implementation policy):
- MetadataLength: <= 1 MiB
- Markdown section uncompressed: <= 256 MiB
- Media section uncompressed: <= 2 GiB
- Max Markdown files: 10,000
- Max media items: 10,000
- Max single media `Data`: 512 MiB (configurable)

---

## 12. Forward Compatibility and Extensibility

- New optional fields MAY be added to the canonical structs in future versions; gob decoders typically ignore unknown fields.
- Future versions MAY define additional section types. v1 readers MAY ignore unknown section types only if they can safely skip them via `PayloadLen`.
- `Version` in the fixed header is authoritative; readers SHOULD fail safely on unknown versions.

---

## 13. Suggested Content Type (Non-Normative)

- `application/vnd.mdocx` (preferred if registered)
- `application/x-mdocx` (fallback)

---

## 14. Compliance Checklist (v1)

A file is MDOCX v1 compliant iff:
- Magic matches exactly.
- Fixed header is 32 bytes; reserved fields are zero.
- Version == 1.
- Two sections appear in order: Markdown (type 1) then Media (type 2).
- Section headers are valid and payload lengths are honored.
- Payload decoding follows §6, including strict bounds for compressed payloads.
- Gob payloads decode into semantically equivalent bundles with `BundleVersion == 1`.

---
