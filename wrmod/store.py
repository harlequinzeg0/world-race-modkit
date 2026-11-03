"""Where the tool keeps its own data. Nothing here lives in the game folder."""
import json
import os
from pathlib import Path

SETTINGS = "settings.json"


def data_dir():
    override = os.environ.get("WRMOD_DATA")
    path = Path(override) if override else Path(os.environ["LOCALAPPDATA"]) / "WorldRaceModkit"
    path.mkdir(parents=True, exist_ok=True)
    return path


def mods_dir():
    return data_dir() / "mods"


def profiles_dir():
    return data_dir() / "profiles"


def load_settings():
    try:
        return json.loads((data_dir() / SETTINGS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    path = data_dir() / SETTINGS
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    os.replace(temp, path)
