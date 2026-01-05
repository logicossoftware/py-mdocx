"""
Constants for the MDOCX file format.
"""

from enum import IntEnum, IntFlag

# Magic bytes: ASCII "MDOCX\r\n" followed by 0x1A
# Hex: 4D 44 4F 43 58 0D 0A 1A
MAGIC = b"MDOCX\r\n\x1a"

# Format version
VERSION = 1

# Fixed header size in bytes
FIXED_HEADER_SIZE = 32

# Section header size in bytes
SECTION_HEADER_SIZE = 16


class HeaderFlags(IntFlag):
    """Header flags bitmask."""
    NONE = 0x0000
    METADATA_JSON = 0x0001  # Metadata block is UTF-8 JSON


class SectionType(IntEnum):
    """Section type identifiers."""
    MARKDOWN = 1
    MEDIA = 2


class CompressionMethod(IntEnum):
    """Compression algorithm identifiers (bits 0-3 of SectionFlags)."""
    NONE = 0x0  # Raw gob bytes
    ZIP = 0x1   # ZIP container with single payload.gob entry
    ZSTD = 0x2  # Zstandard compressed stream
    LZ4 = 0x3   # LZ4 compressed stream
    BROTLI = 0x4  # Brotli compressed stream


class SectionFlags(IntFlag):
    """Section flags bitmask."""
    COMPRESSION_MASK = 0x000F  # Bits 0-3: compression method
    HAS_UNCOMPRESSED_LEN = 0x0010  # Bit 4: payload has 8-byte uncompressed length prefix


# Default limits (implementation policy from RFC §11)
DEFAULT_MAX_METADATA_LENGTH = 1 * 1024 * 1024  # 1 MiB
DEFAULT_MAX_MARKDOWN_UNCOMPRESSED = 256 * 1024 * 1024  # 256 MiB
DEFAULT_MAX_MEDIA_UNCOMPRESSED = 2 * 1024 * 1024 * 1024  # 2 GiB
DEFAULT_MAX_MARKDOWN_FILES = 10_000
DEFAULT_MAX_MEDIA_ITEMS = 10_000
DEFAULT_MAX_SINGLE_MEDIA_DATA = 512 * 1024 * 1024  # 512 MiB
