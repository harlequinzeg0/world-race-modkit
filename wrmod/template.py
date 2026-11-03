"""Turn a stock car into an editable project, and a project into a mod zip.

Project layout:
  mod.json                                  mod details
  files/<archive path>                      text and raw files
  textures/<archive path>.dds               editable texture
  textures/<archive path>.bogmeta.json      original header and export hash
  reference/car_info_entry.xml              the car's stock entry, for reading
  strings.json                              optional text changes
  cars.json                                 a new car's entry, if the project adds one

A zip leaves out anything identical to stock, except a new car, which needs all its files.
"""
import json
import os
import re
import zipfile
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from .gameinfo import RETAIL_SHA256
from .bark import Archive
from .bed import BedError
from .bog import BogError, bog_to_dds, dds_to_bog
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
    cell_of,
    check_icon,
    cut_icon,
    highlight_box,
    highlight_path,
    icon_path,
    logo_path,
    team_name_path,
)
from .modpack import (
    CARS,
    FILES_DIR,
    FORMAT_VERSION,
    MANIFEST,
    NAME_PATTERN,
    STRINGS,
    TEAMS,
    ModError,
    ModInfo,
    parse_mod_json,
    validate_zip,
)

CAR_INFO = "misc/cache/car_info.xml"
TEXTURES_DIR = "textures"
REFERENCE_DIR = "reference"
DDS_SUFFIX = ".dds"
META_SUFFIX = ".bogmeta.json"
TEXTURE_FOLDER_PREFIX = "tex"
HIGH_TEXTURES = "tex_high"
LOW_TEXTURES = "tex_low"


class ProjectError(Exception):
    pass


def list_stock_cars(game):
    text = Archive(game).read(CAR_INFO).decode("latin-1")
    return re.findall(r'<CAR\s+internal_name="([^"]+)"', text)


def _car_paths(archive, car):
    prefix = f"cars/{car}/".lower()
    paths = [p for p in archive.paths() if p.lower().startswith(prefix)]
    for extra in (f"frontend/{car}_movie.bog", f"player_textures/cache/player_{car}.bog"):
        if archive.has(extra):
            paths.append(extra)
    return paths


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _export_texture(project, path, bog, **extra):
    dds = bog_to_dds(bog)
    _write(project / TEXTURES_DIR / (path + DDS_SUFFIX), dds)
    meta = {"header_hex": bog[:56].hex(), "exported_sha256": sha256(dds).hexdigest(), **extra}
    _write(project / TEXTURES_DIR / (path + META_SUFFIX), json.dumps(meta, indent=2).encode())


def _export_cell(project, archive, sheet, box, path, cell):
    """A cell is a part of a shared sheet, so it has no stock file to fall back on when unedited."""
    if (project / TEXTURES_DIR / (path + DDS_SUFFIX)).exists():
        return
    try:
        art = cut_icon(archive.read(f"{sheet}.bog"), archive.read(f"{sheet}.bed"), box, cell)
    except (BedError, IconError) as e:
        raise ProjectError(f"Cannot read {sheet}: {e}") from e
    if art is not None:
        _export_texture(project, path, art)


def _export_icons(project, archive, base, new):
    _export_cell(project, archive, ICON_SHEET, base, icon_path(new), ICON_CELL)
    _export_cell(project, archive, HIGHLIGHT_SHEET, highlight_box(base), highlight_path(new), ICON_CELL)


def _export_team_art(project, archive, base, team):
    _export_cell(project, archive, TEAM_LOGO_SHEET, STOCK_LOGO_BOXES[base], logo_path(team), LOGO_CELL)
    _export_cell(project, archive, TEAM_NAME_SHEET, base, team_name_path(team), TEAM_NAME_CELL)


def _read_list(project, name):
    path = project / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def add_missing_art(game, project):
    """Gives a project the art to paint, for projects made before the tool wrote it."""
    project = Path(project)
    cars, teams = _read_list(project, CARS), _read_list(project, TEAMS)
    if not cars and not teams:
        return
    archive = Archive(game)
    for car in cars:
        _export_icons(project, archive, car["based_on"], car["internal_name"])
    for team in teams:
        if team["base_team"] in STOCK_LOGO_BOXES:
            _export_team_art(project, archive, team["base_team"], team["id"])


