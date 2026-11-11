"""Merge the active mods into a session for the base mod.

Python does all merging, and the DLL only reads the result. Lists the game reads from XML are
generated into the session folder as text edits of the stock files, so their layout stays.
"""
import io
import json
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps

from .gamefiles import game_files, is_overhaul
from .bed import BedError
from .bog import HEADER_SIZE
from .gameinfo import STOCK_EXE
from .icons import (
    HIGHLIGHT_SHEET,
    ICON_CELL,
    ICON_SHEET,
    LOGO_CELL,
    STOCK_LOGO_BOXES,
    TEAM_LOGO_SHEET,
    TEAM_NAME_CELL,
    TEAM_NAME_SHEET,
    IconError,
    add_icons,
    bog_image,
    highlight_box,
    highlight_path,
    icon_path,
    logo_path,
    team_name_path,
)
from .modpack import (
    CARS, FILES_DIR, MANIFEST, OVERHAUL_TAG, ModError, RIM_COLOURS, TEAMS, mod_cars, mod_files, mod_strings, mod_teams,
)
from .physics import PhysicsError, rebase, stock_physics
from .msg import LANGUAGES, apply_edits, load_string_ids, msg_path, new_text_ids, resolve_edits
from .options import session_fields
from .rom import read_rom, write_rom

SESSION_FORMAT = 1
SESSION_FILE = "session.json"
GENERATED_DIR = "generated"
LOG_FILE = "wrse.log"

CAR_INFO = "misc/cache/car_info.xml"
WHEEL_FOLDER = "cars/generic_models/cache"
WHEEL_LEVELS = ("med", "low")
WHEEL_TEXTURE = b"generic_wheel_high_"
SCREENS = ("frontend/car_select_screen.xml", "frontend/multi_player_car_select.xml")
EFFECTS_DIR = "cars/effects/cache/"
ENCODING = "latin1"

STOCK_TEAMS = ("dune_rats", "street_breed", "road_beasts", "wave_rippers", "scorchers")
STOCK_CARS = 35
STOCK_WIDTH = 7
# The DLL refuses more, because the selector sizes its arrays with 8-bit values.
MAX_WIDTH = 16
MAX_TEAMS = 16

BLOKE_HEAD = re.compile(r'(<BlokeHead>.*?Texture=")[^"]*"', re.S)
MOVIE_FIRST_FRAME = re.compile(r'(<MovieFirstFrame>.*?Texture=")([^"]*)"', re.S)
# Where NitroXFueled's car renders park the car, as shares of the picture: left, top, width, height.
GARAGE_CAR_BOX = (0.54, 0.50, 0.40, 0.36)
TEXT_PREFIX = "WRSE_CAR_"
DRIVER_TEXT_PREFIX = "WRSE_DRIVER_"
CAR_ELEMENT = re.compile(r"<CAR [^>]*/>")
SCREEN_ENTRY = re.compile(r'[ \t]*<car_rep ID="(\w+)".*?</car_rep>\r?\n', re.S)
CAR_PARAMS = re.compile(r"cars/([^/]+)/cache/\1\.params", re.I)
# Shared settings for every car, not one car's physics, so a mod's version is used as it is.
NOT_REBASED = {"generic"}
# The Smashmouth cheat swaps every car that names an alternate model, in this attribute order.
ALTERNATE_ATTRIBUTES = ("alternate_internal_name", "alternate_icon_texture", "special_silhouette")
# Stock's own cheat icon and highlight boxes, which every alternate uses.
CHEAT_ICON_BOX = "CHEAT"
CHEAT_SILHOUETTE_BOX = "cheat_hligh"
ALTERNATE_NAME = re.compile(r'\balternate_internal_name="([^"]*)"')


class MergeError(Exception):
    pass


