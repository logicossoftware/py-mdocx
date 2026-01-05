"""
Data models for MDOCX bundles.
"""

from dataclasses import dataclass, field
from typing import Optional
import hashlib


@dataclass
class Metadata:
    """Container metadata (optional JSON block)."""
    title: Optional[str] = None
    description: Optional[str] = None
    creator: Optional[str] = None
    created_at: Optional[str] = None  # RFC3339 timestamp
    root: Optional[str] = None  # Container path of primary Markdown file
    tags: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)  # Additional arbitrary keys
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {}
        if self.title is not None:
            result["title"] = self.title
        if self.description is not None:
            result["description"] = self.description
        if self.creator is not None:
            result["creator"] = self.creator
        if self.created_at is not None:
            result["created_at"] = self.created_at
        if self.root is not None:
            result["root"] = self.root
        if self.tags:
            result["tags"] = self.tags
        result.update(self.extra)
        return result
    
    @classmethod
    def from_dict(cls, data: dict) -> "Metadata":
        """Create Metadata from dictionary."""
        known_keys = {"title", "description", "creator", "created_at", "root", "tags"}
        extra = {k: v for k, v in data.items() if k not in known_keys}
        return cls(
            title=data.get("title"),
            description=data.get("description"),
            creator=data.get("creator"),
            created_at=data.get("created_at"),
            root=data.get("root"),
            tags=data.get("tags", []),
            extra=extra,
        )


@dataclass
class MarkdownFile:
    """A single Markdown file within the bundle."""
    path: str  # Container path, e.g. "docs/readme.md"
    content: bytes  # UTF-8 Markdown bytes
    media_refs: list[str] = field(default_factory=list)  # Referenced media IDs
    attributes: dict[str, str] = field(default_factory=dict)  # Arbitrary per-file attributes
    
    @property
    def content_str(self) -> str:
        """Get content as string."""
        return self.content.decode("utf-8")
    
    @classmethod
    def from_string(cls, path: str, content: str, **kwargs) -> "MarkdownFile":
        """Create MarkdownFile from string content."""
        return cls(path=path, content=content.encode("utf-8"), **kwargs)


@dataclass
class MarkdownBundle:
    """Bundle of Markdown files (Section Type 1)."""
    files: list[MarkdownFile] = field(default_factory=list)
    bundle_version: int = 1
    root_path: str = ""  # Optional: primary markdown path
    
    def validate(self) -> None:
        """Validate bundle constraints."""
        if self.bundle_version != 1:
            raise ValueError(f"BundleVersion must be 1, got {self.bundle_version}")
        if not self.files:
            raise ValueError("MarkdownBundle must contain at least one file")
        
        paths = set()
        for f in self.files:
            if not f.path:
                raise ValueError("MarkdownFile.Path must be non-empty")
            if f.path in paths:
                raise ValueError(f"Duplicate MarkdownFile.Path: {f.path}")
            paths.add(f.path)
            
            # Path validation
            if f.path.startswith("/"):
                raise ValueError(f"Path must not be absolute: {f.path}")
            if ".." in f.path.split("/"):
                raise ValueError(f"Path must not contain '..': {f.path}")


@dataclass
class MediaItem:
    """A single media item within the bundle."""
    id: str  # Stable unique identifier
    data: bytes  # Raw media bytes
    mime_type: str = ""  # e.g. "image/png"
    path: str = ""  # Optional container path
    sha256: bytes = b""  # Optional 32-byte hash
    attributes: dict[str, str] = field(default_factory=dict)
    
    def compute_sha256(self) -> bytes:
        """Compute SHA-256 hash of data."""
        return hashlib.sha256(self.data).digest()
    
    def verify_sha256(self) -> bool:
        """Verify SHA-256 hash if present."""
        if not self.sha256 or self.sha256 == bytes(32):
            return True  # No hash to verify
        return self.sha256 == self.compute_sha256()


@dataclass
class MediaBundle:
    """Bundle of media items (Section Type 2)."""
    items: list[MediaItem] = field(default_factory=list)
    bundle_version: int = 1
    
    def validate(self) -> None:
        """Validate bundle constraints."""
        if self.bundle_version != 1:
            raise ValueError(f"BundleVersion must be 1, got {self.bundle_version}")
        
        ids = set()
        for item in self.items:
            if not item.id:
                raise ValueError("MediaItem.ID must be non-empty")
            if item.id in ids:
                raise ValueError(f"Duplicate MediaItem.ID: {item.id}")
            ids.add(item.id)
            
            # Verify hash if present
            if item.sha256 and item.sha256 != bytes(32):
                if not item.verify_sha256():
                    raise ValueError(f"SHA256 mismatch for MediaItem: {item.id}")
