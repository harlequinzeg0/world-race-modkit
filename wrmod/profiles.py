"""Mod list profiles. Each profile has its own list of active mods and its own save."""
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

STOCK = "Stock"
PROFILE_FILE = "profile.json"
SAVE_FILE = "PROGRESS"
SAVE_DIR = "save"
GAME_SAVE_FOLDER = "HOTWHEEL"
MAX_NAME = 40

NAME_PATTERN = re.compile(r'^[^<>:"/\\|?*\x00-\x1f]+$')
RESERVED = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


class ProfileError(Exception):
    pass


@dataclass
class Profile:
    name: str
    active: list


def _check_name(name):
    valid = (
        NAME_PATTERN.match(name)
        and len(name) <= MAX_NAME
        and name == name.strip()
        and not name.endswith(".")
        and name.lower() not in RESERVED
    )
    if not valid:
        raise ProfileError(f"Bad profile name: {name!r}")


def _exists(root, name):
    return name.lower() in (existing.lower() for existing in list_profiles(root))


def _write(root, profile):
    folder = Path(root) / profile.name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / PROFILE_FILE).write_text(json.dumps({"active": profile.active}, indent=2), encoding="utf-8")


def list_profiles(root):
    root = Path(root)
    found = [p.name for p in root.iterdir() if (p / PROFILE_FILE).is_file()] if root.is_dir() else []
    return [STOCK] + sorted(found, key=str.lower)


def load(root, name):
    if name == STOCK:
        return Profile(STOCK, [])
    try:
        raw = json.loads((Path(root) / name / PROFILE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ProfileError(f"Cannot read profile {name}: {e}") from e
    return Profile(name, list(raw.get("active", [])))


def save(root, profile):
    if profile.name == STOCK:
        raise ProfileError("The Stock profile cannot change")
    _write(root, profile)


def create(root, name):
    _check_name(name)
    if _exists(root, name):
        raise ProfileError(f"A profile named {name} already exists")
    profile = Profile(name, [])
    _write(root, profile)
    return profile


def rename(root, old, new):
    if old == STOCK:
        raise ProfileError("The Stock profile cannot change")
    _check_name(new)
    if _exists(root, new):
        raise ProfileError(f"A profile named {new} already exists")
    (Path(root) / old).rename(Path(root) / new)


def duplicate(root, name, new):
    profile = create(root, new)
    profile.active = list(load(root, name).active)
    _write(root, profile)
    return profile


def delete(root, name):
    if name == STOCK:
        raise ProfileError("The Stock profile cannot change")
    shutil.rmtree(Path(root) / name)


def save_dir(root, name):
    """The folder the game treats as its saves folder for this profile."""
    return Path(root) / name / SAVE_DIR


def save_path(root, name):
    return save_dir(root, name) / GAME_SAVE_FOLDER / SAVE_FILE


def move_old_save(root, name):
    """Early versions kept the save directly in the profile folder."""
    old = Path(root) / name / SAVE_FILE
    new = save_path(root, name)
    if old.is_file() and not new.exists():
        new.parent.mkdir(parents=True, exist_ok=True)
        old.replace(new)


def prune_missing(profile, installed):
    missing = [mod for mod in profile.active if mod not in installed]
    profile.active = [mod for mod in profile.active if mod in installed]
    return missing
