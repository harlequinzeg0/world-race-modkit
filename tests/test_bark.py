from wrmod.bark import Archive, lzss_decompress


def test_lzss_literals_and_match():
    # flag 0b101: literal, match, literal
    src = bytes([0b101]) + b"A" + bytes([0xEE, 0xF0]) + b"B"
    assert lzss_decompress(src, 5) == b"AAAAB"


def test_archive_lists_all_files(game_dir):
    assert len(Archive(game_dir).paths()) == 6786


def test_archive_lookup_ignores_case(game_dir):
    archive = Archive(game_dir)
    assert archive.has("MISC/CACHE/car_info.XML")
    assert not archive.has("misc/cache/nothing.xml")


def test_archive_reads_stored_and_compressed_entries(game_dir):
    archive = Archive(game_dir)
    assert archive.read("misc/cache/car_info.xml").startswith(b"<Root")
    assert archive.read("frontend/ic1_movie.bog").startswith(b"BOG 1.02")
