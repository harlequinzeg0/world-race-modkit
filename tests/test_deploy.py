import json
from pathlib import Path

import pytest

from wrmod import deploy as dep
from wrmod.deploy import DLL_NAME, SESSION_VARIABLE, DeployError, ignored_files, launch, play, prepare, restore
from wrmod.gameinfo import RETAIL_SHA256, STOCK_EXE
from wrmod.merge import SESSION_FILE
from wrmod.options import from_settings
from wrmod.profiles import Profile, save_path

SAVE_REL = "saves/HOTWHEEL/PROGRESS"
DLL = b"the base mod"


class Fake:
    def __init__(self, root):
        self.game = root / "game"
        self.data = root / "data"
        (self.game / "saves/HOTWHEEL").mkdir(parents=True)
        (self.game / SAVE_REL).write_bytes(b"stock")
        (self.game / STOCK_EXE).write_bytes(b"exe")
        (self.data / "profiles/p").mkdir(parents=True)
        self.profile = Profile("p", [])
        self.dll = root / "bin" / DLL_NAME
        self.dll.parent.mkdir()
        self.dll.write_bytes(DLL)

    def add_mod(self, mod_id, files=None, cars=None):
        folder = self.data / "mods" / mod_id
        folder.mkdir(parents=True)
        info = {
            "format_version": 1, "id": mod_id, "name": mod_id, "version": "1", "author": "a",
            "description": "d", "kind": "tweak", "requires_game": RETAIL_SHA256,
        }
        (folder / "mod.json").write_text(json.dumps(info))
        if cars is not None:
            (folder / "cars.json").write_text(json.dumps(cars))
        for path, data in (files or {}).items():
            target = folder / "files" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.profile.active.append(mod_id)

    def run(self, launcher=lambda exe, game, session: 0):
        return play(self.game, self.data, self.profile, launcher=launcher)

    @property
    def profile_save(self):
        return save_path(self.data / "profiles", "p")

    @property
    def manifest(self):
        return self.data / "deploy" / "manifest.json"


def snapshot(game):
    return {p.relative_to(game).as_posix(): p.read_bytes() for p in game.rglob("*") if p.is_file()}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setattr(dep, "game_running", lambda: False)
    made = Fake(tmp_path)
    monkeypatch.setattr(dep, "DLL_SOURCE", made.dll)
    return made


def test_game_folder_gets_only_the_dll(fake):
    fake.add_mod("a", {"x/y.xml": b"mod", "cars/new/cache/new.rom": b"rom"})
    before = snapshot(fake.game)
    seen = {}

    def run(exe, game, session):
        seen.update(snapshot(game))
        return 0

    fake.run(run)
    assert seen == {**before, DLL_NAME: DLL}


def test_folder_is_as_found_after_play(fake):
    fake.add_mod("a", {"x/y.xml": b"mod"})
    before = snapshot(fake.game)
    fake.run()
    assert snapshot(fake.game) == before
    assert not fake.manifest.exists()


def test_launcher_gets_the_stock_exe_and_the_session(fake):
    fake.add_mod("a", {"x.xml": b"m"})
    seen = {}

    def run(exe, game, session):
        seen["exe"] = Path(exe).name
        seen["session"] = json.loads(Path(session).read_text(encoding="utf-8"))
        return 0

    fake.run(run)
    assert seen["exe"] == STOCK_EXE
    assert seen["session"]["roots"][1].endswith("mods/a/files")


def test_play_passes_options_to_the_session(fake):
    seen = {}

    def run(exe, game, session):
        seen["session"] = json.loads(Path(session).read_text(encoding="utf-8"))
        return 0

    play(fake.game, fake.data, fake.profile, launcher=run, options=from_settings({"borderless": False}))
    assert seen["session"]["display"] == {"borderless": False}
    assert seen["session"]["controller"]["enabled"] is True


def test_stock_play_ignores_options(fake):
    seen = []
    play(fake.game, fake.data, Profile("Stock", []), launcher=lambda exe, game, session: seen.append(session) or 0, options=from_settings({}))
    assert seen == [None]


def test_stock_exe_never_changes(fake):
    fake.add_mod("a", {"x.xml": b"m"})
    fake.run(lambda exe, game, session: Path(exe).read_bytes() == b"exe" and 0)
    assert (fake.game / STOCK_EXE).read_bytes() == b"exe"


def test_foreign_dinput8_stops_play_and_stays(fake):
    (fake.game / DLL_NAME).write_bytes(b"someone else's")
    fake.add_mod("a", {"x.xml": b"m"})
    ran = []
    with pytest.raises(DeployError, match=DLL_NAME):
        fake.run(lambda exe, game, session: ran.append(1) or 0)
    assert not ran
    assert (fake.game / DLL_NAME).read_bytes() == b"someone else's"
    assert not fake.manifest.exists()


