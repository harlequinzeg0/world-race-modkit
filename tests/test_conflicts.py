import json

from wrmod.conflicts import find_conflicts


def add_mod(mods, mod_id, files=(), strings=None):
    folder = mods / mod_id
    (folder / "files").mkdir(parents=True)
    for path in files:
        target = folder / "files" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
    if strings is not None:
        (folder / "strings.json").write_text(json.dumps(strings))


def test_no_conflict_between_different_files(tmp_path):
    add_mod(tmp_path, "a", ["x/1.xml"])
    add_mod(tmp_path, "b", ["x/2.xml"])
    assert find_conflicts(tmp_path, ["a", "b"]) == []


def test_lower_in_list_wins_file(tmp_path):
    add_mod(tmp_path, "a", ["x/y.xml"])
    add_mod(tmp_path, "b", ["x/y.xml"])
    c = find_conflicts(tmp_path, ["a", "b"])
    assert [(x.kind, x.key, x.mods, x.winner) for x in c] == [("file", "x/y.xml", ["a", "b"], "b")]


def test_order_changes_the_winner(tmp_path):
    add_mod(tmp_path, "a", ["x/y.xml"])
    add_mod(tmp_path, "b", ["x/y.xml"])
    assert find_conflicts(tmp_path, ["b", "a"])[0].winner == "a"


def test_path_case_ignored(tmp_path):
    add_mod(tmp_path, "a", ["X/Y.XML"])
    add_mod(tmp_path, "b", ["x/y.xml"])
    assert len(find_conflicts(tmp_path, ["a", "b"])) == 1


def test_inactive_mod_is_ignored(tmp_path):
    add_mod(tmp_path, "a", ["x/y.xml"])
    add_mod(tmp_path, "b", ["x/y.xml"])
    assert find_conflicts(tmp_path, ["a"]) == []


def test_same_string_conflicts_once(tmp_path):
    add_mod(tmp_path, "a", strings={"T": "x"})
    add_mod(tmp_path, "b", strings={"T": "y"})
    c = find_conflicts(tmp_path, ["a", "b"])
    assert [(x.kind, x.key, x.winner) for x in c] == [("string", "T", "b")]


def test_string_conflict_is_per_language(tmp_path):
    add_mod(tmp_path, "a", strings={"T": {"french": "x"}})
    add_mod(tmp_path, "b", strings={"T": {"usa": "y"}})
    assert find_conflicts(tmp_path, ["a", "b"]) == []


def test_partial_language_conflict_names_the_language(tmp_path):
    add_mod(tmp_path, "a", strings={"T": "x"})
    add_mod(tmp_path, "b", strings={"T": {"usa": "y"}})
    c = find_conflicts(tmp_path, ["a", "b"])
    assert [(x.kind, x.key, x.winner) for x in c] == [("string", "T [usa]", "b")]