class _Source:
    """Reads a game file from the winning mod, or else from the game."""

    def __init__(self, game, folders):
        self._game = game
        self._folders = folders
        self._game_files = None

    def winner(self, rel):
        for folder in reversed(self._folders):
            if (folder / FILES_DIR / rel).is_file():
                return folder
        return None

    def _mod_path(self, rel):
        folder = self.winner(rel)
        return folder / FILES_DIR / rel if folder else None

    def _stock(self):
        if self._game_files is None:
            self._game_files = game_files(self._game)
        return self._game_files

    def stock_paths(self):
        return self._stock().paths()

    def game_has(self, rel):
        return self._stock().has(rel)

    def game_read(self, rel):
        return self._stock().read(rel)

    def in_mod(self, rel):
        return self._mod_path(rel) is not None

    def has(self, rel):
        return self._mod_path(rel) is not None or self._stock().has(rel)

    def read(self, rel):
        path = self._mod_path(rel)
        return path.read_bytes() if path else self._stock().read(rel)

    def text(self, rel):
        return self.read(rel).decode(ENCODING)


def _attribute(element, name):
    return re.search(rf'\b{name}="([^"]*)"', element).group(1)


def _set_attribute(element, name, value):
    changed, count = re.subn(rf'\b{name}="[^"]*"', f'{name}="{value}"', element, count=1)
    if count != 1:
        raise MergeError(f"The stock entry has no {name}: {element[:60]}")
    return changed


def _drop_attribute(element, name):
    return re.sub(rf'\s+\b{name}="[^"]*"', "", element, count=1)


def _add_attribute(element, name, value):
    return re.sub(r"\s*/>$", f' {name}="{value}"/>', element, count=1)


def _text_name(car):
    return TEXT_PREFIX + car["internal_name"].upper()


def _driver_text_name(car):
    return DRIVER_TEXT_PREFIX + car["internal_name"].upper()


def _portrait(car):
    return f"player_textures/cache/player_{car['internal_name']}"


def _still(name):
    """The car's still picture on the stock car select screen."""
    return f"frontend/{name}_movie"


def _clip(name):
    """A car's clip as the screens name it. The game adds `n` and `.bik` to open it."""
    return f"movies/cars/{name}"


def _clip_file(name):
    return f"n{_clip(name)}.bik"


def _new_texts(cars):
    texts = {_text_name(car): car["display_name"] for _, car in cars}
    texts.update({_driver_text_name(car): car["driver"] for _, car in cars if "driver" in car})
    return texts


def _read_mod_lists(folders):
    cars, teams = [], []
    try:
        for folder in folders:
            cars.extend((folder, car) for car in mod_cars(folder))
            teams.extend(mod_teams(folder))
    except ModError as e:
        raise MergeError(str(e)) from e
    return cars, teams


def _check_teams(teams, source):
    ids = list(STOCK_TEAMS)
    for team in teams:
        if team["id"] in ids:
            raise MergeError(f"Team {team['id']} already exists")
        ids.append(team["id"])
        if team["base_team"] not in STOCK_TEAMS:
            raise MergeError(f"Team {team['id']} has the base team {team['base_team']}, which is not a stock team")
        logo = team.get("logo")
        if logo is None:
            continue
        bed = logo["texture"] + ".bed"
        if not source.has(bed):
            raise MergeError(f"Team {team['id']} uses the logo sheet {logo['texture']}, which does not exist")
        if logo["box"].encode("ascii") + b"\0" not in source.read(bed):
            raise MergeError(f"Team {team['id']} uses the logo box {logo['box']}, which does not exist")
    if len(ids) > MAX_TEAMS:
        raise MergeError(f"There are {len(ids)} teams, and the limit is {MAX_TEAMS}")
    return ids


def _check_cars(cars, stock_names, stock_alternates):
    seen = set(stock_names) | stock_alternates
    for folder, car in cars:
        name = car["internal_name"]
        if car["based_on"] not in stock_names:
            raise MergeError(f"Car {name} is based on {car['based_on']}, which is not a stock car")
        for own in _own_names(car):
            if own in seen:
                raise MergeError(f"Car name {own} is already used")
            seen.add(own)
            prefix = f"cars/{own}/"
            if not any(rel.lower().startswith(prefix) for rel in mod_files(folder)):
                raise MergeError(f"Mod {folder.name} has no files for car {own}. Every added car needs {prefix}")


