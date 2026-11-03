import os
from pathlib import Path

import pytest

from wrmod.bark import Archive
from wrmod.bed import Bed, BedError, Box, read_bed, write_bed


def sample():
    return Bed("sheet.tga", 512, 256, [Box("one", [(0, 0), (18750, 0), (18750, 9375), (0, 9375)]), Box("two", [(1, 2), (3, 4)])])


def test_round_trip():
    bed = sample()
    assert read_bed(write_bed(bed)) == bed


def test_a_link_to_another_box_is_kept():
    bed = Bed("a.tga", 64, 64, [Box("a", [(1, 2)], 1), Box("", [(3, 4)])])
    assert read_bed(write_bed(bed)).boxes[0].link == 1


def test_layout_matches_the_game():
    assert write_bed(Bed("a.tga", 512, 512, [Box("b", [(1, 2)])])) == (
        b"\x01\x01a.tga\0\x00\x02\x00\x02\x01\x00\x01\x00\x01\0\0\0\x02\0\0\0b\0\xff\xff"
    )


def test_box_reads_its_pixels():
    box = Box("one", [(18750, 0), (37500, 0), (37500, 9375), (18750, 9375)])
    assert box.pixels(512, 512) == (96, 0, 96, 48)


def test_find_returns_a_box_or_nothing():
    bed = sample()
    assert bed.find("two").points == [(1, 2), (3, 4)]
    assert bed.find("three") is None


def test_find_ignores_case_as_the_game_does():
    assert sample().find("TWO").points == [(1, 2), (3, 4)]


def test_rectangle_makes_four_corners():
    box = Box.rectangle("new", 96, 512, 96, 48, 512, 1024)
    assert box.pixels(512, 1024) == (96, 512, 96, 48)
    assert len(box.points) == 4


@pytest.mark.parametrize("data", [b"", b"\x01\x02a\0", b"\x01\x01a\0\0\x02\0\x02\x01\0"])
def test_bad_data_is_refused(data):
    with pytest.raises(BedError):
        read_bed(data)


def test_trailing_data_is_refused():
    with pytest.raises(BedError):
        read_bed(write_bed(sample()) + b"x")


@pytest.mark.skipif("WRMOD_GAME" not in os.environ, reason="needs the game")
def test_every_stock_sheet_round_trips():
    archive = Archive(Path(os.environ["WRMOD_GAME"]))
    paths = [p for p in archive.paths() if p.lower().endswith(".bed")]
    assert len(paths) == 28
    for path in paths:
        data = archive.read(path)
        assert write_bed(read_bed(data)) == data, path
