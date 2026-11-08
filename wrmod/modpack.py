"""The mod zip format: mod.json, files/, strings.json, cars.json and teams.json.

A zip comes from the internet, so every member is checked before any is written.
"""
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .gameinfo import RETAIL_SHA256
from .msg import LANGUAGES
from .profiles import RESERVED

BLOCKED_SUFFIXES = (".exe", ".dll", ".asi", ".ocx", ".sys", ".com", ".scr", ".bat", ".cmd", ".ps1", ".vbs")
FORMAT_VERSION = 1
KINDS = ("car", "team", "track", "tweak", "textures")
MANIFEST = "mod.json"
STRINGS = "strings.json"
CARS = "cars.json"
TEAMS = "teams.json"
FILES_DIR = "files"
# An empty file that says the mod's car physics are already for NitroXFueled, so merge leaves them as they are.
OVERHAUL_TAG = "nitroxfueled.tag"

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# These names go into XML attributes and folder names. Stock cars 24_7 and 40_somethin start with a digit.
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,30}$")
ASSET_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_/.-]{0,127}$")
STATS = ("speed", "grip", "boost", "accel")
MAX_STAT = 10


class ModError(Exception):
    pass


@dataclass
class ModInfo:
    format_version: int
    id: str
    name: str
    version: str
    author: str
    description: str
    kind: str
    requires_game: str


def parse_mod_json(data):
    try:
        raw = json.loads(data)
        info = ModInfo(**{name: raw[name] for name in ModInfo.__dataclass_fields__})
    except (ValueError, KeyError, TypeError) as e:
        raise ModError(f"{MANIFEST} is not valid: {e}") from e
    text_fields = (info.id, info.name, info.version, info.author, info.description, info.kind, info.requires_game)
    if not all(isinstance(value, str) for value in text_fields) or not isinstance(info.format_version, int):
        raise ModError(f"{MANIFEST} has a field of the wrong type")
    if info.format_version > FORMAT_VERSION:
        raise ModError(f"This mod needs a newer version of the tool (format {info.format_version})")
    if not ID_PATTERN.match(info.id):
        raise ModError(f"Bad mod id: {info.id!r}")
    if info.kind not in KINDS:
        raise ModError(f"Unknown mod kind: {info.kind!r}")
    if info.requires_game != RETAIL_SHA256:
        raise ModError("This mod was made for a different build of the game")
    return info


def _parse_strings(data):
    try:
        strings = json.loads(data)
    except ValueError as e:
        raise ModError(f"{STRINGS} is not valid: {e}") from e
    if not isinstance(strings, dict):
        raise ModError(f"{STRINGS} must be an object")
    allowed = set(LANGUAGES) | {"default"}
    for name, value in strings.items():
        if isinstance(value, dict):
            if not set(value) <= allowed or not all(isinstance(text, str) for text in value.values()):
                raise ModError(f"{STRINGS}: bad entry for {name}")
        elif not isinstance(value, str):
            raise ModError(f"{STRINGS}: bad entry for {name}")
    return strings


def _read_entries(data, filename):
    try:
        entries = json.loads(data)
    except ValueError as e:
        raise ModError(f"{filename} is not valid: {e}") from e
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ModError(f"{filename} must be a list of objects")
    return entries


def _check_name(value, filename):
    if not isinstance(value, str) or not NAME_PATTERN.match(value):
        raise ModError(f"{filename}: bad name {value!r}")


def _check_text(value, filename):
    if not isinstance(value, str) or not value.strip():
        raise ModError(f"{filename}: bad text {value!r}")


# In the order of the game's wheel textures, generic_wheel_high_0 to _4.
RIM_COLOURS = ("yellow", "green", "silver", "blue", "red")


def _check_car(car):
    for key in ("internal_name", "team", "based_on"):
        _check_name(car.get(key), CARS)
    _check_text(car.get("display_name"), CARS)
    if "driver" in car:
        _check_text(car["driver"], CARS)
    if car.get("rim_colour", RIM_COLOURS[0]) not in RIM_COLOURS:
        raise ModError(f"{CARS}: rim_colour must be one of {', '.join(RIM_COLOURS)}")
    if not isinstance(car.get("ai_car", False), bool):
        raise ModError(f"{CARS}: ai_car must be true or false")
    for stat in STATS:
        value = car.get(stat, 0)
        if type(value) is not int or not 0 <= value <= MAX_STAT:
            raise ModError(f"{CARS}: {stat} must be 0 to {MAX_STAT}")