def _own_names(car):
    """The car's name, then the name of the model the Smashmouth cheat loads in its place."""
    return [car["internal_name"]] + ([car["alternate"]] if "alternate" in car else [])


def _make_rows(stock, cars, team_ids):
    rows = {team: [] for team in team_ids}
    for index, (_, team) in enumerate(stock):
        rows[team].append(index)
    for offset, (_, car) in enumerate(cars):
        if car["team"] not in rows:
            raise MergeError(f"Car {car['internal_name']} uses the unknown team {car['team']}")
        rows[car["team"]].append(STOCK_CARS + offset)
    for team, slots in rows.items():
        if not slots:
            raise MergeError(f"Team {team} has no cars")
        if len(slots) > MAX_WIDTH:
            raise MergeError(f"Team {team} has {len(slots)} cars, and the limit is {MAX_WIDTH}")
    return rows


def _grid_width(rows):
    return max(STOCK_WIDTH, *(len(slots) for slots in rows.values()))


def _check_team_cars(teams, cars, rows):
    last_team = list(rows)[-1]
    for team in teams:
        members = [car for _, car in cars if car["team"] == team["id"]]
        ai_cars = [car for car in members if car.get("ai_car")]
        if not ai_cars:
            raise MergeError(f"Team {team['id']} needs at least one AI car")
        if team["leader"] not in [car["internal_name"] for car in members]:
            raise MergeError(f"The leader of team {team['id']} must be one of its cars")
        # The game's draw never reaches the last grid entry.
        fills_last_entry = team["id"] == last_team and len(rows[last_team]) == _grid_width(rows)
        if fills_last_entry and ai_cars == [members[-1]]:
            raise MergeError(f"Team {team['id']} needs an AI car other than its last car")


def _car_element(base, car, leaders, icons):
    element = base
    changes = {
        "internal_name": car["internal_name"],
        "team_name": car["team"],
        "locked": "false",
        "descriptive_name": _text_name(car),
        "ai_car": "true" if car.get("ai_car") else "false",
        "team_leader": "true" if car["internal_name"] in leaders else "false",
    }
    changes.update({stat: car[stat] for stat in ("speed", "grip", "boost", "accel") if stat in car})
    if car["internal_name"] in icons:
        changes["icon_box"] = car["internal_name"]
    for name, value in changes.items():
        element = _set_attribute(element, name, value)
    # The cheat model belongs to the donor, so a car keeps only one it names itself.
    for name in ALTERNATE_ATTRIBUTES:
        element = _drop_attribute(element, name)
    if "alternate" in car:
        for name, value in zip(ALTERNATE_ATTRIBUTES, (car["alternate"], CHEAT_ICON_BOX, CHEAT_SILHOUETTE_BOX)):
            element = _add_attribute(element, name, value)
    return element


def _edit_car_info(text, elements, cars, leaders, icons):
    by_name = {_attribute(e, "internal_name"): e for e in elements}
    added = [_car_element(by_name[car["based_on"]], car, leaders, icons) for _, car in cars]
    end = list(CAR_ELEMENT.finditer(text))[-1].end()
    return text[:end] + "".join(f"\r\n   {element}" for element in added) + text[end:]


