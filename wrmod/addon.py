"""Package the Blender add-on. Blender installs it from a single zip."""
import zipfile
from pathlib import Path

ADDON_NAME = "world_race_models"
HERE = Path(__file__).parent


def build_addon(out):
    out = Path(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(HERE / "blender_addon.py", f"{ADDON_NAME}/__init__.py")
        archive.write(HERE / "rom.py", f"{ADDON_NAME}/rom.py")
        archive.write(HERE / "wheels.py", f"{ADDON_NAME}/wheels.py")
    return out