def _check_team(team):
    for key in ("id", "leader", "base_team"):
        _check_name(team.get(key), TEAMS)
    _check_text(team.get("display_name"), TEAMS)
    if "logo" not in team:
        return
    logo = team["logo"]
    if not isinstance(logo, dict) or not all(
        isinstance(logo.get(key), str) and ASSET_PATTERN.match(logo[key]) for key in ("texture", "box")
    ):
        raise ModError(f"{TEAMS}: bad logo for {team['id']}")


def parse_cars(data):
    cars = _read_entries(data, CARS)
    for car in cars:
        _check_car(car)
    return cars


def parse_teams(data):
    teams = _read_entries(data, TEAMS)
    for team in teams:
        _check_team(team)
    return teams


def _check_member(member):
    name = member.filename
    unsafe = (
        "\\" in name
        or ":" in name
        or name.startswith("/")
        or any(part in ("", ".", "..") for part in name.rstrip("/").split("/"))
    )
    if unsafe:
        raise ModError(f"Unsafe path in zip: {name}")
    if stat.S_ISLNK(member.external_attr >> 16):
        raise ModError(f"Link in zip: {name}")
    parts = name.rstrip("/").split("/")
    if any(part.split(".")[0].lower() in RESERVED for part in parts):
        raise ModError(f"Reserved device name in zip: {name}")
    # The game loads DLLs from its folder, so a mod could otherwise run code.
    if parts[-1].lower().endswith(BLOCKED_SUFFIXES):
        raise ModError(f"Mods cannot contain programs: {name}")
    if name not in (MANIFEST, STRINGS, CARS, TEAMS, OVERHAUL_TAG) and not name.startswith(f"{FILES_DIR}/"):
        raise ModError(f"File outside the mod layout: {name}")


def _read_validated(archive):
    seen = set()
    for member in archive.infolist():
        _check_member(member)
        key = member.filename.lower()
        if key in seen:
            raise ModError(f"Duplicate path in zip: {member.filename}")
        seen.add(key)
    if MANIFEST not in seen:
        raise ModError(f"The zip has no {MANIFEST}")
    if STRINGS in seen:
        _parse_strings(archive.read(STRINGS))
    if CARS in seen:
        parse_cars(archive.read(CARS))
    if TEAMS in seen:
        parse_teams(archive.read(TEAMS))
    return parse_mod_json(archive.read(MANIFEST))


def validate_zip(path):
    try:
        with zipfile.ZipFile(path) as archive:
            return _read_validated(archive)
    except (zipfile.BadZipFile, OSError) as e:
        raise ModError(f"Cannot read {path}: {e}") from e


def install_zip(path, mods_dir):
    mods_dir = Path(mods_dir)
    try:
        with zipfile.ZipFile(path) as archive:
            info = _read_validated(archive)
            mods_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=mods_dir, prefix=".install-") as temp:
                extracted = Path(temp) / "mod"
                archive.extractall(extracted)
                target = mods_dir / info.id
                if target.exists():
                    shutil.rmtree(target)
                os.replace(extracted, target)
    except (zipfile.BadZipFile, OSError) as e:
        raise ModError(f"Cannot install {path}: {e}") from e
    return info


def installed_mods(mods_dir):
    mods = {}
    mods_dir = Path(mods_dir)
    if not mods_dir.is_dir():
        return mods
    for folder in sorted(mods_dir.iterdir()):
        manifest = folder / MANIFEST
        if not manifest.is_file():
            continue
        try:
            info = parse_mod_json(manifest.read_bytes())
        except ModError:
            continue
        mods[info.id] = info
    return mods


def mod_files(mod_dir):
    root = Path(mod_dir) / FILES_DIR
    if not root.is_dir():
        return []
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def mod_strings(mod_dir):
    path = Path(mod_dir) / STRINGS
    return _parse_strings(path.read_bytes()) if path.is_file() else {}


def mod_cars(mod_dir):
    path = Path(mod_dir) / CARS
    return parse_cars(path.read_bytes()) if path.is_file() else []


def mod_teams(mod_dir):
    path = Path(mod_dir) / TEAMS
    return parse_teams(path.read_bytes()) if path.is_file() else []


def remove_mod(mods_dir, mod_id):
    target = Path(mods_dir) / mod_id
    if not ID_PATTERN.match(mod_id) or not target.is_dir():
        raise ModError(f"No such mod: {mod_id}")
    shutil.rmtree(target)
