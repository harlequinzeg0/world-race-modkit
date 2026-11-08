import json
import zipfile

import pytest

from test_bog import make_dds, make_dxt_bog, make_paletted_bog
from wrmod import template
from wrmod.bed import Bed, Box, write_bed
from wrmod.bog import dds_to_bog, parse_header
from wrmod.icons import HIGHLIGHT_SHEET, ICON_SHEET, TEAM_LOGO_SHEET, TEAM_NAME_SHEET, dxt5_dds
from wrmod.modpack import validate_zip
from wrmod.template import ProjectError, build_mod_zip, changed_files, create_car_project, create_new_car_project, list_stock_cars

CAR_INFO = (
    b'<Root>\r\n   <CAR internal_name="tm" team_name="road_beasts" locked="true"/>\r\n'
    b'   <CAR internal_name="other" team_name="scorchers" locked="false"/>\r\n</Root>\r\n'
)

STOCK = {
    "misc/cache/car_info.xml": CAR_INFO,
    "cars/tm/cache/tm.params": b"ENGINETORQUEMAX 1.0\r\n",
    "cars/tm/cache/tm_med.rom": b"ROM 1.27 data",
    "cars/tm/cache/tex_high/tm.bog": make_paletted_bog(4, 4, 3),
    "cars/tm/cache/tex_high/tm_stunt.bog": make_dxt_bog(fourcc=b"DXT5", unknown_0x24=2, unknown_0x28=1),
    "cars/tm2/cache/tm2.params": b"other car",
    "frontend/tm_movie.bog": make_dxt_bog(),
    "player_textures/cache/player_tm.bog": make_dxt_bog(),
    **{f"{sheet}.bog": dds_to_bog(dxt5_dds(512, 512, bytes(128 * 128 * 16)), None) for sheet in (ICON_SHEET, HIGHLIGHT_SHEET)},
    **{f"{sheet}.bog": dds_to_bog(dxt5_dds(512, 512, bytes(128 * 128 * 16)), None) for sheet in (TEAM_LOGO_SHEET, TEAM_NAME_SHEET)},
    f"{TEAM_LOGO_SHEET}.bed": write_bed(Bed("s.tga", 512, 512, [Box.rectangle("RoadBeasts", 0, 0, 128, 96, 512, 512)])),
    f"{TEAM_NAME_SHEET}.bed": write_bed(Bed("s.tga", 512, 512, [Box.rectangle("road_beasts", 0, 0, 128, 32, 512, 512)])),
    f"{ICON_SHEET}.bed": write_bed(Bed("s.tga", 512, 512, [Box.rectangle("tm", 0, 0, 96, 48, 512, 512)])),
    f"{HIGHLIGHT_SHEET}.bed": write_bed(Bed("s.tga", 512, 512, [Box.rectangle("tm_hlight", 0, 0, 96, 48, 512, 512)])),
}


class StubArchive:
    def __init__(self, game):
        pass

    def paths(self):
        return list(STOCK)

    def has(self, path):
        return path in STOCK

    def read(self, path):
        return STOCK[path]


@pytest.fixture
def stock(monkeypatch):
    monkeypatch.setattr(template, "game_files", StubArchive)
    monkeypatch.setattr(template, "is_overhaul", lambda game: False)


@pytest.fixture
def overhaul_stock(stock, monkeypatch):
    monkeypatch.setattr(template, "is_overhaul", lambda game: True)


@pytest.fixture
def project(stock, tmp_path):
    return create_car_project("game", "tm", tmp_path / "tm")


def names(path):
    with zipfile.ZipFile(path) as z:
        return set(z.namelist())


def test_lists_stock_cars(stock):
    assert list_stock_cars("game") == ["tm", "other"]


def test_project_holds_text_and_raw_files(project):
    assert (project / "files/cars/tm/cache/tm.params").read_bytes() == STOCK["cars/tm/cache/tm.params"]
    assert (project / "files/cars/tm/cache/tm_med.rom").exists()


