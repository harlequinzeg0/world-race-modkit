"""Read and edit the game's .msg text files.

Layout: u32 count, u32 offsets[count] relative to byte 4, then strings that each
end with two null bytes. String IDs are compiled into the EXE, so this module
reads their names from the player's own copy.
"""
import struct

LANGUAGES = {
    "english": "ENGLISH",
    "usa": "USA",
    "french": "FRENCH",
    "german": "GERMAN",
    "italian": "ITALIAN",
    "spanish": "SPANISH",
}

OFFSET_BASE = 4
TERMINATOR = b"\0\0"
# Some stock strings are not UTF-8. surrogateescape keeps those bytes unchanged.
ENCODING = {"encoding": "utf-8", "errors": "surrogateescape"}

STRING_TABLE_VA = 0x59B198
STRING_COUNT = 574
IMAGE_BASE = 0x400000


def msg_path(language):
    return f"strings/{LANGUAGES[language]}.msg"


def read_msg(data):
    if len(data) < OFFSET_BASE:
        raise ValueError("not a .msg file")
    count = struct.unpack_from("<I", data, 0)[0]
    if OFFSET_BASE + count * 4 > len(data):
        raise ValueError("not a .msg file")
    offsets = struct.unpack_from(f"<{count}I", data, OFFSET_BASE)
    ends = offsets[1:] + (len(data) - OFFSET_BASE,)
    return [
        data[OFFSET_BASE + start:OFFSET_BASE + end - len(TERMINATOR)].decode(**ENCODING)
        for start, end in zip(offsets, ends)
    ]


def write_msg(strings):
    offsets = []
    body = bytearray()
    table_size = len(strings) * 4
    for text in strings:
        offsets.append(table_size + len(body))
        body += text.encode(**ENCODING) + TERMINATOR
    return struct.pack(f"<I{len(strings)}I", len(strings), *offsets) + bytes(body)


def load_string_ids(exe):
    ids = {}
    offset = STRING_TABLE_VA - IMAGE_BASE
    for _ in range(STRING_COUNT):
        string_id, pointer = struct.unpack_from("<II", exe, offset)
        offset += 8
        start = pointer - IMAGE_BASE
        ids[exe[start:exe.index(b"\0", start)].decode("ascii")] = string_id
    return ids


def resolve_edits(edits, language):
    resolved = {}
    for name, value in edits.items():
        if isinstance(value, str):
            resolved[name] = value
        elif language in value:
            resolved[name] = value[language]
        elif "default" in value:
            resolved[name] = value["default"]
    return resolved


def new_text_ids(names):
    """New names take IDs after the stock table, in the given order."""
    return {name: STRING_COUNT + index for index, name in enumerate(names)}


def apply_edits(data, edits, ids, new_ids=None):
    strings = read_msg(data)
    known = dict(ids)
    if new_ids:
        known.update(new_ids)
        strings += [""] * (max(new_ids.values()) + 1 - len(strings))
    for name, text in edits.items():
        if name not in known or known[name] >= len(strings):
            raise KeyError(name)
        strings[known[name]] = text
    return write_msg(strings)
