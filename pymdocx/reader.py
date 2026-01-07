"""
MDOCX file reader.
"""

import json
import struct
from io import BytesIO
from typing import BinaryIO, Optional, Tuple, Union
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
    DEFAULT_MAX_METADATA_LENGTH,
    DEFAULT_MAX_MARKDOWN_UNCOMPRESSED,
    DEFAULT_MAX_MEDIA_UNCOMPRESSED,
)
from .models import MarkdownBundle, MarkdownFile, MediaBundle, MediaItem, Metadata
from .gob import decode_markdown_bundle, decode_media_bundle
from .compression import decompress, CompressionError


class MDOCXError(Exception):
    """Base exception for MDOCX errors."""
    pass


class MDOCXFormatError(MDOCXError):
    """Error in MDOCX file format."""
    pass


class MDOCXVersionError(MDOCXError):
    """Unsupported MDOCX version."""
    pass


class MDOCXReader:
    """
    Reader for MDOCX files.
    
    Example usage:
        >>> from pymdocx import MDOCXReader
        >>> 
        >>> reader = MDOCXReader()
        >>> result = reader.read("document.mdocx")
        >>> 
        >>> print(result.metadata)
        >>> for f in result.markdown_bundle.files:
        ...     print(f.path, len(f.content))
    """
    
    def __init__(
        self,
        max_metadata_length: int = DEFAULT_MAX_METADATA_LENGTH,
        max_markdown_uncompressed: int = DEFAULT_MAX_MARKDOWN_UNCOMPRESSED,
        max_media_uncompressed: int = DEFAULT_MAX_MEDIA_UNCOMPRESSED,
        verify_hashes: bool = True,
    ):
        """
        Initialize reader with safety limits.
        
        Args:
            max_metadata_length: Maximum allowed metadata block size
            max_markdown_uncompressed: Maximum uncompressed markdown section size
            max_media_uncompressed: Maximum uncompressed media section size
            verify_hashes: Whether to verify SHA256 hashes on media items
        """
        self.max_metadata_length = max_metadata_length
        self.max_markdown_uncompressed = max_markdown_uncompressed
        self.max_media_uncompressed = max_media_uncompressed
        self.verify_hashes = verify_hashes
    
    def read(self, path: Union[str, Path]) -> "MDOCXDocument":
        """
        Read an MDOCX file from disk.
        
        Args:
            path: Path to the MDOCX file
            
        Returns:
            MDOCXDocument containing all parsed data
        """
        with open(path, 'rb') as f:
            return self.read_from_stream(f)
    
    def read_from_stream(self, stream: BinaryIO) -> "MDOCXDocument":
        """
        Read MDOCX data from a binary stream.
        
        Args:
            stream: Input binary stream
            
        Returns:
            MDOCXDocument containing all parsed data
        """
        # Step 1: Read and validate fixed header
        version, header_flags, metadata_length = self._read_header(stream)
        
        # Step 2: Read metadata block
        metadata = None
        if metadata_length > 0:
            if metadata_length > self.max_metadata_length:
                raise MDOCXFormatError(
                    f"Metadata length {metadata_length} exceeds maximum {self.max_metadata_length}"
                )
            metadata = self._read_metadata(stream, metadata_length, header_flags)
        
        # Step 3: Read markdown section
        markdown_bundle = self._read_section(
            stream,
            expected_type=SectionType.MARKDOWN,
            max_uncompressed=self.max_markdown_uncompressed,
            decoder=decode_markdown_bundle,
        )
        
        # Step 4: Read media section
        media_bundle = self._read_section(
            stream,
            expected_type=SectionType.MEDIA,
            max_uncompressed=self.max_media_uncompressed,
            decoder=decode_media_bundle,
        )
        
        # Step 5: Validate bundles
        markdown_bundle.validate()
        if self.verify_hashes:
            media_bundle.validate()
        
        return MDOCXDocument(
            version=version,
            metadata=metadata,
            markdown_bundle=markdown_bundle,
            media_bundle=media_bundle,
        )
    
    def read_from_bytes(self, data: bytes) -> "MDOCXDocument":
        """
        Read MDOCX data from bytes.
        
        Args:
            data: Complete MDOCX file content as bytes
            
        Returns:
            MDOCXDocument containing all parsed data
        """
        return self.read_from_stream(BytesIO(data))
    
    def _read_header(self, stream: BinaryIO) -> Tuple[int, HeaderFlags, int]:
        """Read and validate the fixed 32-byte header."""
        header = stream.read(FIXED_HEADER_SIZE)
        if len(header) != FIXED_HEADER_SIZE:
            raise MDOCXFormatError(
                f"Incomplete header: expected {FIXED_HEADER_SIZE} bytes, got {len(header)}"
            )
        
        # Unpack header fields
        (
            magic,
            version,
            header_flags,
            fixed_header_size,
            metadata_length,
            reserved0,
            reserved1_low,
            reserved1_high,
        ) = struct.unpack('<8sHHIIIII', header)
        
        # Validate magic
        if magic != MAGIC:
            raise MDOCXFormatError(
                f"Invalid magic bytes: expected {MAGIC!r}, got {magic!r}"
            )
        
        # Validate fixed header size
        if fixed_header_size != FIXED_HEADER_SIZE:
            raise MDOCXFormatError(
                f"Invalid header size: expected {FIXED_HEADER_SIZE}, got {fixed_header_size}"
            )
        
        # Check version
        if version != VERSION:
            raise MDOCXVersionError(
                f"Unsupported version: expected {VERSION}, got {version}"
            )
        
        # Check reserved fields (must be 0 in v1)
        if reserved0 != 0:
            raise MDOCXFormatError(f"Reserved0 must be 0, got {reserved0}")
        if reserved1_low != 0 or reserved1_high != 0:
            raise MDOCXFormatError(
                f"Reserved1 must be 0, got {(reserved1_high << 32) | reserved1_low}"
            )
        
        return version, HeaderFlags(header_flags), metadata_length
    
    def _read_metadata(
        self,
        stream: BinaryIO,
        length: int,
        flags: HeaderFlags,
    ) -> Optional[Metadata]:
        """Read and parse the metadata block."""
        data = stream.read(length)
        if len(data) != length:
            raise MDOCXFormatError(
                f"Incomplete metadata: expected {length} bytes, got {len(data)}"
            )
        
        if flags & HeaderFlags.METADATA_JSON:
            try:
                obj = json.loads(data.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise MDOCXFormatError(f"Invalid metadata JSON: {e}")
            
            if not isinstance(obj, dict):
                raise MDOCXFormatError("Metadata JSON must be an object")
            
            return Metadata.from_dict(obj)
        
        return None
    
    def _read_section(
        self,
        stream: BinaryIO,
        expected_type: SectionType,
        max_uncompressed: int,
        decoder,
    ):
        """Read a section header and payload."""
        # Read section header
        header = stream.read(SECTION_HEADER_SIZE)
        if len(header) != SECTION_HEADER_SIZE:
            raise MDOCXFormatError(
                f"Incomplete section header: expected {SECTION_HEADER_SIZE} bytes, got {len(header)}"
            )
        
        section_type, section_flags, payload_len, reserved = struct.unpack(
            '<HHQI', header
        )
        
        # Validate section type
        if section_type != expected_type:
            raise MDOCXFormatError(
                f"Unexpected section type: expected {expected_type}, got {section_type}"
            )
        
        # Validate reserved
        if reserved != 0:
            raise MDOCXFormatError(f"Section reserved field must be 0, got {reserved}")
        
        # Handle empty payload (allowed for media section)
        if payload_len == 0:
            if expected_type == SectionType.MEDIA:
                return MediaBundle()
            else:
                raise MDOCXFormatError("Markdown section payload cannot be empty")
        
        # Read payload
        payload = stream.read(payload_len)
        if len(payload) != payload_len:
            raise MDOCXFormatError(
                f"Incomplete section payload: expected {payload_len} bytes, got {len(payload)}"
            )
        
        # Determine compression method
        compression_value = section_flags & SectionFlags.COMPRESSION_MASK
        try:
            compression = CompressionMethod(compression_value)
        except ValueError:
            raise MDOCXFormatError(f"Unknown compression method: {compression_value}")
        has_uncompressed_len = bool(section_flags & SectionFlags.HAS_UNCOMPRESSED_LEN)
        
        # Decompress if needed
        if compression == CompressionMethod.NONE:
            if has_uncompressed_len:
                raise MDOCXFormatError(
                    "HAS_UNCOMPRESSED_LEN must not be set for COMP_NONE"
                )
            gob_data = payload
        else:
            if not has_uncompressed_len:
                raise MDOCXFormatError(
                    "HAS_UNCOMPRESSED_LEN must be set for compressed sections"
                )
            
            # Extract uncompressed length prefix
            if len(payload) < 8:
                raise MDOCXFormatError("Payload too short for uncompressed length prefix")
            
            uncompressed_len = struct.unpack('<Q', payload[:8])[0]
            compressed_data = payload[8:]
            
            # Validate against limits
            if uncompressed_len > max_uncompressed:
                raise MDOCXFormatError(
                    f"Uncompressed size {uncompressed_len} exceeds maximum {max_uncompressed}"
                )
            
            try:
                gob_data = decompress(
                    compressed_data,
                    compression,
                    uncompressed_len,
                    max_uncompressed,
                )
            except CompressionError as e:
                raise MDOCXFormatError(f"Decompression failed: {e}")
        
        # Decode gob payload
        try:
            return decoder(gob_data)
        except Exception as e:
            raise MDOCXFormatError(f"Gob decoding failed: {e}")


class MDOCXDocument:
    """
    Represents a parsed MDOCX document.
    
    Attributes:
        version: MDOCX format version
        metadata: Optional document metadata
        markdown_bundle: Bundle of Markdown files
        media_bundle: Bundle of media items
    """
    
    def __init__(
        self,
        version: int,
        metadata: Optional[Metadata],
        markdown_bundle: MarkdownBundle,
        media_bundle: MediaBundle,
    ):
        self.version = version
        self.metadata = metadata
        self.markdown_bundle = markdown_bundle
        self.media_bundle = media_bundle
    
    def get_root_file(self) -> Optional[MarkdownFile]:
        """Get the primary/root Markdown file if specified."""
        root_path = None
        
        # Check bundle root_path first
        if self.markdown_bundle.root_path:
            root_path = self.markdown_bundle.root_path
        # Then metadata root
        elif self.metadata and self.metadata.root:
            root_path = self.metadata.root
        
        if root_path:
            for f in self.markdown_bundle.files:
                if f.path == root_path:
                    return f
        
        # Default to first file
        if self.markdown_bundle.files:
            return self.markdown_bundle.files[0]
        
        return None
    
    def get_media_by_id(self, media_id: str) -> Optional[MediaItem]:
        """Get a media item by its ID."""
        for item in self.media_bundle.items:
            if item.id == media_id:
                return item
        return None
    
    def get_media_by_path(self, path: str) -> Optional[MediaItem]:
        """Get a media item by its path."""
        for item in self.media_bundle.items:
            if item.path == path:
                return item
        return None
    
    def resolve_media_uri(self, uri: str) -> Optional[MediaItem]:
        """
        Resolve a media URI to a MediaItem.
        
        Supports:
            - mdocx://media/<id> - resolves by ID
            - Relative paths - resolves by path
        """
        if uri.startswith("mdocx://media/"):
            media_id = uri[14:]  # Remove "mdocx://media/"
            return self.get_media_by_id(media_id)
        else:
            return self.get_media_by_path(uri)
