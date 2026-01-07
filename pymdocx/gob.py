"""
Go gob serialization for MDOCX bundles.

This module implements Go's encoding/gob format for MDOCX bundle structures.
Go gob is a self-describing binary format that includes type definitions.

Gob wire format:
- Each message: [length (uint)] [type_id (int)] [data...]
- Type definitions use negative type IDs: -N means "defining type N"
- Values use positive type IDs: N means "value of type N"
- Integers: 0-127 as single byte, else (256-n_bytes) followed by big-endian bytes
- Signed ints use zigzag encoding: positive n -> 2n, negative n -> -2n-1

References:
- https://go.dev/blog/gob
- https://pkg.go.dev/encoding/gob
"""

from io import BytesIO
from typing import List, Dict, Tuple

from .models import MarkdownBundle, MarkdownFile, MediaBundle, MediaItem


# Built-in type IDs (from Go's gob/type.go)
TYPE_BOOL = 1
TYPE_INT = 2
TYPE_UINT = 3
TYPE_FLOAT = 4
TYPE_BYTES = 5  # []byte is special-cased as bytes
TYPE_STRING = 6
TYPE_COMPLEX = 7
TYPE_INTERFACE = 8
# Types 9-15 are reserved
TYPE_WIRETYPE = 16
TYPE_ARRAYTYPE = 17
TYPE_COMMONTYPE = 18
TYPE_SLICETYPE = 19
TYPE_STRUCTTYPE = 20
TYPE_FIELDTYPE = 21
# 22 is skipped
TYPE_MAPTYPE = 23

# User types start at 64
FIRST_USER_ID = 64


