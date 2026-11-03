import os
from pathlib import Path

import pytest

from wrmod.bark import Archive
from wrmod.wheels import (
    Wheel,
    params_radius,
    params_width,
    read_wheels,
    visible_radius,
    visible_width,
    write_wheels,
)

PARAMS = (
    "NWHEELS\t\t4\t\t// FOUR WHEELS\r\n"
    "\r\n"
    "// FRONT LEFT WHEEL\r\n"
    "WHEEL\t0\r\n"
    "\r\n"
    "WHEELOFFSET\t\t-0.695\t -0.34\t1.71\r\n"
    "//WHEELOFFSET\t\t9.0\t9.0\t9.0\r\n"
    "WHEELRADIUS\t\t0.43\r\n"
    "WHEELWIDTH\t\t0.35\t// FRONT\r\n"
    "WHEELMINPOS\t\t-0.15\r\n"
    "\r\n"
    "// FRONT RIGHT WHEEL\r\n"
    "WHEEL\t1\r\n"
    "WHEELOFFSET\t\t0.695\t -0.34\t1.71\r\n"
    "WHEELRADIUS\t\t0.46\r\n"
    "WHEELWIDTH\t\t0.4\r\n"
)


def test_read_finds_each_wheel():
    wheels = read_wheels(PARAMS)
    assert [w.index for w in wheels] == [0, 1]
    assert wheels[0].offset == (-0.695, -0.34, 1.71)
    assert wheels[1].radius == 0.46
    assert wheels[1].width == 0.4


def test_read_ignores_commented_lines():
    assert read_wheels(PARAMS)[0].offset[0] == -0.695


def test_read_skips_a_wheel_without_all_its_settings():
    text = "WHEEL\t0\nWHEELRADIUS\t0.4\nWHEEL\t1\nWHEELOFFSET\t1 2 3\nWHEELRADIUS\t0.5\nWHEELWIDTH\t0.3\n"
    assert [w.index for w in read_wheels(text)] == [1]


def test_write_with_the_same_values_keeps_every_byte():
    assert write_wheels(PARAMS, read_wheels(PARAMS)) == PARAMS


def test_write_ignores_noise_smaller_than_the_precision():
    wheels = read_wheels(PARAMS)
    wheels[0].offset = (-0.69500001, -0.34000001, 1.70999999)
    wheels[0].radius = 0.43000002
    assert write_wheels(PARAMS, wheels) == PARAMS


def test_write_changes_only_the_named_wheel():
    wheels = read_wheels(PARAMS)
    wheels[1].offset = (0.5, -0.25, 1.125)
    wheels[1].radius = 0.2
    wheels[1].width = 0.15
    text = write_wheels(PARAMS, wheels)
    assert text.count("\r\n") == PARAMS.count("\r\n")
    assert "-0.695\t -0.34\t1.71\r\n" in text
    assert "WHEELOFFSET\t\t0.5\t -0.25\t1.125\r\n" in text
    assert "WHEELRADIUS\t\t0.2\r\n" in text
    assert "WHEELWIDTH\t\t0.15\r\n" in text
    assert [w.radius for w in read_wheels(text)] == [0.43, 0.2]


def test_write_keeps_a_comment_after_a_value():
    wheels = read_wheels(PARAMS)
    wheels[0].width = 0.5
    assert "WHEELWIDTH\t\t0.5\t// FRONT\r\n" in write_wheels(PARAMS, wheels)


def test_write_changes_only_the_axis_that_moved():
    wheels = read_wheels(PARAMS)
    wheels[0].offset = (-0.695, -0.34, 2.0)
    assert "WHEELOFFSET\t\t-0.695\t -0.34\t2\r\n" in write_wheels(PARAMS, wheels)


def test_write_leaves_a_commented_line_alone():
    wheels = read_wheels(PARAMS)
    wheels[0].offset = (1.0, 1.0, 1.0)
    assert "//WHEELOFFSET\t\t9.0\t9.0\t9.0\r\n" in write_wheels(PARAMS, wheels)


def test_write_has_no_negative_zero():
    wheels = read_wheels(PARAMS)
    wheels[0].offset = (-0.00001, -0.34, 1.71)
    assert "WHEELOFFSET\t\t0\t -0.34\t1.71\r\n" in write_wheels(PARAMS, wheels)


def test_visible_size_matches_the_scale_in_the_game():
    # FUN_0046ea60 multiplies the shared model by WHEELRADIUS * 0.9 and by WHEELWIDTH.
    wheel = Wheel(index=0, offset=(0.0, 0.0, 0.0), radius=0.43, width=0.35)
    assert visible_radius(wheel) == pytest.approx(0.97161 * 0.9 * 0.43, abs=1e-4)
    assert visible_width(wheel) == pytest.approx(0.98687 * 0.35, abs=1e-4)


def test_visible_size_converts_back():
    wheel = Wheel(index=0, offset=(0.0, 0.0, 0.0), radius=0.43, width=0.35)
    assert params_radius(visible_radius(wheel)) == pytest.approx(0.43, abs=1e-9)
    assert params_width(visible_width(wheel)) == pytest.approx(0.35, abs=1e-9)


@pytest.mark.skipif("WRMOD_GAME" not in os.environ, reason="needs the game")
def test_every_stock_car_round_trips_unchanged():
    archive = Archive(Path(os.environ["WRMOD_GAME"]))
    paths = [p for p in archive.paths() if p.endswith(".params") and "/generic/" not in p]
    assert len(paths) == 37
    for path in paths:
        text = archive.read(path).decode("latin-1")
        wheels = read_wheels(text)
        assert len(wheels) == 4, path
        assert write_wheels(text, wheels) == text, path
