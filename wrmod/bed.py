"""Read and write .bed sprite sheets: the named boxes on a texture.

Layout is in docs/FINDINGS.md. Corners are stored as a share of the sheet, scaled by SCALE.
"""
import struct
from dataclasses import dataclass, field

MAGIC = b"\x01\x01"
NO_LINK = -1
SCALE = 100000
ENCODING = "latin-1"


class BedError(Exception):
    pass


@dataclass
class Box:
    name: str
    points: list
    # Fonts and particles pair a box with a second one. Icons and logos have no link.
    link: int = NO_LINK

    def pixels(self, width, height):
        """Left, top, width and height on a sheet of this size."""
        xs = [x * width / SCALE for x, _ in self.points]
        ys = [y * height / SCALE for _, y in self.points]
        left, top = round(min(xs)), round(min(ys))
        return left, top, round(max(xs)) - left, round(max(ys)) - top

    @classmethod
    def rectangle(cls, name, left, top, width, height, sheet_width, sheet_height):
        x0, x1 = (round(x * SCALE / sheet_width) for x in (left, left + width))
        y0, y1 = (round(y * SCALE / sheet_height) for y in (top, top + height))
        return cls(name, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


@dataclass
class Bed:
    source: str
    width: int
    height: int
    boxes: list = field(default_factory=list)

    def find(self, name):
        """The game ignores case here, and stock files rely on it: RoadBeasts finds Roadbeasts."""
        return next((box for box in self.boxes if box.name.lower() == name.lower()), None)


def _text_end(data, start):
    end = data.find(b"\0", start)
    if end < 0:
        raise BedError("a name has no end")
    return end


def read_bed(data):
    if data[:len(MAGIC)] != MAGIC:
        raise BedError("not a sprite sheet")
    try:
        end = _text_end(data, len(MAGIC))
        source = data[len(MAGIC):end].decode(ENCODING)
        width, height, count = struct.unpack_from("<3H", data, end + 1)
        at = end + 7
        boxes = []
        for _ in range(count):
            points = struct.unpack_from("<H", data, at)[0]
            values = struct.unpack_from(f"<{points * 2}I", data, at + 2)
            at += 2 + points * 8
            end = _text_end(data, at)
            name = data[at:end].decode(ENCODING)
            link = struct.unpack_from("<h", data, end + 1)[0]
            at = end + 3
            boxes.append(Box(name, list(zip(values[::2], values[1::2])), link))
    except struct.error as e:
        raise BedError("sprite sheet is cut short") from e
    if at != len(data):
        raise BedError("sprite sheet has extra data")
    return Bed(source, width, height, boxes)


def write_bed(bed):
    out = bytearray(MAGIC + bed.source.encode(ENCODING) + b"\0")
    out += struct.pack("<3H", bed.width, bed.height, len(bed.boxes))
    for box in bed.boxes:
        out += struct.pack("<H", len(box.points))
        out += struct.pack(f"<{len(box.points) * 2}I", *(value for point in box.points for value in point))
        out += box.name.encode(ENCODING) + b"\0" + struct.pack("<h", box.link)
    return bytes(out)
