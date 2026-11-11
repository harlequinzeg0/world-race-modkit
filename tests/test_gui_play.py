import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal

from test_modpack import info, make_zip
from wrmod import profiles, store
from wrmod.gameinfo import GameError
from wrmod.gui import app as app_module
from wrmod.gui import play_tab as play_module
from wrmod.gui import worker as worker_module
from wrmod.gui.app import MainWindow
from wrmod.gui.play_tab import PlayTab
from wrmod.modpack import install_zip


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("WRMOD_DATA", str(tmp_path / "data"))


@pytest.fixture
def errors():
    return []


@pytest.fixture
def tab(qapp, data, tmp_path, errors):
    widget = PlayTab(tmp_path)
    widget.show_error = errors.append
    profiles.create(store.profiles_dir(), "Mine")
    widget.refresh()
    widget.select_profile("Mine")
    return widget


def add_mod(tab, tmp_path, mod_id, files=None):
    members = {"mod.json": info(id=mod_id, name=mod_id.title())}
    for path, data in (files or {}).items():
        members[f"files/{path}"] = data
    tab.add_zip(make_zip(members, tmp_path, f"{mod_id}.zip"))


def saved_active():
    return profiles.load(store.profiles_dir(), "Mine").active


def test_added_zip_appears_as_inactive(tab, tmp_path):
    add_mod(tab, tmp_path, "m1")
    assert tab.inactive_ids() == ["m1"] and tab.active_ids() == []


def test_activate_moves_mod_and_saves_profile(tab, tmp_path):
    add_mod(tab, tmp_path, "m1")
    tab.activate("m1")
    assert tab.active_ids() == ["m1"] and tab.inactive_ids() == []
    assert saved_active() == ["m1"]


def test_deactivate_returns_mod(tab, tmp_path):
    add_mod(tab, tmp_path, "m1")
    tab.activate("m1")
    tab.deactivate("m1")
    assert tab.inactive_ids() == ["m1"] and saved_active() == []


def test_order_change_is_saved(tab, tmp_path):
    add_mod(tab, tmp_path, "m1")
    add_mod(tab, tmp_path, "m2")
    tab.activate("m1")
    tab.activate("m2")
    tab.move("m2", -1)
    assert tab.active_ids() == ["m2", "m1"] and saved_active() == ["m2", "m1"]


def test_move_past_the_end_changes_nothing(tab, tmp_path):
    add_mod(tab, tmp_path, "m1")
    tab.activate("m1")
    tab.move("m1", -1)
    assert tab.active_ids() == ["m1"]


def test_conflict_is_shown_and_does_not_block_play(tab, tmp_path):
    add_mod(tab, tmp_path, "m1", {"x/y.xml": b"1"})
    add_mod(tab, tmp_path, "m2", {"x/y.xml": b"2"})
    tab.activate("m1")
    tab.activate("m2")
    lines = tab.conflict_lines()
    assert len(lines) == 1 and "x/y.xml" in lines[0] and "m2" in lines[0]
    assert tab.play_button.isEnabled()


def test_bad_zip_shows_error_and_adds_nothing(tab, tmp_path, errors):
    tab.add_zip(make_zip({"mod.json": b"{nope"}, tmp_path, "bad.zip"))
    assert errors and tab.inactive_ids() == []


def test_removed_mod_is_reported(tab, tmp_path, errors):
    add_mod(tab, tmp_path, "m1")
    tab.activate("m1")
    (store.mods_dir() / "m1" / "mod.json").unlink()
    tab.refresh()
    assert any("m1" in e for e in errors)
    assert saved_active() == []


def test_remove_mod_deletes_it(tab, tmp_path):
    tab.confirm = lambda text: True
    add_mod(tab, tmp_path, "m1")
    tab.remove_mod("m1")
    assert tab.inactive_ids() == []


def test_remove_mod_needs_confirmation(tab, tmp_path):
    tab.confirm = lambda text: False
    add_mod(tab, tmp_path, "m1")
    tab.remove_mod("m1")
    assert tab.inactive_ids() == ["m1"]


