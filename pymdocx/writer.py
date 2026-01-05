"""
MDOCX file writer.
"""

import json
import struct
from io import BytesIO
from typing import BinaryIO, Optional, Union
from pathlib import Path

from .constants import (
    MAGIC,
    VERSION,
    FIXED_HEADER_SIZE,
    SECTION_HEADER_SIZE,
    HeaderFlags,
    SectionType,
    SectionFlags,
    CompressionMethod,
)
from .models import MarkdownBundle, MediaBundle, Metadata
from .gob import encode_markdown_bundle, encode_media_bundle
from .compression import compress


class MDOCXWriter:
    """
    Writer for MDOCX files.
    
    Example usage:
        >>> from pymdocx import MDOCXWriter, MarkdownBundle, MarkdownFile, Metadata
        >>> 
        >>> bundle = MarkdownBundle(files=[
        ...     MarkdownFile.from_string("readme.md", "# Hello World")
        ... ])
        >>> 
        >>> writer = MDOCXWriter()
        >>> writer.write("output.mdocx", bundle)
    """
    
    def __init__(
        self,
        compression: CompressionMethod = CompressionMethod.NONE,
        markdown_compression: Optional[CompressionMethod] = None,
        media_compression: Optional[CompressionMethod] = None,
    ):
        """
        Initialize writer with compression settings.
        
        Args:
            compression: Default compression for both sections
            markdown_compression: Override compression for markdown section
            media_compression: Override compression for media section
        """
        self.markdown_compression = markdown_compression or compression
        self.media_compression = media_compression or compression
    
    def write(
        self,
        path: Union[str, Path],
        markdown_bundle: MarkdownBundle,
        media_bundle: Optional[MediaBundle] = None,
        metadata: Optional[Metadata] = None,
    ) -> None:
        """
        Write MDOCX file to disk.
        
        Args:
            path: Output file path
            markdown_bundle: Markdown content bundle
            media_bundle: Optional media bundle (empty if not provided)
            metadata: Optional file metadata
        """
        with open(path, 'wb') as f:
            self.write_to_stream(f, markdown_bundle, media_bundle, metadata)
    
    def write_to_stream(
        self,
        stream: BinaryIO,
        markdown_bundle: MarkdownBundle,
        media_bundle: Optional[MediaBundle] = None,
        metadata: Optional[Metadata] = None,
    ) -> None:
        """
        Write MDOCX data to a binary stream.
        
        Args:
            stream: Output binary stream
            markdown_bundle: Markdown content bundle
            media_bundle: Optional media bundle
            metadata: Optional file metadata
        """
        # Validate bundles
        markdown_bundle.validate()
        
        if media_bundle is None:
            media_bundle = MediaBundle()
        else:
            media_bundle.validate()
        
        # Populate SHA256 for media items
        for item in media_bundle.items:
            if not item.sha256 or item.sha256 == bytes(32):
                item.sha256 = item.compute_sha256()
        
        # Prepare metadata
        metadata_bytes = b""
        header_flags = HeaderFlags.NONE
        
        if metadata is not None:
            metadata_dict = metadata.to_dict()
            if metadata_dict:
                metadata_bytes = json.dumps(metadata_dict).encode('utf-8')
                header_flags |= HeaderFlags.METADATA_JSON
        
        # Write fixed header
        self._write_header(stream, header_flags, len(metadata_bytes))
        
        # Write metadata
        if metadata_bytes:
            stream.write(metadata_bytes)
        
        # Write markdown section
        self._write_section(
            stream,
            SectionType.MARKDOWN,
            encode_markdown_bundle(markdown_bundle),
            self.markdown_compression,
        )
        
        # Write media section
        self._write_section(
            stream,
            SectionType.MEDIA,
            encode_media_bundle(media_bundle),
            self.media_compression,
        )
    
    def _write_header(
        self,
        stream: BinaryIO,
        flags: HeaderFlags,
        metadata_length: int,
    ) -> None:
        """Write the fixed 32-byte header."""
        header = struct.pack(
            '<8sHHIIII',
            MAGIC,                    # 8 bytes: magic
            VERSION,                  # 2 bytes: version
            int(flags),               # 2 bytes: header flags
            FIXED_HEADER_SIZE,        # 4 bytes: fixed header size
            metadata_length,          # 4 bytes: metadata length
            0,                        # 4 bytes: reserved0
            0,                        # 4 bytes: first half of reserved1
        )
        # Pad to 32 bytes (need 4 more bytes for second half of reserved1)
        header += struct.pack('<I', 0)
        
        assert len(header) == 32, f"Header size mismatch: {len(header)}"
        stream.write(header)
    
    def _write_section(
        self,
        stream: BinaryIO,
        section_type: SectionType,
        gob_payload: bytes,
        compression: CompressionMethod,
    ) -> None:
        """Write a section with header and payload."""
        # Compress payload if needed
        if compression == CompressionMethod.NONE:
            section_flags = SectionFlags(0)
            payload = gob_payload
        else:
            section_flags = SectionFlags(compression) | SectionFlags.HAS_UNCOMPRESSED_LEN
            compressed = compress(gob_payload, compression)
            # Prepend uncompressed length
            payload = struct.pack('<Q', len(gob_payload)) + compressed
        
        # Write section header
        section_header = struct.pack(
            '<HHQI',
            int(section_type),        # 2 bytes: section type
            int(section_flags),       # 2 bytes: section flags
            len(payload),             # 8 bytes: payload length
            0,                        # 4 bytes: reserved
        )
        
        assert len(section_header) == 16, f"Section header size mismatch: {len(section_header)}"
        stream.write(section_header)
        stream.write(payload)
    
    def to_bytes(
        self,
        markdown_bundle: MarkdownBundle,
        media_bundle: Optional[MediaBundle] = None,
        metadata: Optional[Metadata] = None,
    ) -> bytes:
        """
        Generate MDOCX file content as bytes.
        
        Args:
            markdown_bundle: Markdown content bundle
            media_bundle: Optional media bundle
            metadata: Optional file metadata
            
        Returns:
            Complete MDOCX file content as bytes
        """
        buf = BytesIO()
        self.write_to_stream(buf, markdown_bundle, media_bundle, metadata)
        return buf.getvalue()
