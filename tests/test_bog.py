import struct
from hashlib import sha256

import pytest

from wrmod.bark import Archive
from wrmod.bog import (
    BogError,
    TYPE_DXT5,
    bog_to_dds,
    dds_to_bog,
    parse_header,
    restore_bog,
)

MAGIC = b"BOG 1.02   \0"


def mip_bytes(fourcc, width, height, mips):
    block = 8 if fourcc == b"DXT1" else 16
    total = 0
    for _ in range(mips):
        total += max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * block
        width, height = max(1, width // 2), max(1, height // 2)
    return total


def make_dds(fourcc, width, height, mips):
    header = b"DDS " + struct.pack("<7I", 124, 0xA1007, height, width, 0, 0, mips) + bytes(44)
    header += struct.pack("<2I", 32, 4) + fourcc + bytes(20) + struct.pack("<I", 0x401008) + bytes(16)
    return header + bytes(i % 251 for i in range(mip_bytes(fourcc, width, height, mips)))


def make_rgba_dds(width, height):
    header = b"DDS " + struct.pack("<7I", 124, 0x100F, height, width, width * 4, 0, 1) + bytes(44)
    header += struct.pack("<2I", 32, 0x41) + bytes(4) + struct.pack("<5I", 32, 0xFF0000, 0xFF00, 0xFF, 0xFF000000)
    header += struct.pack("<I", 0x1000) + bytes(16)
    return header + bytes(width * height * 4)


def make_dxt_bog(fourcc=b"DXT1", width=64, height=64, mips=7, unknown_0x24=0, unknown_0x28=0, unknown_0x30=0):
    dds = make_dds(fourcc, width, height, mips)
    kind = 256 if fourcc == b"DXT1" else 512
    fields = (kind, width, height, mips, 1, len(dds), unknown_0x24, unknown_0x28, 0, unknown_0x30, 0)
    return MAGIC + struct.pack("<11I", *fields) + dds


def make_paletted_bog(width, height, mips):
    palette = bytes(v for i in range(256) for v in (i, 255 - i, 7, 255))
    count = sum(max(1, width >> m) * max(1, height >> m) for m in range(mips))
    pixels = bytes(i % 256 for i in range(count))
    fields = (64, width, height, mips, 1, count, 0, 0, 0, 0, 0)
    return MAGIC + struct.pack("<11I", *fields) + palette + pixels


def read_bit_count(dds):
    return struct.unpack_from("<I", dds, 88)[0]


def test_dxt_round_trip_keeps_unknown_header_fields():
    bog = make_dxt_bog(fourcc=b"DXT5", unknown_0x24=2, unknown_0x28=1, unknown_0x30=0xFFFFFFFE)
    assert dds_to_bog(bog_to_dds(bog), bog[:56]) == bog


def test_new_texture_defaults():
    bog = dds_to_bog(make_dds(b"DXT5", 64, 64, 7), None)
    h = parse_header(bog)
    assert (h.type, h.width, h.height, h.mips, h.count) == (TYPE_DXT5, 64, 64, 7, 1)
    assert bog[0x24:0x28] == (2).to_bytes(4, "little")


def test_size_change_updates_understood_fields_only():
    old = make_dxt_bog(fourcc=b"DXT1", width=256, height=256, mips=9, unknown_0x28=1)
    new = dds_to_bog(make_dds(b"DXT1", 512, 512, 10), old[:56])
    h = parse_header(new)
    assert (h.width, h.height, h.mips, h.size) == (512, 512, 10, len(new) - 56)
    assert new[0x28:0x2C] == old[0x28:0x2C]


def test_dxt1_replacing_paletted_skin_sets_type():
    new = dds_to_bog(make_dds(b"DXT1", 512, 512, 10), make_paletted_bog(4, 4, 3)[:56])
    assert parse_header(new).type == 256


def test_format_change_sets_alpha_field():
    old = make_dxt_bog(fourcc=b"DXT1")
    assert dds_to_bog(make_dds(b"DXT5", 64, 64, 7), old[:56])[0x24:0x28] == (2).to_bytes(4, "little")
    old5 = make_dxt_bog(fourcc=b"DXT5", unknown_0x24=2)
    assert dds_to_bog(make_dds(b"DXT1", 64, 64, 7), old5[:56])[0x24:0x28] == bytes(4)


def test_dds_without_mip_count_is_one_level():
    dds = bytearray(make_dds(b"DXT1", 8, 8, 1))
    dds[28:32] = bytes(4)
    assert parse_header(dds_to_bog(bytes(dds), None)).mips == 1


def test_paletted_exports_32_bit_dds():
    dds = bog_to_dds(make_paletted_bog(4, 4, 3))
    assert dds[:4] == b"DDS " and read_bit_count(dds) == 32
    assert len(dds) == 128 + (16 + 4 + 1) * 4


def test_paletted_export_keeps_palette_byte_order():
    # Palette entries are stored B, G, R, A, which is also the DDS pixel order.
    bog = make_paletted_bog(1, 1, 1)
    bog = bog[:56 + 1024] + bytes([5])
    assert bog_to_dds(bog)[128:132] == bytes([5, 250, 7, 255])


def test_uncompressed_dds_refused_for_dxt():
    with pytest.raises(BogError, match="DXT1 or DXT5"):
        dds_to_bog(make_rgba_dds(4, 4), None)


def test_not_a_dds_refused():
    with pytest.raises(BogError):
        dds_to_bog(b"not a dds at all" + bytes(200), None)


def test_truncated_dds_refused():
    with pytest.raises(BogError, match="short"):
        dds_to_bog(make_dds(b"DXT1", 64, 64, 7)[:-1], None)


def test_bad_magic_refused():
    with pytest.raises(BogError):
        parse_header(b"XXX 9.99" + bytes(60))


def test_short_file_refused():
    with pytest.raises(BogError):
        parse_header(MAGIC)


def test_unedited_paletted_restores_exact_bytes():
    bog = make_paletted_bog(4, 4, 3)
    dds = bog_to_dds(bog)
    assert restore_bog(dds, sha256(dds).hexdigest(), bog) == bog


def test_edited_texture_is_converted_not_restored():
    bog = make_dxt_bog(fourcc=b"DXT1", unknown_0x28=1)
    edited = make_dds(b"DXT1", 128, 128, 8)
    out = restore_bog(edited, "different", bog)
    assert parse_header(out).width == 128 and out[0x28:0x2C] == bog[0x28:0x2C]


def test_all_stock_textures_round_trip(game_dir):
    archive = Archive(game_dir)
    paths = [p for p in archive.paths() if p.lower().endswith(".bog")]
    assert len(paths) == 3579
    for path in paths:
        bog = archive.read(path)
        dds = bog_to_dds(bog)
        assert restore_bog(dds, sha256(dds).hexdigest(), bog) == bog
        if parse_header(bog).type != 64:
            assert dds_to_bog(dds, bog[:56]) == bog, path
