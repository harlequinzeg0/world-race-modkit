"""Read and change the wheel settings in a car's .params file.

The Blender add-on packs this file, so it stays free of the mod tool and of Blender. A change
touches only the numbers that moved, so a car's comments and tuning stay as they were.
"""
import re
from dataclasses import dataclass

# The size of the shared model, cars/generic_models/cache/generic_wheel_med.rom.
MODEL_RADIUS = 0.97162
MODEL_WIDTH = 0.98687
# FUN_0046ea60 draws a wheel at this share of WHEELRADIUS, and at the full WHEELWIDTH.
DRAWN_RADIUS = 0.9
# Blender holds single precision floats, so a value that did not move comes back with noise.
SAME_VALUE = 0.00005

_LINE = re.compile(r"^[ \t]*(WHEELOFFSET|WHEELRADIUS|WHEELWIDTH|WHEEL)[ \t]+([^\r\n/]*)", re.M)
_NUMBER = re.compile(r"-?\d*\.?\d+")


@dataclass
class Wheel:
    index: int
    offset: tuple
    radius: float
    width: float


def _settings(text):
    """Each wheel value with its place in the text: (wheel, setting, [(start, end, value)])."""
    wheel = None
    for line in _LINE.finditer(text):
        name = line.group(1)
        numbers = [(m.start() + line.start(2), m.end() + line.start(2), float(m.group()))
                   for m in _NUMBER.finditer(line.group(2))]
        if name == "WHEEL":
            wheel = int(numbers[0][2]) if numbers else None
        elif wheel is not None:
            yield wheel, name, numbers


def read_wheels(text):
    found = {}
    for wheel, name, numbers in _settings(text):
        found.setdefault(wheel, {})[name] = [value for _, _, value in numbers]
    wheels = []
    for index, values in sorted(found.items()):
        offset, radius, width = (values.get(n, []) for n in ("WHEELOFFSET", "WHEELRADIUS", "WHEELWIDTH"))
        if len(offset) == 3 and len(radius) == 1 and len(width) == 1:
            wheels.append(Wheel(index, tuple(offset), radius[0], width[0]))
    return wheels


def _number(value):
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def write_wheels(text, wheels):
    wanted = {wheel.index: wheel for wheel in wheels}
    changes = []
    for index, name, numbers in _settings(text):
        wheel = wanted.get(index)
        if wheel is None:
            continue
        values = {"WHEELOFFSET": wheel.offset, "WHEELRADIUS": (wheel.radius,), "WHEELWIDTH": (wheel.width,)}[name]
        for (start, end, old), new in zip(numbers, values):
            if abs(new - old) >= SAME_VALUE:
                changes.append((start, end, _number(new)))
    # Working from the end keeps the earlier places valid.
    for start, end, number in sorted(changes, reverse=True):
        text = text[:start] + number + text[end:]
    return text


def visible_radius(wheel):
    return wheel.radius * DRAWN_RADIUS * MODEL_RADIUS


def visible_width(wheel):
    return wheel.width * MODEL_WIDTH


def params_radius(radius):
    return radius / (DRAWN_RADIUS * MODEL_RADIUS)


def params_width(width):
    return width / MODEL_WIDTH