def _write_garage(source, generated, name, backdrop):
    try:
        backdrop_bog = source.read(f"{backdrop}.bog")
        garage = bog_image(backdrop_bog, backdrop)
        still = bog_image(source.read(f"{_still(name)}.bog"), f"The still picture of {name}")
    except KeyError as e:
        raise MergeError(f"The garage picture {backdrop} is missing") from e
    except IconError as e:
        raise MergeError(str(e)) from e
    left, top, width, height = (round(share * size) for share, size in zip(GARAGE_CAR_BOX, garage.size * 2))
    still = ImageOps.contain(still, (width, height), Image.Resampling.LANCZOS)
    garage.paste(still, (left + (width - still.width) // 2, top + (height - still.height) // 2), still)
    png = io.BytesIO()
    garage.save(png, format="PNG")
    path = f"frontend/{name}_garage"
    target = generated / f"{path}.bog"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(backdrop_bog[:HEADER_SIZE] + png.getvalue())
    return path


def _write_garages(source, cars, rows, teams, stock_names, generated):
    """Overhauls such as NitroXFueled show a team garage first, then play a render of the car.
    An added car shows its team's garage, with its still where the renders park the cars, and
    plays its own clip if its mod has one. Stock shows each car's own still, so it needs none of
    this. Returns each car's first frame and clip."""
    by_name = {m.group(1): m.group(0) for m in SCREEN_ENTRY.finditer(source.text(SCREENS[0]))}
    base_teams = {team["id"]: team["base_team"] for team in teams}
    garages, clips = {}, {}
    for _, car in cars:
        name = car["internal_name"]
        first_frame = MOVIE_FIRST_FRAME.search(by_name[car["based_on"]])
        if not first_frame or first_frame.group(2) == _still(car["based_on"]):
            continue
        team = base_teams.get(car["team"], car["team"])
        team_frame = MOVIE_FIRST_FRAME.search(by_name[stock_names[rows[team][0]]])
        if not team_frame:
            continue
        has_still = source.in_mod(f"{_still(name)}.bog")
        garages[name] = _write_garage(source, generated, name, team_frame.group(2)) if has_still else team_frame.group(2)
        if source.in_mod(_clip_file(name)):
            clips[name] = _clip(name)
    return garages, clips


def _screen_entry(entry, car, logo, highlights, portraits, garage=None, clip=None):
    based_on = car["based_on"]
    name = car["internal_name"]
    entry = entry.replace(f'ID="{based_on}"', f'ID="{name}"', 1).replace(_still(based_on), _still(name))
    if garage:
        entry = MOVIE_FIRST_FRAME.sub(rf'\g<1>{garage}"', entry)
    entry = _set_attribute(entry, "CarName", _text_name(car))
    if "driver" in car:
        entry = _set_attribute(entry, "CharacterName", _driver_text_name(car))
    if name in highlights:
        entry = _set_attribute(entry, "SilhouetteName", highlight_box(name))
    if name in portraits:
        # The screen names a head of its own. It is the same size and picture as the car's portrait.
        entry = BLOKE_HEAD.sub(rf'\g<1>{_portrait(car)}"', entry)
    if clip:
        entry = _set_attribute(entry, "Movie", clip)
    elif "MovieFirstFrame" in entry:
        # The base car's clip shows the wrong car. With no name the clip never opens, and the
        # car's still picture stays. A missing file is worse: the last clip stays on screen.
        entry = _set_attribute(entry, "Movie", "")
    return _set_attribute(entry, "TeamLogo", logo)


def _team_logos(by_name, stock_names, rows, teams, own_logos):
    # By name, because an overhaul can order car_info.xml differently from the screens.
    logos = {}
    for team, slots in rows.items():
        if team in STOCK_TEAMS:
            logos[team] = _attribute(by_name[stock_names[slots[0]]], "TeamLogo")
    for team in teams:
        logos[team["id"]] = team["id"] if team["id"] in own_logos else logos[team["base_team"]]
    return logos


def _edit_screen(text, cars, rows, teams, rel, art, stock_names):
    entries = list(SCREEN_ENTRY.finditer(text))
    if not entries or len(entries) % STOCK_CARS:
        raise MergeError(f"{rel} has {len(entries)} car entries, which is not a multiple of {STOCK_CARS}")
    for start in reversed(range(0, len(entries), STOCK_CARS)):
        chunk = entries[start:start + STOCK_CARS]
        by_name = {m.group(1): m.group(0) for m in chunk}
        logos = _team_logos(by_name, stock_names, rows, teams, art.logos)
        added = "".join(
            _screen_entry(by_name[car["based_on"]], car, logos[car["team"]], art.highlights, art.portraits,
                          art.garages.get(car["internal_name"]), art.clips.get(car["internal_name"]))
            for _, car in cars
        )
        text = text[:chunk[-1].end()] + added + text[chunk[-1].end():]
    width = _grid_width(rows)
    text = text.replace(f'MaxCarIcons="{STOCK_CARS}"', f'MaxCarIcons="{len(rows) * width}"')
    text = re.sub(r'(cFrontendObjectScrollableSelectorCar[^>]*NumObjectsInScrollList=")\d+"', rf'\g<1>{width}"', text)
    return re.sub(r'(cFrontendObjectScrollableSelectorTeam[^>]*NumObjectsInScrollList=")\d+"', rf'\g<1>{len(rows)}"', text)


def _write_generated(generated, rel, text):
    try:
        ET.fromstring(text)
    except ET.ParseError as e:
        raise MergeError(f"Generated {rel} is not valid XML: {e}") from e
    target = generated / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode(ENCODING))


def _write_team_effects(source, teams, generated):
    """The game loads effect files by team name, and a missing one crashes it in a race."""
    for team in teams:
        suffix = f"_{team['base_team']}.xml"
        for rel in source.stock_paths():
            if rel.lower().startswith(EFFECTS_DIR) and rel.lower().endswith(suffix):
                effect = f"{rel[:-len(suffix)]}_{team['id']}.xml"
                if not source.in_mod(effect):
                    target = generated / effect
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read(rel))