def test_textures_export_as_dds_with_saved_header(project):
    dds = project / "textures/cars/tm/cache/tex_high/tm_stunt.bog.dds"
    assert dds.read_bytes()[:4] == b"DDS "
    meta = json.loads((project / "textures/cars/tm/cache/tex_high/tm_stunt.bog.bogmeta.json").read_text())
    assert bytes.fromhex(meta["header_hex"]) == STOCK["cars/tm/cache/tex_high/tm_stunt.bog"][:56]


def test_project_collects_files_outside_car_folder(project):
    assert (project / "textures/frontend/tm_movie.bog.dds").exists()
    assert (project / "textures/player_textures/cache/player_tm.bog.dds").exists()


def test_project_skips_cars_with_a_similar_name(project):
    assert not (project / "files/cars/tm2").exists()


def test_project_keeps_car_info_entry_for_reference(project):
    entry = (project / "reference/car_info_entry.xml").read_bytes()
    assert b'internal_name="tm"' in entry and b"other" not in entry


def test_project_has_valid_details(project):
    meta = json.loads((project / "mod.json").read_text())
    assert meta["kind"] == "car" and meta["id"] == "tm_mod"


def test_unknown_car_refused(stock, tmp_path):
    with pytest.raises(ProjectError):
        create_car_project("game", "nope", tmp_path / "x")


def test_existing_folder_not_overwritten(stock, tmp_path):
    (tmp_path / "tm").mkdir()
    with pytest.raises(ProjectError):
        create_car_project("game", "tm", tmp_path / "tm")


def test_new_project_shows_no_changes(project):
    assert changed_files(project, "game") == []


def test_unedited_project_refuses_to_build(project, tmp_path):
    with pytest.raises(ProjectError, match="nothing changed"):
        build_mod_zip(project, "game", tmp_path / "m.zip")
    assert not (tmp_path / "m.zip").exists()


def test_zip_holds_only_changed_files(project, tmp_path):
    params = project / "files/cars/tm/cache/tm.params"
    params.write_bytes(b"ENGINETORQUEMAX 2.0\r\n")
    assert changed_files(project, "game") == ["cars/tm/cache/tm.params"]
    z = build_mod_zip(project, "game", tmp_path / "m.zip")
    assert names(z) == {"mod.json", "files/cars/tm/cache/tm.params"}
    assert validate_zip(z).id == "tm_mod"


def test_edited_texture_becomes_bog_with_original_fields(project, tmp_path):
    dds = project / "textures/cars/tm/cache/tex_high/tm_stunt.bog.dds"
    dds.write_bytes(make_dds(b"DXT5", 128, 128, 8))
    z = build_mod_zip(project, "game", tmp_path / "m.zip")
    with zipfile.ZipFile(z) as archive:
        bog = archive.read("files/cars/tm/cache/tex_high/tm_stunt.bog")
    assert parse_header(bog).width == 128
    assert bog[0x28:0x2C] == STOCK["cars/tm/cache/tex_high/tm_stunt.bog"][0x28:0x2C]


def test_paletted_skin_replaced_with_dxt(project, tmp_path):
    dds = project / "textures/cars/tm/cache/tex_high/tm.bog.dds"
    dds.write_bytes(make_dds(b"DXT1", 512, 512, 10))
    z = build_mod_zip(project, "game", tmp_path / "m.zip")
    with zipfile.ZipFile(z) as archive:
        assert parse_header(archive.read("files/cars/tm/cache/tex_high/tm.bog")).type == 256


def test_uncompressed_edit_gives_clear_error(project, tmp_path):
    dds = project / "textures/cars/tm/cache/tex_high/tm.bog.dds"
    original = dds.read_bytes()
    dds.write_bytes(original + b"\0")  # still the 32-bit export, now edited
    with pytest.raises(ProjectError, match="DXT1 or DXT5"):
        build_mod_zip(project, "game", tmp_path / "m.zip")


def test_new_file_counts_as_changed(project, tmp_path):
    new = project / "files/cars/tm/cache/extra.xml"
    new.write_bytes(b"<new/>")
    assert changed_files(project, "game") == ["cars/tm/cache/extra.xml"]
    assert "files/cars/tm/cache/extra.xml" in names(build_mod_zip(project, "game", tmp_path / "m.zip"))


