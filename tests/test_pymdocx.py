"""
Tests for pymdocx package.
"""

import pytest
import hashlib
from io import BytesIO
import struct

from pymdocx import (
    MarkdownBundle,
    MarkdownFile,
    MediaBundle,
    MediaItem,
    Metadata,
    MDOCXReader,
    MDOCXWriter,
    MDOCXFormatError,
    CompressionMethod,
    MAGIC,
    VERSION,
    SectionType,
)
from pymdocx.constants import SectionFlags
from pymdocx.gob import (
    encode_markdown_bundle,
    decode_markdown_bundle,
    encode_media_bundle,
    decode_media_bundle,
)


def _fixed_header(*, header_flags: int = 0, metadata_length: int = 0) -> bytes:
    return struct.pack(
        '<8sHHIIIII',
        MAGIC,
        VERSION,
        header_flags,
        32,
        metadata_length,
        0,
        0,
        0,
    )


def _section_header(*, section_type: SectionType, section_flags: int, payload_len: int) -> bytes:
    return struct.pack(
        '<HHQI',
        int(section_type),
        int(section_flags),
        payload_len,
        0,
    )


class TestModels:
    """Tests for data models."""
    
    def test_markdown_file_from_string(self):
        """Test creating MarkdownFile from string content."""
        mf = MarkdownFile.from_string("test.md", "# Hello World")
        assert mf.path == "test.md"
        assert mf.content == b"# Hello World"
        assert mf.content_str == "# Hello World"
    
    def test_markdown_bundle_validation(self):
        """Test MarkdownBundle validation."""
        bundle = MarkdownBundle(files=[
            MarkdownFile.from_string("a.md", "# A"),
            MarkdownFile.from_string("b.md", "# B"),
        ])
        bundle.validate()  # Should not raise
    
    def test_markdown_bundle_empty_fails(self):
        """Test that empty MarkdownBundle fails validation."""
        bundle = MarkdownBundle(files=[])
        with pytest.raises(ValueError, match="at least one file"):
            bundle.validate()
    
    def test_markdown_bundle_duplicate_paths_fails(self):
        """Test that duplicate paths fail validation."""
        bundle = MarkdownBundle(files=[
            MarkdownFile.from_string("a.md", "# A"),
            MarkdownFile.from_string("a.md", "# A again"),
        ])
        with pytest.raises(ValueError, match="Duplicate"):
            bundle.validate()
    
    def test_markdown_bundle_absolute_path_fails(self):
        """Test that absolute paths fail validation."""
        bundle = MarkdownBundle(files=[
            MarkdownFile.from_string("/absolute/path.md", "# Test"),
        ])
        with pytest.raises(ValueError, match="absolute"):
            bundle.validate()
    
    def test_media_item_sha256(self):
        """Test SHA256 computation and verification."""
        data = b"test data"
        item = MediaItem(
            id="test",
            data=data,
            sha256=hashlib.sha256(data).digest(),
        )
        assert item.verify_sha256()
    
    def test_media_item_sha256_mismatch(self):
        """Test SHA256 verification failure."""
        # Use a non-zero wrong hash to trigger actual verification
        wrong_hash = b"\x01" + b"\x00" * 31  # Non-zero hash that doesn't match
        item = MediaItem(
            id="test",
            data=b"test data",
            sha256=wrong_hash,
        )
        assert not item.verify_sha256()
    
    def test_metadata_round_trip(self):
        """Test Metadata to/from dict."""
        meta = Metadata(
            title="Test Doc",
            description="A test document",
            creator="Test Author",
            root="index.md",
            tags=["test", "example"],
        )
        d = meta.to_dict()
        meta2 = Metadata.from_dict(d)
        
        assert meta2.title == meta.title
        assert meta2.description == meta.description
        assert meta2.creator == meta.creator
        assert meta2.root == meta.root
        assert meta2.tags == meta.tags