def _team_logo(team, own_logos):
    """A team's own art wins, then the logo it names, then its base team's logo."""
    if team["id"] in own_logos:
        return {"texture": TEAM_LOGO_SHEET, "box": team["id"]}
    return team.get("logo") or {"texture": TEAM_LOGO_SHEET, "box": STOCK_LOGO_BOXES[team["base_team"]]}


def _session_tables(cars, teams, rows, own_logos):
    team_ids = list(rows)
    added = {team["id"]: team for team in teams}
    table = []
    for index, (team_id, slots) in enumerate(rows.items()):
        team = added.get(team_id)
        table.append({
            "id": team_id,
            "slots": slots,
            "logo": _team_logo(team, own_logos) if team else None,
            "base_team": team_ids.index(team["base_team"]) if team else index,
        })
    car_table = [
        {"index": STOCK_CARS + offset, "team": team_ids.index(car["team"]), "name": car["internal_name"], "based_on": car["based_on"]}
        for offset, (_, car) in enumerate(cars)
    ]
    return car_table, table


def _write_sheet(source, names, generated, sheet, path_of, box_of, cell):
    """Adds the art that mods give to these names to a sheet, and returns the names that had some."""
    found = {name: path_of(name) for name in names if source.in_mod(path_of(name))}
    if not found:
        return set()
    try:
        icons = {box_of(name): source.read(path) for name, path in found.items()}
        bog, bed = add_icons(source.read(f"{sheet}.bog"), source.read(f"{sheet}.bed"), icons, cell)
    except (BedError, IconError) as e:
        raise MergeError(str(e)) from e
    target = generated / sheet
    target.parent.mkdir(parents=True, exist_ok=True)
    target.with_suffix(".bog").write_bytes(bog)
    target.with_suffix(".bed").write_bytes(bed)
    return set(found)


@dataclass
class _Art:
    """The cars and teams that bring their own art, so the screens can point at it."""

    icons: set
    highlights: set
    portraits: set
    logos: set
    # On an overhaul, car name to its first frame, and to its own clip if its mod has one.
    garages: dict = field(default_factory=dict)
    clips: dict = field(default_factory=dict)


