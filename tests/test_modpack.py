import json
import stat
import zipfile

import pytest

from wrmod.gameinfo import RETAIL_SHA256
from wrmod.modpack import (
    ModError,
    install_zip,
    installed_mods,
    mod_cars,
    mod_files,
    mod_strings,
    mod_teams,
    parse_cars,
    parse_mod_json,
    parse_teams,
    remove_mod,
    validate_zip,
)


def info(**changes):
    data = {
        "format_version": 1,
        "id": "neon_mill",
        "name": "Neon Mill",
        "version": "1.0",
        "author": "Tester",
        "description": "A test mod",
        "kind": "car",
        "requires_game": RETAIL_SHA256,
    }
    data.update(changes)
    return json.dumps(data).encode()


GOOD = info()


def make_zip(members, folder, name="mod.zip"):
    path = folder / name
    with zipfile.ZipFile(path, "w") as z:
        for member, data in members.items():
            z.writestr(member, data)
    return path


def assert_refused(path, mods):
    with pytest.raises(ModError):
        install_zip(path, mods)
    assert not mods.exists() or not any(mods.iterdir())


def test_good_zip_installs(tmp_path):
    z = make_zip({"mod.json": GOOD, "files/cars/x/cache/x.params": b"p"}, tmp_path)
    mod = install_zip(z, tmp_path / "mods")
    assert mod.id == "neon_mill"
    assert mod_files(tmp_path / "mods" / "neon_mill") == ["cars/x/cache/x.params"]
    assert (tmp_path / "mods/neon_mill/files/cars/x/cache/x.params").read_bytes() == b"p"


@pytest.mark.parametrize(
    "name",
    [
        "../evil.txt",
        "files/../../evil.txt",
        "files/../mod2.json",
        "C:/evil.txt",
        "/evil.txt",
        "files\\..\\evil.txt",
        "files/a.txt:stream",
    ],
)
def test_escaping_paths_refused(name, tmp_path):
    assert_refused(make_zip({"mod.json": GOOD, name: b"x"}, tmp_path), tmp_path / "mods")