class TestGob:
    """Tests for gob encoding/decoding."""
    
    def test_markdown_bundle_round_trip(self):
        """Test encoding and decoding MarkdownBundle."""
        bundle = MarkdownBundle(
            bundle_version=1,
            root_path="index.md",
            files=[
                MarkdownFile(
                    path="index.md",
                    content=b"# Hello World\n\nThis is a test.",
                    media_refs=["img1", "img2"],
                    attributes={"author": "Test"},
                ),
                MarkdownFile(
                    path="docs/page.md",
                    content=b"# Page 2",
                ),
            ],
        )
        
        encoded = encode_markdown_bundle(bundle)
        decoded = decode_markdown_bundle(encoded)
        
        assert decoded.bundle_version == 1
        assert decoded.root_path == "index.md"
        assert len(decoded.files) == 2
        assert decoded.files[0].path == "index.md"
        assert decoded.files[0].content == b"# Hello World\n\nThis is a test."
        assert decoded.files[0].media_refs == ["img1", "img2"]
        assert decoded.files[0].attributes == {"author": "Test"}
    
    def test_media_bundle_round_trip(self):
        """Test encoding and decoding MediaBundle."""
        bundle = MediaBundle(
            bundle_version=1,
            items=[
                MediaItem(
                    id="logo",
                    path="assets/logo.png",
                    mime_type="image/png",
                    data=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
                    sha256=hashlib.sha256(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100).digest(),
                    attributes={"alt": "Logo"},
                ),
            ],
        )
        
        encoded = encode_media_bundle(bundle)
        decoded = decode_media_bundle(encoded)
        
        assert decoded.bundle_version == 1
        assert len(decoded.items) == 1
        assert decoded.items[0].id == "logo"
        assert decoded.items[0].path == "assets/logo.png"
        assert decoded.items[0].mime_type == "image/png"
        assert decoded.items[0].attributes == {"alt": "Logo"}
    
    def test_empty_media_bundle(self):
        """Test empty MediaBundle."""
        bundle = MediaBundle(bundle_version=1, items=[])
        
        encoded = encode_media_bundle(bundle)
        decoded = decode_media_bundle(encoded)
        
        assert decoded.bundle_version == 1
        assert len(decoded.items) == 0


class TestWriterReader:
    """Tests for MDOCXWriter and MDOCXReader."""
    
    def test_basic_round_trip(self):
        """Test writing and reading a simple MDOCX file."""
        md_bundle = MarkdownBundle(files=[
            MarkdownFile.from_string("readme.md", "# Test Document\n\nHello!"),
        ])
        
        writer = MDOCXWriter()
        data = writer.to_bytes(md_bundle)
        
        reader = MDOCXReader()
        doc = reader.read_from_bytes(data)
        
        assert doc.version == 1
        assert len(doc.markdown_bundle.files) == 1
        assert doc.markdown_bundle.files[0].path == "readme.md"
        assert doc.markdown_bundle.files[0].content_str == "# Test Document\n\nHello!"
    
    def test_with_metadata(self):
        """Test round trip with metadata."""
        md_bundle = MarkdownBundle(files=[
            MarkdownFile.from_string("index.md", "# Index"),
        ])
        meta = Metadata(
            title="My Document",
            creator="Test Author",
            root="index.md",
        )
        
        writer = MDOCXWriter()
        data = writer.to_bytes(md_bundle, metadata=meta)
        
        reader = MDOCXReader()
        doc = reader.read_from_bytes(data)
        
        assert doc.metadata is not None
        assert doc.metadata.title == "My Document"
        assert doc.metadata.creator == "Test Author"
        assert doc.metadata.root == "index.md"
    
    def test_with_media(self):
        """Test round trip with media items."""
        md_bundle = MarkdownBundle(files=[
            MarkdownFile.from_string(
                "index.md",
                "# Hello\n\n![Logo](mdocx://media/logo)"
            ),
        ])
        
        image_data = b"\x89PNG\r\n\x1a\n" + b"fake image data" * 10
        media_bundle = MediaBundle(items=[
            MediaItem(
                id="logo",
                path="assets/logo.png",
                mime_type="image/png",
                data=image_data,
            ),
        ])
        
        writer = MDOCXWriter()
        data = writer.to_bytes(md_bundle, media_bundle)
        
        reader = MDOCXReader()
        doc = reader.read_from_bytes(data)
        
        assert len(doc.media_bundle.items) == 1
        assert doc.media_bundle.items[0].id == "logo"
        assert doc.media_bundle.items[0].data == image_data
        
        # Test URI resolution
        item = doc.resolve_media_uri("mdocx://media/logo")
        assert item is not None
        assert item.id == "logo"
    
    def test_zip_compression(self):
        """Test ZIP compression."""
        md_bundle = MarkdownBundle(files=[
            MarkdownFile.from_string("test.md", "# Test\n" * 100),
        ])
        
        writer = MDOCXWriter(compression=CompressionMethod.ZIP)
        data = writer.to_bytes(md_bundle)
        
        reader = MDOCXReader()
        doc = reader.read_from_bytes(data)
        
        assert doc.markdown_bundle.files[0].content_str == "# Test\n" * 100
    
    def test_get_root_file(self):
        """Test getting the root file."""
        md_bundle = MarkdownBundle(
            root_path="docs/main.md",
            files=[
                MarkdownFile.from_string("readme.md", "# Readme"),
                MarkdownFile.from_string("docs/main.md", "# Main"),
            ],
        )
        
        writer = MDOCXWriter()
        data = writer.to_bytes(md_bundle)
        
        reader = MDOCXReader()
        doc = reader.read_from_bytes(data)
        
        root = doc.get_root_file()
        assert root is not None
        assert root.path == "docs/main.md"


