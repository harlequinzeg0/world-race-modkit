# World Race Mod Manager

A mod manager and mod-making tool for Hot Wheels World Race (PC, 2003). Players add mod zips, choose which are active, and press Play. Modders start from a stock car, edit it in normal tools, and build a zip to share.

You need your own copy of the game. This project contains no game files.

## Install

1. Install [uv](https://docs.astral.sh/uv/) once. In PowerShell:

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

2. Double-click `WorldRaceModkit.bat`. The first start downloads Python and Qt, which takes a few minutes.
3. Choose your game folder. It must be the retail build, and you must have run the game's launcher once, so that `Config.cfg` exists.

The tool refuses a game inside Program Files, because Windows may redirect the game's saves there. It offers to copy the game to another folder instead.

## Play with mods

Add a mod zip, then move it to the active list. If two active mods change the same file or text, the tool warns you, and the mod lower in the list wins.

Each profile has its own mod list and its own save, and starts with fresh progress. The Stock profile runs the unmodified game with your normal save.

The tool never changes your original EXE, `harchive`, or stock save. Mods stay in the tool's data folder, and each profile's save stays in its profile folder. When you press Play, it:

1. Merges the active mods into a session folder.
2. Copies the base mod, `dinput8.dll`, into the game folder.
3. Starts the stock game with that session.
4. When the game exits, removes `dinput8.dll`.

The base mod is the World Race Script Extender, in `base_mod/`. It loads with the game, serves mod files from their own folders, moves saves to the profile, and adds cars and teams. With no session it only forwards input calls, so a leftover copy leaves the game stock. If the tool finds another program's `dinput8.dll` in the game folder, it stops and leaves that file alone.

If the game or the tool crashes, the tool removes the DLL at its next start. You can also run `worldrace.py recover`.

## Make a mod

See [docs/making-mods.md](docs/making-mods.md).

## Command line

Every core action works without the window:

```text
uv run --script worldrace.py list --game PATH
uv run --script worldrace.py extract OUT --game PATH
uv run --script worldrace.py bog2dds IN.bog OUT.dds
uv run --script worldrace.py dds2bog IN.dds OUT.bog --like ORIGINAL.bog
uv run --script worldrace.py template twin_mill PROJECT_FOLDER --game PATH
uv run --script worldrace.py newcar ballistic neon_mill road_beasts PROJECT_FOLDER --game PATH
uv run --script worldrace.py addon world_race_models.zip
uv run --script worldrace.py build PROJECT_FOLDER mod.zip --game PATH
uv run --script worldrace.py install mod.zip
uv run --script worldrace.py play PROFILE --game PATH
uv run --script worldrace.py recover --game PATH
```

## Status

Works now: texture, physics and text mods, new cars beside the stock ones, new car bodies through a Blender add-on, car icons, new teams, new cars and teams as AI opponents, zips, profiles, and Play on the unchanged stock EXE.

Not done yet: custom wheel models, effects refitted to a new body, new collision shapes, and new tracks. Tracks depend on decoding the game's track format. See [docs/FINDINGS.md](docs/FINDINGS.md) for the reverse engineering notes.

## Development

```text
uv run --no-project --with pytest --with PySide6-Essentials pytest
```

Tests that need the game are skipped unless `WRMOD_GAME` points at a game folder. Tests that need Blender 4.5 are skipped if it is not installed, and `WRMOD_BLENDER` can point at it. Do not commit game files or extracted data.

The base mod needs Rust with the `i686-pc-windows-msvc` target. Run these from `base_mod/`, then copy the DLL to `wrmod/bin/`:

```text
cargo test
cargo build --release --target i686-pc-windows-msvc
```