def test_leftover_copy_of_our_dll_is_taken_back(fake):
    (fake.game / DLL_NAME).write_bytes(DLL)
    fake.add_mod("a", {"x.xml": b"m"})
    fake.run()
    assert not (fake.game / DLL_NAME).exists()


def test_recovery_removes_dll_after_crash(fake):
    fake.add_mod("a", {"x.xml": b"m"})
    prepare(fake.game, fake.data, fake.profile)
    assert (fake.game / DLL_NAME).exists()
    assert restore(fake.game, fake.data) is True
    assert not (fake.game / DLL_NAME).exists()
    assert not fake.manifest.exists()
    assert restore(fake.game, fake.data) is False


def test_recovery_leaves_a_dll_that_changed(fake):
    fake.add_mod("a", {"x.xml": b"m"})
    prepare(fake.game, fake.data, fake.profile)
    (fake.game / DLL_NAME).write_bytes(b"replaced by another tool")
    assert restore(fake.game, fake.data) is True
    assert (fake.game / DLL_NAME).read_bytes() == b"replaced by another tool"


def test_recovery_refuses_another_game_folder(fake, tmp_path):
    fake.add_mod("a", {"x.xml": b"m"})
    prepare(fake.game, fake.data, fake.profile)
    other = tmp_path / "other_copy"
    other.mkdir()
    (other / DLL_NAME).write_bytes(b"other copy's own file")
    with pytest.raises(DeployError, match="pending"):
        restore(other, fake.data)
    assert (other / DLL_NAME).read_bytes() == b"other copy's own file"
    assert fake.manifest.exists()
    assert restore(fake.game, fake.data) is True


def test_locked_dll_keeps_manifest_for_retry(fake, monkeypatch):
    fake.add_mod("a", {"x.xml": b"m"})
    prepare(fake.game, fake.data, fake.profile)
    real = Path.unlink

    def locked(self, *args, **kwargs):
        if self.name == DLL_NAME:
            raise PermissionError("in use")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(dep, "RETRY_DELAYS", ())
    monkeypatch.setattr(Path, "unlink", locked)
    with pytest.raises(DeployError, match=DLL_NAME):
        restore(fake.game, fake.data)
    monkeypatch.setattr(Path, "unlink", real)
    assert fake.manifest.exists()
    assert restore(fake.game, fake.data) is True


def test_failed_dll_copy_leaves_nothing(fake, monkeypatch):
    fake.add_mod("a", {"x.xml": b"m"})
    fake.dll.unlink()
    before = snapshot(fake.game)
    with pytest.raises(DeployError):
        fake.run()
    assert snapshot(fake.game) == before
    assert not fake.manifest.exists()


def test_stock_profile_copies_nothing_and_sets_no_session(fake):
    before = snapshot(fake.game)
    seen = []

    def run(exe, game, session):
        seen.append((Path(exe).name, session, snapshot(game)))
        return 0

    play(fake.game, fake.data, Profile("Stock", []), launcher=run)
    assert seen == [(STOCK_EXE, None, before)]
    assert not fake.manifest.exists()


def test_empty_profile_still_has_its_own_save(fake):
    seen = []
    fake.run(lambda exe, game, session: seen.append(session) or 0)
    assert seen[0] is not None


def test_launch_sets_session_variable(fake, monkeypatch):
    seen = {}

    class Process:
        def __init__(self, command, cwd, env):
            seen.update(command=command, cwd=cwd, env=env)

        def wait(self):
            return 7

    monkeypatch.setattr(dep.subprocess, "Popen", Process)
    assert launch(fake.game / STOCK_EXE, fake.game, Path("D:/s/session.json")) == 7
    assert seen["env"][SESSION_VARIABLE] == str(Path("D:/s/session.json"))
    assert seen["command"][1:] == ["run_via_launcher"]
    assert seen["cwd"] == fake.game


def test_launch_without_a_session_clears_the_variable(fake, monkeypatch):
    seen = {}

    class Process:
        def __init__(self, command, cwd, env):
            seen.update(env=env)

        def wait(self):
            return 0

    monkeypatch.setattr(dep.subprocess, "Popen", Process)
    monkeypatch.setenv(SESSION_VARIABLE, "left over")
    launch(fake.game / STOCK_EXE, fake.game)
    assert SESSION_VARIABLE not in seen["env"]


def test_save_stays_in_profile_folder(fake):
    fake.add_mod("a", {"x.xml": b"m"})

    def run(exe, game, session):
        folder = Path(json.loads(Path(session).read_text(encoding="utf-8"))["save_dir"])
        target = folder / "HOTWHEEL/PROGRESS"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"modded progress")
        return 0

    fake.run(run)
    assert (fake.game / SAVE_REL).read_bytes() == b"stock"
    assert fake.profile_save.read_bytes() == b"modded progress"


