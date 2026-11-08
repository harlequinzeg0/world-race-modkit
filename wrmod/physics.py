"""Read, write and rebase the physics in a car's .params file.

Overhauls such as NitroXFueled retune every car by tier, not by one percent. A mod made on the
stock game carries stock physics, so on an overhaul its car is much slower than the field. The
rebase moves the mod's physics onto the overhaul's base car and keeps the mod's own changes as
shares of the stock values. Wheels stay as the mod has them, because they fit the mod's body.
"""
import re

COUNTS = {
    "NENGINEBINS": "ENGINETORQUECURVE",
    "NCORNERINGFORCEBINS": "CORNERINGFORCECURVE",
    "NSIDEFORCEBINS": "SIDEFORCECURVE",
    "NGEARS": "GEARRATIOS",
}
LIST_KEYS = tuple(COUNTS.values())
GEAR_ROW = 3
SAME_VALUE = 1e-6

_WHEELS = re.compile(r"^[ \t]*(?:NWHEELS|WHEEL)\b", re.M)
_KEY = re.compile(r"[A-Z][A-Z0-9_]*")
_NUMBER = re.compile(r"-?\d*\.?\d+")


class PhysicsError(Exception):
    pass


def split_params(text):
    """(physics, wheels). Some overhaul files have no NWHEELS, so the first WHEEL also starts the wheels."""
    match = _WHEELS.search(text)
    return (text[:match.start()], text[match.start():]) if match else (text, "")


def read_physics(text):
    values = {}
    key = None
    for line in split_params(text)[0].splitlines():
        for token in line.split("//")[0].split():
            if _KEY.fullmatch(token):
                key = token
                values[key] = []
            elif _NUMBER.fullmatch(token) and key is not None:
                values[key].append(float(token))
            else:
                raise PhysicsError(f"Cannot read {token!r} in the car physics")
    return values


def _number(value):
    return f"{value:g}"


def write_physics(values):
    lines = []
    for key, numbers in values.items():
        if key in LIST_KEYS:
            lines.append(key)
            row = GEAR_ROW if key == "GEARRATIOS" else 1
            for start in range(0, len(numbers), row):
                lines.append("\t" + "\t".join(_number(n) for n in numbers[start:start + row]))
        else:
            lines.append("\t".join([key, *map(_number, numbers)]))
    return "".join(line + "\r\n" for line in lines)


def _same(mod, stock):
    return len(mod) == len(stock) and all(abs(m - s) <= SAME_VALUE * max(1.0, abs(s)) for m, s in zip(mod, stock))


def _value(key, mod, stock, overhaul):
    """The rebased numbers for one key, or None to leave the key out."""
    if key in mod and key in stock:
        m, s = mod[key], stock[key]
        if _same(m, s):
            return overhaul.get(key)
        o = overhaul.get(key)
        if o is not None and len(o) == len(m) == len(s):
            return [om * mm / ss if ss != 0 else mm for om, mm, ss in zip(o, m, s)]
        return m
    if key in mod:
        return mod[key]
    if key in stock:
        return None
    return overhaul[key]


def rebase(mod_text, stock, overhaul_text):
    mod = read_physics(mod_text)
    overhaul = read_physics(overhaul_text)
    result = {}
    for key in [*overhaul, *(k for k in mod if k not in overhaul)]:
        value = None if key in COUNTS else _value(key, mod, stock, overhaul)
        if key in COUNTS or value is not None:
            result[key] = value
    for count, list_key in COUNTS.items():
        if count not in result:
            continue
        if list_key in result:
            per_entry = GEAR_ROW if list_key == "GEARRATIOS" else 1
            result[count] = [float(len(result[list_key]) // per_entry)]
        else:
            del result[count]
    return write_physics(result) + split_params(mod_text)[1]
