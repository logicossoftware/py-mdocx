# PyMDOCX

Python implementation of the MDOCX (MarkDown Open Container eXchange) file format.

PyPI (v0.1.0): https://pypi.org/project/logicossoftware-mdocx/0.1.0/

MDOCX is a single-file container format for bundling one or more Markdown documents with associated binary media (images, audio, video, etc.), suitable for exchange, archival, and transport.

## Installation

```bash
pip install logicossoftware-mdocx
```

### Optional compression support

```bash
# Install with all compression algorithms
pip install logicossoftware-mdocx[all]

# Or install individual compression libraries
pip install logicossoftware-mdocx[zstd]   # Zstandard (recommended)
pip install logicossoftware-mdocx[lz4]    # LZ4 (fast)
pip install logicossoftware-mdocx[brotli] # Brotli (high compression)
```

## Quick Start

### Creating an MDOCX file

```python
from pymdocx import (
    MDOCXWriter,
    MarkdownBundle,
    MarkdownFile,
    MediaBundle,
    MediaItem,
    Metadata,
    CompressionMethod,
)

# Create markdown content
md_bundle = MarkdownBundle(
    root_path="index.md",
    files=[
        MarkdownFile.from_string(
            "index.md",
            "# My Document\n\n![Logo](mdocx://media/logo)\n\nWelcome!"
        ),
        MarkdownFile.from_string(
            "docs/chapter1.md",
            "# Chapter 1\n\nThis is the first chapter."
        ),
    ],
)

# Add media (optional)
with open("logo.png", "rb") as f:
    logo_data = f.read()

media_bundle = MediaBundle(items=[
    MediaItem(
        id="logo",
        path="assets/logo.png",
        mime_type="image/png",
        data=logo_data,
    ),
])

# Add metadata (optional)
metadata = Metadata(
    title="My Document",
    creator="Author Name",
    root="index.md",
    tags=["example", "documentation"],
)

# Write the file
writer = MDOCXWriter(compression=CompressionMethod.ZSTD)
writer.write("document.mdocx", md_bundle, media_bundle, metadata)
```

### Reading an MDOCX file

```python
from pymdocx import MDOCXReader

reader = MDOCXReader()
doc = reader.read("document.mdocx")

# Access metadata
if doc.metadata:
    print(f"Title: {doc.metadata.title}")
    print(f"Creator: {doc.metadata.creator}")

# Access markdown files
for md_file in doc.markdown_bundle.files:
    print(f"File: {md_file.path}")
    print(f"Content: {md_file.content_str[:100]}...")

# Get the root/primary file
root_file = doc.get_root_file()
if root_file:
    print(f"Root file: {root_file.path}")

# Access media
for item in doc.media_bundle.items:
    print(f"Media: {item.id} ({item.mime_type})")

# Resolve media URIs from markdown
media = doc.resolve_media_uri("mdocx://media/logo")
if media:
    print(f"Found media: {len(media.data)} bytes")

# List contents (paths, sizes, metadata)
contents = doc.list_contents()
print("Root:", contents["root"])
for item in contents["markdown"]:
    print("MD:", item["path"], item["size"])
for item in contents["media"]:
    print("Media:", item["id"], item["path"], item["size"])
```

## Compression Options

| Method | Description | Use Case |
|--------|-------------|----------|
| `CompressionMethod.NONE` | No compression | Maximum compatibility |
| `CompressionMethod.ZIP` | ZIP/DEFLATE | Good interoperability |
| `CompressionMethod.ZSTD` | Zstandard | **Recommended** - best speed/ratio |
| `CompressionMethod.LZ4` | LZ4 | Fastest compression/decompression |
| `CompressionMethod.BROTLI` | Brotli | Maximum compression ratio |

```python
# Use different compression for markdown and media
writer = MDOCXWriter(
    markdown_compression=CompressionMethod.ZSTD,
    media_compression=CompressionMethod.LZ4,
)
```

## API Reference

### Models

- **`MarkdownBundle`**: Collection of Markdown files
- **`MarkdownFile`**: Single Markdown document with path and content
- **`MediaBundle`**: Collection of media items
- **`MediaItem`**: Binary media with ID, path, MIME type, and data
- **`Metadata`**: Document metadata (title, creator, tags, etc.)

### Reader/Writer

- **`MDOCXReader`**: Read and parse MDOCX files
- **`MDOCXWriter`**: Create MDOCX files

### MDOCXReader Options

```python
reader = MDOCXReader(
    max_metadata_length=1024*1024,      # 1 MiB
    max_markdown_uncompressed=256*1024*1024,  # 256 MiB
    max_media_uncompressed=2*1024*1024*1024,  # 2 GiB
    verify_hashes=True,  # Verify SHA256 hashes on media
)
```

## File Format

MDOCX files consist of:

1. **Fixed Header** (32 bytes): Magic, version, flags
2. **Metadata Block** (optional): UTF-8 JSON
3. **Markdown Section**: Bundled Markdown files
4. **Media Section**: Bundled binary media

See [rfc.md](rfc.md) for the complete specification.

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v
```

## License

MIT License
Python implementation of MDOCX file format