def test_old_profile_save_moves_to_the_new_place(fake):
    old = fake.data / "profiles/p/PROGRESS"
    old.write_bytes(b"my old progress")
    fake.run()
    assert not old.exists()
    assert fake.profile_save.read_bytes() == b"my old progress"


def test_old_profile_save_never_replaces_a_new_one(fake):
    old = fake.data / "profiles/p/PROGRESS"
    old.write_bytes(b"old")
    fake.profile_save.parent.mkdir(parents=True)
    fake.profile_save.write_bytes(b"new")
    fake.run()
    assert fake.profile_save.read_bytes() == b"new"
    assert old.read_bytes() == b"old"


def test_mod_files_in_movie_or_sound_folders_warn(fake):
    fake.add_mod("a", {"movies/cars/x.bik": b"m", "Sound/y.fsb": b"m", "misc/z.xml": b"m"})
    assert ignored_files(fake.data / "mods", ["a"]) == ["Sound/y.fsb", "movies/cars/x.bik"]


def test_mod_cannot_touch_saves(fake):
    fake.add_mod("a", {"saves/HOTWHEEL/other": b"mod"})
    with pytest.raises(DeployError, match="saves"):
        fake.run()


def test_missing_mod_stops_before_any_change(fake):
    fake.profile.active.append("gone")
    before = snapshot(fake.game)
    with pytest.raises(DeployError, match="gone"):
        fake.run()
    assert snapshot(fake.game) == before


def test_merge_problem_stops_before_any_change(fake):
    fake.add_mod("a", cars=[{"internal_name": "Bad Name"}])
    before = snapshot(fake.game)
    with pytest.raises(DeployError, match="Bad Name"):
        fake.run()
    assert snapshot(fake.game) == before
    assert not fake.manifest.exists()


def test_game_crash_exit_code_still_restores(fake):
    fake.add_mod("a", {"x.xml": b"m"})
    before = snapshot(fake.game)
    assert fake.run(lambda exe, game, session: -1073741819) == -1073741819
    assert snapshot(fake.game) == before


def test_launch_failure_still_restores(fake):
    fake.add_mod("a", {"x.xml": b"m"})
    before = snapshot(fake.game)

    def boom(exe, game, session):
        raise OSError("cannot start")

    with pytest.raises(DeployError, match="cannot start"):
        fake.run(boom)
    assert snapshot(fake.game) == before


def test_play_refused_while_game_runs(fake, monkeypatch):
    fake.add_mod("a", {"x.xml": b"m"})
    monkeypatch.setattr(dep, "game_running", lambda: True)
    before = snapshot(fake.game)
    with pytest.raises(DeployError, match="already running"):
        fake.run()
    assert snapshot(fake.game) == before


def test_stock_play_refused_while_game_runs(fake, monkeypatch):
    monkeypatch.setattr(dep, "game_running", lambda: True)
    with pytest.raises(DeployError, match="already running"):
        play(fake.game, fake.data, Profile("Stock", []), launcher=lambda *a: 0)


def test_recovery_waits_while_game_runs(fake, monkeypatch):
    fake.add_mod("a", {"x.xml": b"m"})
    prepare(fake.game, fake.data, fake.profile)
    monkeypatch.setattr(dep, "game_running", lambda: True)
    with pytest.raises(DeployError, match="already running"):
        restore(fake.game, fake.data)
    assert (fake.game / DLL_NAME).exists()


def test_play_recovers_a_leftover_first(fake):
    fake.add_mod("a", {"x.xml": b"m"})
    prepare(fake.game, fake.data, fake.profile)
    fake.run()
    assert not (fake.game / DLL_NAME).exists()
    assert not fake.manifest.exists()


def test_session_file_is_written_for_the_game(fake):
    fake.add_mod("a", {"x.xml": b"m"})
    path = prepare(fake.game, fake.data, fake.profile)
    assert path.name == SESSION_FILE and path.is_file()
    restore(fake.game, fake.data)


def test_interrupted_dll_copy_leaves_nothing(fake, monkeypatch):
    fake.add_mod("a", {"x.xml": b"m"})
    before = snapshot(fake.game)

    def partial(source, target):
        Path(target).write_bytes(b"half a dll")
        raise OSError("disk full")

    monkeypatch.setattr(dep.shutil, "copyfile", partial)
    with pytest.raises(DeployError, match="disk full"):
        fake.run()
    assert snapshot(fake.game) == before
    assert not fake.manifest.exists()


def test_recovery_removes_a_partial_copy(fake):
    fake.add_mod("a", {"x.xml": b"m"})
    prepare(fake.game, fake.data, fake.profile)
    (fake.game / DLL_NAME).unlink()
    (fake.game / dep.DLL_TEMP).write_bytes(b"half a dll")
    assert restore(fake.game, fake.data) is True
    assert not (fake.game / dep.DLL_TEMP).exists()
