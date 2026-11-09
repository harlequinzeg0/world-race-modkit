import itertools
import math
import struct

import pytest

from wrmod.bark import Archive
from wrmod.hsc import HscError, Hitbox, hull_mesh, planes_from_faces, read_hsc, write_hsc

BOX = (-1.0, -0.5, -2.0, 1.0, 1.0, 2.0)


def box_planes(bounds):
    low, high = bounds[:3], bounds[3:]
    planes = []
    for axis in range(3):
        normal = [0.0, 0.0, 0.0]
        normal[axis] = 1.0
        planes.append((*normal, -high[axis]))
        normal[axis] = -1.0
        planes.append((*normal, low[axis]))
    return planes


def sample(bounds=BOX):
    return Hitbox(1, [box_planes(bounds)], [(0.0, 0.8, 0.5, 0.3)], [(0.5, 0.0, -1.0, 0.6), (-0.5, 0.0, 1.0, 0.6)])


def flat(entries):
    return [value for entry in entries for value in entry]


def inside(planes, point):
    return all(sum(p[i] * point[i] for i in range(3)) + p[3] <= 1e-6 for p in planes)


def test_round_trip_keeps_every_byte():
    data = write_hsc(sample())
    assert data[:4] == b"CSH\0"
    assert write_hsc(read_hsc(data)) == data


def test_round_trip_of_every_stock_hitbox(game_dir):
    archive = Archive(game_dir)
    paths = [p for p in archive.paths() if p.lower().endswith(".hsc")]
    assert paths
    for path in paths:
        assert write_hsc(read_hsc(archive.read(path))) == archive.read(path), path


@pytest.mark.parametrize("data", [b"", b"XYZ\0" + bytes(8), write_hsc(sample())[:-4], write_hsc(sample()) + b"\0"])
def test_a_broken_file_is_refused(data):
    with pytest.raises(HscError):
        read_hsc(data)


def test_blank_planes_add_no_face():
    assert len(hull_mesh([*box_planes(BOX), (0.0, 0.0, 0.0, 0.0)])[1]) == 6


def same_planes(found, expected):
    return len(found) == len(expected) and all(
        any(all(abs(a - b) < 1e-6 for a, b in zip(plane, other)) for other in found) for plane in expected
    )


def box_faces(bounds=BOX, flip=False):
    corners, faces = hull_mesh(box_planes(bounds))
    return [[corners[i] for i in (reversed(face) if flip else face)] for face in faces]


@pytest.mark.parametrize("flip", [False, True])
def test_planes_from_faces_face_outward_whatever_the_winding(flip):
    assert same_planes(planes_from_faces(box_faces(flip=flip)), box_planes(BOX))


def test_triangles_in_one_side_give_one_plane():
    triangles = [tri for face in box_faces() for tri in ([face[0], face[1], face[2]], [face[0], face[2], face[3]])]
    assert same_planes(planes_from_faces(triangles), box_planes(BOX))


def test_planes_round_trip_through_a_stock_hull(game_dir):
    planes = [p for p in read_hsc(Archive(game_dir).read("cars/deora2/cache/deora2.hsc")).plane_groups[0] if any(p[:3])]
    corners, faces = hull_mesh(planes)
    found = planes_from_faces([[corners[i] for i in face] for face in faces])
    assert all(any(all(abs(a - b) < 1e-4 for a, b in zip(plane, other)) for other in planes) for plane in found)
    assert len(found) == len(faces)


@pytest.mark.parametrize("faces", [[], [[(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0, 0), (0, 1, 0), (1, 0, 0)]]])
def test_a_hull_with_no_volume_is_refused(faces):
    with pytest.raises(HscError):
        planes_from_faces(faces)


def test_hull_mesh_of_a_box():
    corners, faces = hull_mesh(box_planes(BOX))
    assert sorted(corners) == sorted(itertools.product(*zip(BOX[:3], BOX[3:])))
    assert len(faces) == 6 and all(len(face) == 4 for face in faces)


def test_hull_faces_turn_counter_clockwise_seen_from_outside():
    planes = box_planes(BOX)
    corners, faces = hull_mesh(planes)
    for plane, face in zip(planes, faces):
        a, b, c = (corners[i] for i in face[:3])
        edge1 = [b[i] - a[i] for i in range(3)]
        edge2 = [c[i] - a[i] for i in range(3)]
        normal = (edge1[1] * edge2[2] - edge1[2] * edge2[1], edge1[2] * edge2[0] - edge1[0] * edge2[2], edge1[0] * edge2[1] - edge1[1] * edge2[0])
        assert sum(normal[i] * plane[i] for i in range(3)) > 0


def test_every_hull_corner_is_inside_every_plane():
    planes = [(0.6, 0.8, 0.0, -1.0), *box_planes(BOX)]
    corners, _ = hull_mesh(planes)
    assert all(inside(planes, corner) for corner in corners)


def test_stock_planes_point_outward(game_dir):
    """Inside means n.p + d <= 0, so a stock body's centre must be inside its hull."""
    archive = Archive(game_dir)
    hitbox = read_hsc(archive.read("cars/deora2/cache/deora2.hsc"))
    assert inside(hitbox.plane_groups[0], (0.0, 0.2, 0.0))
    assert struct.unpack_from("<I", archive.read("cars/deora2/cache/deora2.hsc"), 8)[0] == len(hitbox.plane_groups)
