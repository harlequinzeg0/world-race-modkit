import io
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image

from wrmod import merge
from wrmod.bed import Bed, Box, read_bed, write_bed
from wrmod.bog import HEADER_SIZE, dds_to_bog, parse_header
from wrmod.gameinfo import RETAIL_SHA256, STOCK_EXE
from wrmod.icons import HIGHLIGHT_SHEET, ICON_SHEET, TEAM_LOGO_SHEET, TEAM_NAME_SHEET, dxt5_dds
from wrmod.merge import MergeError, build_session
from wrmod.modpack import OVERHAUL_TAG
from wrmod.physics import read_physics
from test_physics import OVERHAUL as OVERHAUL_PARAMS, STOCK as STOCK_PARAMS
from wrmod.msg import LANGUAGES, STRING_COUNT, msg_path, read_msg, write_msg
from wrmod.options import from_settings
from wrmod.rom import Material, Rom, read_rom, write_rom

TEAMS = ("dune_rats", "street_breed", "road_beasts", "wave_rippers", "scorchers")
LOGOS = ("dune_ratz", "street_breed", "RoadBeasts", "WaveRippers", "Scorchers")
STOCK_ORDER = [f"{team}_{i}" for team in TEAMS for i in range(7)]
STOCK_ORDER[15] = "ballistic"


