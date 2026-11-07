"""Cells on shared sprite sheets: car icons, team logos and team names.

The game draws each from one sheet and finds a box by name. Stock art fills those sheets, so added
cells go on new rows under it. On a stock sheet, compressed blocks copy without decoding, so the
stock art keeps its exact pixels. Lower mip levels would need decoding, so a grown sheet has one
level. Its stock art then loses them too, but the game draws this art at about its full size.

Overhauls such as NitroXFueled replace sheets with bigger images in other formats, and keep a
header that no longer matches. Those sheets are decoded, grown, and written back as PNG.
"""
import io
import math
import re
import struct

from PIL import Image

from .bed import Box, read_bed, write_bed
from .bog import DDS_HEADER_SIZE, HEADER_SIZE, TYPE_DXT5, BogError, bog_to_dds, dds_to_bog, parse_header

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


def _is_block_sheet(bog, header):
    """A stock sheet: one DXT5 image that matches its header, so its blocks can be copied."""
    dds = bog[HEADER_SIZE:HEADER_SIZE + DDS_HEADER_SIZE]
    if header.type != TYPE_DXT5 or len(dds) < DDS_HEADER_SIZE or dds[:4] != b"DDS " or dds[84:88] != b"DXT5":
        return False
    height, width = struct.unpack_from("<II", dds, 12)
    return (width, height) == (header.width, header.height)


def _grow_bed(bed, width, height, names, cell):
    """Adds a box per name on new rows under a sheet of this size, and keeps stock boxes on their
    pixels. Returns the grown height and each new box's left and top."""
    cell_width, cell_height = cell
    columns = width // cell_width
    grown = _grown_height(height, math.ceil(len(names) / columns), cell_height)
    for box in bed.boxes:
        box.points = [(x, round(y * height / grown)) for x, y in box.points]
    places = {}
    for number, name in enumerate(names):
        places[name] = (number % columns * cell_width, height + number // columns * cell_height)
        bed.boxes.append(Box.rectangle(name, *places[name], cell_width, cell_height, width, grown))
    bed.height = grown
    return grown, places


def _add_blocks(sheet_bog, header, bed, icons, cell):
    height, places = _grow_bed(bed, header.width, header.height, list(icons), cell)
    stride = _stride(header.width)
    pixels = bytearray(_block_rows(height) * stride)
    pixels[:_block_rows(header.height) * stride] = _top_level(sheet_bog, header.width, header.height)
    cell_width, cell_height = cell
    row_bytes = _stride(cell_width)
    for name, icon in icons.items():
        left, top = places[name]
        art = _top_level(icon, cell_width, cell_height)
        for row in range(_block_rows(cell_height)):
            at = (_block_rows(top) + row) * stride + _stride(left)
            pixels[at:at + row_bytes] = art[row * row_bytes:(row + 1) * row_bytes]
    return dds_to_bog(dxt5_dds(header.width, height, bytes(pixels)), header.raw), write_bed(bed)


def bog_image(bog, what):
    """The picture inside a BOG, whatever its header says, as RGBA."""
    try:
        return Image.open(io.BytesIO(bog_to_dds(bog))).convert("RGBA")
    except (BogError, OSError, ValueError) as e:
        raise IconError(f"{what} is not an image the tool can read: {e}") from e


def _add_to_image(sheet_bog, header, bed, icons, cell):
    """Boxes stay in the .bed's own units, and the art is scaled to the image's size."""
    sheet = bog_image(sheet_bog, "The sheet")
    x_scale, y_scale = sheet.width / bed.width, sheet.height / bed.height
    height, places = _grow_bed(bed, bed.width, bed.height, list(icons), cell)
    grown = Image.new("RGBA", (sheet.width, round(height * y_scale)))
    grown.paste(sheet, (0, 0))
    size = (round(cell[0] * x_scale), round(cell[1] * y_scale))
    for name, icon in icons.items():
        left, top = places[name]
        art = bog_image(icon, f"The art for {name}").resize(size, Image.Resampling.LANCZOS)
        grown.paste(art, (round(left * x_scale), round(top * y_scale)))
    png = io.BytesIO()
    grown.save(png, format="PNG")
    # The game loads the image after the header whatever the header says, as overhauls rely on.
    return header.raw + png.getvalue(), write_bed(bed)


def add_icons(sheet_bog, sheet_bed, icons, cell=ICON_CELL):
    """The sheet and its boxes with `{box name: art}` added. Stock boxes stay on their pixels."""
    try:
        header = parse_header(sheet_bog)
    except BogError as e:
        raise IconError(f"The sheet is not a texture: {e}") from e
    bed = read_bed(sheet_bed)
    for name, icon in icons.items():
        check_icon(name, icon, cell)
        if bed.find(name) is not None:
            raise IconError(f"The sheet already has a box named {name}")
    if _is_block_sheet(sheet_bog, header):
        return _add_blocks(sheet_bog, header, bed, icons, cell)
    return _add_to_image(sheet_bog, header, bed, icons, cell)