def test_stock_profile_cannot_be_deleted(tab, errors):
    tab.select_profile(profiles.STOCK)
    tab.delete_profile()
    assert errors and profiles.STOCK in profiles.list_profiles(store.profiles_dir())


def test_stock_profile_takes_no_mods(tab, tmp_path, errors):
    add_mod(tab, tmp_path, "m1")
    tab.select_profile(profiles.STOCK)
    tab.activate("m1")
    assert errors and tab.active_ids() == []


def test_new_profile_is_selected(tab, errors):
    tab.new_profile("Second")
    assert tab.profile.name == "Second" and errors == []


def test_bad_profile_name_shows_error(tab, errors):
    tab.new_profile("../x")
    assert errors and tab.profile.name == "Mine"


def test_each_profile_keeps_its_own_list(tab, tmp_path):
    add_mod(tab, tmp_path, "m1")
    tab.activate("m1")
    tab.new_profile("Second")
    assert tab.active_ids() == []
    tab.select_profile("Mine")
    assert tab.active_ids() == ["m1"]


def test_selected_profile_is_remembered(tab):
    tab.select_profile("Mine")
    assert store.load_settings()["profile"] == "Mine"


class StubWorker(QObject):
    finished_code = Signal(int)
    failed = Signal(str)
    made = []

    def __init__(self, *args):
        super().__init__()
        StubWorker.made.append(self)

    def start(self):
        pass


def test_play_button_disabled_while_running(tab, monkeypatch):
    monkeypatch.setattr(play_module, "PlayWorker", StubWorker)
    tab.play()
    assert not tab.play_button.isEnabled()
    StubWorker.made[-1].finished_code.emit(0)
    assert tab.play_button.isEnabled()


def test_play_failure_is_shown(tab, monkeypatch, errors):
    monkeypatch.setattr(play_module, "PlayWorker", StubWorker)
    tab.play()
    StubWorker.made[-1].failed.emit("sound/x.fsb already exists")
    assert errors == ["sound/x.fsb already exists"] and tab.play_button.isEnabled()


def test_no_game_disables_play(qapp, data):
    assert not PlayTab(None).play_button.isEnabled()


@pytest.fixture
def window(qapp, data, tmp_path, monkeypatch):
    win = MainWindow()
    win.shown_errors = []
    win.show_error = win.shown_errors.append
    win.play_tab.show_error = win.shown_errors.append
    return win


def accept_folders(monkeypatch):
    monkeypatch.setattr(app_module, "check_game_folder", lambda path: None)


def test_first_run_asks_for_folder_when_no_setting(window, tmp_path, monkeypatch):
    accept_folders(monkeypatch)
    window.ask_folder = lambda: str(tmp_path)
    window.start()
    assert store.load_settings()["game"] == str(tmp_path)
    assert window.play_tab.play_button.isEnabled()


def test_options_tab_gets_the_game(window, tmp_path, monkeypatch):
    accept_folders(monkeypatch)
    window.ask_folder = lambda: str(tmp_path)
    window.start()
    assert window.options_tab.game == str(tmp_path)


def test_cancelled_folder_leaves_play_disabled(window):
    window.ask_folder = lambda: None
    window.start()
    assert not window.play_tab.play_button.isEnabled()


def test_bad_folder_asks_again(window, tmp_path, monkeypatch):
    def refuse(path):
        raise GameError("missing_exe", "no game here")

    monkeypatch.setattr(app_module, "check_game_folder", refuse)
    answers = [str(tmp_path), None]
    window.ask_folder = lambda: answers.pop(0)
    window.start()
    assert window.shown_errors == ["no game here"] and answers == []


def test_protected_folder_offers_copy(window, tmp_path, monkeypatch):
    target = tmp_path / "copied"

    def refuse_program_files(path):
        if path != str(target):
            raise GameError("protected", "cannot use")

    copied = []
    monkeypatch.setattr(app_module, "check_game_folder", refuse_program_files)
    monkeypatch.setattr(window, "copy_game", lambda src, dst: copied.append((src, dst)))
    window.ask_folder = lambda: "C:/Program Files/Game"
    window.ask_copy_target = lambda: str(target)
    window.start()
    assert copied == [("C:/Program Files/Game", str(target))]
    assert store.load_settings()["game"] == str(target)