def test_symlink_member_refused(tmp_path):
    path = tmp_path / "mod.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mod.json", GOOD)
        link = zipfile.ZipInfo("files/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(link, "C:/Windows")
    assert_refused(path, tmp_path / "mods")


def test_newer_format_refused(tmp_path):
    assert_refused(make_zip({"mod.json": info(format_version=2)}, tmp_path), tmp_path / "mods")


def test_bad_json_refused(tmp_path):
    assert_refused(make_zip({"mod.json": b"{nope"}, tmp_path), tmp_path / "mods")


def test_missing_mod_json_refused(tmp_path):
    assert_refused(make_zip({"files/a": b"x"}, tmp_path), tmp_path / "mods")


def test_not_a_zip_refused(tmp_path):
    path = tmp_path / "mod.zip"
    path.write_bytes(b"not a zip")
    assert_refused(path, tmp_path / "mods")


def test_other_game_build_refused(tmp_path):
    assert_refused(make_zip({"mod.json": info(requires_game="0" * 64)}, tmp_path), tmp_path / "mods")


def test_member_outside_layout_refused(tmp_path):
    assert_refused(make_zip({"mod.json": GOOD, "readme.exe": b"x"}, tmp_path), tmp_path / "mods")


def test_duplicate_paths_refused(tmp_path):
    assert_refused(make_zip({"mod.json": GOOD, "files/A.txt": b"1", "files/a.txt": b"2"}, tmp_path), tmp_path / "mods")


@pytest.mark.parametrize("bad_id", ["", "Upper", "a b", "../x", "x" * 65, "-x"])
def test_bad_id_refused(bad_id, tmp_path):
    assert_refused(make_zip({"mod.json": info(id=bad_id)}, tmp_path), tmp_path / "mods")


def test_unknown_kind_refused():
    with pytest.raises(ModError):
        parse_mod_json(info(kind="weather"))


def test_missing_field_refused():
    data = json.loads(GOOD)
    del data["name"]
    with pytest.raises(ModError):
        parse_mod_json(json.dumps(data).encode())


@pytest.mark.parametrize("strings", [b"[]", b'{"X": 1}', b'{"X": {"klingon": "y"}}', b"{nope"])
def test_bad_strings_refused(strings, tmp_path):
    assert_refused(make_zip({"mod.json": GOOD, "strings.json": strings}, tmp_path), tmp_path / "mods")


def test_strings_are_read_back(tmp_path):
    z = make_zip({"mod.json": GOOD, "strings.json": b'{"X": "Hi", "Y": {"default": "a", "french": "b"}}'}, tmp_path)
    install_zip(z, tmp_path / "mods")
    assert mod_strings(tmp_path / "mods/neon_mill") == {"X": "Hi", "Y": {"default": "a", "french": "b"}}


def test_mod_without_strings_gives_empty(tmp_path):
    install_zip(make_zip({"mod.json": GOOD}, tmp_path), tmp_path / "mods")
    assert mod_strings(tmp_path / "mods/neon_mill") == {}


def test_reinstall_replaces_older_version(tmp_path):
    old = make_zip({"mod.json": info(version="1.0"), "files/old.txt": b"x"}, tmp_path, "old.zip")
    new = make_zip({"mod.json": info(version="2.0"), "files/new.txt": b"x"}, tmp_path, "new.zip")
    mods = tmp_path / "mods"
    install_zip(old, mods)
    install_zip(new, mods)
    assert installed_mods(mods)["neon_mill"].version == "2.0"
    assert mod_files(mods / "neon_mill") == ["new.txt"]


def test_failed_reinstall_keeps_the_old_mod(tmp_path):
    mods = tmp_path / "mods"
    install_zip(make_zip({"mod.json": GOOD, "files/a.txt": b"x"}, tmp_path, "a.zip"), mods)
    bad = make_zip({"mod.json": GOOD, "../evil": b"x"}, tmp_path, "b.zip")
    with pytest.raises(ModError):
        install_zip(bad, mods)
    assert mod_files(mods / "neon_mill") == ["a.txt"]


def test_broken_installed_mod_is_ignored(tmp_path):
    mods = tmp_path / "mods"
    (mods / "broken").mkdir(parents=True)
    (mods / "broken/mod.json").write_bytes(b"{nope")
    assert installed_mods(mods) == {}


def test_validate_reads_without_installing(tmp_path):
    assert validate_zip(make_zip({"mod.json": GOOD}, tmp_path)).name == "Neon Mill"


def test_remove_mod(tmp_path):
    mods = tmp_path / "mods"
    install_zip(make_zip({"mod.json": GOOD}, tmp_path), mods)
    remove_mod(mods, "neon_mill")
    assert installed_mods(mods) == {}


def test_remove_unknown_mod_refused(tmp_path):
    with pytest.raises(ModError):
        remove_mod(tmp_path, "../other")


@pytest.mark.parametrize("name", ["files/con", "files/sound/com1.fsb", "files/NUL.txt", "files/aux/x.bog"])
def test_device_names_refused(name, tmp_path):
    assert_refused(make_zip({"mod.json": GOOD, name: b"x"}, tmp_path), tmp_path / "mods")


@pytest.mark.parametrize("name", ["files/d3d9.dll", "files/GAME.EXE", "files/x/hook.asi", "files/run.bat"])
def test_executable_files_refused(name, tmp_path):
    assert_refused(make_zip({"mod.json": GOOD, name: b"x"}, tmp_path), tmp_path / "mods")


CAR = {"internal_name": "neon", "team": "road_beasts", "display_name": "Neon", "based_on": "ballistic"}
TEAM = {
    "id": "neon_riders", "display_name": "Neon Riders", "leader": "neon", "base_team": "road_beasts",
    "logo": {"texture": "misc/cache/flash", "box": "flash_1"},
}


def test_zip_with_cars_and_teams_installs(tmp_path):
    files = {"mod.json": info(), "cars.json": json.dumps([CAR]), "teams.json": json.dumps([TEAM])}
    install_zip(make_zip(files, tmp_path), tmp_path / "mods")
    assert mod_cars(tmp_path / "mods/neon_mill") == [CAR]
    assert mod_teams(tmp_path / "mods/neon_mill") == [TEAM]


@pytest.mark.parametrize("change", [{"based_on": "24_7"}, {"based_on": "40_somethin"}, {"internal_name": "24_8"}])
def test_names_can_start_with_a_digit_like_stock_cars(change):
    assert parse_cars(json.dumps([{**CAR, **change}])) == [{**CAR, **change}]


def test_mod_with_no_car_list_has_no_cars(tmp_path):
    assert mod_cars(tmp_path) == [] and mod_teams(tmp_path) == []


@pytest.mark.parametrize("change", [
    {"internal_name": "Bad Name"},
    {"internal_name": "a" * 32},
    {"internal_name": 'x"y'},
    {"team": ""},
    {"based_on": None},
    {"display_name": ""},
    {"display_name": 5},
    {"ai_car": "yes"},
    {"rim_colour": "pink"},
    {"rim_colour": 3},
    {"speed": 11},
    {"grip": -1},
    {"boost": "3"},
    {"accel": True},
])
def test_bad_car_refused(change):
    with pytest.raises(ModError):
        parse_cars(json.dumps([{**CAR, **change}]))


@pytest.mark.parametrize("change", [
    {"id": "Bad Id"},
    {"leader": None},
    {"base_team": ""},
    {"display_name": " "},
    {"logo": {"texture": "a"}},
    {"logo": {"texture": 'a"b', "box": "c"}},
])
def test_bad_team_refused(change):
    with pytest.raises(ModError):
        parse_teams(json.dumps([{**TEAM, **change}]))


@pytest.mark.parametrize("text", ["{", "{}", "[1]"])
def test_car_list_must_be_a_list_of_objects(text):
    with pytest.raises(ModError):
        parse_cars(text)


def test_zip_with_a_bad_car_list_refused(tmp_path):
    files = {"mod.json": info(), "cars.json": json.dumps([{**CAR, "speed": 99}])}
    assert_refused(make_zip(files, tmp_path), tmp_path / "mods")


@pytest.mark.parametrize("driver", ["", "  ", 5, None])
def test_bad_driver_refused(driver):
    car = {"internal_name": "neon", "team": "road_beasts", "display_name": "Neon", "based_on": "tm", "driver": driver}
    with pytest.raises(ModError, match="bad text"):
        parse_cars(json.dumps([car]).encode())


def test_driver_is_optional():
    car = {"internal_name": "neon", "team": "road_beasts", "display_name": "Neon", "based_on": "tm"}
    assert parse_cars(json.dumps([car]).encode()) == [car]


def test_a_team_needs_no_logo_field():
    team = {"id": "neon", "display_name": "Neon", "leader": "n1", "base_team": "road_beasts"}
    assert parse_teams(json.dumps([team]).encode()) == [team]


def test_an_empty_logo_field_is_refused():
    team = {"id": "neon", "display_name": "Neon", "leader": "n1", "base_team": "road_beasts", "logo": None}
    with pytest.raises(ModError, match="logo"):
        parse_teams(json.dumps([team]).encode())


def test_a_car_can_name_a_rim_colour():
    assert parse_cars(json.dumps([{**CAR, "rim_colour": "blue"}]))[0]["rim_colour"] == "blue"


def test_overhaul_tag_is_accepted(tmp_path):
    path = make_zip({"mod.json": GOOD, "nitroxfueled.tag": b""}, tmp_path)
    assert validate_zip(path).id == "neon_mill"
    install_zip(path, tmp_path / "mods")
    assert (tmp_path / "mods/neon_mill/nitroxfueled.tag").is_file()


def test_overhaul_tag_only_at_the_root(tmp_path):
    path = make_zip({"mod.json": GOOD, "sub/nitroxfueled.tag": b""}, tmp_path)
    with pytest.raises(ModError, match="outside the mod layout"):
        validate_zip(path)
