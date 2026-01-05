"""
PyMDOCX - Python implementation of the MDOCX file format.

MDOCX (MarkDown Open Container eXchange) is a single-file container
holding one or more Markdown documents plus referenced binary media.
"""

from .models import (
    MarkdownBundle,
    MarkdownFile,
    MediaBundle,
    MediaItem,
    Metadata,
)
from .reader import MDOCXReader, MDOCXDocument, MDOCXError, MDOCXFormatError, MDOCXVersionError
from .writer import MDOCXWriter
from .constants import (
    MAGIC,
    VERSION,
    CompressionMethod,
    SectionType,
)
from .compression import CompressionError

__version__ = "0.1.0"
__all__ = [
    # Models
    "MarkdownBundle",
    "MarkdownFile",
    "MediaBundle",
    "MediaItem",
    "Metadata",
    # Reader/Writer
    "MDOCXReader",
    "MDOCXWriter",
    "MDOCXDocument",
    # Exceptions
    "MDOCXError",
    "MDOCXFormatError",
    "MDOCXVersionError",
    "CompressionError",
    # Constants
    "MAGIC",
    "VERSION",
    "CompressionMethod",
    "SectionType",
]
