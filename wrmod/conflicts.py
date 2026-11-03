"""Find where active mods supply the same file or text. Lower in the list wins."""
from dataclasses import dataclass
from pathlib import Path

from .modpack import mod_files, mod_strings
from .msg import LANGUAGES, resolve_edits


@dataclass
class Conflict:
    kind: str
    key: str
    mods: list
    winner: str


def _file_conflicts(mods_dir, active):
    owners = {}
    for mod in active:
        for path in mod_files(mods_dir / mod):
            owners.setdefault(path.lower(), []).append(mod)
    return [Conflict("file", path, mods, mods[-1]) for path, mods in owners.items() if len(mods) > 1]


def _string_conflicts(mods_dir, active):
    owners = {}
    for mod in active:
        edits = mod_strings(mods_dir / mod)
        for language in LANGUAGES:
            for name in resolve_edits(edits, language):
                owners.setdefault((name, language), []).append(mod)
    # A plain string touches all six languages. Report that as one conflict.
    grouped = {}
    for (name, language), mods in owners.items():
        if len(mods) > 1:
            grouped.setdefault((name, tuple(mods)), []).append(language)
    conflicts = []
    for (name, mods), languages in grouped.items():
        key = name if len(languages) == len(LANGUAGES) else f"{name} [{', '.join(languages)}]"
        conflicts.append(Conflict("string", key, list(mods), mods[-1]))
    return conflicts


def find_conflicts(mods_dir, active):
    mods_dir = Path(mods_dir)
    return _file_conflicts(mods_dir, active) + _string_conflicts(mods_dir, active)
