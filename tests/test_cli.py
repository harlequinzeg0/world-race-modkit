import json
import zipfile

import pytest

from test_bog import make_dds, make_dxt_bog, make_paletted_bog
from wrmod import cli, store
from wrmod.cli import main
from wrmod.gameinfo import RETAIL_SHA256


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("WRMOD_DATA", str(tmp_path / "data"))


def write_sample_bog(path):
    path.write_bytes(make_dxt_bog(fourcc=b"DXT5", unknown_0x24=2, unknown_0x28=1))
    return path


def test_bog2dds_and_back(tmp_path):
    bog = write_sample_bog(tmp_path / "a.bog")
    assert main(["bog2dds", str(bog), str(tmp_path / "a.dds")]) == 0
    assert main(["dds2bog", str(tmp_path / "a.dds"), str(tmp_path / "b.bog"), "--like", str(bog)]) == 0
    assert (tmp_path / "b.bog").read_bytes() == bog.read_bytes()


def test_unedited_paletted_comes_back_identical(tmp_path):
    bog = tmp_path / "a.bog"
    bog.write_bytes(make_paletted_bog(4, 4, 3))
    main(["bog2dds", str(bog), str(tmp_path / "a.dds")])
    assert main(["dds2bog", str(tmp_path / "a.dds"), str(tmp_path / "b.bog"), "--like", str(bog)]) == 0
    assert (tmp_path / "b.bog").read_bytes() == bog.read_bytes()


def test_dds2bog_without_original(tmp_path):
    dds = tmp_path / "a.dds"
    dds.write_bytes(make_dds(b"DXT1", 8, 8, 1))
    assert main(["dds2bog", str(dds), str(tmp_path / "a.bog")]) == 0
    assert (tmp_path / "a.bog").read_bytes()[:8] == b"BOG 1.02"


def test_errors_return_1_with_message(tmp_path, capsys):
    assert main(["bog2dds", str(tmp_path / "missing.bog"), "x"]) == 1
    assert "missing.bog" in capsys.readouterr().err


def test_bad_texture_returns_1(tmp_path, capsys):
    bad = tmp_path / "bad.bog"
    bad.write_bytes(b"nope")
    assert main(["bog2dds", str(bad), str(tmp_path / "x")]) == 1
    assert "BOG" in capsys.readouterr().err


def test_game_commands_need_a_folder(capsys):
    assert main(["recover"]) == 1
    assert "--game" in capsys.readouterr().err


def test_saved_game_folder_is_used(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(cli.deploy, "restore", lambda game, data: seen.append(str(game)) or False)
    store.save_settings({"game": str(tmp_path)})
    assert main(["recover"]) == 0
    assert seen == [str(tmp_path)]


def test_install_zip(tmp_path, capsys):
    path = tmp_path / "m.zip"
    info = {
        "format_version": 1, "id": "m1", "name": "M", "version": "1", "author": "a",
        "description": "d", "kind": "tweak", "requires_game": RETAIL_SHA256,
    }
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mod.json", json.dumps(info))
    assert main(["install", str(path)]) == 0
    assert (store.mods_dir() / "m1" / "mod.json").is_file()


def test_patch_command_is_gone(tmp_path):
    with pytest.raises(SystemExit):
        main(["patch", str(tmp_path / "x.exe"), "--game", str(tmp_path)])


def test_list_prints_archive_paths(game_dir, capsys):
    assert main(["list", "--game", str(game_dir)]) == 0
    assert "misc/cache/car_info.xml" in capsys.readouterr().out


def test_template_and_build(game_dir, tmp_path):
    project = tmp_path / "p"
    assert main(["template", "twin_mill", str(project), "--game", str(game_dir)]) == 0
    assert main(["build", str(project), str(tmp_path / "m.zip"), "--game", str(game_dir)]) == 1
    params = project / "files/cars/twin_mill/cache/twin_mill.params"
    params.write_bytes(params.read_bytes() + b"\n")
    assert main(["build", str(project), str(tmp_path / "m.zip"), "--game", str(game_dir)]) == 0
    assert (tmp_path / "m.zip").is_file()


def test_newcar_makes_a_project(game_dir, tmp_path):
    dest = tmp_path / "neon"
    assert main(["newcar", "ballistic", "neon", "road_beasts", str(dest), "--game", str(game_dir)]) == 0
    assert (dest / "cars.json").is_file()


def test_newcar_bad_name_is_an_error(game_dir, tmp_path, capsys):
    assert main(["newcar", "ballistic", "Bad Name", "road_beasts", str(tmp_path / "x"), "--game", str(game_dir)]) == 1
    assert "Bad car name" in capsys.readouterr().err


def test_addon_command_writes_the_zip(tmp_path, capsys):
    out = tmp_path / "addon.zip"
    assert main(["addon", str(out)]) == 0
    assert zipfile.is_zipfile(out)
