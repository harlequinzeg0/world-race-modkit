"""Check and copy a game install."""
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

RETAIL_SHA256 = "ab816e5b823947b022097649d6c0cf9615d54584de6102c80d8dfb48ab2dfd32"
STOCK_EXE = "HotWheelsWorldRace.exe"
PROTECTED_VARS = ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")


class GameError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _is_under(path, root):
    path = os.path.normcase(os.path.abspath(path))
    root = os.path.normcase(os.path.abspath(root))
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def is_protected(path):
    path = Path(path)
    for name in PROTECTED_VARS:
        root = os.environ.get(name)
        if root and _is_under(path, root):
            return True
    if path.is_dir():
        try:
            with tempfile.TemporaryFile(dir=path):
                pass
        except OSError:
            return True
    return False


def check_game_folder(path):
    path = Path(path)
    exe = path / STOCK_EXE
    if not exe.is_file():
        raise GameError("missing_exe", f"{STOCK_EXE} is not in {path}")
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    if digest != RETAIL_SHA256:
        raise GameError("unknown_build", f"This game build is not supported: {digest}")
    # Checked first: in Program Files, Windows may redirect Config.cfg elsewhere.
    if is_protected(path):
        raise GameError("protected", f"The tool cannot safely use {path}. Copy the game to another folder.")
    if not (path / "Config.cfg").is_file():
        raise GameError("no_config", "Config.cfg is missing. Run the game's launcher once, then try again.")


def _virtual_store(path):
    """Windows redirects writes by old programs in protected folders to this folder."""
    return Path(os.environ.get("LOCALAPPDATA", "")) / "VirtualStore" / path.relative_to(path.anchor)


def copy_game(src, dst, progress=None):
    src, dst = Path(src), Path(dst)
    if dst.exists():
        raise GameError("dest_exists", f"{dst} already exists")
    # Redirected files come last, because they are the newer copies of the save and config.
    roots = [src, _virtual_store(src.absolute())]
    work = []
    for root in roots:
        work += [(root, p) for p in root.rglob("*") if p.is_file() and p.relative_to(root).parts[0] != "DISC"]
    for done, (root, source) in enumerate(work, start=1):
        target = dst / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if progress:
            progress(done, len(work))