def stock_car(index, name):
    team = TEAMS[index // 7]
    return (
        f'<CAR internal_name="{name}" team_name="{team}" locked="true" descriptive_name="STOCK_{index}" '
        f'icon_box="{name}" speed="2" grip="5" boost="3" accel="6" sample_bank="BANK_{index}" ai_car="true" '
        f'team_leader="false"/>'
    )


def stock_rep(index, name):
    logo = LOGOS[index // 7]
    return (
        f'   <car_rep ID="{name}" TeamLogo="{logo}" Movie="movies/cars/{name}" SilhouetteName="{name}_hlight" CharacterName="DRIVER_{index}" CarName="CAR_{index}">\r\n'
        f'      <BlokeHead><cStrategySprite ID="HEAD" Texture="frontend/head_{name}"/></BlokeHead>\r\n'
        f'      <MovieFirstFrame><cStrategySprite Texture="frontend/{name}_movie"/></MovieFirstFrame>\r\n'
        f"   </car_rep>\r\n"
    )


def screen(sets):
    reps = "".join(stock_rep(i, name) for i, name in enumerate(STOCK_ORDER))
    groups = "".join(f"<cars>\r\n{reps}</cars>\r\n" for _ in range(sets))
    return (
        '<Screen><cFrontendObjectScrollableSelectorCar ID="C" NumObjectsInScrollList="7" MaxCarIcons="35"/>\r\n'
        '<cFrontendObjectScrollableSelectorTeam ID="T" NumObjectsInScrollList="5"/>\r\n'
        f"{groups}</Screen>"
    ).encode("latin1")


def stock_sheets():
    sheets = {}
    for sheet in (ICON_SHEET, HIGHLIGHT_SHEET, TEAM_LOGO_SHEET, TEAM_NAME_SHEET):
        boxes = [Box.rectangle("ballistic", 0, 0, 96, 48, 512, 512)]
        sheets[f"{sheet}.bog"] = dds_to_bog(dxt5_dds(512, 512, bytes(128 * 128 * 16)), None)
        sheets[f"{sheet}.bed"] = write_bed(Bed("s.tga", 512, 512, boxes))
    return sheets


def wheel_model():
    record = b"generic_wheel_high_0".ljust(0x8C, b"\0")
    return write_rom(Rom(materials=[Material(record)]))


FILES = {
    "cars/generic_models/cache/generic_wheel_med.rom": wheel_model(),
    "cars/generic_models/cache/generic_wheel_low.rom": wheel_model(),
    "misc/cache/car_info.xml": (
        "<Cars>\r\n   " + "\r\n   ".join(stock_car(i, n) for i, n in enumerate(STOCK_ORDER)) + "\r\n</Cars>"
    ).encode("latin1"),
    "frontend/car_select_screen.xml": screen(1),
    "frontend/multi_player_car_select.xml": screen(2),
    "misc/cache/flash.bed": b"\x01\x01flash.tga\0\0\0flash_1\0flash_2\0",
    "cars/ballistic/cache/ballistic.params": OVERHAUL_PARAMS.encode("latin1"),
    **stock_sheets(),
    "cars/effects/cache/stunt.xml": b"<plain/>",
    "cars/effects/cache/stunt_road_beasts.xml": b"<beasts/>",
    "cars/effects/cache/landing_road_beasts.xml": b"<landing/>",
    "cars/effects/cache/stunt_scorchers.xml": b"<scorchers/>",
    **{msg_path(language): write_msg(["stock"] * STRING_COUNT) for language in LANGUAGES},
}


class FakeArchive:
    def __init__(self, game):
        pass

    def paths(self):
        return list(FILES)

    def has(self, path):
        return path.lower() in {key.lower() for key in FILES}

    def read(self, path):
        return FILES[path]


@pytest.fixture
def stock(tmp_path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    (game / STOCK_EXE).write_bytes(b"exe")
    monkeypatch.setattr(merge, "game_files", FakeArchive)
    monkeypatch.setattr(merge, "load_string_ids", lambda exe: {"X": 0})
    monkeypatch.setattr(merge, "is_overhaul", lambda game: False)
    monkeypatch.setattr(merge, "stock_physics", lambda: {"ballistic": read_physics(STOCK_PARAMS)})
    return game


def make_mod(mods_dir, mod_id, cars=None, teams=None, files=(), strings=None, blobs=None, tagged=False):
    folder = mods_dir / mod_id
    folder.mkdir(parents=True)
    if tagged:
        (folder / OVERHAUL_TAG).write_bytes(b"")
    info = {
        "format_version": 1, "id": mod_id, "name": mod_id, "version": "1", "author": "a",
        "description": "d", "kind": "car", "requires_game": RETAIL_SHA256,
    }
    (folder / "mod.json").write_text(json.dumps(info))
    if cars is not None:
        (folder / "cars.json").write_text(json.dumps(cars))
    if teams is not None:
        (folder / "teams.json").write_text(json.dumps(teams))
    if strings:
        (folder / "strings.json").write_text(json.dumps(strings))
    for rel in files:
        target = folder / "files" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"data")
    for rel, data in (blobs or {}).items():
        target = folder / "files" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def car(name, team="road_beasts", **changes):
    return {"internal_name": name, "team": team, "display_name": name.upper(), "based_on": "ballistic", **changes}


def car_mod(name, team="road_beasts", **changes):
    return {"cars": [car(name, team, **changes)], "files": [f"cars/{name}/cache/{name}.pts"]}


def team_mod(team_id="neon_riders", cars=("n1", "n2", "n3")):
    entries = [car(name, team_id, ai_car=True) for name in cars]
    team = {
        "id": team_id, "display_name": "Neon Riders", "logo": {"texture": "misc/cache/flash", "box": "flash_1"},
        "leader": cars[0], "base_team": "road_beasts",
    }
    return {"cars": entries, "teams": [team], "files": [f"cars/{name}/cache/{name}.pts" for name in cars]}


def build(stock, mods, tmp_path, options=None):
    mods_dir = tmp_path / "mods"
    active = []
    for number, mod in enumerate(mods):
        mod_id = f"mod{number}"
        make_mod(mods_dir, mod_id, **mod)
        active.append(mod_id)
    path = build_session(stock, mods_dir, active, tmp_path / "save", tmp_path / "session", options)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def generated(tmp_path, rel):
    return (tmp_path / "session/generated" / rel).read_bytes().decode("latin1")


def internal_names(tmp_path):
    return re.findall(r'<CAR internal_name="(\w+)"', generated(tmp_path, "misc/cache/car_info.xml"))


def added_element(tmp_path, name):
    return re.search(rf'<CAR internal_name="{name}"[^>]*/>', generated(tmp_path, "misc/cache/car_info.xml")).group(0)


def test_added_car_goes_after_stock_cars(stock, tmp_path):
    session = build(stock, [car_mod("neon")], tmp_path)
    assert internal_names(tmp_path)[:35] == STOCK_ORDER and internal_names(tmp_path)[35] == "neon"
    assert session["teams"][2]["slots"][-1] == 35


def test_session_lists_the_added_car(stock, tmp_path):
    session = build(stock, [car_mod("neon")], tmp_path)
    assert session["cars"] == [{"index": 35, "team": 2, "name": "neon", "based_on": "ballistic"}]


def test_added_car_is_unlocked(stock, tmp_path):
    build(stock, [car_mod("neon")], tmp_path)
    assert 'locked="false"' in added_element(tmp_path, "neon")


def test_attributes_come_from_based_on(stock, tmp_path):
    build(stock, [car_mod("neon")], tmp_path)
    element = added_element(tmp_path, "neon")
    assert 'sample_bank="BANK_15"' in element and 'grip="5"' in element


def test_stats_can_be_changed(stock, tmp_path):
    build(stock, [car_mod("neon", speed=9, ai_car=True)], tmp_path)
    element = added_element(tmp_path, "neon")
    assert 'speed="9"' in element and 'ai_car="true"' in element


def test_added_car_is_not_ai_unless_asked(stock, tmp_path):
    build(stock, [car_mod("neon")], tmp_path)
    assert 'ai_car="false"' in added_element(tmp_path, "neon")


def test_every_screen_list_gets_the_car(stock, tmp_path):
    build(stock, [car_mod("neon")], tmp_path)
    assert generated(tmp_path, "frontend/car_select_screen.xml").count('<car_rep ID="neon"') == 1
    assert generated(tmp_path, "frontend/multi_player_car_select.xml").count('<car_rep ID="neon"') == 2


def test_a_new_car_shows_its_still_picture_and_no_clip(stock, tmp_path):
    build(stock, [car_mod("neon")], tmp_path)
    text = generated(tmp_path, "frontend/car_select_screen.xml")
    rep = re.search(r'<car_rep ID="neon".*?</car_rep>', text, re.S).group(0)
    assert 'Movie=""' in rep
    assert "frontend/neon_movie" in rep


def test_stock_cars_keep_their_clips(stock, tmp_path):
    build(stock, [car_mod("neon")], tmp_path)
    text = generated(tmp_path, "frontend/car_select_screen.xml")
    assert text.count('Movie=""') == 1
    assert 'Movie="movies/cars/ballistic"' in text


def test_a_screen_with_no_still_keeps_the_base_clip():
    # The multiplayer screen has no MovieFirstFrame, so an empty clip would leave its panel blank.
    entry = '<car_rep ID="ballistic" TeamLogo="x" Movie="movies/cars/road/ballis" CarName="C"><BlokeHead/></car_rep>'
    car = {"based_on": "ballistic", "internal_name": "neon"}
    assert 'Movie="movies/cars/road/ballis"' in merge._screen_entry(entry, car, "logo", set(), set())


GARAGE_COLOURS = {team: (40 * number, 10, 10) for number, team in enumerate(TEAMS)}
RED = (255, 0, 0)


def picture_bog(image):
    out = io.BytesIO()
    image.save(out, format="PNG")
    return dds_to_bog(dxt5_dds(4, 4, bytes(16)), None)[:HEADER_SIZE] + out.getvalue()


def picture_of(bog):
    return Image.open(io.BytesIO(bog[HEADER_SIZE:])).convert("RGB")


@pytest.fixture
def overhaul(stock, monkeypatch):
    """Like NitroXFueled: each car's first frame is its team's garage, and its clip is a render."""
    text = FILES["frontend/car_select_screen.xml"].decode("latin1")
    for index, name in enumerate(STOCK_ORDER):
        text = text.replace(f'Texture="frontend/{name}_movie"', f'Texture="frontend/garage/{TEAMS[index // 7]}"')
    monkeypatch.setitem(FILES, "frontend/car_select_screen.xml", text.encode("latin1"))
    for team, colour in GARAGE_COLOURS.items():
        monkeypatch.setitem(FILES, f"frontend/garage/{team}.bog", picture_bog(Image.new("RGB", (200, 100), colour)))
    return stock


def red_still():
    return {"frontend/neon_movie.bog": picture_bog(Image.new("RGB", (256, 128), RED))}


def test_on_an_overhaul_an_added_car_shows_its_still_in_its_team_garage(overhaul, tmp_path):
    build(overhaul, [{**car_mod("neon"), "blobs": red_still()}], tmp_path)
    rep = neon_rep(tmp_path)
    assert 'Texture="frontend/neon_garage"' in rep and 'Movie=""' in rep
    garage = picture_of((tmp_path / "session/generated/frontend/neon_garage.bog").read_bytes())
    assert garage.size == (200, 100)
    assert garage.getpixel((5, 5)) == GARAGE_COLOURS["road_beasts"]
    # The overhaul's renders park the car at the front right.
    assert garage.getpixel((147, 68)) == RED


def test_on_an_overhaul_an_added_team_uses_its_base_team_garage(overhaul, tmp_path):
    mod = team_mod(cars=("neon",))
    build(overhaul, [{**mod, "blobs": red_still()}], tmp_path)
    garage = picture_of((tmp_path / "session/generated/frontend/neon_garage.bog").read_bytes())
    assert garage.getpixel((5, 5)) == GARAGE_COLOURS["road_beasts"]


def test_on_an_overhaul_a_car_with_no_still_keeps_the_plain_garage(overhaul, tmp_path):
    build(overhaul, [car_mod("neon")], tmp_path)
    assert 'Texture="frontend/garage/road_beasts"' in neon_rep(tmp_path)
    assert not (tmp_path / "session/generated/frontend/neon_garage.bog").exists()


def test_team_logos_follow_names_when_car_info_is_reordered(stock, tmp_path, monkeypatch):
    # NitroXFueled lists wave_rippers first in car_info.xml, and keeps the stock order on screen.
    order = STOCK_ORDER[21:28] + STOCK_ORDER[:21] + STOCK_ORDER[28:]
    stock_index = {name: index for index, name in enumerate(STOCK_ORDER)}
    text = "<Cars>\r\n   " + "\r\n   ".join(stock_car(stock_index[n], n) for n in order) + "\r\n</Cars>"
    monkeypatch.setitem(FILES, "misc/cache/car_info.xml", text.encode("latin1"))
    build(stock, [car_mod("neon")], tmp_path)
    assert 'TeamLogo="RoadBeasts"' in neon_rep(tmp_path)


CLIP = {"nmovies/cars/neon.bik": b"BIKi"}


def test_on_an_overhaul_a_car_with_its_own_clip_plays_it(overhaul, tmp_path):
    build(overhaul, [{**car_mod("neon"), "blobs": {**red_still(), **CLIP}}], tmp_path)
    assert 'Movie="movies/cars/neon"' in neon_rep(tmp_path)
    assert 'Texture="frontend/neon_garage"' in neon_rep(tmp_path)
    assert 'Movie="movies/cars/neon"' in neon_rep(tmp_path, "frontend/multi_player_car_select.xml")


def test_on_an_overhaul_a_clip_needs_no_still(overhaul, tmp_path):
    build(overhaul, [{**car_mod("neon"), "blobs": CLIP}], tmp_path)
    assert 'Movie="movies/cars/neon"' in neon_rep(tmp_path)
    assert 'Texture="frontend/garage/road_beasts"' in neon_rep(tmp_path)


def test_stock_keeps_the_still_even_with_a_clip(stock, tmp_path):
    build(stock, [{**car_mod("neon"), "blobs": {**red_still(), **CLIP}}], tmp_path)
    assert 'Movie=""' in neon_rep(tmp_path)


def test_a_stock_screen_makes_no_garage(stock, tmp_path):
    build(stock, [{**car_mod("neon"), "blobs": red_still()}], tmp_path)
    assert "frontend/neon_movie" in neon_rep(tmp_path)
    assert not (tmp_path / "session/generated/frontend/neon_garage.bog").exists()


def test_screen_entry_uses_the_new_name_and_movie(stock, tmp_path):
    session = build(stock, [car_mod("neon")], tmp_path)
    text = generated(tmp_path, "frontend/car_select_screen.xml")
    rep = re.search(r'<car_rep ID="neon".*?</car_rep>', text, re.S).group(0)
    assert 'CarName="WRSE_CAR_NEON"' in rep and "frontend/neon_movie" in rep and 'CharacterName="DRIVER_15"' in rep
    assert session["text"] == {"WRSE_CAR_NEON": 574}


def test_screen_counts_grow_with_the_grid(stock, tmp_path):
    build(stock, [team_mod(cars=[f"n{i}" for i in range(9)])], tmp_path)
    for rel in merge.SCREENS:
        text = generated(tmp_path, rel)
        assert 'MaxCarIcons="54"' in text
        assert re.search(r'SelectorCar [^>]*NumObjectsInScrollList="9"', text)
        assert re.search(r'SelectorTeam [^>]*NumObjectsInScrollList="6"', text)
        ET.fromstring(text)


def test_car_on_a_stock_team_takes_that_teams_logo(stock, tmp_path):
    build(stock, [car_mod("neon", team="scorchers")], tmp_path)
    rep = re.search(r'<car_rep ID="neon"[^>]*>', generated(tmp_path, "frontend/car_select_screen.xml")).group(0)
    assert 'TeamLogo="Scorchers"' in rep


def test_display_name_reaches_every_language(stock, tmp_path):
    build(stock, [car_mod("neon")], tmp_path)
    for language in LANGUAGES:
        data = (tmp_path / "session/generated" / msg_path(language)).read_bytes()
        strings = read_msg(data)
        assert strings[574] == "NEON" and strings[0] == "stock"


def test_stock_text_edits_still_apply(stock, tmp_path):
    build(stock, [{"strings": {"X": "changed"}}], tmp_path)
    data = (tmp_path / "session/generated" / msg_path("usa")).read_bytes()
    assert read_msg(data)[0] == "changed"


def test_later_mod_wins_stock_text(stock, tmp_path):
    build(stock, [{"strings": {"X": "first"}}, {"strings": {"X": "second"}}], tmp_path)
    assert read_msg((tmp_path / "session/generated" / msg_path("usa")).read_bytes())[0] == "second"


def test_unknown_text_id_refused(stock, tmp_path):
    with pytest.raises(MergeError, match="NOPE"):
        build(stock, [{"strings": {"NOPE": "x"}}], tmp_path)


def test_new_team_follows_the_stock_teams(stock, tmp_path):
    session = build(stock, [team_mod()], tmp_path)
    team = session["teams"][5]
    assert team["id"] == "neon_riders" and team["slots"] == [35, 36, 37] and team["base_team"] == 2
    assert team["logo"] == {"texture": "misc/cache/flash", "box": "flash_1"}


def test_stock_teams_keep_their_order_and_no_logo(stock, tmp_path):
    session = build(stock, [team_mod()], tmp_path)
    assert [team["id"] for team in session["teams"][:5]] == list(TEAMS)
    assert session["teams"][0]["slots"] == list(range(7)) and session["teams"][0]["logo"] is None


def test_leader_is_marked(stock, tmp_path):
    build(stock, [team_mod()], tmp_path)
    assert 'team_leader="true"' in added_element(tmp_path, "n1")
    assert 'team_leader="false"' in added_element(tmp_path, "n2")


def test_cars_can_join_a_team_from_another_mod(stock, tmp_path):
    session = build(stock, [team_mod(), car_mod("extra", team="neon_riders")], tmp_path)
    assert session["teams"][5]["slots"] == [35, 36, 37, 38]


def test_unknown_team_refused(stock, tmp_path):
    with pytest.raises(MergeError, match="ghosts"):
        build(stock, [car_mod("neon", team="ghosts")], tmp_path)


def test_team_with_no_ai_car_refused(stock, tmp_path):
    mod = team_mod()
    for entry in mod["cars"]:
        entry["ai_car"] = False
    with pytest.raises(MergeError, match="neon_riders"):
        build(stock, [mod], tmp_path)


def test_team_with_no_cars_refused(stock, tmp_path):
    mod = team_mod()
    mod["cars"] = []
    with pytest.raises(MergeError, match="neon_riders"):
        build(stock, [mod], tmp_path)


def test_leader_must_be_on_the_team(stock, tmp_path):
    mod = team_mod()
    mod["teams"][0]["leader"] = "ballistic"
    with pytest.raises(MergeError, match="leader"):
        build(stock, [mod], tmp_path)


def test_team_id_cannot_repeat(stock, tmp_path):
    mod = team_mod()
    mod["teams"][0]["id"] = "scorchers"
    with pytest.raises(MergeError, match="scorchers"):
        build(stock, [mod], tmp_path)


def test_base_team_must_be_stock(stock, tmp_path):
    mod = team_mod()
    mod["teams"][0]["base_team"] = "ghosts"
    with pytest.raises(MergeError, match="ghosts"):
        build(stock, [mod], tmp_path)


def test_logo_box_must_exist(stock, tmp_path):
    mod = team_mod()
    mod["teams"][0]["logo"]["box"] = "flash_9"
    with pytest.raises(MergeError, match="flash_9"):
        build(stock, [mod], tmp_path)


def test_logo_texture_must_exist(stock, tmp_path):
    mod = team_mod()
    mod["teams"][0]["logo"]["texture"] = "misc/cache/ghost"
    with pytest.raises(MergeError, match="ghost"):
        build(stock, [mod], tmp_path)


def test_duplicate_car_name_refused(stock, tmp_path):
    with pytest.raises(MergeError, match="neon"):
        build(stock, [car_mod("neon"), car_mod("neon")], tmp_path)


def test_stock_car_name_refused(stock, tmp_path):
    with pytest.raises(MergeError, match="ballistic"):
        build(stock, [car_mod("ballistic")], tmp_path)


def test_unknown_based_on_refused(stock, tmp_path):
    with pytest.raises(MergeError, match="ghost"):
        build(stock, [car_mod("neon", based_on="ghost")], tmp_path)


def test_car_needs_its_own_files(stock, tmp_path):
    mod = car_mod("neon")
    mod["files"] = []
    with pytest.raises(MergeError, match="neon"):
        build(stock, [mod], tmp_path)


def test_team_too_long_refused(stock, tmp_path):
    with pytest.raises(MergeError, match="road_beasts"):
        build(stock, [car_mod(f"c{i}") for i in range(10)], tmp_path)


def test_too_many_teams_refused(stock, tmp_path):
    with pytest.raises(MergeError, match="teams"):
        build(stock, [team_mod(f"team_{i}", [f"t{i}"]) for i in range(12)], tmp_path)


def test_missing_mod_refused(stock, tmp_path):
    with pytest.raises(MergeError, match="ghost"):
        build_session(stock, tmp_path / "mods", ["ghost"], tmp_path / "save", tmp_path / "session")


def test_roots_put_generated_first_and_lowest_mod_next(stock, tmp_path):
    session = build(stock, [{"files": ["a.txt"]}, {"files": ["b.txt"]}], tmp_path)
    assert session["roots"] == [
        (tmp_path / "session/generated").resolve().as_posix(),
        (tmp_path / "mods/mod1/files").resolve().as_posix(),
        (tmp_path / "mods/mod0/files").resolve().as_posix(),
    ]


def test_mod_with_no_files_gets_no_root(stock, tmp_path):
    session = build(stock, [{"strings": {"X": "y"}}], tmp_path)
    assert len(session["roots"]) == 1


def test_session_holds_paths_and_format(stock, tmp_path):
    session = build(stock, [{"files": ["a.txt"]}], tmp_path)
    assert session["format"] == 1
    assert session["save_dir"] == (tmp_path / "save").resolve().as_posix()
    assert session["log_path"] == (tmp_path / "session/wrse.log").resolve().as_posix()


def test_no_added_content_writes_no_car_files(stock, tmp_path):
    session = build(stock, [{"files": ["a.txt"]}], tmp_path)
    assert session["cars"] == [] and session["teams"] == [] and session["text"] == {}
    assert not any(p.is_file() for p in (tmp_path / "session/generated").rglob("*"))


def test_mod_copy_of_a_list_file_is_the_base(stock, tmp_path):
    mods_dir = tmp_path / "mods"
    changed = FILES["misc/cache/car_info.xml"].replace(b'sample_bank="BANK_15"', b'sample_bank="MINE"')
    make_mod(mods_dir, "tweak", files=[])
    target = mods_dir / "tweak/files/misc/cache/car_info.xml"
    target.parent.mkdir(parents=True)
    target.write_bytes(changed)
    make_mod(mods_dir, "new", **car_mod("neon"))
    build_session(stock, mods_dir, ["tweak", "new"], tmp_path / "save", tmp_path / "session")
    assert 'sample_bank="MINE"' in added_element(tmp_path, "neon")


def test_a_rebuild_clears_old_files(stock, tmp_path):
    build(stock, [{"strings": {"X": "y"}}], tmp_path)
    stale = tmp_path / "session/generated" / msg_path("usa")
    assert stale.is_file()
    build_session(stock, tmp_path / "mods", [], tmp_path / "save", tmp_path / "session")
    assert not stale.exists()


def test_session_holds_options(stock, tmp_path):
    path = build_session(stock, tmp_path / "mods", [], tmp_path / "save", tmp_path / "session", options=from_settings({}))
    session = json.loads(path.read_text(encoding="utf-8"))
    assert session["display"]["borderless"] is True
    assert session["controller"]["layout"]["nitro"] == "b"


def test_session_without_options_has_no_new_fields(stock, tmp_path):
    path = build_session(stock, tmp_path / "mods", [], tmp_path / "save", tmp_path / "session")
    session = json.loads(path.read_text(encoding="utf-8"))
    assert "display" not in session
    assert "controller" not in session


def test_merge_on_the_real_stock_files(game_dir, tmp_path):
    mods_dir = tmp_path / "mods"
    make_mod(mods_dir, "new", **team_mod())
    path = build_session(game_dir, mods_dir, ["new"], tmp_path / "save", tmp_path / "session")
    session = json.loads(Path(path).read_text(encoding="utf-8"))
    assert [len(team["slots"]) for team in session["teams"]] == [7, 7, 7, 7, 7, 3]
    assert session["teams"][2]["slots"][:2] == [14, 15]
    assert len(internal_names(tmp_path)) == 38
    assert generated(tmp_path, "frontend/car_select_screen.xml").count("<car_rep ID=") == 38
    assert generated(tmp_path, "frontend/multi_player_car_select.xml").count("<car_rep ID=") == 76
    assert 'MaxCarIcons="42"' in generated(tmp_path, "frontend/car_select_screen.xml")
    strings = read_msg((tmp_path / "session/generated" / msg_path("english")).read_bytes())
    assert strings[574:] == ["N1", "N2", "N3"]


def test_added_team_gets_its_base_teams_effects(stock, tmp_path):
    build(stock, [team_mod()], tmp_path)
    assert generated(tmp_path, "cars/effects/cache/stunt_neon_riders.xml") == "<beasts/>"
    assert generated(tmp_path, "cars/effects/cache/landing_neon_riders.xml") == "<landing/>"


def test_only_the_base_teams_effects_are_copied(stock, tmp_path):
    build(stock, [team_mod()], tmp_path)
    effects = sorted(p.name for p in (tmp_path / "session/generated/cars/effects/cache").iterdir())
    assert effects == ["landing_neon_riders.xml", "stunt_neon_riders.xml"]


def test_a_mods_own_team_effect_wins(stock, tmp_path):
    mod = team_mod()
    mod["files"].append("cars/effects/cache/stunt_neon_riders.xml")
    build(stock, [mod], tmp_path)
    assert not (tmp_path / "session/generated/cars/effects/cache/stunt_neon_riders.xml").exists()
    assert (tmp_path / "session/generated/cars/effects/cache/landing_neon_riders.xml").is_file()


def test_real_team_effects_are_all_copied(game_dir, tmp_path):
    mods_dir = tmp_path / "mods"
    make_mod(mods_dir, "new", **team_mod())
    build_session(game_dir, mods_dir, ["new"], tmp_path / "save", tmp_path / "session")
    assert len(list((tmp_path / "session/generated/cars/effects/cache").iterdir())) == 13


def test_non_ascii_tool_folder_refused(stock, tmp_path):
    # The game opens paths with ANSI calls, and the DLL passes UTF-8 bytes.
    mods_dir = tmp_path / "Jos\u00e9" / "mods"
    make_mod(mods_dir, "a", files=["a.txt"])
    with pytest.raises(MergeError, match="WRMOD_DATA"):
        build_session(stock, mods_dir, ["a"], tmp_path / "save", tmp_path / "session")


def test_non_ascii_save_folder_refused(stock, tmp_path):
    with pytest.raises(MergeError, match="WRMOD_DATA"):
        build_session(stock, tmp_path / "mods", [], tmp_path / "Jos\u00e9", tmp_path / "session")


def full_row_team(ai_slots):
    names = [f"n{i}" for i in range(7)]
    mod = team_mod(cars=names)
    for slot, entry in enumerate(mod["cars"]):
        entry["ai_car"] = slot in ai_slots
    return mod


def test_team_whose_only_ai_car_cannot_be_drawn_refused(stock, tmp_path):
    with pytest.raises(MergeError, match="neon_riders"):
        build(stock, [full_row_team({6})], tmp_path)


def test_a_second_ai_car_makes_the_last_slot_safe(stock, tmp_path):
    session = build(stock, [full_row_team({5, 6})], tmp_path)
    assert len(session["teams"][5]["slots"]) == 7


def test_last_slot_is_safe_when_the_row_is_short(stock, tmp_path):
    mod = full_row_team({6})
    session = build(stock, [mod, car_mod("a"), car_mod("b")], tmp_path)
    assert len(session["teams"][2]["slots"]) == 9


def icon(size=96):
    return dds_to_bog(dxt5_dds(size, 48, bytes(size // 4 * 12 * 16)), None)


def session_file(tmp_path, rel):
    return tmp_path / "session/generated" / rel


def test_a_car_icon_joins_the_sheet(stock, tmp_path):
    build(stock, [{**car_mod("neon"), "blobs": {"frontend/neon_icon.bog": icon()}}], tmp_path)
    bed = read_bed(session_file(tmp_path, f"{ICON_SHEET}.bed").read_bytes())
    assert bed.find("neon").pixels(512, 1024) == (0, 512, 96, 48)
    assert parse_header(session_file(tmp_path, f"{ICON_SHEET}.bog").read_bytes()).height == 1024
    assert 'icon_box="neon"' in added_element(tmp_path, "neon")


def test_a_car_with_no_icon_keeps_the_base_cars(stock, tmp_path):
    build(stock, [car_mod("neon")], tmp_path)
    assert not session_file(tmp_path, f"{ICON_SHEET}.bed").exists()
    assert 'icon_box="ballistic"' in added_element(tmp_path, "neon")


def test_a_highlight_joins_its_own_sheet(stock, tmp_path):
    build(stock, [{**car_mod("neon"), "blobs": {"frontend/neon_icon_hlight.bog": icon()}}], tmp_path)
    bed = read_bed(session_file(tmp_path, f"{HIGHLIGHT_SHEET}.bed").read_bytes())
    assert bed.find("neon_hlight") is not None
    rep = re.search(r'<car_rep ID="neon"[^>]*', generated(tmp_path, "frontend/car_select_screen.xml")).group(0)
    assert 'SilhouetteName="neon_hlight"' in rep


def test_a_car_with_no_highlight_keeps_the_base_cars(stock, tmp_path):
    build(stock, [{**car_mod("neon"), "blobs": {"frontend/neon_icon.bog": icon()}}], tmp_path)
    rep = re.search(r'<car_rep ID="neon"[^>]*', generated(tmp_path, "frontend/car_select_screen.xml")).group(0)
    assert 'SilhouetteName="ballistic_hlight"' in rep
    assert not session_file(tmp_path, f"{HIGHLIGHT_SHEET}.bed").exists()


def test_icons_from_two_mods_share_one_sheet(stock, tmp_path):
    mods = [{**car_mod(name), "blobs": {f"frontend/{name}_icon.bog": icon()}} for name in ("a1", "b2")]
    build(stock, mods, tmp_path)
    bed = read_bed(session_file(tmp_path, f"{ICON_SHEET}.bed").read_bytes())
    assert bed.find("a1").pixels(512, 1024) == (0, 512, 96, 48)
    assert bed.find("b2").pixels(512, 1024) == (96, 512, 96, 48)


def test_an_icon_of_the_wrong_size_stops_the_build(stock, tmp_path):
    with pytest.raises(MergeError, match="neon"):
        build(stock, [{**car_mod("neon"), "blobs": {"frontend/neon_icon.bog": icon(64)}}], tmp_path)


def test_a_car_can_name_its_driver(stock, tmp_path):
    session = build(stock, [car_mod("neon", driver="Rick Rod")], tmp_path)
    rep = re.search(r'<car_rep ID="neon"[^>]*', generated(tmp_path, "frontend/car_select_screen.xml")).group(0)
    assert 'CharacterName="WRSE_DRIVER_NEON"' in rep
    assert session["text"] == {"WRSE_CAR_NEON": 574, "WRSE_DRIVER_NEON": 575}


def test_a_car_with_no_driver_adds_no_text_for_one(stock, tmp_path):
    assert "WRSE_DRIVER_NEON" not in build(stock, [car_mod("neon")], tmp_path)["text"]


def neon_rep(tmp_path, screen="frontend/car_select_screen.xml"):
    return re.search(r'<car_rep ID="neon".*?</car_rep>', generated(tmp_path, screen), re.S).group(0)


def test_a_car_with_its_own_portrait_shows_it(stock, tmp_path):
    build(stock, [{**car_mod("neon"), "blobs": {"player_textures/cache/player_neon.bog": b"portrait"}}], tmp_path)
    assert 'Texture="player_textures/cache/player_neon"' in neon_rep(tmp_path)
    assert 'Texture="player_textures/cache/player_neon"' in neon_rep(tmp_path, "frontend/multi_player_car_select.xml")


def test_only_the_head_moves_to_the_portrait(stock, tmp_path):
    build(stock, [{**car_mod("neon"), "blobs": {"player_textures/cache/player_neon.bog": b"portrait"}}], tmp_path)
    assert "frontend/neon_movie" in neon_rep(tmp_path)
    assert "frontend/head_" not in neon_rep(tmp_path)


def test_a_car_with_no_portrait_keeps_the_base_head(stock, tmp_path):
    build(stock, [car_mod("neon")], tmp_path)
    assert 'Texture="frontend/head_ballistic"' in neon_rep(tmp_path)


def test_a_screen_entry_with_no_head_is_left_alone():
    entry = '<car_rep ID="ballistic" TeamLogo="x" Movie="m" CarName="C"></car_rep>'
    car = {"based_on": "ballistic", "internal_name": "neon"}
    assert "player_textures" not in merge._screen_entry(entry, car, "logo", set(), {"neon"})


def art(width, height):
    return dds_to_bog(dxt5_dds(width, height, bytes(width // 4 * (height // 4) * 16)), None)


def team_with(blobs=None, logo=True):
    mod = team_mod()
    if not logo:
        del mod["teams"][0]["logo"]
    return {**mod, "blobs": blobs or {}}


def test_a_team_logo_joins_the_sheet(stock, tmp_path):
    session = build(stock, [team_with({"frontend/neon_riders_logo.bog": art(128, 96)})], tmp_path)
    assert session["teams"][5]["logo"] == {"texture": TEAM_LOGO_SHEET, "box": "neon_riders"}
    bed = read_bed(session_file(tmp_path, f"{TEAM_LOGO_SHEET}.bed").read_bytes())
    assert bed.find("neon_riders").pixels(512, 1024) == (0, 512, 128, 96)
    rep = re.search(r'<car_rep ID="n1"[^>]*', generated(tmp_path, "frontend/car_select_screen.xml")).group(0)
    assert 'TeamLogo="neon_riders"' in rep


def test_a_team_name_joins_the_hud_sheet(stock, tmp_path):
    build(stock, [team_with({"frontend/neon_riders_team_name.bog": art(128, 32)})], tmp_path)
    bed = read_bed(session_file(tmp_path, f"{TEAM_NAME_SHEET}.bed").read_bytes())
    assert bed.find("neon_riders").pixels(512, 1024) == (0, 512, 128, 32)


def test_a_team_with_no_logo_uses_the_base_teams(stock, tmp_path):
    session = build(stock, [team_with(logo=False)], tmp_path)
    assert session["teams"][5]["logo"] == {"texture": TEAM_LOGO_SHEET, "box": "RoadBeasts"}
    assert not session_file(tmp_path, f"{TEAM_LOGO_SHEET}.bed").exists()


def test_a_team_logo_file_beats_the_logo_field(stock, tmp_path):
    session = build(stock, [team_with({"frontend/neon_riders_logo.bog": art(128, 96)})], tmp_path)
    assert session["teams"][5]["logo"]["box"] == "neon_riders"


def test_a_team_logo_of_the_wrong_size_stops_the_build(stock, tmp_path):
    with pytest.raises(MergeError, match="neon_riders"):
        build(stock, [team_with({"frontend/neon_riders_logo.bog": art(96, 48)})], tmp_path)


def test_a_car_can_choose_its_rim_colour(stock, tmp_path):
    session = build(stock, [car_mod("neon", rim_colour="red")], tmp_path)
    assert session["rims"]["neon"] == 4


def test_rim_colours_follow_the_wheel_textures(stock, tmp_path):
    session = build(stock, [car_mod("neon", rim_colour="yellow")], tmp_path)
    assert "neon" not in session["rims"]


def test_without_team_rims_a_car_with_no_rim_colour_stays_yellow(stock, tmp_path):
    assert build(stock, [car_mod("neon")], tmp_path)["rims"] == {}


TEAM_RIMS = {"team_rims": True}


def test_team_rims_give_stock_cars_their_teams_colour(stock, tmp_path):
    rims = build(stock, [], tmp_path, from_settings(TEAM_RIMS))["rims"]
    assert (rims["street_breed_0"], rims["ballistic"], rims["wave_rippers_6"], rims["scorchers_3"]) == (1, 2, 3, 4)
    assert "dune_rats_0" not in rims


def test_team_rims_off_keeps_every_stock_car_yellow(stock, tmp_path):
    assert build(stock, [], tmp_path, from_settings({"team_rims": False}))["rims"] == {}


def test_a_mod_car_follows_its_teams_rim(stock, tmp_path):
    assert build(stock, [car_mod("neon", team="wave_rippers")], tmp_path, from_settings(TEAM_RIMS))["rims"]["neon"] == 3


def test_a_cars_own_rim_colour_beats_its_team(stock, tmp_path):
    rims = build(stock, [car_mod("neon", team="wave_rippers", rim_colour="yellow")], tmp_path, from_settings(TEAM_RIMS))["rims"]
    assert "neon" not in rims


def test_a_car_in_an_added_team_stays_yellow(stock, tmp_path):
    rims = build(stock, [team_mod()], tmp_path, from_settings(TEAM_RIMS))["rims"]
    assert not {"n1", "n2", "n3"} & set(rims)


@pytest.mark.parametrize("rim", [1, 2, 3, 4])
def test_team_rims_make_every_team_wheel_model(stock, tmp_path, rim):
    build(stock, [], tmp_path, from_settings(TEAM_RIMS))
    assert [m.name for m in read_rom(rim_model(tmp_path, rim, "med").read_bytes()).materials] == [f"generic_wheel_high_{rim}"]


def rim_model(tmp_path, rim, level):
    return tmp_path / f"session/generated/cars/generic_models/cache/rim_{rim}/generic_wheel_{level}.rom"


@pytest.mark.parametrize("level", ["med", "low"])
def test_a_rim_colour_gets_a_wheel_model_with_its_texture(stock, tmp_path, level):
    build(stock, [car_mod("neon", rim_colour="red")], tmp_path)
    assert [m.name for m in read_rom(rim_model(tmp_path, 4, level).read_bytes()).materials] == ["generic_wheel_high_4"]


def test_the_stock_rim_colour_needs_no_wheel_model(stock, tmp_path):
    build(stock, [car_mod("neon", rim_colour="yellow")], tmp_path)
    assert not rim_model(tmp_path, 0, "med").parent.exists()


def test_a_car_with_no_rim_colour_makes_no_wheel_model(stock, tmp_path):
    build(stock, [car_mod("neon")], tmp_path)
    assert not (tmp_path / "session/generated/cars/generic_models").exists()


TUNED = STOCK_PARAMS.replace("1.18", "0.8")
BALLISTIC_PARAMS = "cars/ballistic/cache/ballistic.params"


@pytest.fixture
def overhaul_game(stock, monkeypatch):
    monkeypatch.setattr(merge, "is_overhaul", lambda game: True)
    return stock


def params_mod(name, text, path=None, **changes):
    mod = car_mod(name, **changes)
    return {**mod, "blobs": {path or f"cars/{name}/cache/{name}.params": text.encode("latin1")}}


def stock_params_mod(text, tagged=False):
    return {"blobs": {BALLISTIC_PARAMS: text.encode("latin1")}, "tagged": tagged}


def torque(tmp_path, rel):
    return read_physics(generated(tmp_path, rel))["ENGINETORQUEMAX"]


def has_generated(tmp_path, rel):
    return (tmp_path / "session/generated" / rel).exists()


def test_on_an_overhaul_an_untagged_added_car_is_rebased(overhaul_game, tmp_path):
    build(overhaul_game, [params_mod("neon", TUNED)], tmp_path)
    assert torque(tmp_path, "cars/neon/cache/neon.params") == [pytest.approx(1.5 * 0.8 / 1.18)]


def test_on_an_overhaul_a_tagged_mod_is_left_alone(overhaul_game, tmp_path):
    build(overhaul_game, [{**params_mod("neon", TUNED), "tagged": True}], tmp_path)
    assert not has_generated(tmp_path, "cars/neon/cache/neon.params")


def test_on_an_overhaul_a_stock_car_params_is_rebased(overhaul_game, tmp_path):
    build(overhaul_game, [stock_params_mod(TUNED)], tmp_path)
    assert torque(tmp_path, BALLISTIC_PARAMS) == [pytest.approx(1.5 * 0.8 / 1.18)]


def test_a_stock_game_never_rebases(stock, tmp_path):
    build(stock, [params_mod("neon", TUNED), stock_params_mod(TUNED)], tmp_path)
    assert not has_generated(tmp_path, "cars/neon/cache/neon.params")
    assert not has_generated(tmp_path, BALLISTIC_PARAMS)


def test_rebase_follows_the_winning_mod(overhaul_game, tmp_path):
    build(overhaul_game, [stock_params_mod(TUNED), stock_params_mod(TUNED, tagged=True)], tmp_path)
    assert not has_generated(tmp_path, BALLISTIC_PARAMS)
    build(overhaul_game, [stock_params_mod(TUNED, tagged=True), stock_params_mod(TUNED)], tmp_path / "again")
    assert has_generated(tmp_path / "again", BALLISTIC_PARAMS)


def test_overhaul_values_come_from_the_game_not_a_mod(overhaul_game, tmp_path):
    replaced = stock_params_mod(OVERHAUL_PARAMS.replace("1.5", "9.0"), tagged=True)
    build(overhaul_game, [replaced, params_mod("neon", TUNED)], tmp_path)
    assert torque(tmp_path, "cars/neon/cache/neon.params") == [pytest.approx(1.5 * 0.8 / 1.18)]


def test_params_of_an_unknown_car_is_left_alone(overhaul_game, tmp_path):
    build(overhaul_game, [{"blobs": {"cars/mystery/cache/mystery.params": TUNED.encode("latin1")}}], tmp_path)
    assert not has_generated(tmp_path, "cars/mystery/cache/mystery.params")


def test_unreadable_params_is_left_alone(overhaul_game, tmp_path):
    build(overhaul_game, [params_mod("neon", "ENGINETORQUEMAX abc\r\n")], tmp_path)
    assert not has_generated(tmp_path, "cars/neon/cache/neon.params")


def test_params_path_case_does_not_matter(overhaul_game, tmp_path):
    mod = {**params_mod("neon", TUNED, path="cars/Neon/cache/neon.params"), "files": ()}
    build(overhaul_game, [mod], tmp_path)
    assert has_generated(tmp_path, "cars/Neon/cache/neon.params")


def test_generic_params_is_never_rebased(overhaul_game, tmp_path, monkeypatch):
    monkeypatch.setitem(FILES, "cars/generic/cache/generic.params", OVERHAUL_PARAMS.encode("latin1"))
    monkeypatch.setattr(merge, "stock_physics", lambda: {"generic": read_physics(STOCK_PARAMS)})
    build(overhaul_game, [{"blobs": {"cars/generic/cache/generic.params": TUNED.encode("latin1")}}], tmp_path)
    assert not has_generated(tmp_path, "cars/generic/cache/generic.params")


@pytest.fixture
def cheat_base(stock, monkeypatch):
    """The base car names a Smashmouth cheat model, like stock super_tuned."""
    text = FILES["misc/cache/car_info.xml"].decode("latin1").replace(
        '<CAR internal_name="ballistic"',
        '<CAR internal_name="ballistic" alternate_internal_name="smashmouth" special_silhouette="cheat_hligh" alternate_icon_texture="CHEAT"',
    )
    monkeypatch.setitem(FILES, "misc/cache/car_info.xml", text.encode("latin1"))
    return stock


def test_a_new_car_does_not_take_its_donors_cheat_model(cheat_base, tmp_path):
    build(cheat_base, [car_mod("neon")], tmp_path)
    element = added_element(tmp_path, "neon")
    assert "alternate" not in element and "special_silhouette" not in element


def test_a_new_car_can_name_its_own_cheat_model(cheat_base, tmp_path):
    mod = car_mod("neon", alternate="neon_cheat")
    mod["files"].append("cars/neon_cheat/cache/neon_cheat.pts")
    build(cheat_base, [mod], tmp_path)
    element = added_element(tmp_path, "neon")
    assert 'alternate_internal_name="neon_cheat"' in element
    assert 'alternate_icon_texture="CHEAT"' in element and 'special_silhouette="cheat_hligh"' in element


def test_a_cheat_model_needs_its_own_files(stock, tmp_path):
    with pytest.raises(MergeError, match="neon_cheat"):
        build(stock, [car_mod("neon", alternate="neon_cheat")], tmp_path)


def test_a_cheat_model_cannot_take_a_stock_cheat_name(cheat_base, tmp_path):
    mod = car_mod("neon", alternate="smashmouth")
    mod["files"].append("cars/smashmouth/cache/smashmouth.pts")
    with pytest.raises(MergeError, match="smashmouth"):
        build(cheat_base, [mod], tmp_path)


def test_a_cheat_model_cannot_take_another_cars_name(stock, tmp_path):
    mod = car_mod("neon", alternate="ballistic")
    mod["files"].append("cars/ballistic/cache/ballistic.pts")
    with pytest.raises(MergeError, match="ballistic"):
        build(stock, [mod], tmp_path)
