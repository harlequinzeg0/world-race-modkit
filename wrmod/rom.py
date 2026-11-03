"""Read and write the game's ROM 1.27 models (.rom and .shm).

This file has no dependencies, so the Blender add-on can use it as it is.

Layout, from FUN_0051d2c0 and FUN_0051d4c0:
  0x00  magic, 12 bytes
  0x0C  six counts: materials, table B, tags, table D, table E, meshes
  0x24  12 bytes, the same in every stock file
  0x30  bounds, 3 floats min and 3 floats max
  0x48  the tables, one after the other, then the meshes

A mesh is a 0x34 byte head, triangles, bone data, extra data, then vertices.
Fields with no known meaning are kept as bytes, so a stock file writes back unchanged.
"""
import struct
from dataclasses import dataclass, field

MAGIC = b"ROM 1.27\0"
MAGIC_SIZE = 12
HEADER_SIZE = 0x48
MATERIAL_SIZE = 0x8C
TABLE_B_SIZE = 0x7C
TAG_SIZE = 0x2C
TABLE_D_SIZE = 0x68
TABLE_E_SIZE = 0x20
MESH_HEAD_SIZE = 0x34
BONE_SIZE = 0x2A0
VERTEX_SIZE = 0x38

MATERIAL_NAME_SIZE = 20
TAG_NAME_SIZE = 0x20
HEADER_FILLER = bytes.fromhex("ffffffffffffffff000080bf")
BOUNDS_AT = 0x30
UNSET = 0xFFFFFFFF
UNSET_FIELDS = (UNSET,) * 7

_COUNTS = struct.Struct("<6I")
_BOUNDS = struct.Struct("<6f")
_HEAD = struct.Struct("<13I")
_TRIANGLE = struct.Struct("<3I")
_VERTEX = struct.Struct("<8f16sI4s")


class RomError(Exception):
    pass


@dataclass
class Vertex:
    position: tuple
    normal: tuple
    uv: tuple
    colour: int = 0xFFFFFFFF
    extra: bytes = bytes(16)
    tail: bytes = bytes(4)


def _text(data):
    return data.split(b"\0")[0].decode("ascii", "replace")


def _named(name, size):
    data = name.encode("ascii")
    if len(data) >= size:
        raise RomError(f"Name is too long, the limit is {size - 1}: {name}")
    return data + bytes(size - len(data))


POINT_MAGIC = b"POINT 1.00"
POINT_HEADER_SIZE = 20
POINT_NAME_SIZE = 32
COM_TAG = "com"
# Every stock point has this orientation, as three row vectors after the position.
POINT_AXES = (0.0, 0.0, 1.0, -0.0, 1.0, 0.0, -1.0, 0.0, 0.0)
_POINT = struct.Struct("<32s12f")


class Material:
    """The name is a texture name. What the rest of the record means is not known."""

    def __init__(self, record):
        self.record = bytes(record)

    @property
    def name(self):
        return _text(self.record[:MATERIAL_NAME_SIZE])

    @name.setter
    def name(self, value):
        self.record = _named(value, MATERIAL_NAME_SIZE) + self.record[MATERIAL_NAME_SIZE:]


class Tag:
    """A named point, such as the centre of mass or a headlight."""

    def __init__(self, record):
        self.record = bytes(record)

    @property
    def name(self):
        return _text(self.record[:TAG_NAME_SIZE])

    @name.setter
    def name(self, value):
        data = value.encode("ascii")
        if len(data) >= TAG_NAME_SIZE:
            raise RomError(f"Point name {value} is too long")
        self.record = data.ljust(TAG_NAME_SIZE, b"\0") + self.record[TAG_NAME_SIZE:]

    @property
    def position(self):
        return struct.unpack_from("<3f", self.record, TAG_NAME_SIZE)

    @position.setter
    def position(self, value):
        self.record = self.record[:TAG_NAME_SIZE] + struct.pack("<3f", *value)


@dataclass
class Mesh:
    flags: int
    material: int
    triangles: list
    vertices: list
    fields: tuple = UNSET_FIELDS
    bones: bytes = b""
    extra: bytes = b""


@dataclass
class Rom:
    materials: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    meshes: list = field(default_factory=list)
    table_b: bytes = b""
    table_d: bytes = b""
    table_e: bytes = b""
    filler: bytes = HEADER_FILLER
    # None means write_rom works them out. Set this to None after moving any vertex.
    bounds: tuple = None


def _records(data, offset, count, size):
    return [data[offset + i * size:offset + (i + 1) * size] for i in range(count)]


