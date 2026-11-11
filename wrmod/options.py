"""Player options that WRSE uses in game: the Xbox controller layout and the borderless window.

The Mod Manager keeps them in its settings file and copies them into each session. A bad or
missing entry gets its default, so a hand-edited settings file never stops Play.
"""
from pathlib import Path

ACTIONS = ("accelerate", "brake", "second_brake", "steer", "flip", "handbrake", "nitro", "camera_change", "camera_behind")
# Steering and flips need an axis, so only they take a stick.
STICKS = ("left_stick", "right_stick")
STICK_ACTIONS = ("steer", "flip")
BUTTONS = ("a", "b", "x", "y", "lb", "rb", "lt", "rt", "back", "left_stick_click", "right_stick_click")
DEFAULT_LAYOUT = {
    "accelerate": "rt",
    "brake": "lt",
    "second_brake": "y",
    "steer": "left_stick",
    "flip": "left_stick",
    "handbrake": "a",
    "nitro": "b",
    "camera_change": "x",
    "camera_behind": "right_stick_click",
}

CONFIG_FILE = "Config.cfg"
# Player 1's input device name in the launcher's Config.cfg, ended by a NUL.
PLAYER_ONE_DEVICE = 0x225
DEVICE_NAME_SIZE = 0x100


def choices(action):
    return STICKS if action in STICK_ACTIONS else BUTTONS


def _flag(value):
    return value if isinstance(value, bool) else True


def from_settings(settings):
    saved = settings.get("layout")
    saved = saved if isinstance(saved, dict) else {}
    layout = {action: saved[action] if saved.get(action) in choices(action) else default for action, default in DEFAULT_LAYOUT.items()}
    return {
        "borderless": _flag(settings.get("borderless")),
        "controller": _flag(settings.get("controller")),
        "layout": layout,
    }


def session_fields(opts):
    return {
        "display": {"borderless": opts["borderless"]},
        "controller": {"enabled": opts["controller"], "layout": dict(opts["layout"])},
    }


def player_one_device(game):
    """The launcher's input device for player 1, or None when Config.cfg cannot tell."""
    try:
        data = (Path(game) / CONFIG_FILE).read_bytes()
    except OSError:
        return None
    field = data[PLAYER_ONE_DEVICE:PLAYER_ONE_DEVICE + DEVICE_NAME_SIZE]
    if b"\0" not in field:
        return None
    return field.split(b"\0", 1)[0].decode("latin-1")