class GobEncoder:
    """Encodes Python objects to Go gob format."""
    
    def __init__(self):
        self.buffer = BytesIO()
        self.next_type_id = FIRST_USER_ID
        self.defined_types: Dict[str, int] = {}
    
    def _encode_uint(self, value: int) -> bytes:
        """Encode an unsigned integer in gob format."""
        if value <= 127:
            return bytes([value])
        # Count bytes needed
        n = (value.bit_length() + 7) // 8
        return bytes([256 - n]) + value.to_bytes(n, 'big')
    
    def _encode_int(self, value: int) -> bytes:
        """Encode a signed integer in gob zigzag format."""
        if value >= 0:
            return self._encode_uint(value * 2)
        else:
            return self._encode_uint((-value * 2) - 1)
    
    def _encode_string(self, s: str) -> bytes:
        """Encode a string: length prefix + UTF-8 bytes."""
        encoded = s.encode('utf-8')
        return self._encode_uint(len(encoded)) + encoded
    
    def _encode_bytes(self, data: bytes) -> bytes:
        """Encode a byte slice: length prefix + bytes."""
        return self._encode_uint(len(data)) + data
    
    def _alloc_type_id(self, name: str) -> int:
        """Allocate a new type ID for a named type."""
        if name in self.defined_types:
            return self.defined_types[name]
        tid = self.next_type_id
        self.next_type_id += 1
        self.defined_types[name] = tid
        return tid
    
    def _write_message(self, type_id: int, data: bytes) -> None:
        """Write a complete gob message: [length][type_id][data]."""
        # Build message content: type_id + data
        content = self._encode_int(type_id) + data
        # Write: length prefix + content
        self.buffer.write(self._encode_uint(len(content)))
        self.buffer.write(content)
    
    def _build_struct_type(self, type_id: int, type_name: str, 
                           fields: List[Tuple[str, int]]) -> bytes:
        """Build wireType data for a struct type definition.
        
        wireType struct has field 3 = StructT (*structType)
        structType has: CommonType (embedded), Field ([]fieldType)
        CommonType has: Name (string), Id (typeId)
        fieldType has: Name (string), Id (typeId)
        """
        buf = BytesIO()
        
        # wireType field delta 3 = StructT
        buf.write(self._encode_uint(3))
        
        # *structType - not nil indicator
        buf.write(self._encode_uint(1))
        
        # structType.CommonType.Name (field delta 1)
        buf.write(self._encode_uint(1))
        buf.write(self._encode_string(type_name))
        
        # structType.CommonType.Id (field delta 1 from Name)
        buf.write(self._encode_uint(1))
        buf.write(self._encode_int(type_id))
        
        # End of CommonType (0)
        buf.write(self._encode_uint(0))
        
        # structType.Field (field delta 1 from CommonType)
        buf.write(self._encode_uint(1))
        
        # []fieldType - length prefix
        buf.write(self._encode_uint(len(fields)))
        
        # Each fieldType
        for field_name, field_type_id in fields:
            # fieldType.Name (field delta 1)
            buf.write(self._encode_uint(1))
            buf.write(self._encode_string(field_name))
            
            # fieldType.Id (field delta 1)
            buf.write(self._encode_uint(1))
            buf.write(self._encode_int(field_type_id))
            
            # End of fieldType (0)
            buf.write(self._encode_uint(0))
        
        # End of structType (0)
        buf.write(self._encode_uint(0))
        
        # End of wireType (0)
        buf.write(self._encode_uint(0))
        
        return buf.getvalue()
    
    def _build_slice_type(self, type_id: int, type_name: str, 
                          elem_type_id: int) -> bytes:
        """Build wireType data for a slice type definition.
        
        wireType field 2 = SliceT (*sliceType)
        sliceType has: CommonType (embedded), Elem (typeId)
        """
        buf = BytesIO()
        
        # wireType field delta 2 = SliceT
        buf.write(self._encode_uint(2))
        
        # *sliceType - not nil indicator
        buf.write(self._encode_uint(1))
        
        # sliceType.CommonType.Name (field delta 1)
        buf.write(self._encode_uint(1))
        buf.write(self._encode_string(type_name))
        
        # sliceType.CommonType.Id (field delta 1)
        buf.write(self._encode_uint(1))
        buf.write(self._encode_int(type_id))
        
        # End of CommonType (0)
        buf.write(self._encode_uint(0))
        
        # sliceType.Elem (field delta 1)
        buf.write(self._encode_uint(1))
        buf.write(self._encode_int(elem_type_id))
        
        # End of sliceType (0)
        buf.write(self._encode_uint(0))
        
        # End of wireType (0)
        buf.write(self._encode_uint(0))
        
        return buf.getvalue()
    
    def _build_map_type(self, type_id: int, type_name: str,
                        key_type_id: int, elem_type_id: int) -> bytes:
        """Build wireType data for a map type definition.
        
        wireType field 4 = MapT (*mapType)
        mapType has: CommonType (embedded), Key (typeId), Elem (typeId)
        """
        buf = BytesIO()
        
        # wireType field delta 4 = MapT
        buf.write(self._encode_uint(4))
        
        # *mapType - not nil indicator
        buf.write(self._encode_uint(1))
        
        # mapType.CommonType.Name (field delta 1)
        buf.write(self._encode_uint(1))
        buf.write(self._encode_string(type_name))
        
        # mapType.CommonType.Id (field delta 1)
        buf.write(self._encode_uint(1))
        buf.write(self._encode_int(type_id))
        
        # End of CommonType (0)
        buf.write(self._encode_uint(0))
        
        # mapType.Key (field delta 1)
        buf.write(self._encode_uint(1))
        buf.write(self._encode_int(key_type_id))
        
        # mapType.Elem (field delta 1)
        buf.write(self._encode_uint(1))
        buf.write(self._encode_int(elem_type_id))
        
        # End of mapType (0)
        buf.write(self._encode_uint(0))
        
        # End of wireType (0)
        buf.write(self._encode_uint(0))
        
        return buf.getvalue()
    
    def _build_array_type(self, type_id: int, type_name: str,
                          elem_type_id: int, length: int) -> bytes:
        """Build wireType data for an array type definition.
        
        wireType field 1 = ArrayT (*arrayType)
        arrayType has: CommonType (embedded), Elem (typeId), Len (int)
        """
        buf = BytesIO()
        
        # wireType field delta 1 = ArrayT
        buf.write(self._encode_uint(1))
        
        # *arrayType - not nil indicator
        buf.write(self._encode_uint(1))
        
        # arrayType.CommonType.Name (field delta 1)
        buf.write(self._encode_uint(1))
        buf.write(self._encode_string(type_name))
        
        # arrayType.CommonType.Id (field delta 1)
        buf.write(self._encode_uint(1))
        buf.write(self._encode_int(type_id))
        
        # End of CommonType (0)
        buf.write(self._encode_uint(0))
        
        # arrayType.Elem (field delta 1)
        buf.write(self._encode_uint(1))
        buf.write(self._encode_int(elem_type_id))
        
        # arrayType.Len (field delta 1)
        buf.write(self._encode_uint(1))
        buf.write(self._encode_int(length))
        
        # End of arrayType (0)
        buf.write(self._encode_uint(0))
        
        # End of wireType (0)
        buf.write(self._encode_uint(0))
        
        return buf.getvalue()
    
    def _define_type(self, type_id: int, wiretype_data: bytes) -> None:
        """Write a type definition message."""
        # Type definition uses negative type ID
        self._write_message(-type_id, wiretype_data)
    
    def _encode_struct_value(self, fields: List[Tuple[int, bytes]]) -> bytes:
        """Encode a struct value with field deltas."""
        buf = BytesIO()
        prev_field = 0
        
        for field_num, field_data in fields:
            if field_data:  # Skip zero/empty fields
                delta = field_num + 1 - prev_field
                prev_field = field_num + 1
                buf.write(self._encode_uint(delta))
                buf.write(field_data)
        
        # End of struct
        buf.write(self._encode_uint(0))
        return buf.getvalue()
    
    def _encode_markdown_file(self, mf: MarkdownFile) -> bytes:
        """Encode a MarkdownFile struct value."""
        fields = []
        
        # Field 0: Path (string)
        if mf.path:
            fields.append((0, self._encode_string(mf.path)))
        
        # Field 1: Content ([]byte)
        if mf.content:
            fields.append((1, self._encode_bytes(mf.content)))
        
        # Field 2: MediaRefs ([]string)
        if mf.media_refs:
            buf = BytesIO()
            buf.write(self._encode_uint(len(mf.media_refs)))
            for s in mf.media_refs:
                buf.write(self._encode_string(s))
            fields.append((2, buf.getvalue()))
        
        # Field 3: Attributes (map[string]string)
        if mf.attributes:
            buf = BytesIO()
            buf.write(self._encode_uint(len(mf.attributes)))
            for k, v in mf.attributes.items():
                buf.write(self._encode_string(k))
                buf.write(self._encode_string(v))
            fields.append((3, buf.getvalue()))
        
        return self._encode_struct_value(fields)
    
    def _encode_media_item(self, mi: MediaItem) -> bytes:
        """Encode a MediaItem struct value."""
        fields = []
        
        # Field 0: ID (string)
        if mi.id:
            fields.append((0, self._encode_string(mi.id)))
        
        # Field 1: Path (string)
        if mi.path:
            fields.append((1, self._encode_string(mi.path)))
        
        # Field 2: MIMEType (string)
        if mi.mime_type:
            fields.append((2, self._encode_string(mi.mime_type)))
        
        # Field 3: Data ([]byte)
        if mi.data:
            fields.append((3, self._encode_bytes(mi.data)))
        
        # Field 4: SHA256 ([32]uint8 array) - only if not all zeros
        # Arrays of uint8 are encoded as: length (uint) + each element as uint
        if mi.sha256 and mi.sha256 != bytes(32):
            sha_buf = BytesIO()
            sha_buf.write(self._encode_uint(32))  # Array length
            for b in mi.sha256:
                sha_buf.write(self._encode_uint(b))  # Each byte as uint
            fields.append((4, sha_buf.getvalue()))
        
        # Field 5: Attributes (map[string]string)
        if mi.attributes:
            buf = BytesIO()
            buf.write(self._encode_uint(len(mi.attributes)))
            for k, v in mi.attributes.items():
                buf.write(self._encode_string(k))
                buf.write(self._encode_string(v))
            fields.append((5, buf.getvalue()))
        
        return self._encode_struct_value(fields)
    
    def encode_markdown_bundle(self, bundle: MarkdownBundle) -> bytes:
        """Encode a MarkdownBundle to gob format."""
        self.buffer = BytesIO()
        self.next_type_id = FIRST_USER_ID
        self.defined_types = {}
        
        # Define types in order that Go uses:
        # 1. MarkdownBundle (type 64)
        # 2. []MarkdownFile (type 68) 
        # 3. MarkdownFile (type 65)
        # 4. []string (type 66)
        # 5. map[string]string (type 67)
        
        # Allocate IDs first
        bundle_id = self._alloc_type_id("MarkdownBundle")  # 64
        md_file_id = self._alloc_type_id("MarkdownFile")   # 65
        slice_s_id = self._alloc_type_id("[]string")       # 66
        map_ss_id = self._alloc_type_id("map[string]string")  # 67
        slice_md_id = self._alloc_type_id("[]MarkdownFile")   # 68
        
        # Define MarkdownBundle (type 64)
        self._define_type(bundle_id, self._build_struct_type(
            bundle_id, "MarkdownBundle",
            [
                ("BundleVersion", TYPE_UINT),
                ("RootPath", TYPE_STRING),
                ("Files", slice_md_id),
            ]
        ))
        
        # Define []MarkdownFile (type 68)
        self._define_type(slice_md_id, self._build_slice_type(
            slice_md_id, "[]mdocx.MarkdownFile", md_file_id
        ))
        
        # Define MarkdownFile (type 65)
        self._define_type(md_file_id, self._build_struct_type(
            md_file_id, "MarkdownFile",
            [
                ("Path", TYPE_STRING),
                ("Content", TYPE_BYTES),
                ("MediaRefs", slice_s_id),
                ("Attributes", map_ss_id),
            ]
        ))
        
        # Define []string (type 66)
        self._define_type(slice_s_id, self._build_slice_type(
            slice_s_id, "[]string", TYPE_STRING
        ))
        
        # Define map[string]string (type 67)
        self._define_type(map_ss_id, self._build_map_type(
            map_ss_id, "map[string]string", TYPE_STRING, TYPE_STRING
        ))
        
        # Encode bundle value
        fields = []
        
        # Field 0: BundleVersion (uint16)
        if bundle.bundle_version != 0:
            fields.append((0, self._encode_uint(bundle.bundle_version)))
        
        # Field 1: RootPath (string)
        if bundle.root_path:
            fields.append((1, self._encode_string(bundle.root_path)))
        
        # Field 2: Files ([]MarkdownFile)
        if bundle.files:
            buf = BytesIO()
            buf.write(self._encode_uint(len(bundle.files)))
            for f in bundle.files:
                buf.write(self._encode_markdown_file(f))
            fields.append((2, buf.getvalue()))
        
        value_data = self._encode_struct_value(fields)
        
        # Write value message with positive type ID
        self._write_message(bundle_id, value_data)
        
        return self.buffer.getvalue()
    
    def encode_media_bundle(self, bundle: MediaBundle) -> bytes:
        """Encode a MediaBundle to gob format."""
        self.buffer = BytesIO()
        self.next_type_id = FIRST_USER_ID
        self.defined_types = {}
        
        # Allocate type IDs
        bundle_id = self._alloc_type_id("MediaBundle")     # 64
        item_id = self._alloc_type_id("MediaItem")         # 65
        sha256_id = self._alloc_type_id("[32]uint8")       # 66
        map_ss_id = self._alloc_type_id("map[string]string")  # 67
        slice_item_id = self._alloc_type_id("[]MediaItem") # 68
        
        # Define MediaBundle (type 64)
        self._define_type(bundle_id, self._build_struct_type(
            bundle_id, "MediaBundle",
            [
                ("BundleVersion", TYPE_UINT),
                ("Items", slice_item_id),
            ]
        ))
        
        # Define []MediaItem (type 68)
        self._define_type(slice_item_id, self._build_slice_type(
            slice_item_id, "[]mdocx.MediaItem", item_id
        ))
        
        # Define MediaItem (type 65)
        self._define_type(item_id, self._build_struct_type(
            item_id, "MediaItem",
            [
                ("ID", TYPE_STRING),
                ("Path", TYPE_STRING),
                ("MIMEType", TYPE_STRING),
                ("Data", TYPE_BYTES),
                ("SHA256", sha256_id),
                ("Attributes", map_ss_id),
            ]
        ))
        
        # Define [32]uint8 (type 66)
        self._define_type(sha256_id, self._build_array_type(
            sha256_id, "[32]uint8", TYPE_UINT, 32
        ))
        
        # Define map[string]string (type 67)
        self._define_type(map_ss_id, self._build_map_type(
            map_ss_id, "map[string]string", TYPE_STRING, TYPE_STRING
        ))
        
        # Encode bundle value
        fields = []
        
        # Field 0: BundleVersion
        if bundle.bundle_version != 0:
            fields.append((0, self._encode_uint(bundle.bundle_version)))
        
        # Field 1: Items
        if bundle.items:
            buf = BytesIO()
            buf.write(self._encode_uint(len(bundle.items)))
            for item in bundle.items:
                buf.write(self._encode_media_item(item))
            fields.append((1, buf.getvalue()))
        
        value_data = self._encode_struct_value(fields)
        self._write_message(bundle_id, value_data)
        
        return self.buffer.getvalue()


