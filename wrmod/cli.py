"""Command line for every core action."""
import argparse
import sys
from hashlib import sha256
from pathlib import Path

from . import addon, bark, bog, deploy, modpack, profiles, store, template
from .gamefiles import game_files
from .gameinfo import GameError, check_game_folder


class UsageError(Exception):
    pass


def _game(args):
    game = args.game or store.load_settings().get("game")
    if not game:
        raise UsageError("No game folder set. Pass --game PATH.")
    return Path(game)


def _cmd_list(args):
    for path in game_files(_game(args)).paths():
        print(path)


def _cmd_extract(args):
    bark.extract_all(_game(args), args.out, progress=lambda done, total: print(f"{done}/{total}", flush=True))


def _cmd_bog2dds(args):
    Path(args.out).write_bytes(bog.bog_to_dds(Path(args.input).read_bytes()))


def _cmd_dds2bog(args):
    dds = Path(args.input).read_bytes()
    if args.like:
        original = Path(args.like).read_bytes()
        unedited = sha256(bog.bog_to_dds(original)).hexdigest()
        data = bog.restore_bog(dds, unedited, original)
    else:
        data = bog.dds_to_bog(dds, None)
    Path(args.out).write_bytes(data)


def _cmd_template(args):
    print(template.create_car_project(_game(args), args.car, args.dest))


def _cmd_addon(args):
    print(addon.build_addon(args.out))


def _cmd_newcar(args):
    print(template.create_new_car_project(_game(args), args.base, args.name, args.team, args.dest))


def _cmd_build(args):
    print(template.build_mod_zip(args.project, _game(args), args.out))


def _cmd_install(args):
    info = modpack.install_zip(args.zip, store.mods_dir())
    print(f"Installed {info.name} ({info.id})")


def _cmd_play(args):
    game = _game(args)
    check_game_folder(game)
    profile = profiles.load(store.profiles_dir(), args.profile)
    for rel in deploy.ignored_files(store.mods_dir(), profile.active):
        print(f"warning: the game cannot load {rel} from a mod", file=sys.stderr)
    code = deploy.play(game, store.data_dir(), profile)
    print(f"Game exited with code {code}")


def _cmd_recover(args):
    fixed = deploy.restore(_game(args), store.data_dir())
    print("Restored the game folder." if fixed else "Nothing to restore.")


def _parser():
    parser = argparse.ArgumentParser(prog="worldrace", description="World Race Mod Manager")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, func, *arguments, game=True):
        command = sub.add_parser(name)
        for argument in arguments:
            command.add_argument(argument)
        if game:
            command.add_argument("--game")
        command.set_defaults(func=func)
        return command

    add("list", _cmd_list)
    add("extract", _cmd_extract, "out")
    add("bog2dds", _cmd_bog2dds, "input", "out", game=False)
    add("dds2bog", _cmd_dds2bog, "input", "out", game=False).add_argument("--like")
    add("template", _cmd_template, "car", "dest")
    add("newcar", _cmd_newcar, "base", "name", "team", "dest")
    add("addon", _cmd_addon, "out", game=False)
    add("build", _cmd_build, "project", "out")
    add("install", _cmd_install, "zip", game=False)
    add("play", _cmd_play, "profile")
    add("recover", _cmd_recover)
    return parser


def main(argv):
    args = _parser().parse_args(argv)
    try:
        args.func(args)
    except (
        UsageError,
        OSError,
        ValueError,
        GameError,
        bog.BogError,
        modpack.ModError,
        profiles.ProfileError,
        template.ProjectError,
        deploy.DeployError,
    ) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0