def test_deleted_export_is_not_a_change(project):
    (project / "textures/frontend/tm_movie.bog.dds").unlink()
    assert changed_files(project, "game") == []


def test_strings_alone_are_a_change(project, tmp_path):
    (project / "strings.json").write_text('{"TWIN_MILL": "NEON MILL"}')
    assert names(build_mod_zip(project, "game", tmp_path / "m.zip")) == {"mod.json", "strings.json"}


def test_bad_details_stop_the_build(project, tmp_path):
    (project / "files/cars/tm/cache/tm.params").write_bytes(b"changed")
    meta = json.loads((project / "mod.json").read_text())
    meta["id"] = "Bad Id"
    (project / "mod.json").write_text(json.dumps(meta))
    with pytest.raises(ProjectError):
        build_mod_zip(project, "game", tmp_path / "m.zip")
    assert not (tmp_path / "m.zip").exists()


def test_real_car_template(game_dir, tmp_path):
    p = create_car_project(game_dir, "twin_mill", tmp_path / "tm")
    assert (p / "textures/frontend/twin_mill_movie.bog.dds").exists()
    assert (p / "textures/player_textures/cache/player_twin_mill.bog.dds").exists()
    assert (p / "textures/cars/twin_mill/cache/tex_high/twin_mill.bog.dds").exists()
    assert (p / "files/cars/twin_mill/cache/twin_mill.params").exists()
    assert (p / "files/cars/twin_mill/cache/twin_mill_med.rom").exists()
    assert b'internal_name="twin_mill"' in (p / "reference/car_info_entry.xml").read_bytes()
    assert changed_files(p, game_dir) == []
    params = p / "files/cars/twin_mill/cache/twin_mill.params"
    params.write_bytes(params.read_bytes().replace(b"ENGINETORQUEMAX", b"ENGINETORQUEMAX "))
    z = build_mod_zip(p, game_dir, tmp_path / "m.zip")
    assert names(z) == {"mod.json", "files/cars/twin_mill/cache/twin_mill.params"}
    assert validate_zip(z).id == "twin_mill_mod"


def test_all_stock_cars_list(game_dir):
    assert len(list_stock_cars(game_dir)) == 35


@pytest.fixture
def new_car(stock, tmp_path):
    return create_new_car_project("game", "tm", "neon", "road_beasts", tmp_path / "neon")


def test_new_car_copies_files_under_new_name(new_car):
    assert (new_car / "files/cars/neon/cache/neon.params").read_bytes() == STOCK["cars/tm/cache/tm.params"]
    assert (new_car / "files/cars/neon/cache/neon_med.rom").is_file()
    assert (new_car / "textures/cars/neon/cache/tex_high/neon_stunt.bog.dds").is_file()
    assert (new_car / "textures/frontend/neon_movie.bog.dds").is_file()
    assert (new_car / "textures/player_textures/cache/player_neon.bog.dds").is_file()
    assert not (new_car / "files/cars/tm").exists()


def test_new_car_writes_cars_json(new_car):
    assert json.loads((new_car / "cars.json").read_text()) == [{
        "internal_name": "neon", "team": "road_beasts", "display_name": "NEON", "based_on": "tm", "ai_car": False,
    }]


def test_new_car_display_name_uses_spaces(stock, tmp_path):
    project = create_new_car_project("game", "tm", "neon_mill", "road_beasts", tmp_path / "p")
    assert json.loads((project / "cars.json").read_text())[0]["display_name"] == "NEON MILL"


def test_new_car_project_has_valid_details(new_car):
    meta = json.loads((new_car / "mod.json").read_text())
    assert meta["id"] == "neon_mod" and meta["kind"] == "car"


