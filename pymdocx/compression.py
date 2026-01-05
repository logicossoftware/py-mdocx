"""
Compression handlers for MDOCX sections.
"""

import io
import zipfile
from typing import Tuple

from .constants import CompressionMethod


class CompressionError(Exception):
    """Error during compression or decompression."""
    pass


def _check_zstd():
    """Check if zstandard is available."""
    try:
        import zstandard
        return zstandard
    except ImportError:
        raise CompressionError(
            "zstandard package not installed. Install with: pip install zstandard"
        )


def _check_lz4():
    """Check if lz4 is available."""
    try:
        import lz4.frame
        return lz4.frame
    except ImportError:
        raise CompressionError(
            "lz4 package not installed. Install with: pip install lz4"
        )


def _check_brotli():
    """Check if brotli is available."""
    try:
        import brotli
        return brotli
    except ImportError:
        raise CompressionError(
            "brotli package not installed. Install with: pip install brotli"
        )


def compress(data: bytes, method: CompressionMethod) -> bytes:
    """
    Compress data using the specified method.
    
    Args:
        data: Raw bytes to compress
        method: Compression method to use
        
    Returns:
        Compressed bytes (without uncompressed length prefix)
    """
    if method == CompressionMethod.NONE:
        return data
    
    elif method == CompressionMethod.ZIP:
        # Create ZIP archive with single payload.gob entry
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('payload.gob', data)
        return buf.getvalue()
    
    elif method == CompressionMethod.ZSTD:
        zstd = _check_zstd()
        cctx = zstd.ZstdCompressor()
        return cctx.compress(data)
    
    elif method == CompressionMethod.LZ4:
        lz4_frame = _check_lz4()
        return lz4_frame.compress(data)
    
    elif method == CompressionMethod.BROTLI:
        brotli = _check_brotli()
        return brotli.compress(data)
    
    else:
        raise CompressionError(f"Unknown compression method: {method}")


def decompress(
    data: bytes, 
    method: CompressionMethod, 
    expected_size: int,
    max_size: int = None
) -> bytes:
    """
    Decompress data using the specified method.
    
    Args:
        data: Compressed bytes
        method: Compression method used
        expected_size: Expected uncompressed size
        max_size: Maximum allowed uncompressed size (for safety)
        
    Returns:
        Decompressed bytes
        
    Raises:
        CompressionError: If decompression fails or size limits exceeded
    """
    if max_size is not None and expected_size > max_size:
        raise CompressionError(
            f"Uncompressed size {expected_size} exceeds maximum {max_size}"
        )
    
    if method == CompressionMethod.NONE:
        return data
    
    elif method == CompressionMethod.ZIP:
        return _decompress_zip(data, expected_size)
    
    elif method == CompressionMethod.ZSTD:
        return _decompress_zstd(data, expected_size)
    
    elif method == CompressionMethod.LZ4:
        return _decompress_lz4(data, expected_size)
    
    elif method == CompressionMethod.BROTLI:
        return _decompress_brotli(data, expected_size)
    
    else:
        raise CompressionError(f"Unknown compression method: {method}")


def _decompress_zip(data: bytes, expected_size: int) -> bytes:
    """Decompress ZIP container."""
    buf = io.BytesIO(data)
    try:
        with zipfile.ZipFile(buf, 'r') as zf:
            names = zf.namelist()
            
            # Must contain exactly one entry named "payload.gob"
            if len(names) != 1:
                raise CompressionError(
                    f"ZIP archive must contain exactly one entry, got {len(names)}"
                )
            
            if names[0] != 'payload.gob':
                raise CompressionError(
                    f"ZIP entry must be named 'payload.gob', got '{names[0]}'"
                )
            
            info = zf.getinfo('payload.gob')
            if info.file_size != expected_size:
                raise CompressionError(
                    f"ZIP entry size {info.file_size} != expected {expected_size}"
                )
            
            result = zf.read('payload.gob')
            if len(result) != expected_size:
                raise CompressionError(
                    f"Decompressed size {len(result)} != expected {expected_size}"
                )
            
            return result
            
    except zipfile.BadZipFile as e:
        raise CompressionError(f"Invalid ZIP archive: {e}")


def _decompress_zstd(data: bytes, expected_size: int) -> bytes:
    """Decompress Zstandard stream."""
    zstd = _check_zstd()
    
    dctx = zstd.ZstdDecompressor()
    try:
        result = dctx.decompress(data, max_output_size=expected_size + 1)
    except zstd.ZstdError as e:
        raise CompressionError(f"Zstandard decompression failed: {e}")
    
    if len(result) != expected_size:
        raise CompressionError(
            f"Decompressed size {len(result)} != expected {expected_size}"
        )
    
    return result


def _decompress_lz4(data: bytes, expected_size: int) -> bytes:
    """Decompress LZ4 stream."""
    lz4_frame = _check_lz4()
    
    try:
        result = lz4_frame.decompress(data)
    except Exception as e:
        raise CompressionError(f"LZ4 decompression failed: {e}")
    
    if len(result) != expected_size:
        raise CompressionError(
            f"Decompressed size {len(result)} != expected {expected_size}"
        )
    
    return result


def _decompress_brotli(data: bytes, expected_size: int) -> bytes:
    """Decompress Brotli stream."""
    brotli = _check_brotli()
    
    try:
        result = brotli.decompress(data)
    except brotli.error as e:
        raise CompressionError(f"Brotli decompression failed: {e}")
    
    if len(result) != expected_size:
        raise CompressionError(
            f"Decompressed size {len(result)} != expected {expected_size}"
        )
    
    return result


def get_available_methods() -> list[CompressionMethod]:
    """Get list of available compression methods."""
    methods = [CompressionMethod.NONE, CompressionMethod.ZIP]
    
    try:
        import zstandard
        methods.append(CompressionMethod.ZSTD)
    except ImportError:
        pass
    
    try:
        import lz4.frame
        methods.append(CompressionMethod.LZ4)
    except ImportError:
        pass
    
    try:
        import brotli
        methods.append(CompressionMethod.BROTLI)
    except ImportError:
        pass
    
    return methods
