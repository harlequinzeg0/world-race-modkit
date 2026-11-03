"""Convert textures between the game's BOG format and DDS.

BOG layout is in docs/FINDINGS.md. DXT textures hold a whole DDS file after the
56-byte header. Paletted textures hold a palette and 8-bit pixels, and export as
32-bit DDS. The game accepts DXT in paletted slots, so edits always import as DXT.
"""
import struct
from dataclasses import dataclass
from hashlib import sha256

HEADER_SIZE = 56
TYPE_DXT1 = 256
TYPE_DXT5 = 512
TYPE_PALETTED = 64

MAGIC = b"BOG 1.02   \0"
PALETTE_SIZE = 1024
DDS_HEADER_SIZE = 128
ALPHA_OFFSET = 0x24
ALPHA_DXT5 = 2
DXT_TYPES = {b"DXT1": TYPE_DXT1, b"DXT5": TYPE_DXT5}
DXT_BLOCK_BYTES = {b"DXT1": 8, b"DXT5": 16}

DDS_FLAGS_RGBA = 0x2100F  # caps, height, width, pitch, pixel format, mip count
DDS_PF_RGBA = 0x41  # RGB with alpha
DDS_CAPS_MIPMAPPED = 0x401008


class BogError(Exception):
    pass


@dataclass
class BogHeader:
    type: int
    width: int
    height: int
    mips: int
    count: int
    size: int
    raw: bytes


def parse_header(data):
    if len(data) < HEADER_SIZE or data[:len(MAGIC)] != MAGIC:
        raise BogError("not a BOG 1.02 texture")
    fields = struct.unpack_from("<6I", data, len(MAGIC))
    return BogHeader(*fields, raw=bytes(data[:HEADER_SIZE]))


def _mip_sizes(width, height, mips):
    for _ in range(mips):
        yield width, height
        width, height = max(1, width // 2), max(1, height // 2)


def _rgba_dds_header(width, height, mips):
    header = b"DDS " + struct.pack("<7I", 124, DDS_FLAGS_RGBA, height, width, width * 4, 0, mips) + bytes(44)
    header += struct.pack("<2I", 32, DDS_PF_RGBA) + bytes(4)
    header += struct.pack("<5I", 32, 0xFF0000, 0xFF00, 0xFF, 0xFF000000)
    return header + struct.pack("<I", DDS_CAPS_MIPMAPPED) + bytes(16)


def _paletted_to_dds(data, header):
    palette = data[HEADER_SIZE:HEADER_SIZE + PALETTE_SIZE]
    indices = data[HEADER_SIZE + PALETTE_SIZE:HEADER_SIZE + PALETTE_SIZE + header.size]
    if len(palette) != PALETTE_SIZE or len(indices) != header.size:
        raise BogError("paletted texture is cut short")
    # Palette entries are B, G, R, A, which is the DDS pixel order, so each
    # channel is one 256-byte lookup table.
    pixels = bytearray(len(indices) * 4)
    for channel in range(4):
        pixels[channel::4] = indices.translate(palette[channel::4])
    return _rgba_dds_header(header.width, header.height, header.mips) + bytes(pixels)


def bog_to_dds(data):
    header = parse_header(data)
    if header.type == TYPE_PALETTED:
        return _paletted_to_dds(bytes(data), header)
    if header.type in (TYPE_DXT1, TYPE_DXT5):
        return bytes(data[HEADER_SIZE:])
    raise BogError(f"unsupported texture type {header.type}")


def dds_to_bog(dds, original_header):
    if len(dds) < DDS_HEADER_SIZE or dds[:4] != b"DDS ":
        raise BogError("not a DDS file")
    height, width = struct.unpack_from("<II", dds, 12)
    mips = max(1, struct.unpack_from("<I", dds, 28)[0])
    fourcc = dds[84:88]
    if fourcc not in DXT_TYPES:
        raise BogError("textures must be saved as DXT1 or DXT5")
    block = DXT_BLOCK_BYTES[fourcc]
    expected = sum(max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block for w, h in _mip_sizes(width, height, mips))
    if len(dds) - DDS_HEADER_SIZE < expected:
        raise BogError("DDS file is too short for its size and mip count")

    kind = DXT_TYPES[fourcc]
    if original_header is None:
        header = bytearray(MAGIC + struct.pack("<I", kind) + bytes(HEADER_SIZE - len(MAGIC) - 4))
        previous_kind = None
    else:
        header = bytearray(parse_header(original_header).raw)
        previous_kind = parse_header(original_header).type
    struct.pack_into("<6I", header, len(MAGIC), kind, width, height, mips, 1, len(dds))
    if kind != previous_kind:
        struct.pack_into("<I", header, ALPHA_OFFSET, ALPHA_DXT5 if kind == TYPE_DXT5 else 0)
    return bytes(header) + dds


def restore_bog(dds, exported_sha256, original_bog):
    if sha256(dds).hexdigest() == exported_sha256:
        return original_bog
    return dds_to_bog(dds, original_bog[:HEADER_SIZE])