def add_team(game, project, display_name, base_team):
    """Makes a team around a new car project's cars, and returns the team's id."""
    project = Path(project)
    cars = _read_list(project, CARS)
    if not cars:
        raise ProjectError("A team needs a new car. Make one first, or open a new car project.")
    if _read_list(project, TEAMS):
        raise ProjectError("This project already has a team.")
    if base_team not in STOCK_LOGO_BOXES:
        raise ProjectError(f"The base team must be a stock team, not {base_team}")
    team_id = re.sub(r"[^a-z0-9]+", "_", display_name.lower()).strip("_")
    if not NAME_PATTERN.match(team_id):
        raise ProjectError(f"Bad team name: {display_name!r}")
    if team_id in STOCK_LOGO_BOXES:
        raise ProjectError(f"{team_id} is already a stock team")
    for car in cars:
        car["team"] = team_id
        car["ai_car"] = True
    team = {"id": team_id, "display_name": display_name.strip(), "leader": cars[0]["internal_name"], "base_team": base_team}
    _export_team_art(project, Archive(game), base_team, team_id)
    _write(project / CARS, json.dumps(cars, indent=2).encode())
    _write(project / TEAMS, json.dumps([team], indent=2).encode())
    return team_id


def _write_reference(project, archive, car):
    entry = re.search(rb'<CAR\s+internal_name="' + re.escape(car.encode()) + rb'"[^>]*/>', archive.read(CAR_INFO))
    _write(project / REFERENCE_DIR / "car_info_entry.xml", entry.group(0))


def _write_details(project, car):
    info = ModInfo(
        format_version=FORMAT_VERSION,
        id=f"{car}_mod".lower(),
        name=f"{car} mod",
        version="1.0",
        author="",
        description="",
        kind="car",
        requires_game=RETAIL_SHA256,
    )
    _write(project / MANIFEST, json.dumps(asdict(info), indent=2).encode())


def create_car_project(game, car, dest, progress=None):
    dest = Path(dest)
    archive = Archive(game)
    if car not in list_stock_cars(game):
        raise ProjectError(f"No stock car named {car}")
    if dest.exists():
        raise ProjectError(f"{dest} already exists")

    paths = _car_paths(archive, car)
    for done, path in enumerate(paths, start=1):
        data = archive.read(path)
        if path.lower().endswith(".bog"):
            _export_texture(dest, path, data)
        else:
            _write(dest / FILES_DIR / path, data)
        if progress:
            progress(done, len(paths))

    _write_reference(dest, archive, car)
    _write_details(dest, car)
    return dest


def _renamed_path(path, base, new):
    parts = path.split("/")
    if parts[0].lower() == "cars":
        parts[1] = new
    parts[-1] = re.sub(re.escape(base), new, parts[-1], flags=re.IGNORECASE)
    return "/".join(parts)


def _base_name_path(path, base, new):
    """A model names its textures, so the new folder needs them under the base car's names too."""
    parts = path.split("/")
    is_car_texture = parts[0].lower() == "cars" and parts[-2].lower().startswith(TEXTURE_FOLDER_PREFIX)
    if not is_car_texture or base.lower() not in parts[-1].lower():
        return None
    parts[1] = new
    return "/".join(parts)


