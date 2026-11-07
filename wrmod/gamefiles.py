"""The game's own files, from the harchive pair or, with no archive, from loose folders.

Overhauls such as NitroXFueled ship no archive and run on loose files. Their files must be
the base that mods merge onto, or a merged file would undo the overhaul's changes.
"""
from pathlib import Path

from .bark import Archive

ARCHIVE_INDEX = "harchive.bah"
# Loose folders that hold player data, not game data.
NOT_GAME_DATA = {"saves"}


class LooseFiles:
    """Game files under the game folder, with the same lookups as Archive. Lookups ignore case, like the game."""

    def __init__(self, game_dir):
        game_dir = Path(game_dir)
        self._files = {}
        for path in game_dir.rglob("*"):
            rel = path.relative_to(game_dir)
            # The archive holds only files inside folders, so files at the top are programs and settings.
            if len(rel.parts) > 1 and rel.parts[0].lower() not in NOT_GAME_DATA and path.is_file():
                self._files[rel.as_posix().lower()] = (rel.as_posix(), path)

    def paths(self):
        return [rel for rel, _ in self._files.values()]

    def has(self, path):
        return path.lower() in self._files

    def read(self, path):
        return self._files[path.lower()][1].read_bytes()


def game_files(game_dir):
    game_dir = Path(game_dir)
    if (game_dir / ARCHIVE_INDEX).is_file():
        return Archive(game_dir)
    files = LooseFiles(game_dir)
    if not files.paths():
        raise FileNotFoundError(f"{game_dir} has no {ARCHIVE_INDEX} and no loose game files")
    return files