class TestCompression:
    """Tests for compression support."""
    
    def test_zstd_compression(self):
        """Test Zstandard compression if available."""
        try:
            import zstandard
        except ImportError:
            pytest.skip("zstandard not installed")
        
        md_bundle = MarkdownBundle(files=[
            MarkdownFile.from_string("test.md", "# Test\n" * 1000),
        ])
        
        writer = MDOCXWriter(compression=CompressionMethod.ZSTD)
        data = writer.to_bytes(md_bundle)
        
        reader = MDOCXReader()
        doc = reader.read_from_bytes(data)
        
        assert doc.markdown_bundle.files[0].content_str == "# Test\n" * 1000
    
    def test_lz4_compression(self):
        """Test LZ4 compression if available."""
        try:
            import lz4.frame
        except ImportError:
            pytest.skip("lz4 not installed")
        
        md_bundle = MarkdownBundle(files=[
            MarkdownFile.from_string("test.md", "# Test\n" * 1000),
        ])
        
        writer = MDOCXWriter(compression=CompressionMethod.LZ4)
        data = writer.to_bytes(md_bundle)
        
        reader = MDOCXReader()
        doc = reader.read_from_bytes(data)
        
        assert doc.markdown_bundle.files[0].content_str == "# Test\n" * 1000
    
    def test_brotli_compression(self):
        """Test Brotli compression if available."""
        try:
            import brotli
        except ImportError:
            pytest.skip("brotli not installed")
        
        md_bundle = MarkdownBundle(files=[
            MarkdownFile.from_string("test.md", "# Test\n" * 1000),
        ])
        
        writer = MDOCXWriter(compression=CompressionMethod.BROTLI)
        data = writer.to_bytes(md_bundle)
        
        reader = MDOCXReader()
        doc = reader.read_from_bytes(data)
        
        assert doc.markdown_bundle.files[0].content_str == "# Test\n" * 1000


class TestMalformedInputs:
    def test_rejects_unknown_header_flags(self):
        data = _fixed_header(header_flags=0x8000)
        reader = MDOCXReader()

        with pytest.raises(MDOCXFormatError, match="Unknown header flags"):
            reader.read_from_bytes(data)

    def test_rejects_unknown_section_flags(self):
        data = _fixed_header() + _section_header(
            section_type=SectionType.MARKDOWN,
            section_flags=0x0020,  # unknown bit
            payload_len=1,
        )
        reader = MDOCXReader()

        with pytest.raises(MDOCXFormatError, match="Unknown section flags"):
            reader.read_from_bytes(data)

    def test_rejects_unknown_compression_method(self):
        data = _fixed_header() + _section_header(
            section_type=SectionType.MARKDOWN,
            section_flags=int(SectionFlags.HAS_UNCOMPRESSED_LEN) | 0x0005,  # compression id 5 is undefined
            payload_len=1,
        )
        reader = MDOCXReader()

        with pytest.raises(MDOCXFormatError, match="Unknown compression method"):
            reader.read_from_bytes(data)

    def test_payload_len_guardrail_for_uncompressed_section(self):
        reader = MDOCXReader(max_markdown_uncompressed=16)
        data = _fixed_header() + _section_header(
            section_type=SectionType.MARKDOWN,
            section_flags=0,
            payload_len=17,
        )

        with pytest.raises(MDOCXFormatError, match="exceeds maximum"):
            reader.read_from_bytes(data)

    def test_truncated_gob_payload_is_format_error(self):
        payload = b"\x01"  # valid uint length prefix, but truncated message body
        data = _fixed_header() + _section_header(
            section_type=SectionType.MARKDOWN,
            section_flags=0,
            payload_len=len(payload),
        ) + payload

        reader = MDOCXReader()
        with pytest.raises(MDOCXFormatError, match="Gob decoding failed"):
            reader.read_from_bytes(data)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
