import pytest

from wrmod.bark import Archive
from wrmod.msg import LANGUAGES, STRING_COUNT, apply_edits, load_string_ids, msg_path, new_text_ids, read_msg, resolve_edits, write_msg


def test_msg_round_trip():
    assert read_msg(write_msg(["A", "BC", ""])) == ["A", "BC", ""]


def test_msg_keeps_non_ascii_text():
    assert read_msg(write_msg(["DEORA® II"])) == ["DEORA® II"]


def test_msg_offsets_are_relative_to_byte_4():
    data = write_msg(["A", "BC"])
    assert data[:4] == (2).to_bytes(4, "little")
    assert data[4:8] == (8).to_bytes(4, "little")
    assert data[12:14] == b"A\0"


def test_empty_file_refused():
    with pytest.raises(ValueError):
        read_msg(b"\x01")


def test_plain_string_applies_to_every_language():
    assert resolve_edits({"X": "Hi"}, "german") == {"X": "Hi"}


def test_language_override_and_default():
    edits = {"X": {"default": "Hi", "french": "Salut"}}
    assert resolve_edits(edits, "french") == {"X": "Salut"}
    assert resolve_edits(edits, "usa") == {"X": "Hi"}


def test_language_missing_with_no_default_is_skipped():
    assert resolve_edits({"X": {"french": "Salut"}}, "usa") == {}


def test_edit_changes_only_the_named_string():
    data = write_msg(["A", "B", "C"])
    assert read_msg(apply_edits(data, {"Y": "new"}, {"X": 0, "Y": 1})) == ["A", "new", "C"]


def test_unknown_id_refused():
    with pytest.raises(KeyError):
        apply_edits(write_msg(["A"]), {"NOPE": "x"}, {"X": 0})


def test_id_past_the_end_refused():
    with pytest.raises(KeyError):
        apply_edits(write_msg(["A"]), {"X": "x"}, {"X": 9})


def test_new_name_appends_after_stock():
    stock = [f"text {i}" for i in range(STRING_COUNT)]
    new_ids = new_text_ids(["CAR_NEON"])
    assert new_ids == {"CAR_NEON": 574}
    strings = read_msg(apply_edits(write_msg(stock), {"CAR_NEON": "Neon"}, {"X": 0}, new_ids))
    assert strings[:574] == stock
    assert strings[574] == "Neon"


def test_new_names_take_ids_in_order():
    assert new_text_ids(["A", "B"]) == {"A": 574, "B": 575}


def test_stock_edit_works_beside_a_new_name():
    stock = ["old"] + [""] * (STRING_COUNT - 1)
    data = apply_edits(write_msg(stock), {"X": "new", "CAR_NEON": "Neon"}, {"X": 0}, new_text_ids(["CAR_NEON"]))
    strings = read_msg(data)
    assert (strings[0], strings[574]) == ("new", "Neon")


def test_unknown_name_is_still_refused_with_new_names():
    with pytest.raises(KeyError):
        apply_edits(write_msg(["A"] * STRING_COUNT), {"NOPE": "x"}, {"X": 0}, new_text_ids(["CAR_NEON"]))


def test_paths_use_archive_names():
    assert msg_path("usa") == "strings/USA.msg"
    assert set(LANGUAGES) == {"english", "usa", "french", "german", "italian", "spanish"}


def test_stock_msg_files_round_trip(game_dir):
    archive = Archive(game_dir)
    for language in LANGUAGES:
        data = archive.read(msg_path(language))
        strings = read_msg(data)
        assert len(strings) == 574
        assert write_msg(strings) == data, language


def test_string_ids_read_from_exe(game_dir):
    ids = load_string_ids((game_dir / "HotWheelsWorldRace.exe").read_bytes())
    assert len(ids) == 574
    assert ids["TWIN_MILL"] == 109
