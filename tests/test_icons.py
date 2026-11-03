import os
import struct
from pathlib import Path

import pytest

from wrmod.bark import Archive
from wrmod.bed import Bed, Box, read_bed, write_bed
from wrmod.bog import HEADER_SIZE, dds_to_bog, parse_header
from wrmod.icons import (
    HIGHLIGHT_SHEET,
    ICON_HEIGHT,
    ICON_SHEET,
    ICON_WIDTH,
    LOGO_CELL,
    STOCK_LOGO_BOXES,
    TEAM_LOGO_SHEET,
    TEAM_NAME_CELL,
    TEAM_NAME_SHEET,
    IconError,
    add_icons,
    cell_of,
    check_icon,
    cut_icon,
    dxt5_dds,
)

BLOCK = 16
DDS_HEAD = 128


def sheet(height=512):
    """Each block holds its own row and column, so a moved block shows up."""
    pixels = bytearray()
    for row in range(height // 4):
        for column in range(128):
            pixels += struct.pack("<HH", row, column) + bytes(BLOCK - 4)
    return dds_to_bog(dxt5_dds(512, height, bytes(pixels)), None)


def bed():
    return write_bed(Bed("s.tga", 512, 512, [Box.rectangle("one", 0, 0, 96, 48, 512, 512), Box.rectangle("two", 96, 48, 96, 48, 512, 512)]))


def icon(fill=0xAB):
    return dds_to_bog(dxt5_dds(ICON_WIDTH, ICON_HEIGHT, bytes([fill]) * (24 * 12 * BLOCK)), None)


def pixels_of(bog):
    return bog[HEADER_SIZE + DDS_HEAD:]


def block(bog, row, column):
    start = (row * 128 + column) * BLOCK
    return pixels_of(bog)[start:start + BLOCK]


def test_cut_icon_takes_its_cell():
    cut = cut_icon(sheet(), bed(), "two")
    header = parse_header(cut)
    assert (header.width, header.height, header.mips) == (ICON_WIDTH, ICON_HEIGHT, 1)
    assert pixels_of(cut)[:4] == struct.pack("<HH", 12, 24)
    assert len(pixels_of(cut)) == 24 * 12 * BLOCK


def test_cut_icon_of_a_missing_box_is_nothing():
    assert cut_icon(sheet(), bed(), "three") is None


def test_cut_icon_snaps_a_box_to_the_nearest_blocks():
    odd = write_bed(Bed("s.tga", 512, 512, [Box.rectangle("one", 95, 47, 97, 49, 512, 512)]))
    assert pixels_of(cut_icon(sheet(), odd, "one"))[:4] == struct.pack("<HH", 12, 24)


def test_add_icons_doubles_the_sheet_and_keeps_stock_pixels():
    bog, _ = add_icons(sheet(), bed(), {"neon": icon()})
    header = parse_header(bog)
    assert (header.width, header.height, header.mips) == (512, 1024, 1)
    assert pixels_of(bog)[:128 * 128 * BLOCK] == pixels_of(sheet())[:128 * 128 * BLOCK]


def test_add_icons_places_each_icon_on_the_new_rows():
    bog, new_bed = add_icons(sheet(), bed(), {"a": icon(1), "b": icon(2)})
    boxes = read_bed(new_bed)
    assert boxes.find("a").pixels(512, 1024) == (0, 512, 96, 48)
    assert boxes.find("b").pixels(512, 1024) == (96, 512, 96, 48)
    assert block(bog, 128, 0)[0] == 1
    assert block(bog, 128, 24)[0] == 2
    assert block(bog, 139, 23)[0] == 1


def test_add_icons_keeps_stock_boxes_on_their_pixels():
    _, new_bed = add_icons(sheet(), bed(), {"a": icon()})
    assert read_bed(new_bed).find("two").pixels(512, 1024) == (96, 48, 96, 48)
    assert read_bed(new_bed).height == 1024


def test_add_icons_wraps_to_a_new_row():
    _, new_bed = add_icons(sheet(), bed(), {f"c{i}": icon() for i in range(6)})
    assert read_bed(new_bed).find("c5").pixels(512, 1024) == (0, 560, 96, 48)


def test_add_icons_grows_again_when_the_new_rows_are_full():
    bog, new_bed = add_icons(sheet(), bed(), {f"c{i}": icon() for i in range(51)})
    assert parse_header(bog).height == 2048
    assert read_bed(new_bed).find("c50").pixels(512, 2048) == (0, 992, 96, 48)
    assert read_bed(new_bed).find("two").pixels(512, 2048) == (96, 48, 96, 48)


def test_check_icon_refuses_the_wrong_size():
    wrong = dds_to_bog(dxt5_dds(64, 32, bytes(16 * 8 * BLOCK)), None)
    with pytest.raises(IconError, match="96"):
        check_icon("neon", wrong)


def test_check_icon_refuses_dxt1():
    head = bytearray(dxt5_dds(ICON_WIDTH, ICON_HEIGHT, b""))
    head[84:88] = b"DXT1"
    wrong = dds_to_bog(bytes(head) + bytes(24 * 12 * 8), None)
    with pytest.raises(IconError, match="DXT5"):
        check_icon("neon", wrong)


def test_a_sheet_that_is_not_dxt5_is_refused():
    head = bytearray(dxt5_dds(512, 512, b""))
    head[84:88] = b"DXT1"
    wrong = dds_to_bog(bytes(head) + bytes(128 * 128 * 8), None)
    with pytest.raises(IconError, match="DXT5"):
        add_icons(wrong, bed(), {"a": icon()})


def test_a_new_name_already_on_the_sheet_is_refused():
    with pytest.raises(IconError, match="two"):
        add_icons(sheet(), bed(), {"two": icon()})


@pytest.mark.skipif("WRMOD_GAME" not in os.environ, reason="needs the game")
def test_every_stock_car_has_an_icon_that_cuts_and_goes_back():
    archive = Archive(Path(os.environ["WRMOD_GAME"]))
    sheet_bog = archive.read(f"{ICON_SHEET}.bog")
    sheet_bed = archive.read(f"{ICON_SHEET}.bed")
    cars = [b.name for b in read_bed(sheet_bed).boxes[:15] if not b.name.endswith("_text")]
    assert len(cars) == 15
    for car in cars:
        cut = cut_icon(sheet_bog, sheet_bed, car)
        check_icon(car, cut)
        check_icon(car, cut_icon(archive.read(f"{HIGHLIGHT_SHEET}.bog"), archive.read(f"{HIGHLIGHT_SHEET}.bed"), f"{car}_hlight"))
    bog, new_bed = add_icons(sheet_bog, sheet_bed, {"neon": cut})
    assert cut_icon(bog, new_bed, "neon")[HEADER_SIZE:] == cut[HEADER_SIZE:]
    assert cut_icon(bog, new_bed, cars[3])[HEADER_SIZE:] == cut_icon(sheet_bog, sheet_bed, cars[3])[HEADER_SIZE:]


def logo(fill=0xAB):
    return dds_to_bog(dxt5_dds(128, 96, bytes([fill]) * (32 * 24 * BLOCK)), None)


def wide_bed():
    return write_bed(Bed("s.tga", 512, 256, [Box.rectangle("one", 0, 0, 128, 96, 512, 256)]))


def test_logos_use_their_own_cell_size():
    bog, new_bed = add_icons(sheet(256), wide_bed(), {"neon": logo()}, LOGO_CELL)
    assert parse_header(bog).height == 512
    assert read_bed(new_bed).find("neon").pixels(512, 512) == (0, 256, 128, 96)
    assert read_bed(new_bed).find("one").pixels(512, 512) == (0, 0, 128, 96)


def test_a_cell_wraps_at_its_own_width():
    _, new_bed = add_icons(sheet(256), wide_bed(), {f"t{i}": logo() for i in range(5)}, LOGO_CELL)
    assert read_bed(new_bed).find("t4").pixels(512, 512) == (0, 352, 128, 96)


def test_cut_icon_takes_a_cell_of_any_size():
    cut = cut_icon(sheet(256), wide_bed(), "one", LOGO_CELL)
    header = parse_header(cut)
    assert (header.width, header.height) == LOGO_CELL


def test_check_icon_uses_the_cell_it_is_given():
    check_icon("neon", logo(), LOGO_CELL)
    with pytest.raises(IconError, match="128x96"):
        check_icon("neon", icon(), LOGO_CELL)


@pytest.mark.parametrize("path, cell", [
    ("frontend/a_icon.bog", (96, 48)),
    ("frontend/a_icon_hlight.bog", (96, 48)),
    ("frontend/a_logo.bog", LOGO_CELL),
    ("frontend/a_team_name.bog", TEAM_NAME_CELL),
    ("frontend/a_movie.bog", None),
    ("cars/a/a_logo.bog", None),
])
def test_cell_of_a_project_file(path, cell):
    assert cell_of(path) == cell


@pytest.mark.skipif("WRMOD_GAME" not in os.environ, reason="needs the game")
@pytest.mark.parametrize("sheet_name, cell, boxes", [
    (TEAM_LOGO_SHEET, LOGO_CELL, list(STOCK_LOGO_BOXES.values())),
    (TEAM_NAME_SHEET, TEAM_NAME_CELL, ["dune_rats", "street_breed", "road_beasts", "wave_rippers", "scorchers"]),
])
def test_every_stock_team_cuts_and_goes_back(sheet_name, cell, boxes):
    archive = Archive(Path(os.environ["WRMOD_GAME"]))
    sheet_bog, sheet_bed = archive.read(f"{sheet_name}.bog"), archive.read(f"{sheet_name}.bed")
    cuts = {box: cut_icon(sheet_bog, sheet_bed, box, cell) for box in boxes}
    assert all(cuts.values())
    bog, new_bed = add_icons(sheet_bog, sheet_bed, {"neon": cuts[boxes[0]]}, cell)
    assert cut_icon(bog, new_bed, "neon", cell)[HEADER_SIZE:] == cuts[boxes[0]][HEADER_SIZE:]
    assert cut_icon(bog, new_bed, boxes[1], cell)[HEADER_SIZE:] == cuts[boxes[1]][HEADER_SIZE:]