def test_new_car_zip_holds_its_files(new_car, tmp_path):
    z = build_mod_zip(new_car, "game", tmp_path / "m.zip")
    held = names(z)
    assert {"mod.json", "cars.json", "files/cars/neon/cache/neon.params", "files/cars/neon/cache/neon_med.rom"} <= held
    assert {"files/frontend/neon_movie.bog", "files/player_textures/cache/player_neon.bog"} <= held
    with zipfile.ZipFile(z) as archive:
        assert archive.read("files/frontend/neon_movie.bog") == STOCK["frontend/tm_movie.bog"]
    assert validate_zip(z).id == "neon_mod"


def test_new_car_keeps_base_texture_names_too(new_car, tmp_path):
    z = build_mod_zip(new_car, "game", tmp_path / "m.zip")
    with zipfile.ZipFile(z) as archive:
        assert archive.read("files/cars/neon/cache/tex_high/tm.bog") == STOCK["cars/tm/cache/tex_high/tm.bog"]
        assert archive.read("files/cars/neon/cache/tex_high/neon.bog") == STOCK["cars/tm/cache/tex_high/tm.bog"]
        assert "files/frontend/tm_movie.bog" not in archive.namelist()


def test_new_car_skin_edit_reaches_both_names(new_car, tmp_path):
    dds = new_car / "textures/cars/neon/cache/tex_high/neon.bog.dds"
    dds.write_bytes(make_dds(b"DXT1", 512, 512, 10))
    z = build_mod_zip(new_car, "game", tmp_path / "m.zip")
    with zipfile.ZipFile(z) as archive:
        assert parse_header(archive.read("files/cars/neon/cache/tex_high/neon.bog")).type == 256
        assert archive.read("files/cars/neon/cache/tex_high/tm.bog") == archive.read("files/cars/neon/cache/tex_high/neon.bog")


def test_new_car_lists_all_its_files_as_changes(new_car):
    assert "cars/neon/cache/tex_high/neon.bog" in changed_files(new_car, "game")


def test_stock_car_project_still_has_no_cars_json(project):
    assert not (project / "cars.json").exists()


@pytest.mark.parametrize("name", ["tm", "other", "Bad Name", "", "a" * 32, "x/y"])
def test_new_name_must_be_valid_and_unused(stock, tmp_path, name):
    with pytest.raises(ProjectError):
        create_new_car_project("game", "tm", name, "road_beasts", tmp_path / "p")
    assert not (tmp_path / "p").exists()


def test_new_car_needs_a_real_base(stock, tmp_path):
    with pytest.raises(ProjectError, match="nope"):
        create_new_car_project("game", "nope", "neon", "road_beasts", tmp_path / "p")


def test_new_car_needs_a_valid_team_name(stock, tmp_path):
    with pytest.raises(ProjectError):
        create_new_car_project("game", "tm", "neon", "Bad Team", tmp_path / "p")


def test_new_car_never_overwrites_a_folder(stock, tmp_path):
    (tmp_path / "p").mkdir()
    with pytest.raises(ProjectError):
        create_new_car_project("game", "tm", "neon", "road_beasts", tmp_path / "p")


def test_real_new_car(game_dir, tmp_path):
    project = create_new_car_project(game_dir, "ballistic", "neon_mill", "road_beasts", tmp_path / "p")
    z = build_mod_zip(project, game_dir, tmp_path / "m.zip")
    held = names(z)
    assert "files/cars/neon_mill/cache/neon_mill_med.rom" in held
    assert "files/cars/neon_mill/cache/tex_high/ballistic.bog" in held
    assert validate_zip(z).id == "neon_mill_mod"


def edited_icon():
    return dxt5_dds(96, 48, bytes([7]) * (24 * 12 * 16))


def test_new_car_gets_icons_to_paint(new_car):
    assert (new_car / "textures/frontend/neon_icon.bog.dds").is_file()
    assert (new_car / "textures/frontend/neon_icon_hlight.bog.dds").is_file()


def test_new_car_skips_a_highlight_the_base_car_does_not_have(stock, tmp_path, monkeypatch):
    bare = {**STOCK, f"{HIGHLIGHT_SHEET}.bed": write_bed(Bed("s.tga", 512, 512, []))}
    monkeypatch.setattr(StubArchive, "read", lambda self, path: bare[path])
    project = create_new_car_project("game", "tm", "neon", "road_beasts", tmp_path / "p")
    assert (project / "textures/frontend/neon_icon.bog.dds").is_file()
    assert not (project / "textures/frontend/neon_icon_hlight.bog.dds").exists()


