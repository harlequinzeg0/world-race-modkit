import json
import os
import zipfile

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_bog import make_dds, make_dxt_bog
from test_template import StubArchive
from wrmod import template
from wrmod.gui import make_tab as make_module
from wrmod.gui.make_tab import MakeTab


@pytest.fixture
def errors():
    return []


@pytest.fixture
def tab(qapp, monkeypatch, errors):
    monkeypatch.setattr(template, "game_files", StubArchive)
    widget = MakeTab("game")
    widget.show_error = errors.append
    return widget


@pytest.fixture
def opened(tab, tmp_path):
    tab.start_from_car("tm", tmp_path / "tm")
    return tab


def test_game_lists_cars(tab):
    assert [tab.car_box.itemText(i) for i in range(tab.car_box.count())] == ["tm", "other"]


def test_no_game_disables_starting(qapp):
    widget = MakeTab(None)
    assert not widget.start_button.isEnabled()


def test_unreadable_game_lists_nothing(qapp, tmp_path):
    widget = MakeTab(tmp_path)
    assert widget.car_box.count() == 0 and not widget.start_button.isEnabled()


def test_start_from_car_opens_project(opened, tmp_path):
    assert opened.project == tmp_path / "tm"
    assert opened.name_edit.text() == "tm mod"
    assert opened.build_button.isEnabled()


def test_start_error_is_shown(tab, tmp_path, errors):
    (tmp_path / "taken").mkdir()
    tab.start_from_car("tm", tmp_path / "taken")
    assert errors and tab.project is None


def test_details_form_writes_mod_json(opened):
    opened.name_edit.setText("Neon Mill")
    opened.author_edit.setText("Jesse")
    opened.version_edit.setText("2.0")
    opened.description_edit.setPlainText("A bright car")
    opened.kind_box.setCurrentText("textures")
    opened.save_details()
    meta = json.loads((opened.project / "mod.json").read_text())
    assert (meta["name"], meta["author"], meta["version"]) == ("Neon Mill", "Jesse", "2.0")
    assert (meta["description"], meta["kind"]) == ("A bright car", "textures")


def test_open_project_reads_details(opened, qapp, tmp_path, errors, monkeypatch):
    opened.name_edit.setText("Saved name")
    opened.save_details()
    other = MakeTab("game")
    other.show_error = errors.append
    other.open_project(tmp_path / "tm")
    assert other.name_edit.text() == "Saved name"


def test_open_invalid_project_is_refused(tab, tmp_path, errors):
    tab.open_project(tmp_path)
    assert errors and tab.project is None


def test_changed_list_updates_after_edit(opened):
    assert opened.changed_list() == []
    (opened.project / "files/cars/tm/cache/tm.params").write_bytes(b"new")
    opened.refresh_changes()
    assert opened.changed_list() == ["cars/tm/cache/tm.params"]
    assert opened.change_list.count() == 1


def test_build_error_is_shown_when_nothing_changed(opened, tmp_path, errors):
    assert opened.build(tmp_path / "m.zip") is None
    assert any("nothing changed" in e for e in errors)


def test_build_writes_zip_with_form_details(opened, tmp_path):
    (opened.project / "files/cars/tm/cache/tm.params").write_bytes(b"new")
    opened.name_edit.setText("Built name")
    out = opened.build(tmp_path / "m.zip")
    with zipfile.ZipFile(out) as z:
        assert json.loads(z.read("mod.json"))["name"] == "Built name"


def test_single_file_convert_picks_direction_by_extension(tab, tmp_path):
    bog = tmp_path / "a.bog"
    bog.write_bytes(make_dxt_bog())
    assert tab.convert_file(bog) == tmp_path / "a.dds"
    dds = tmp_path / "b.dds"
    dds.write_bytes(make_dds(b"DXT1", 8, 8, 1))
    assert tab.convert_file(dds) == tmp_path / "b.bog"


def test_convert_never_overwrites(tab, tmp_path, errors):
    bog = tmp_path / "a.bog"
    bog.write_bytes(make_dxt_bog())
    (tmp_path / "a.dds").write_bytes(b"precious")
    assert tab.convert_file(bog) is None
    assert errors and (tmp_path / "a.dds").read_bytes() == b"precious"


def test_convert_other_file_is_refused(tab, tmp_path, errors):
    other = tmp_path / "a.png"
    other.write_bytes(b"x")
    assert tab.convert_file(other) is None and errors


def test_bad_texture_shows_error(tab, tmp_path, errors):
    bad = tmp_path / "a.bog"
    bad.write_bytes(b"nope")
    assert tab.convert_file(bad) is None and errors


def test_project_folder_can_be_opened_in_explorer(opened, monkeypatch):
    seen = []
    monkeypatch.setattr(make_module.os, "startfile", seen.append)
    opened.open_folder()
    assert seen == [str(opened.project)]


def test_make_tab_offers_new_car(tab, tmp_path):
    teams = [tab.team_box.itemText(i) for i in range(tab.team_box.count())]
    assert "road_beasts" in teams and tab.new_button.isEnabled()
    tab.new_from_car("tm", "neon", "scorchers", tmp_path / "neon")
    assert tab.project == tmp_path / "neon"
    assert json.loads((tab.project / "cars.json").read_text())[0]["team"] == "scorchers"


def test_new_car_error_is_shown(tab, tmp_path, errors):
    tab.new_from_car("tm", "Bad Name", "scorchers", tmp_path / "neon")
    assert errors and tab.project is None


def test_no_game_disables_new_car(qapp):
    assert not MakeTab(None).new_button.isEnabled()


def test_notice_no_longer_says_new_cars_are_coming(tab):
    assert "later version" not in make_module.NOTICE


def test_make_tab_saves_the_blender_addon(tab, tmp_path):
    out = tab.save_addon(tmp_path / "addon.zip")
    assert zipfile.is_zipfile(out)


def test_addon_save_error_is_shown(tab, tmp_path, errors):
    assert tab.save_addon(tmp_path / "missing_folder/addon.zip") is None
    assert errors


def test_addon_button_works_with_no_game(qapp):
    assert MakeTab(None).addon_button.isEnabled()


def test_opening_an_older_car_project_adds_its_icons(tab, tmp_path):
    tab.new_from_car("tm", "neon", "road_beasts", tmp_path / "neon")
    icon = tmp_path / "neon/textures/frontend/neon_icon.bog.dds"
    icon.unlink()
    tab.open_project(tmp_path / "neon")
    assert icon.is_file()


def test_make_team_moves_the_open_car_onto_it(tab, tmp_path):
    tab.new_from_car("tm", "neon", "road_beasts", tmp_path / "neon")
    tab.make_team("Neon Riders", "road_beasts")
    assert json.loads((tmp_path / "neon/cars.json").read_text())[0]["team"] == "neon_riders"
    assert (tmp_path / "neon/teams.json").is_file()


def test_make_team_shows_a_refused_name(tab, tmp_path, errors):
    tab.new_from_car("tm", "neon", "road_beasts", tmp_path / "neon")
    tab.make_team("!!!", "road_beasts")
    assert errors and not (tmp_path / "neon/teams.json").exists()


def test_team_button_needs_an_open_project(tab, tmp_path):
    assert not tab.team_button.isEnabled()
    tab.new_from_car("tm", "neon", "road_beasts", tmp_path / "neon")
    assert tab.team_button.isEnabled()
