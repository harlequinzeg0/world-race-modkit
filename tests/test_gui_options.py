import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from wrmod import store
from wrmod.gui.options_tab import PAD_WARNING, OptionsTab
from wrmod.options import ACTIONS, CONFIG_FILE, DEFAULT_LAYOUT, PLAYER_ONE_DEVICE


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("WRMOD_DATA", str(tmp_path / "data"))


@pytest.fixture
def tab(qapp, data):
    return OptionsTab()


def pick(tab, action, value):
    combo = tab.combo(action)
    combo.setCurrentIndex(combo.findData(value))


def write_config(game, device):
    data = bytearray(0x300)
    name = device.encode() + b"\0"
    data[PLAYER_ONE_DEVICE:PLAYER_ONE_DEVICE + len(name)] = name
    (game / CONFIG_FILE).write_bytes(bytes(data))


def test_starts_with_defaults(tab):
    assert tab.borderless_box.isChecked() and tab.controller_box.isChecked()
    assert {action: tab.combo(action).currentData() for action in ACTIONS} == DEFAULT_LAYOUT


def test_starts_with_saved_choices(qapp, data):
    store.save_settings({"borderless": False, "layout": {"nitro": "y"}})
    tab = OptionsTab()
    assert not tab.borderless_box.isChecked()
    assert tab.combo("nitro").currentData() == "y"


def test_change_is_saved(tab):
    pick(tab, "nitro", "y")
    assert store.load_settings()["layout"]["nitro"] == "y"


def test_other_settings_stay(tab):
    store.save_settings({"game": "D:/game"})
    pick(tab, "nitro", "y")
    assert store.load_settings()["game"] == "D:/game"


def test_reset_restores_defaults(tab):
    pick(tab, "nitro", "y")
    tab.reset()
    assert tab.combo("nitro").currentData() == "b"
    assert store.load_settings()["layout"] == DEFAULT_LAYOUT


def test_unticking_controller_disables_rows_and_saves(tab):
    tab.controller_box.setChecked(False)
    assert not tab.combo("nitro").isEnabled()
    assert store.load_settings()["controller"] is False
    tab.controller_box.setChecked(True)
    assert tab.combo("nitro").isEnabled()


def test_borderless_box_saves(tab):
    tab.borderless_box.setChecked(False)
    assert store.load_settings()["borderless"] is False


def test_warns_when_player_one_is_a_pad(tab, tmp_path):
    write_config(tmp_path, "Controller (Xbox One For Windows)")
    tab.set_game(tmp_path)
    assert tab.warning.text() == PAD_WARNING
    tab.controller_box.setChecked(False)
    assert tab.warning.text() == ""


def test_no_warning_for_the_keyboard_or_no_game(tab, tmp_path):
    tab.set_game(None)
    assert tab.warning.text() == ""
    write_config(tmp_path, "Keyboard")
    tab.set_game(tmp_path)
    assert tab.warning.text() == ""