def _write_art(source, cars, teams, generated):
    car_names = [car["internal_name"] for _, car in cars]
    team_ids = [team["id"] for team in teams]
    same = lambda name: name
    icons = _write_sheet(source, car_names, generated, ICON_SHEET, icon_path, same, ICON_CELL)
    highlights = _write_sheet(source, car_names, generated, HIGHLIGHT_SHEET, highlight_path, highlight_box, ICON_CELL)
    logos = _write_sheet(source, team_ids, generated, TEAM_LOGO_SHEET, logo_path, same, LOGO_CELL)
    # A team with no art here is still safe: the DLL retries a missing box with the base team's.
    _write_sheet(source, team_ids, generated, TEAM_NAME_SHEET, team_name_path, same, TEAM_NAME_CELL)
    portraits = {car["internal_name"] for _, car in cars if source.in_mod(f"{_portrait(car)}.bog")}
    return _Art(icons, highlights, portraits, logos)


def _rim_table(source, cars, team_rims):
    """Each car's rim colour by car name, leaving out yellow, the colour every wheel has.

    The game has a rim texture for each stock team but never picks it, so with `team_rims` a car
    in a stock team gets its team's colour. A mod car's own `rim_colour` wins. The DLL picks the
    wheels by the car's own name, which stays when the Smashmouth cheat loads another model, so a
    cheat model needs no entry.
    """
    team_rim = lambda team: STOCK_TEAMS.index(team) if team_rims and team in STOCK_TEAMS else 0
    rims = {}
    # Stock cars are yellow without team rims, so only then does the car list need reading.
    for element in CAR_ELEMENT.findall(source.text(CAR_INFO)) if team_rims else []:
        rims[_attribute(element, "internal_name")] = team_rim(_attribute(element, "team_name"))
    for _, car in cars:
        rims[car["internal_name"]] = RIM_COLOURS.index(car["rim_colour"]) if "rim_colour" in car else team_rim(car["team"])
    return {name: rim for name, rim in rims.items() if rim}


def _write_rim_models(source, rims, generated):
    """All wheels share one texture, so a rim colour needs wheel models with its own material."""
    for rim in set(rims.values()):
        for level in WHEEL_LEVELS:
            name = f"generic_wheel_{level}.rom"
            wheel = read_rom(source.read(f"{WHEEL_FOLDER}/{name}"))
            # Only the digit changes, because the stock name runs past the 19 letters Material allows.
            wheel.materials[0].record = wheel.materials[0].record.replace(WHEEL_TEXTURE + b"0", WHEEL_TEXTURE + b"%d" % rim, 1)
            target = generated / WHEEL_FOLDER / f"rim_{rim}" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(write_rom(wheel))


def _write_lists(source, cars, teams, generated):
    text = source.text(CAR_INFO)
    elements = CAR_ELEMENT.findall(text)
    if len(elements) != STOCK_CARS:
        raise MergeError(f"{CAR_INFO} has {len(elements)} cars, and the tool needs the stock {STOCK_CARS}")
    stock = [(_attribute(e, "internal_name"), _attribute(e, "team_name")) for e in elements]
    stock_names = [name for name, _ in stock]
    stock_alternates = {match.group(1) for match in map(ALTERNATE_NAME.search, elements) if match}
    team_ids = _check_teams(teams, source)
    _check_cars(cars, stock_names, stock_alternates)
    rows = _make_rows(stock, cars, team_ids)
    _check_team_cars(teams, cars, rows)
    leaders = {team["leader"] for team in teams}
    art = _write_art(source, cars, teams, generated)
    art.garages, art.clips = _write_garages(source, cars, rows, teams, stock_names, generated)
    _write_generated(generated, CAR_INFO, _edit_car_info(text, elements, cars, leaders, art.icons))
    for rel in SCREENS:
        _write_generated(generated, rel, _edit_screen(source.text(rel), cars, rows, teams, rel, art, stock_names))
    _write_team_effects(source, teams, generated)
    return _session_tables(cars, teams, rows, art.logos)


