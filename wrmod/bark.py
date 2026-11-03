"""Reader and extractor for the Bark 1.06 archive (harchive.bah + harchive.bad).

Formats below were recovered from HotWheelsWorldRace.exe:
  index walk    FUN_004db3d0
  path lookup   FUN_004db130 (case-insensitive, no hash use)
  entry decode  FUN_0050e4c0 / FUN_0050e520 (LZSS)

.bah layout, all little-endian u32:
  char magic[12]            "Bark 1.06"
  dir:   name_len, file_count, subdir_count, data_base, name[name_len]
         file[file_count]
         dir[subdir_count]  (recursive, files before subdirectories)
  file:  name_len, offset, stored_size, raw_size, hash, name[name_len]

.bad entry at file.offset:
  u32 method (0 = stored, 1 = LZSS), u32 raw_size, data
"""
import multiprocessing
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = b"Bark 1.06"
HEADER_SIZE = 12
RING_SIZE = 4096
RING_MASK = RING_SIZE - 1
RING_START = 0xFEE
MATCH_MIN = 3


@dataclass
class Entry:
    path: str
    offset: int
    stored_size: int
    raw_size: int
    hash: int


@dataclass
class Directory:
    path: str
    data_base: int
    files: list = field(default_factory=list)
    subdirs: list = field(default_factory=list)


def read_index(bah_path):
    with open(bah_path, "rb") as f:
        data = f.read()
    if data[:len(MAGIC)] != MAGIC:
        raise ValueError(f"{bah_path}: not a {MAGIC.decode()} index")

    pos = HEADER_SIZE

    def read_name(length):
        nonlocal pos
        raw = data[pos:pos + length]
        pos += length
        return raw.split(b"\0", 1)[0].decode("latin-1")

    def read_dir(parent):
        nonlocal pos
        name_len, file_count, subdir_count, data_base = struct.unpack_from("<4I", data, pos)
        pos += 16
        name = read_name(name_len)
        path = f"{parent}/{name}" if parent and name else (parent or name)
        node = Directory(path, data_base)
        for _ in range(file_count):
            name_len, offset, stored, raw, hash_ = struct.unpack_from("<5I", data, pos)
            pos += 20
            file_name = read_name(name_len)
            full = f"{path}/{file_name}" if path else file_name
            node.files.append(Entry(full, offset, stored, raw, hash_))
        for _ in range(subdir_count):
            node.subdirs.append(read_dir(path))
        return node

    root = read_dir("")
    if pos != len(data):
        raise ValueError(f"index parse ended at {pos}, file is {len(data)} bytes")
    return root


def walk_files(node):
    yield from node.files
    for sub in node.subdirs:
        yield from walk_files(sub)


def lzss_decompress(src, raw_size):
    ring = bytearray(RING_SIZE)
    out = bytearray()
    r = RING_START
    i = 0
    flags = 0
    while len(out) < raw_size:
        flags >>= 1
        if not flags & 0x100:
            flags = src[i] | 0xFF00
            i += 1
        if flags & 1:
            b = src[i]
            i += 1
            out.append(b)
            ring[r] = b
            r = (r + 1) & RING_MASK
        else:
            lo, hi = src[i], src[i + 1]
            i += 2
            start = lo | ((hi & 0xF0) << 4)
            for k in range((hi & 0x0F) + MATCH_MIN):
                b = ring[(start + k) & RING_MASK]
                ring[r] = b
                r = (r + 1) & RING_MASK
                out.append(b)
                if len(out) >= raw_size:
                    break
    return bytes(out)


def read_entry(bad, entry):
    bad.seek(entry.offset)
    blob = bad.read(entry.stored_size)
    method, raw_size = struct.unpack_from("<II", blob, 0)
    if raw_size != entry.raw_size:
        raise ValueError(f"{entry.path}: index size {entry.raw_size}, entry size {raw_size}")
    if method == 0:
        data = blob[8:8 + raw_size]
    elif method == 1:
        data = lzss_decompress(memoryview(blob)[8:], raw_size)
    else:
        raise ValueError(f"{entry.path}: unknown method {method}")
    if len(data) != raw_size:
        raise ValueError(f"{entry.path}: decoded {len(data)} bytes, expected {raw_size}")
    return data


def _extract_chunk(args):
    bad_path, out_dir, entries = args
    with open(bad_path, "rb") as bad:
        for entry in entries:
            data = read_entry(bad, entry)
            target = os.path.join(out_dir, *entry.path.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(data)
    return len(entries)


def extract_all(game_dir, out_dir, jobs=None, progress=None):
    game_dir = Path(game_dir)
    entries = list(walk_files(read_index(game_dir / "harchive.bah")))
    jobs = jobs or os.cpu_count() or 4
    # Large files dominate the run time, so deal them out across chunks by size.
    entries.sort(key=lambda e: e.raw_size, reverse=True)
    chunks = [[] for _ in range(jobs * 8)]
    for i, entry in enumerate(entries):
        chunks[i % len(chunks)].append(entry)
    work = [(str(game_dir / "harchive.bad"), str(out_dir), chunk) for chunk in chunks if chunk]
    done = 0
    with multiprocessing.Pool(jobs) as pool:
        for count in pool.imap_unordered(_extract_chunk, work):
            done += count
            if progress:
                progress(done, len(entries))


class Archive:
    """The game's harchive pair, addressed by path. Lookups ignore case, like the game."""

    def __init__(self, game_dir):
        game_dir = Path(game_dir)
        self._bad_path = game_dir / "harchive.bad"
        self._entries = {e.path.lower(): e for e in walk_files(read_index(game_dir / "harchive.bah"))}

    def paths(self):
        return [e.path for e in self._entries.values()]

    def has(self, path):
        return path.lower() in self._entries

    def read(self, path):
        entry = self._entries[path.lower()]
        with open(self._bad_path, "rb") as bad:
            return read_entry(bad, entry)