def test_an_unpainted_icon_stays_out_of_the_zip(new_car, tmp_path):
    held = names(build_mod_zip(new_car, "game", tmp_path / "m.zip"))
    assert "files/frontend/neon_icon.bog" not in held


def test_a_painted_icon_goes_in_the_zip(new_car, tmp_path):
    (new_car / "textures/frontend/neon_icon.bog.dds").write_bytes(edited_icon())
    held = names(build_mod_zip(new_car, "game", tmp_path / "m.zip"))
    assert "files/frontend/neon_icon.bog" in held


def test_a_painted_icon_of_the_wrong_size_stops_the_build(new_car, tmp_path):
    (new_car / "textures/frontend/neon_icon.bog.dds").write_bytes(dxt5_dds(64, 32, bytes(16 * 8 * 16)))
    with pytest.raises(ProjectError, match="neon"):
        build_mod_zip(new_car, "game", tmp_path / "m.zip")


def test_add_car_icons_fills_in_an_older_project(new_car):
    (new_car / "textures/frontend/neon_icon.bog.dds").unlink()
    template.add_missing_art("game", new_car)
    assert (new_car / "textures/frontend/neon_icon.bog.dds").is_file()


def test_add_car_icons_keeps_a_painted_icon(new_car):
    path = new_car / "textures/frontend/neon_icon.bog.dds"
    path.write_bytes(edited_icon())
    template.add_missing_art("game", new_car)
    assert path.read_bytes() == edited_icon()


def test_add_car_icons_passes_over_a_project_with_no_new_cars(stock, tmp_path):
    project = create_car_project("game", "tm", tmp_path / "p")
    template.add_missing_art("game", project)
    assert not (project / "textures/frontend/tm_icon.bog.dds").exists()


def test_add_team_makes_the_team_from_a_name(new_car):
    team = template.add_team("game", new_car, "Neon Riders", "road_beasts")
    assert team == "neon_riders"
    assert json.loads((new_car / "teams.json").read_text()) == [{
        "id": "neon_riders", "display_name": "Neon Riders", "leader": "neon", "base_team": "road_beasts",
    }]


def test_add_team_moves_the_car_onto_it_as_an_opponent(new_car):
    template.add_team("game", new_car, "Neon Riders", "road_beasts")
    car = json.loads((new_car / "cars.json").read_text())[0]
    assert car["team"] == "neon_riders" and car["ai_car"] is True


def test_add_team_gives_art_to_paint(new_car):
    template.add_team("game", new_car, "Neon Riders", "road_beasts")
    assert (new_car / "textures/frontend/neon_riders_logo.bog.dds").is_file()
    assert (new_car / "textures/frontend/neon_riders_team_name.bog.dds").is_file()


def test_unpainted_team_art_stays_out_of_the_zip(new_car, tmp_path):
    template.add_team("game", new_car, "Neon Riders", "road_beasts")
    held = names(build_mod_zip(new_car, "game", tmp_path / "m.zip"))
    assert "teams.json" in held and "files/frontend/neon_riders_logo.bog" not in held


def test_painted_team_art_goes_in_the_zip(new_car, tmp_path):
    template.add_team("game", new_car, "Neon Riders", "road_beasts")
    (new_car / "textures/frontend/neon_riders_logo.bog.dds").write_bytes(dxt5_dds(128, 96, bytes([7]) * (32 * 24 * 16)))
    assert "files/frontend/neon_riders_logo.bog" in names(build_mod_zip(new_car, "game", tmp_path / "m.zip"))


def test_painted_team_art_of_the_wrong_size_stops_the_build(new_car, tmp_path):
    template.add_team("game", new_car, "Neon Riders", "road_beasts")
    (new_car / "textures/frontend/neon_riders_logo.bog.dds").write_bytes(edited_icon())
    with pytest.raises(ProjectError, match="128x96"):
        build_mod_zip(new_car, "game", tmp_path / "m.zip")