def create_new_car_project(game, base, new_name, team, dest, progress=None):
    dest = Path(dest)
    archive = Archive(game)
    stock_cars = list_stock_cars(game)
    if base not in stock_cars:
        raise ProjectError(f"No stock car named {base}")
    if not NAME_PATTERN.match(new_name):
        raise ProjectError(f"Bad car name: {new_name!r}. Use lower case letters, digits and underscores.")
    if new_name in stock_cars:
        raise ProjectError(f"{new_name} is already a stock car")
    if not NAME_PATTERN.match(team):
        raise ProjectError(f"Bad team name: {team!r}")
    if dest.exists():
        raise ProjectError(f"{dest} already exists")

    paths = _car_paths(archive, base)
    for done, path in enumerate(paths, start=1):
        data = archive.read(path)
        target = _renamed_path(path, base, new_name)
        if path.lower().endswith(".bog"):
            alias = _base_name_path(path, base, new_name)
            _export_texture(dest, target, data, source=path, aliases=[alias] if alias else [])
        else:
            _write(dest / FILES_DIR / target, data)
        if progress:
            progress(done, len(paths))

    _export_icons(dest, archive, base, new_name)
    _write_reference(dest, archive, base)
    _write_details(dest, new_name)
    car = {
        "internal_name": new_name,
        "team": team,
        "display_name": new_name.replace("_", " ").upper(),
        "based_on": base,
        "ai_car": False,
    }
    _write(dest / CARS, json.dumps([car], indent=2).encode())
    return dest


def _file_changes(project, archive):
    root = project / FILES_DIR
    if not root.is_dir():
        return {}
    changes = {}
    for source in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = source.relative_to(root).as_posix()
        data = source.read_bytes()
        if not archive.has(rel) or archive.read(rel) != data:
            changes[rel] = data
    return changes


@dataclass
class _Texture:
    """dds is None for an unedited new car texture, which goes in the zip from `source`."""
    dds: bytes | None
    header: bytes | None
    source: str | None
    aliases: list


def _low_twin(root, rel):
    """AI cars read tex_low, so a new texture must be there too unless it has its own low version."""
    low = rel.replace(f"/{HIGH_TEXTURES}/", f"/{LOW_TEXTURES}/")
    return [low] if low != rel and not (root / (low + DDS_SUFFIX)).exists() else []


def _texture_changes(project):
    root = project / TEXTURES_DIR
    if not root.is_dir():
        return {}
    changes = {}
    for path in sorted(root.rglob("*" + DDS_SUFFIX)):
        rel = path.relative_to(root).as_posix()[:-len(DDS_SUFFIX)]
        data = path.read_bytes()
        meta_path = path.with_name(path.name[:-len(DDS_SUFFIX)] + META_SUFFIX)
        meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
        source, aliases = meta.get("source"), meta.get("aliases", _low_twin(root, rel))
        if meta and sha256(data).hexdigest() == meta["exported_sha256"]:
            if source:
                changes[rel] = _Texture(None, None, source, aliases)
            continue
        header = bytes.fromhex(meta["header_hex"]) if meta else None
        changes[rel] = _Texture(data, header, source, aliases)
    return changes


def changed_files(project, game):
    project = Path(project)
    return sorted({*_file_changes(project, Archive(game)), *_texture_changes(project)})


def _texture_bog(rel, texture, archive):
    if texture.dds is None:
        return archive.read(texture.source)
    try:
        bog = dds_to_bog(texture.dds, texture.header)
        cell = cell_of(rel)
        if cell:
            check_icon(rel, bog, cell)
        return bog
    except (BogError, IconError) as e:
        raise ProjectError(f"{rel}: {e}") from e


def build_mod_zip(project, game, out):
    project, out = Path(project), Path(out)
    game_files = Archive(game)
    files = _file_changes(project, game_files)
    textures = _texture_changes(project)
    lists = [name for name in (STRINGS, CARS, TEAMS) if (project / name).is_file()]
    if not files and not textures and not lists:
        raise ProjectError("nothing changed, so there is nothing to build")

    manifest = (project / MANIFEST).read_bytes()
    temp = out.with_name(out.name + ".tmp")
    try:
        parse_mod_json(manifest)
        for rel, texture in textures.items():
            bog = _texture_bog(rel, texture, game_files)
            files[rel] = bog
            files.update((alias, bog) for alias in texture.aliases)
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(MANIFEST, manifest)
            for name in lists:
                archive.writestr(name, (project / name).read_bytes())
            for rel, data in files.items():
                archive.writestr(f"{FILES_DIR}/{rel}", data)
        validate_zip(temp)
        os.replace(temp, out)
    except ModError as e:
        raise ProjectError(str(e)) from e
    finally:
        temp.unlink(missing_ok=True)
    return out