def test_leftover_manifest_recovers_at_start(window, tmp_path, monkeypatch):
    accept_folders(monkeypatch)
    store.save_settings({"game": str(tmp_path)})
    calls = []
    monkeypatch.setattr(app_module.deploy, "restore", lambda game, data: calls.append(game) or True)
    window.start()
    assert calls == [tmp_path]


def test_window_stays_open_while_game_runs(window, monkeypatch):
    monkeypatch.setattr(play_module, "PlayWorker", StubWorker)
    window.play_tab.set_game("D:/game")
    window.play_tab.play()
    window.show()
    assert window.close() is False
    assert window.shown_errors
    StubWorker.made[-1].finished_code.emit(0)
    assert window.close() is True


def test_copy_goes_into_a_new_folder(window, tmp_path, monkeypatch):
    chosen = tmp_path / "parent"
    chosen.mkdir()
    monkeypatch.setattr(app_module.QFileDialog, "getExistingDirectory", lambda *a: str(chosen))
    assert window.ask_copy_target() == str(chosen / app_module.COPY_FOLDER)


def test_app_exits_cleanly(tmp_path):
    code = (
        "from wrmod.gui import app as a\n"
        "a.QApplication.exec = lambda *args: 0\n"
        "a.MainWindow.start = lambda self: None\n"
        "raise SystemExit(a.run_gui())\n"
    )
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "WRMOD_DATA": str(tmp_path)}
    result = subprocess.run([sys.executable, "-c", code], env=env, cwd=Path(__file__).parent.parent, timeout=30)
    assert result.returncode == 0


def test_profile_controls_locked_while_game_runs(tab, monkeypatch):
    monkeypatch.setattr(play_module, "PlayWorker", StubWorker)
    tab.play()
    assert not tab.profile_box.isEnabled()
    assert tab.profile_buttons and not any(b.isEnabled() for b in tab.profile_buttons)
    StubWorker.made[-1].finished_code.emit(0)
    assert tab.profile_box.isEnabled() and all(b.isEnabled() for b in tab.profile_buttons)


def test_game_folder_button_locked_while_game_runs(window, monkeypatch):
    monkeypatch.setattr(play_module, "PlayWorker", StubWorker)
    window.play_tab.set_game("D:/game")
    window.play_tab.play()
    assert not window.folder_button.isEnabled()
    StubWorker.made[-1].failed.emit("x")
    assert window.folder_button.isEnabled()


def test_unexpected_error_in_play_reaches_the_window(qapp, tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise KeyError("phase")

    monkeypatch.setattr(worker_module.deploy, "play", broken)
    seen = []
    worker = worker_module.PlayWorker(tmp_path, tmp_path, None, None)
    worker.failed.connect(seen.append)
    worker.run()
    assert seen and "phase" in seen[0]


def test_startup_disk_error_is_shown(window, tmp_path, monkeypatch):
    accept_folders(monkeypatch)
    store.save_settings({"game": str(tmp_path)})

    def broken(game, data):
        raise OSError("drive is read-only")

    monkeypatch.setattr(app_module.deploy, "restore", broken)
    window.start()
    assert any("read-only" in e for e in window.shown_errors)


def test_worker_reports_a_crash_exit_code(qapp, monkeypatch):
    # Windows crash codes do not fit a signed 32-bit integer.
    monkeypatch.setattr(worker_module.deploy, "play", lambda game, data, profile, options: 0xC0000005)
    worker = worker_module.PlayWorker("game", "data", None, None)
    codes, failures = [], []
    worker.finished_code.connect(codes.append, Qt.DirectConnection)
    worker.failed.connect(failures.append, Qt.DirectConnection)
    worker.run()
    assert codes == [0xC0000005] and failures == []