class GobDecoder:
    """Decodes Go gob format to Python objects."""
    
    def __init__(self, data: bytes):
        self.buffer = BytesIO(data)
        self.types: Dict[int, dict] = {}
    
    def _read_uint(self) -> int:
        """Read an unsigned integer."""
        b = self.buffer.read(1)
        if not b:
            raise EOFError("Unexpected end of gob data")
        
        first = b[0]
        if first <= 127:
            return first
        else:
            n = 256 - first
            data = self.buffer.read(n)
            if len(data) != n:
                raise EOFError("Unexpected end of gob data")
            return int.from_bytes(data, 'big')
    
    def _read_int(self) -> int:
        """Read a signed integer (zigzag decoded)."""
        u = self._read_uint()
        if u & 1:
            return -((u + 1) // 2)
        return u // 2
    
    def _read_bytes(self) -> bytes:
        """Read a byte slice."""
        length = self._read_uint()
        data = self.buffer.read(length)
        if len(data) != length:
            raise EOFError("Unexpected end of gob data")
        return data
    
    def _read_string(self) -> str:
        """Read a string."""
        return self._read_bytes().decode('utf-8')
    
    def _skip_value(self) -> None:
        """Skip over an unknown value by reading its byte count."""
        length = self._read_uint()
        self.buffer.read(length)
    
    def _decode_markdown_file(self) -> MarkdownFile:
        """Decode a MarkdownFile struct."""
        path = ""
        content = b""
        media_refs: List[str] = []
        attributes: Dict[str, str] = {}
        
        prev_field = 0
        while True:
            delta = self._read_uint()
            if delta == 0:
                break
            
            field_num = prev_field + delta - 1
            prev_field = field_num + 1
            
            if field_num == 0:  # Path
                path = self._read_string()
            elif field_num == 1:  # Content
                content = self._read_bytes()
            elif field_num == 2:  # MediaRefs
                count = self._read_uint()
                media_refs = [self._read_string() for _ in range(count)]
            elif field_num == 3:  # Attributes
                count = self._read_uint()
                for _ in range(count):
                    k = self._read_string()
                    v = self._read_string()
                    attributes[k] = v
        
        return MarkdownFile(
            path=path,
            content=content,
            media_refs=media_refs,
            attributes=attributes,
        )
    
    def _decode_media_item(self) -> MediaItem:
        """Decode a MediaItem struct."""
        id_ = ""
        path = ""
        mime_type = ""
        data = b""
        sha256 = bytes(32)
        attributes: Dict[str, str] = {}
        
        prev_field = 0
        while True:
            delta = self._read_uint()
            if delta == 0:
                break
            
            field_num = prev_field + delta - 1
            prev_field = field_num + 1
            
            if field_num == 0:  # ID
                id_ = self._read_string()
            elif field_num == 1:  # Path
                path = self._read_string()
            elif field_num == 2:  # MIMEType
                mime_type = self._read_string()
            elif field_num == 3:  # Data
                data = self._read_bytes()
            elif field_num == 4:  # SHA256 - [32]uint8 array
                # Go encodes [N]uint8 as: length (uint), followed by N uint values
                # Each uint8 value is encoded: 0-127 as single byte, 128-255 as 0xff + byte
                length = self._read_uint()
                if length != 32:
                    raise ValueError(f"SHA256 array must have 32 elements, got {length}")
                sha256_bytes = []
                for _ in range(length):
                    sha256_bytes.append(self._read_uint())
                sha256 = bytes(sha256_bytes)
            elif field_num == 5:  # Attributes
                count = self._read_uint()
                for _ in range(count):
                    k = self._read_string()
                    v = self._read_string()
                    attributes[k] = v
        
        return MediaItem(
            id=id_,
            path=path,
            mime_type=mime_type,
            data=data,
            sha256=sha256,
            attributes=attributes,
        )
    
    def _read_message(self) -> Tuple[int, BytesIO]:
        """Read a complete gob message, return (type_id, content_reader)."""
        msg_len = self._read_uint()
        content = self.buffer.read(msg_len)
        if len(content) != msg_len:
            raise EOFError("Unexpected end of gob data")
        
        content_reader = BytesIO(content)

        # Read type ID from content (gob int encoded, zigzag decoded)
        b0 = content_reader.read(1)
        if not b0:
            raise EOFError("Unexpected end of gob message")
        first = b0[0]
        if first <= 127:
            u = first
        else:
            n = 256 - first
            raw = content_reader.read(n)
            if len(raw) != n:
                raise EOFError("Unexpected end of gob message")
            u = int.from_bytes(raw, 'big')
        
        # Zigzag decode
        if u & 1:
            type_id = -((u + 1) // 2)
        else:
            type_id = u // 2
        
        return type_id, content_reader
    
    def decode_markdown_bundle(self) -> MarkdownBundle:
        """Decode a MarkdownBundle from gob format."""
        # Read messages until we get a value (positive type ID)
        while True:
            type_id, content = self._read_message()
            
            if type_id >= 0:
                # This is a value
                break
            # else: skip type definition (content already consumed)
        
        # Decode bundle value from content
        bundle_version = 1
        root_path = ""
        files: List[MarkdownFile] = []
        
        # Reset our buffer to read from content
        self.buffer = content
        
        prev_field = 0
        while True:
            delta = self._read_uint()
            if delta == 0:
                break
            
            field_num = prev_field + delta - 1
            prev_field = field_num + 1
            
            if field_num == 0:  # BundleVersion
                bundle_version = self._read_uint()
            elif field_num == 1:  # RootPath
                root_path = self._read_string()
            elif field_num == 2:  # Files
                count = self._read_uint()
                files = [self._decode_markdown_file() for _ in range(count)]
        
        return MarkdownBundle(
            bundle_version=bundle_version,
            root_path=root_path,
            files=files,
        )
    
    def decode_media_bundle(self) -> MediaBundle:
        """Decode a MediaBundle from gob format."""
        # Read messages until we get a value (positive type ID)
        while True:
            type_id, content = self._read_message()
            
            if type_id >= 0:
                break
        
        # Decode bundle value
        bundle_version = 1
        items: List[MediaItem] = []
        
        self.buffer = content
        
        prev_field = 0
        while True:
            delta = self._read_uint()
            if delta == 0:
                break
            
            field_num = prev_field + delta - 1
            prev_field = field_num + 1
            
            if field_num == 0:  # BundleVersion
                bundle_version = self._read_uint()
            elif field_num == 1:  # Items
                count = self._read_uint()
                items = [self._decode_media_item() for _ in range(count)]
        
        return MediaBundle(
            bundle_version=bundle_version,
            items=items,
        )


# Convenience functions
def encode_markdown_bundle(bundle: MarkdownBundle) -> bytes:
    """Encode a MarkdownBundle to gob format."""
    return GobEncoder().encode_markdown_bundle(bundle)


def decode_markdown_bundle(data: bytes) -> MarkdownBundle:
    """Decode a MarkdownBundle from gob format."""
    return GobDecoder(data).decode_markdown_bundle()


def encode_media_bundle(bundle: MediaBundle) -> bytes:
    """Encode a MediaBundle to gob format."""
    return GobEncoder().encode_media_bundle(bundle)


def decode_media_bundle(data: bytes) -> MediaBundle:
    """Decode a MediaBundle from gob format."""
    return GobDecoder(data).decode_media_bundle()
