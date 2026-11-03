"""Cells on shared sprite sheets: car icons, team logos and team names.

The game draws each from one sheet and finds a box by name. Stock art fills those sheets, so added
cells go on new rows under it. Compressed blocks copy without decoding, which keeps the tool free
of an image library. Lower mip levels would need decoding, so a grown sheet has one level. Its
stock art then loses them too, but the game draws this art at about its full size.
"""
import math
import re
import struct

from .bed import Box, read_bed, write_bed
from .bog import DDS_HEADER_SIZE, HEADER_SIZE, TYPE_DXT5, BogError, dds_to_bog, parse_header

ICON_SHEET = "frontend/car_icons"
HIGHLIGHT_SHEET = "frontend/car_icons_highlights"
TEAM_LOGO_SHEET = "frontend/team_icons"
TEAM_NAME_SHEET = "hud/menus"
ICON_WIDTH = 96
ICON_HEIGHT = 48
ICON_CELL = (ICON_WIDTH, ICON_HEIGHT)
LOGO_CELL = (128, 96)
TEAM_NAME_CELL = (128, 32)
BLOCK_PIXELS = 4
BLOCK_BYTES = 16

# Box names differ between the sheets. On the name sheet, a stock team's box is its own id.
STOCK_LOGO_BOXES = {
    "dune_rats": "dune_ratz",
    "street_breed": "street_breed",
    "road_beasts": "RoadBeasts",
    "wave_rippers": "wave_rippers",
    "scorchers": "scorchers",
}

CELL_FILES = (
    (re.compile(r"frontend/.+_icon(_hlight)?\.bog"), ICON_CELL),
    (re.compile(r"frontend/.+_logo\.bog"), LOGO_CELL),
    (re.compile(r"frontend/.+_team_name\.bog"), TEAM_NAME_CELL),
)

DDS_FLAGS = 0x81007  # caps, height, width, pixel format, linear size
DDS_PF_FOURCC = 4
DDS_CAPS_TEXTURE = 0x1000


class IconError(Exception):
    pass


def icon_path(car):
    return f"frontend/{car}_icon.bog"


def highlight_path(car):
    return f"frontend/{car}_icon_hlight.bog"


def highlight_box(car):
    return f"{car}_hlight"


def logo_path(team):
    return f"frontend/{team}_logo.bog"


def team_name_path(team):
    return f"frontend/{team}_team_name.bog"


def cell_of(path):
    """The size a project's art file must be, or None if the file is not a sheet cell."""
    return next((cell for pattern, cell in CELL_FILES if pattern.fullmatch(path)), None)


def dxt5_dds(width, height, pixels):
    header = b"DDS " + struct.pack("<7I", 124, DDS_FLAGS, height, width, len(pixels), 0, 1) + bytes(44)
    header += struct.pack("<2I", 32, DDS_PF_FOURCC) + b"DXT5" + bytes(20)
    return header + struct.pack("<I", DDS_CAPS_TEXTURE) + bytes(16) + pixels


def _stride(width):
    return width // BLOCK_PIXELS * BLOCK_BYTES


def _block_rows(height):
    return height // BLOCK_PIXELS


def _top_level(bog, width, height):
    start = HEADER_SIZE + DDS_HEADER_SIZE
    return bog[start:start + _stride(width) * _block_rows(height)]


def _read_sheet(bog):
    try:
        header = parse_header(bog)
    except BogError as e:
        raise IconError(f"The sheet is not a texture: {e}") from e
    if header.type != TYPE_DXT5:
        raise IconError("The sheet must be DXT5")
    return header


def check_icon(name, bog, cell=ICON_CELL):
    try:
        header = parse_header(bog)
    except BogError as e:
        raise IconError(f"The art for {name} is not a texture: {e}") from e
    if header.type != TYPE_DXT5 or (header.width, header.height) != cell:
        raise IconError(f"The art for {name} must be DXT5 at {cell[0]}x{cell[1]}")


def _on_grid(value):
    return round(value / BLOCK_PIXELS) * BLOCK_PIXELS


def cut_icon(sheet_bog, sheet_bed, box_name, cell=ICON_CELL):
    """A box as a texture of its own, or None if the sheet has no such box.

    Stock boxes sit up to 2 pixels off the block grid. This is a picture to paint over, so the
    nearest whole cell of blocks is close enough.
    """
    header = _read_sheet(sheet_bog)
    box = read_bed(sheet_bed).find(box_name)
    if box is None:
        return None
    left, top = (_on_grid(value) for value in box.pixels(header.width, header.height)[:2])
    pixels = _top_level(sheet_bog, header.width, header.height)
    stride = _stride(header.width)
    start = _block_rows(top) * stride + _stride(left)
    width, height = cell
    rows = (pixels[start + row * stride:start + row * stride + _stride(width)] for row in range(_block_rows(height)))
    return dds_to_bog(dxt5_dds(width, height, b"".join(rows)), None)


def _grown_height(sheet_height, new_rows, cell_height):
    height = sheet_height
    while height < sheet_height + new_rows * cell_height:
        height *= 2
    return height


def add_icons(sheet_bog, sheet_bed, icons, cell=ICON_CELL):
    """The sheet and its boxes with `{box name: art}` added. Stock boxes stay on their pixels."""
    header = _read_sheet(sheet_bog)
    bed = read_bed(sheet_bed)
    cell_width, cell_height = cell
    columns = header.width // cell_width
    height = _grown_height(header.height, math.ceil(len(icons) / columns), cell_height)
    stride = _stride(header.width)
    pixels = bytearray(_block_rows(height) * stride)
    pixels[:_block_rows(header.height) * stride] = _top_level(sheet_bog, header.width, header.height)
    for box in bed.boxes:
        box.points = [(x, round(y * header.height / height)) for x, y in box.points]
    row_bytes = _stride(cell_width)
    for number, (name, icon) in enumerate(icons.items()):
        check_icon(name, icon, cell)
        if bed.find(name) is not None:
            raise IconError(f"The sheet already has a box named {name}")
        left, top = number % columns * cell_width, header.height + number // columns * cell_height
        art = _top_level(icon, cell_width, cell_height)
        for row in range(_block_rows(cell_height)):
            at = (_block_rows(top) + row) * stride + _stride(left)
            pixels[at:at + row_bytes] = art[row * row_bytes:(row + 1) * row_bytes]
        bed.boxes.append(Box.rectangle(name, left, top, cell_width, cell_height, header.width, height))
    bed.height = height
    return dds_to_bog(dxt5_dds(header.width, height, bytes(pixels)), header.raw), write_bed(bed)
