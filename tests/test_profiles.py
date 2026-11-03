import pytest

from wrmod import profiles, store
from wrmod.profiles import Profile, ProfileError, prune_missing


def test_stock_always_exists(tmp_path):
    assert profiles.STOCK in profiles.list_profiles(tmp_path)
    assert profiles.load(tmp_path, profiles.STOCK).active == []


def test_stock_cannot_change(tmp_path):
    with pytest.raises(ProfileError):
        profiles.delete(tmp_path, profiles.STOCK)
    with pytest.raises(ProfileError):
        profiles.rename(tmp_path, profiles.STOCK, "x")
    with pytest.raises(ProfileError):
        profiles.save(tmp_path, Profile(profiles.STOCK, ["m1"]))


@pytest.mark.parametrize("name", ["../x", "a/b", "a\\b", "", "CON", "name.", " x ", "a:b", "x" * 41])
def test_bad_names_refused(tmp_path, name):
    with pytest.raises(ProfileError):
        profiles.create(tmp_path, name)


def test_create_and_save_round_trip(tmp_path):
    profiles.create(tmp_path, "Racing")
    profiles.save(tmp_path, Profile("Racing", ["m1", "m2"]))
    assert profiles.load(tmp_path, "Racing").active == ["m1", "m2"]
    assert profiles.list_profiles(tmp_path) == [profiles.STOCK, "Racing"]


def test_duplicate_name_refused(tmp_path):
    profiles.create(tmp_path, "Racing")
    with pytest.raises(ProfileError):
        profiles.create(tmp_path, "racing")


def write_save(root, name):
    path = profiles.save_path(root, name)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"save")


def test_rename_keeps_mods_and_save(tmp_path):
    profiles.create(tmp_path, "a")
    profiles.save(tmp_path, Profile("a", ["m1"]))
    write_save(tmp_path, "a")
    profiles.rename(tmp_path, "a", "b")
    assert profiles.load(tmp_path, "b").active == ["m1"]
    assert profiles.save_path(tmp_path, "b").read_bytes() == b"save"
    assert "a" not in profiles.list_profiles(tmp_path)


def test_rename_onto_existing_refused(tmp_path):
    profiles.create(tmp_path, "a")
    profiles.create(tmp_path, "b")
    with pytest.raises(ProfileError):
        profiles.rename(tmp_path, "a", "b")


def test_duplicate_copies_list_not_save(tmp_path):
    profiles.create(tmp_path, "a")
    profiles.save(tmp_path, Profile("a", ["m1"]))
    write_save(tmp_path, "a")
    copy = profiles.duplicate(tmp_path, "a", "b")
    assert copy.active == ["m1"]
    assert not profiles.save_path(tmp_path, "b").exists()


def test_delete_removes_profile(tmp_path):
    profiles.create(tmp_path, "a")
    profiles.delete(tmp_path, "a")
    assert profiles.list_profiles(tmp_path) == [profiles.STOCK]


def test_load_unknown_refused(tmp_path):
    with pytest.raises(ProfileError):
        profiles.load(tmp_path, "nope")


def test_removed_mod_is_pruned_and_reported():
    p = Profile("a", ["m1", "gone"])
    assert prune_missing(p, {"m1"}) == ["gone"]
    assert p.active == ["m1"]


def test_data_dir_uses_override(tmp_path, monkeypatch):
    monkeypatch.setenv("WRMOD_DATA", str(tmp_path / "data"))
    assert store.data_dir() == tmp_path / "data"
    assert store.data_dir().is_dir()


def test_settings_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("WRMOD_DATA", str(tmp_path))
    assert store.load_settings() == {}
    store.save_settings({"game": "D:/x"})
    assert store.load_settings() == {"game": "D:/x"}


def test_corrupt_settings_start_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("WRMOD_DATA", str(tmp_path))
    (tmp_path / "settings.json").write_bytes(b"{nope")
    assert store.load_settings() == {}
