import struct
from pathlib import Path

import pytest

from wrmod.bark import Archive
from wrmod.rom import MATERIAL_SIZE, MAGIC, TAG_SIZE, Material, Mesh, Rom, RomError, Tag, Vertex, centre_of_mass, read_rom, write_points, write_rom


def vertex(x=1.0, u=0.25):
    return Vertex(position=(x, 2.0, 3.0), normal=(0.0, 1.0, 0.0), uv=(u, 0.75), colour=0x84646464)


def material_record(name=b"skin"):
    return name + b"\0" * (20 - len(name)) + b"\xAB" * (MATERIAL_SIZE - 20)


def tag_record(name=b"com", position=(1.0, 2.0, 3.0)):
    head = name + b"\0" * (TAG_SIZE - 12 - len(name))
    return head + struct.pack("<3f", *position)


def sample():
    mesh = Mesh(flags=0x40, material=0, triangles=[(0, 1, 2)], vertices=[vertex(0.0), vertex(1.0), vertex(2.0)])
    return Rom(materials=[Material(material_record())], tags=[Tag(tag_record())], meshes=[mesh])


def test_new_rom_starts_with_the_magic():
    assert write_rom(sample())[:9] == MAGIC


def test_counts_are_in_the_header():
    data = write_rom(sample())
    assert struct.unpack_from("<6I", data, 0xC) == (1, 0, 1, 0, 0, 1)


def test_bounds_follow_the_vertices():
    data = write_rom(sample())
    assert struct.unpack_from("<6f", data, 0x30) == (0.0, 2.0, 3.0, 2.0, 2.0, 3.0)


def test_round_trip_keeps_mesh_data():
    mesh = read_rom(write_rom(sample())).meshes[0]
    assert mesh.triangles == [(0, 1, 2)]
    assert mesh.vertices[1].position == (1.0, 2.0, 3.0)
    assert mesh.vertices[1].uv == (0.25, 0.75)
    assert mesh.vertices[1].colour == 0x84646464
    assert (mesh.flags, mesh.material) == (0x40, 0)


def test_material_name_reads_to_the_first_null():
    assert read_rom(write_rom(sample())).materials[0].name == "skin"


def test_material_rename_keeps_the_rest_of_the_record():
    material = Material(material_record(b"a_longer_old_name"))
    material.name = "new"
    assert material.name == "new"
    assert material.record[20:] == b"\xAB" * (MATERIAL_SIZE - 20)


def test_material_name_must_fit():
    with pytest.raises(RomError):
        Material(material_record()).name = "x" * 20


def test_tag_reads_name_and_position():
    tag = read_rom(write_rom(sample())).tags[0]
    assert tag.name == "com" and tag.position == (1.0, 2.0, 3.0)


def test_tag_position_can_change():
    tag = Tag(tag_record())
    tag.position = (4.0, 5.0, 6.0)
    assert tag.position == (4.0, 5.0, 6.0) and tag.name == "com"


def test_triangle_past_the_vertices_refused():
    rom = sample()
    rom.meshes[0].triangles = [(0, 1, 3)]
    with pytest.raises(RomError, match="triangle"):
        write_rom(rom)


def test_material_past_the_table_refused():
    rom = sample()
    rom.meshes[0].material = 1
    with pytest.raises(RomError, match="material"):
        write_rom(rom)


def test_wrong_magic_refused():
    with pytest.raises(RomError, match="ROM 1.27"):
        read_rom(b"NOT A ROM" + bytes(100))


def test_truncated_file_refused():
    with pytest.raises(RomError):
        read_rom(write_rom(sample())[:-1])


def test_extra_bytes_at_the_end_refused():
    with pytest.raises(RomError):
        read_rom(write_rom(sample()) + b"\0")


def test_short_file_refused():
    with pytest.raises(RomError):
        read_rom(MAGIC)


def test_every_stock_model_round_trips(game_dir):
    archive = Archive(game_dir)
    paths = [p for p in archive.paths() if p.lower().endswith((".rom", ".shm"))]
    assert len(paths) > 1000
    for path in paths:
        data = archive.read(path)
        assert write_rom(read_rom(data)) == data, path


def test_stock_body_reads_as_a_car(game_dir):
    rom = read_rom(Archive(game_dir).read("cars/ballistic/cache/ballistic_med.rom"))
    assert [m.name for m in rom.materials] == ["ballistic", "generic_headlight"]
    assert [t.name for t in rom.tags][:3] == ["com", "lefttaillight", "righttaillight"]
    assert sum(len(m.triangles) for m in rom.meshes) == 2939


def test_points_are_stored_from_the_centre_of_mass():
    tags = [Tag(tag_record(b"com", (0.5, 1.0, 2.0))), Tag(tag_record(b"headlight 0.3 1.0", (1.5, 3.0, 5.0)))]
    data = write_points(tags)
    assert data[:10] == b"POINT 1.00"
    assert struct.unpack_from("<I", data, 16)[0] == 2
    assert len(data) == 20 + 2 * 80
    record = data[100:180]
    assert record.startswith(b"headlight 0.3 1.0\0")
    assert struct.unpack_from("<3f", record, 32) == (1.0, 2.0, 3.0)


def test_centre_of_mass_comes_from_the_com_tag():
    tags = [Tag(tag_record(b"a", (9.0, 9.0, 9.0))), Tag(tag_record(b"com", (0.5, 1.0, 2.0)))]
    assert centre_of_mass(tags) == (0.5, 1.0, 2.0)


def test_a_model_with_no_com_is_centred_on_zero():
    assert centre_of_mass([Tag(tag_record(b"a", (9.0, 9.0, 9.0)))]) == (0.0, 0.0, 0.0)


def test_points_with_no_com_stay_where_they_are():
    data = write_points([Tag(tag_record(b"a", (1.0, 2.0, 3.0)))])
    assert struct.unpack_from("<3f", data, 20 + 32) == (1.0, 2.0, 3.0)


def test_stock_points_are_rebuilt_from_the_model(game_dir):
    archive = Archive(game_dir)
    rom = read_rom(archive.read("cars/ballistic/cache/ballistic_med.rom"))
    stock = archive.read("cars/ballistic/cache/ballistic.pts")
    rebuilt = write_points(rom.tags)
    assert len(rebuilt) == len(stock)
    for i in range(len(rom.tags)):
        at = 20 + i * 80
        assert rebuilt[at:at + 32].split(b"\0")[0] == stock[at:at + 32].split(b"\0")[0]
        assert struct.unpack_from("<3f", rebuilt, at + 32) == pytest.approx(struct.unpack_from("<3f", stock, at + 32), abs=1e-4)


def test_tag_name_can_change():
    tag = Tag(tag_record(b"backlight 0.4 1.0 0.2 0.0", (1.0, 2.0, 3.0)))
    tag.name = "backlight 0.4 1.00 0.00 1.00"
    assert tag.name == "backlight 0.4 1.00 0.00 1.00"
    assert tag.position == (1.0, 2.0, 3.0)


def test_a_shorter_tag_name_leaves_nothing_of_the_old_one():
    tag = Tag(tag_record(b"backlight 0.4 1.0 0.2 0.0"))
    tag.name = "com"
    assert tag.name == "com"


def test_a_tag_name_too_long_for_the_record_is_refused():
    tag = Tag(tag_record())
    with pytest.raises(RomError):
        tag.name = "a" * 32