@pytest.mark.parametrize("name", ["", "   ", "!!!", "dune_rats", "Dune Rats"])
def test_add_team_refuses_a_bad_or_stock_name(new_car, name):
    with pytest.raises(ProjectError):
        template.add_team("game", new_car, name, "road_beasts")


def test_add_team_refuses_a_base_that_is_not_stock(new_car):
    with pytest.raises(ProjectError, match="base"):
        template.add_team("game", new_car, "Neon", "neon_riders")


def test_add_team_refuses_a_second_team(new_car):
    template.add_team("game", new_car, "Neon Riders", "road_beasts")
    with pytest.raises(ProjectError, match="already"):
        template.add_team("game", new_car, "Other", "road_beasts")


def test_add_team_needs_a_new_car(stock, tmp_path):
    project = create_car_project("game", "tm", tmp_path / "p")
    with pytest.raises(ProjectError, match="new car"):
        template.add_team("game", project, "Neon", "road_beasts")


def test_add_missing_art_fills_in_a_team(new_car):
    template.add_team("game", new_car, "Neon Riders", "road_beasts")
    (new_car / "textures/frontend/neon_riders_logo.bog.dds").unlink()
    template.add_missing_art("game", new_car)
    assert (new_car / "textures/frontend/neon_riders_logo.bog.dds").is_file()


def test_a_new_texture_also_goes_in_tex_low(new_car, tmp_path):
    high = new_car / "textures/cars/neon/cache/tex_high/second_part.bog.dds"
    high.write_bytes(edited_icon())
    held = names(build_mod_zip(new_car, "game", tmp_path / "m.zip"))
    assert {"files/cars/neon/cache/tex_high/second_part.bog", "files/cars/neon/cache/tex_low/second_part.bog"} <= held


def test_a_painted_low_texture_is_not_replaced(new_car, tmp_path):
    folder = new_car / "textures/cars/neon/cache"
    (folder / "tex_high/second_part.bog.dds").write_bytes(edited_icon())
    (folder / "tex_low").mkdir(exist_ok=True)
    low = dxt5_dds(96, 48, bytes([9]) * (24 * 12 * 16))
    (folder / "tex_low/second_part.bog.dds").write_bytes(low)
    z = build_mod_zip(new_car, "game", tmp_path / "m.zip")
    with zipfile.ZipFile(z) as archive:
        assert archive.read("files/cars/neon/cache/tex_low/second_part.bog").endswith(low[128:])


def test_project_from_stock_has_no_tag(project, new_car):
    assert not (project / "nitroxfueled.tag").exists()
    assert not (new_car / "nitroxfueled.tag").exists()


def test_project_from_an_overhaul_has_the_tag(overhaul_stock, tmp_path):
    assert (create_car_project("game", "tm", tmp_path / "tm") / "nitroxfueled.tag").is_file()
    assert (create_new_car_project("game", "tm", "neon", "road_beasts", tmp_path / "neon") / "nitroxfueled.tag").is_file()


def test_build_copies_the_tag(overhaul_stock, tmp_path):
    project = create_car_project("game", "tm", tmp_path / "tm")
    (project / "files/cars/tm/cache/tm.params").write_bytes(b"ENGINETORQUEMAX 2.0\r\n")
    assert "nitroxfueled.tag" in names(build_mod_zip(project, "game", tmp_path / "m.zip"))


def test_build_without_tag_has_none(project, tmp_path):
    (project / "files/cars/tm/cache/tm.params").write_bytes(b"ENGINETORQUEMAX 2.0\r\n")
    assert "nitroxfueled.tag" not in names(build_mod_zip(project, "game", tmp_path / "m.zip"))


def test_tag_alone_is_not_a_change(overhaul_stock, tmp_path):
    project = create_car_project("game", "tm", tmp_path / "tm")
    with pytest.raises(ProjectError, match="nothing changed"):
        build_mod_zip(project, "game", tmp_path / "m.zip")
