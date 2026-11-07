import pytest

from wrmod.bark import Archive
from wrmod.gamefiles import LooseFiles, game_files


@pytest.fixture
def loose_game(tmp_path):
    game = tmp_path / "game"
    files = {
        "HotWheelsWorldRace.exe": b"exe",
        "misc/cache/car_info.xml": b"<Root/>",
        "Cars/Ballistic/cache/ballistic.params": b"params",
        "saves/HOTWHEEL/PROGRESS": b"save",
    }
    for rel, data in files.items():
        (game / rel).parent.mkdir(parents=True, exist_ok=True)
        (game / rel).write_bytes(data)
    return game


def test_a_game_with_no_archive_uses_its_loose_files(loose_game):
    assert isinstance(game_files(loose_game), LooseFiles)


def test_loose_files_list_game_data_only(loose_game):
    assert sorted(LooseFiles(loose_game).paths()) == ["Cars/Ballistic/cache/ballistic.params", "misc/cache/car_info.xml"]


def test_loose_lookup_ignores_case_like_the_game(loose_game):
    files = LooseFiles(loose_game)
    assert files.has("cars/ballistic/CACHE/ballistic.params")
    assert files.read("MISC/cache/car_info.xml") == b"<Root/>"
    assert not files.has("saves/HOTWHEEL/PROGRESS")


def test_a_missing_loose_file_is_a_key_error_like_the_archive(loose_game):
    with pytest.raises(KeyError):
        LooseFiles(loose_game).read("misc/cache/nothing.xml")


def test_a_folder_with_no_archive_and_no_game_data_is_refused(tmp_path):
    (tmp_path / "HotWheelsWorldRace.exe").write_bytes(b"exe")
    with pytest.raises(FileNotFoundError, match="harchive.bah"):
        game_files(tmp_path)


def test_a_game_with_an_archive_uses_it(game_dir):
    assert isinstance(game_files(game_dir), Archive)