def _write_text(game, source, folders, new_texts, generated):
    edits_by_mod = [mod_strings(folder) for folder in folders]
    if not any(edits_by_mod) and not new_texts:
        return {}
    ids = load_string_ids((Path(game) / STOCK_EXE).read_bytes())
    new_ids = new_text_ids(list(new_texts))
    for language in LANGUAGES:
        merged = {}
        for edits in edits_by_mod:
            merged.update(resolve_edits(edits, language))
        merged.update(new_texts)
        if not merged:
            continue
        rel = msg_path(language)
        try:
            data = apply_edits(source.read(rel), merged, ids, new_ids)
        except KeyError as e:
            raise MergeError(f"Unknown text ID {e.args[0]}") from e
        target = generated / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return new_ids


def _write_physics(source, folders, cars, generated):
    """Overhauls retune every car, so physics from a mod made on the stock game move onto the overhaul's base car."""
    stock = stock_physics()
    based_on = {own: car["based_on"] for _, car in cars for own in _own_names(car)}
    found = {}
    for folder in folders:
        for rel in mod_files(folder):
            match = CAR_PARAMS.fullmatch(rel)
            if match:
                found.setdefault(rel.lower(), (rel, match.group(1).lower()))
    for rel, car in found.values():
        if (source.winner(rel) / OVERHAUL_TAG).is_file():
            continue
        base = based_on.get(car, car)
        base_rel = f"cars/{base}/cache/{base}.params"
        if base in NOT_REBASED or base not in stock or not source.game_has(base_rel):
            continue
        try:
            text = rebase(source.text(rel), stock[base], source.game_read(base_rel).decode(ENCODING))
        except PhysicsError:
            # The mod's own file still loads, which is better than refusing Play over one odd file.
            continue
        target = generated / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode(ENCODING))


def _check_paths(mods_dir, save_dir, out_dir):
    """The game opens paths with ANSI calls, and the DLL passes it UTF-8 bytes."""
    for path in (Path(mods_dir).resolve(), Path(save_dir).resolve(), out_dir):
        if not str(path).isascii():
            raise MergeError(f"The game cannot open {path}. Set WRMOD_DATA to a folder with a plain English path.")


def _mod_folders(mods_dir, active):
    folders = []
    for mod in active:
        folder = Path(mods_dir) / mod
        if not (folder / MANIFEST).is_file():
            raise MergeError(f"Mod {mod} is not installed")
        folders.append(folder)
    return folders


def build_session(game, mods_dir, active, save_dir, out_dir, options=None):
    """Write session.json and generated files to out_dir, and return the session path.

    `options` comes from `options.from_settings`. Without it, WRSE leaves input and the window stock.
    """
    out_dir = Path(out_dir).resolve()
    _check_paths(mods_dir, save_dir, out_dir)
    folders = _mod_folders(mods_dir, active)
    generated = out_dir / GENERATED_DIR
    shutil.rmtree(generated, ignore_errors=True)
    generated.mkdir(parents=True)

    source = _Source(game, folders)
    cars, teams = _read_mod_lists(folders)
    car_table, team_table = [], []
    if cars or teams:
        car_table, team_table = _write_lists(source, cars, teams, generated)
    text = _write_text(game, source, folders, _new_texts(cars), generated)
    rims = _rim_table(source, cars, options is not None and options["team_rims"])
    _write_rim_models(source, rims, generated)
    if is_overhaul(game):
        _write_physics(source, folders, cars, generated)

    file_roots = [folder / FILES_DIR for folder in reversed(folders) if (folder / FILES_DIR).is_dir()]
    session = {
        "format": SESSION_FORMAT,
        "roots": [generated.as_posix()] + [root.resolve().as_posix() for root in file_roots],
        "save_dir": Path(save_dir).resolve().as_posix(),
        "log_path": (out_dir / LOG_FILE).as_posix(),
        "cars": car_table,
        "teams": team_table,
        "text": text,
        "rims": rims,
    }
    if options is not None:
        session.update(session_fields(options))
    path = out_dir / SESSION_FILE
    path.write_text(json.dumps(session, indent=2), encoding="utf-8")
    return path
