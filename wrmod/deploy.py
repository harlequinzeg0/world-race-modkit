"""Run the game with a profile through the base mod.

The game folder gains only dinput8.dll, and only while the game runs. Mod files stay in the
tool's data folder and saves stay in the profile folder, so a crash can leave nothing but the
DLL. With no session the DLL does nothing, so even that leftover leaves the game stock.
The manifest is written before the DLL is copied, so restore() can always finish the job.
"""
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .gameinfo import STOCK_EXE
from .merge import MergeError, build_session
from .modpack import ModError, mod_files
from .profiles import STOCK, move_old_save, save_dir

DLL_NAME = "dinput8.dll"
DLL_TEMP = DLL_NAME + ".wrse-tmp"
DLL_SOURCE = Path(__file__).parent / "bin" / DLL_NAME
SESSION_VARIABLE = "WRSE_SESSION"
GAME_MUTEX = "HotWheelsWorldRaceGameMutex"
LAUNCH_FLAG = "run_via_launcher"
MANIFEST_FILE = "manifest.json"
SESSION_DIR = "session"
SAVES_PREFIX = "saves/"
# The game opens movies and sound directly, not through its file layer.
UNREACHABLE_PREFIXES = ("movies/", "sound/")
RETRY_DELAYS = (0.2, 0.5, 1.0)
SYNCHRONIZE = 0x100000


class DeployError(Exception):
    pass


def game_running():
    handle = ctypes.windll.kernel32.OpenMutexW(SYNCHRONIZE, False, GAME_MUTEX)
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
    return bool(handle)


def _deploy_dir(data):
    return Path(data) / "deploy"


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_manifest(data):
    path = _deploy_dir(data) / MANIFEST_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _write_manifest(data, manifest):
    folder = _deploy_dir(data)
    folder.mkdir(parents=True, exist_ok=True)
    temp = folder / (MANIFEST_FILE + ".tmp")
    temp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(temp, folder / MANIFEST_FILE)


def _unlink_with_retry(path):
    for delay in RETRY_DELAYS:
        try:
            path.unlink(missing_ok=True)
            return
        except OSError:
            time.sleep(delay)
    path.unlink(missing_ok=True)


def _same_folder(first, second):
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def restore(game, data):
    manifest = _read_manifest(data)
    if manifest is None:
        return False
    if game_running():
        raise DeployError("The game is already running")
    game = Path(game)
    if not _same_folder(manifest["game"], game):
        raise DeployError(f"A deployment is pending in {manifest['game']}. Open that folder to recover it.")
    target = game / DLL_NAME
    try:
        _unlink_with_retry(game / DLL_TEMP)
        if target.is_file() and _digest(target) == manifest["dll"]:
            _unlink_with_retry(target)
    except OSError as e:
        raise DeployError(f"Could not remove {DLL_NAME}: {e}") from e
    (_deploy_dir(data) / MANIFEST_FILE).unlink()
    return True


def _check_mod_files(mods_dir, active):
    for mod in active:
        for rel in mod_files(Path(mods_dir) / mod):
            if rel.lower().startswith(SAVES_PREFIX):
                raise DeployError(f"A mod cannot change saves: {rel}")


def ignored_files(mods_dir, active):
    """Mod files the game can never load, for showing to the player."""
    found = set()
    for mod in active:
        found.update(rel for rel in mod_files(Path(mods_dir) / mod) if rel.lower().startswith(UNREACHABLE_PREFIXES))
    return sorted(found)


def _check_dll_slot(target):
    """Our own leftover is fine. Anything else belongs to the player and must stay."""
    if target.exists() and (not DLL_SOURCE.is_file() or _digest(target) != _digest(DLL_SOURCE)):
        raise DeployError(f"{target} is not this tool's file. Move it out of the game folder to play with mods.")


def prepare(game, data, profile):
    """Write the session and put the DLL in place. Return the session path."""
    game, data = Path(game), Path(data)
    if game_running():
        raise DeployError("The game is already running")
    restore(game, data)
    target = game / DLL_NAME
    _check_dll_slot(target)
    profiles_dir = data / "profiles"
    mods_dir = data / "mods"
    try:
        _check_mod_files(mods_dir, profile.active)
        move_old_save(profiles_dir, profile.name)
        session = build_session(game, mods_dir, profile.active, save_dir(profiles_dir, profile.name), _deploy_dir(data) / SESSION_DIR)
        _write_manifest(data, {"game": str(game), "dll": _digest(DLL_SOURCE)})
    except (MergeError, ModError, OSError) as e:
        raise DeployError(str(e)) from e
    # A copy cut short must never sit under the DLL's real name, where the game would load it.
    temp = game / DLL_TEMP
    try:
        shutil.copyfile(DLL_SOURCE, temp)
        os.replace(temp, target)
    except OSError as e:
        restore(game, data)
        raise DeployError(str(e)) from e
    return session


def launch(exe, game, session=None):
    env = dict(os.environ)
    env.pop(SESSION_VARIABLE, None)
    if session is not None:
        env[SESSION_VARIABLE] = str(session)
    return subprocess.Popen([str(exe), LAUNCH_FLAG], cwd=game, env=env).wait()


def play(game, data, profile, launcher=launch):
    game = Path(game)
    if profile.name == STOCK:
        if game_running():
            raise DeployError("The game is already running")
        restore(game, data)
        try:
            return launcher(game / STOCK_EXE, game, None)
        except OSError as e:
            raise DeployError(str(e)) from e
    session = prepare(game, data, profile)
    try:
        return launcher(game / STOCK_EXE, game, session)
    except OSError as e:
        raise DeployError(str(e)) from e
    finally:
        restore(game, data)
