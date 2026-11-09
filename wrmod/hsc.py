"""The car hitbox file (.hsc): a convex hull and two lists of spheres, in the body model's space.

Layout (FUN_004558c0 reads it): "CSH\\0", a version, the count of plane groups, then each group as a
count and planes (nx, ny, nz, d) with n.p + d <= 0 inside. Then two lists, each a count and spheres
(x, y, z, radius). The first list sits in the upper body and the second covers the whole body. What
the game uses each part for is not decoded.

The Blender add-on shows a hitbox with `hull_mesh` and turns an edited hull back into planes with
`planes_from_faces`.
"""
import math
import struct
from dataclasses import dataclass, field

MAGIC = b"CSH\0"
_HEADER = struct.Struct("<4sII")
_COUNT = struct.Struct("<I")
_ENTRY = struct.Struct("<4f")
# Plane intersections closer than this are one hull corner.
SAME_POINT = 1e-4
# Faces this close in direction and distance are one side of the hull.
SAME_NORMAL = 0.9999
SAME_DISTANCE = 1e-4


def is_blank(plane):
    """Stock hitboxes pad their plane lists with all-zero planes, which bound nothing."""
    return not any(plane[:3])


class HscError(Exception):
    pass


@dataclass
class Hitbox:
    version: int = 1
    plane_groups: list = field(default_factory=list)
    upper_spheres: list = field(default_factory=list)
    body_spheres: list = field(default_factory=list)


def _read_list(data, offset):
    if offset + _COUNT.size > len(data):
        raise HscError("Hitbox file ends early")
    (count,) = _COUNT.unpack_from(data, offset)
    offset += _COUNT.size
    end = offset + count * _ENTRY.size
    if end > len(data):
        raise HscError("Hitbox file ends early")
    return [_ENTRY.unpack_from(data, offset + i * _ENTRY.size) for i in range(count)], end


def read_hsc(data):
    if len(data) < _HEADER.size or data[:4] != MAGIC:
        raise HscError("Not a hitbox file")
    _, version, groups = _HEADER.unpack_from(data)
    offset = _HEADER.size
    hitbox = Hitbox(version)
    for _ in range(groups):
        planes, offset = _read_list(data, offset)
        hitbox.plane_groups.append(planes)
    hitbox.upper_spheres, offset = _read_list(data, offset)
    hitbox.body_spheres, offset = _read_list(data, offset)
    if offset != len(data):
        raise HscError("Hitbox file has data past its last sphere")
    return hitbox


def write_hsc(hitbox):
    parts = [_HEADER.pack(MAGIC, hitbox.version, len(hitbox.plane_groups))]
    for entries in (*hitbox.plane_groups, hitbox.upper_spheres, hitbox.body_spheres):
        parts.append(_COUNT.pack(len(entries)))
        parts.extend(_ENTRY.pack(*entry) for entry in entries)
    return b"".join(parts)


def _det(rows):
    return (
        rows[0][0] * (rows[1][1] * rows[2][2] - rows[1][2] * rows[2][1])
        - rows[0][1] * (rows[1][0] * rows[2][2] - rows[1][2] * rows[2][0])
        + rows[0][2] * (rows[1][0] * rows[2][1] - rows[1][1] * rows[2][0])
    )


def _corner(a, b, c):
    """Where three planes meet, or None when two are parallel. Cramer's rule."""
    rows = [a[:3], b[:3], c[:3]]
    det = _det(rows)
    if abs(det) < 1e-9:
        return None
    values = [-a[3], -b[3], -c[3]]
    return tuple(
        _det([[values[row] if col == column else rows[row][col] for col in range(3)] for row in range(3)]) / det
        for column in range(3)
    )


def hull_mesh(planes):
    """(corners, faces) of the solid the planes enclose, for a picture of the hull.

    Each face lists its corners in turn, counter-clockwise seen from outside.
    """
    planes = [plane for plane in planes if not is_blank(plane)]
    corners = []
    for i in range(len(planes)):
        for j in range(i + 1, len(planes)):
            for k in range(j + 1, len(planes)):
                corner = _corner(planes[i], planes[j], planes[k])
                if corner is None:
                    continue
                inside = all(sum(p[axis] * corner[axis] for axis in range(3)) + p[3] <= SAME_POINT for p in planes)
                if inside and not any(math.dist(corner, seen) < SAME_POINT for seen in corners):
                    corners.append(corner)
    faces = []
    for p in planes:
        on = [n for n, corner in enumerate(corners) if abs(sum(p[axis] * corner[axis] for axis in range(3)) + p[3]) <= SAME_POINT]
        if len(on) < 3:
            continue
        centre = [sum(corners[n][axis] for n in on) / len(on) for axis in range(3)]
        # Two directions across the face, to sort its corners by angle around the centre.
        normal = p[:3]
        helper = (1.0, 0.0, 0.0) if abs(normal[0]) < 0.9 else (0.0, 1.0, 0.0)
        u = _cross(normal, helper)
        v = _cross(normal, u)

        def angle(n):
            offset = [corners[n][axis] - centre[axis] for axis in range(3)]
            return math.atan2(_dot(offset, v), _dot(offset, u))

        faces.append(sorted(on, key=angle))
    return corners, faces


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _newell_normal(points):
    """A polygon's normal that does not depend on which three corners are picked."""
    normal = [0.0, 0.0, 0.0]
    for (x1, y1, z1), (x2, y2, z2) in zip(points, points[1:] + points[:1]):
        normal[0] += (y1 - y2) * (z1 + z2)
        normal[1] += (z1 - z2) * (x1 + x2)
        normal[2] += (x1 - x2) * (y1 + y2)
    return normal


def planes_from_faces(faces):
    """The planes of a convex hull, from its faces as lists of corner points.

    Each plane faces away from the middle of the hull, whatever the face's winding. Faces in one
    plane, such as the two triangles of a square side, give one plane.
    """
    points = [point for face in faces for point in face]
    if not points:
        raise HscError("The hitbox hull has no faces")
    middle = [sum(point[axis] for point in points) / len(points) for axis in range(3)]
    planes = []
    for face in faces:
        normal = _newell_normal(list(face))
        length = math.sqrt(_dot(normal, normal))
        if length < 1e-9:
            continue
        normal = [value / length for value in normal]
        offset = -sum(_dot(normal, point) for point in face) / len(face)
        if _dot(normal, middle) + offset > 0:
            normal, offset = [-value for value in normal], -offset
        plane = (*normal, offset)
        if not any(_dot(plane[:3], seen[:3]) > SAME_NORMAL and abs(plane[3] - seen[3]) < SAME_DISTANCE for seen in planes):
            planes.append(plane)
    if len(planes) < 4:
        raise HscError("The hitbox hull is flat, so it encloses nothing")
    return planes