def _read_mesh(data, offset):
    if offset + MESH_HEAD_SIZE > len(data):
        raise RomError("Model file ends inside a mesh")
    head = _HEAD.unpack_from(data, offset)
    flags, material, f2, f3, f4, triangles, bones, extra, vertices, f9, f10, f11, f12 = head
    triangles_at = offset + MESH_HEAD_SIZE
    bones_at = triangles_at + triangles * _TRIANGLE.size
    extra_at = bones_at + bones * BONE_SIZE
    vertices_at = extra_at + extra * 4
    end = vertices_at + vertices * VERTEX_SIZE
    if end > len(data):
        raise RomError("Model file ends inside a mesh")
    mesh = Mesh(
        flags=flags,
        material=material,
        triangles=list(_TRIANGLE.iter_unpack(data[triangles_at:bones_at])),
        vertices=[
            Vertex(v[:3], v[3:6], v[6:8], v[9], v[8], v[10])
            for v in _VERTEX.iter_unpack(data[vertices_at:end])
        ],
        fields=(f2, f3, f4, f9, f10, f11, f12),
        bones=data[bones_at:extra_at],
        extra=data[extra_at:vertices_at],
    )
    return mesh, end


def read_rom(data):
    if len(data) < HEADER_SIZE or data[:len(MAGIC)] != MAGIC:
        raise RomError("Not a ROM 1.27 model file")
    materials, table_b, tags, table_d, table_e, meshes = _COUNTS.unpack_from(data, MAGIC_SIZE)
    offset = HEADER_SIZE
    sections = []
    for count, size in (
        (materials, MATERIAL_SIZE),
        (table_b, TABLE_B_SIZE),
        (tags, TAG_SIZE),
        (table_d, TABLE_D_SIZE),
        (table_e, TABLE_E_SIZE),
    ):
        sections.append((offset, count, size))
        offset += count * size
    if offset > len(data):
        raise RomError("Model file ends inside a table")
    rom = Rom(
        materials=[Material(r) for r in _records(data, *sections[0])],
        tags=[Tag(r) for r in _records(data, *sections[2])],
        table_b=data[sections[1][0]:sections[2][0]],
        table_d=data[sections[3][0]:sections[4][0]],
        table_e=data[sections[4][0]:sections[4][0] + table_e * TABLE_E_SIZE],
        filler=data[0x24:BOUNDS_AT],
        bounds=_BOUNDS.unpack_from(data, BOUNDS_AT),
    )
    for _ in range(meshes):
        mesh, offset = _read_mesh(data, offset)
        rom.meshes.append(mesh)
    if offset != len(data):
        raise RomError("Model file has data past its last mesh")
    return rom


def work_out_bounds(meshes):
    points = [vertex.position for mesh in meshes for vertex in mesh.vertices]
    if not points:
        return (0.0,) * 6
    axes = list(zip(*points))
    return (*(min(axis) for axis in axes), *(max(axis) for axis in axes))


def _check_mesh(mesh, material_count):
    last = len(mesh.vertices)
    if any(index >= last for triangle in mesh.triangles for index in triangle):
        raise RomError(f"A triangle uses a vertex past the end of its {last} vertices")
    if mesh.material != UNSET and material_count and mesh.material >= material_count:
        raise RomError(f"A mesh uses material {mesh.material}, but there are only {material_count}")


def _write_mesh(mesh):
    f2, f3, f4, f9, f10, f11, f12 = mesh.fields
    parts = [_HEAD.pack(
        mesh.flags, mesh.material, f2, f3, f4, len(mesh.triangles), len(mesh.bones) // BONE_SIZE,
        len(mesh.extra) // 4, len(mesh.vertices), f9, f10, f11, f12,
    )]
    parts.extend(_TRIANGLE.pack(*triangle) for triangle in mesh.triangles)
    parts.append(mesh.bones)
    parts.append(mesh.extra)
    parts.extend(
        _VERTEX.pack(*v.position, *v.normal, *v.uv, v.extra, v.colour, v.tail)
        for v in mesh.vertices
    )
    return b"".join(parts)


def write_rom(rom):
    for mesh in rom.meshes:
        _check_mesh(mesh, len(rom.materials))
    bounds = work_out_bounds(rom.meshes) if rom.bounds is None else rom.bounds
    parts = [
        MAGIC + bytes(MAGIC_SIZE - len(MAGIC)),
        _COUNTS.pack(
            len(rom.materials), len(rom.table_b) // TABLE_B_SIZE, len(rom.tags),
            len(rom.table_d) // TABLE_D_SIZE, len(rom.table_e) // TABLE_E_SIZE, len(rom.meshes),
        ),
        rom.filler,
        _BOUNDS.pack(*bounds),
    ]
    parts.extend(material.record for material in rom.materials)
    parts.append(rom.table_b)
    parts.extend(tag.record for tag in rom.tags)
    parts.append(rom.table_d)
    parts.append(rom.table_e)
    parts.extend(_write_mesh(mesh) for mesh in rom.meshes)
    return b"".join(parts)


def centre_of_mass(tags):
    return next((tag.position for tag in tags if tag.name == COM_TAG), (0.0, 0.0, 0.0))


def write_points(tags):
    """A .pts file holds the same named points as the model, measured from the centre of mass."""
    origin = centre_of_mass(tags)
    records = []
    for tag in tags:
        offset = (tag.position[i] - origin[i] for i in range(3))
        records.append(_POINT.pack(tag.record[:POINT_NAME_SIZE], *offset, *POINT_AXES))
    head = POINT_MAGIC + bytes(POINT_HEADER_SIZE - len(POINT_MAGIC) - 4) + struct.pack("<I", len(tags))
    return head + b"".join(records)
