import hashlib

import pytest

from wrmod import gameinfo
from wrmod.gameinfo import GameError, check_game_folder, copy_game, is_protected


def good_game(folder, monkeypatch):
    folder.mkdir(exist_ok=True)
    exe = b"game"
    monkeypatch.setattr(gameinfo, "RETAIL_SHA256", hashlib.sha256(exe).hexdigest())
    (folder / "HotWheelsWorldRace.exe").write_bytes(exe)
    (folder / "Config.cfg").write_bytes(b"cfg")
    return folder


def code_for(path):
    with pytest.raises(GameError) as e:
        check_game_folder(path)
    return e.value.code


def test_protected_folder_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert is_protected(tmp_path / "Game")


def test_normal_folder_not_protected(monkeypatch, tmp_path):
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))
    monkeypatch.setenv("ProgramW6432", str(tmp_path / "pf64"))
    assert not is_protected(tmp_path)


def test_missing_exe_refused(tmp_path):
    assert code_for(tmp_path) == "missing_exe"


def test_unknown_build_refused(tmp_path):
    (tmp_path / "HotWheelsWorldRace.exe").write_bytes(b"x")
    assert code_for(tmp_path) == "unknown_build"


def test_missing_config_refused(tmp_path, monkeypatch):
    game = good_game(tmp_path / "g", monkeypatch)
    (game / "Config.cfg").unlink()
    assert code_for(game) == "no_config"


def test_game_in_protected_folder_refused(tmp_path, monkeypatch):
    game = good_game(tmp_path / "g", monkeypatch)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert code_for(game) == "protected"


def test_good_game_passes(tmp_path, monkeypatch):
    for name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        monkeypatch.setenv(name, str(tmp_path / "pf"))
    check_game_folder(good_game(tmp_path / "g", monkeypatch))


def test_copy_game_skips_disc(tmp_path):
    src = tmp_path / "src"
    (src / "DISC").mkdir(parents=True)
    (src / "DISC" / "Setup.dat").write_bytes(b"big")
    (src / "saves").mkdir()
    (src / "saves" / "PROGRESS").write_bytes(b"s")
    (src / "game.exe").write_bytes(b"e")
    copy_game(src, tmp_path / "dst")
    assert (tmp_path / "dst" / "saves" / "PROGRESS").read_bytes() == b"s"
    assert (tmp_path / "dst" / "game.exe").exists()
    assert not (tmp_path / "dst" / "DISC").exists()


def test_copy_game_refuses_existing_destination(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "dst").mkdir()
    with pytest.raises(GameError):
        copy_game(tmp_path / "src", tmp_path / "dst")


def test_protected_is_reported_before_missing_config(tmp_path, monkeypatch):
    # In Program Files, Windows may redirect Config.cfg, so its absence means nothing.
    game = good_game(tmp_path / "g", monkeypatch)
    (game / "Config.cfg").unlink()
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert code_for(game) == "protected"


def test_copy_brings_files_windows_redirected(tmp_path, monkeypatch):
    src = tmp_path / "Program Files" / "Game"
    (src / "saves/HOTWHEEL").mkdir(parents=True)
    (src / "saves/HOTWHEEL/PROGRESS").write_bytes(b"old")
    (src / "game.exe").write_bytes(b"e")
    local = tmp_path / "local"
    twin = local / "VirtualStore" / src.relative_to(src.anchor)
    (twin / "saves/HOTWHEEL").mkdir(parents=True)
    (twin / "saves/HOTWHEEL/PROGRESS").write_bytes(b"real progress")
    (twin / "Config.cfg").write_bytes(b"cfg")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    copy_game(src, tmp_path / "dst")
    assert (tmp_path / "dst/saves/HOTWHEEL/PROGRESS").read_bytes() == b"real progress"
    assert (tmp_path / "dst/Config.cfg").read_bytes() == b"cfg"
    assert (tmp_path / "dst/game.exe").read_bytes() == b"e"
