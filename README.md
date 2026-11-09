# World Race Mod Manager

A mod manager and mod-making tool for the LGU Release by Bladez1992 of Hot Wheels World Race (PC, 2003). It also supports the NitroXFueled 1.3 overhaul. Players add mod zips, choose which are active, and press Play. Modders start from a stock car, edit it in normal tools, and build a zip to share.

You need your own copy of the game. This project contains no game files. The only game data it ships is the physics numbers of the stock cars, which the NitroXFueled support needs.

## Install

1. Install [uv](https://docs.astral.sh/uv/) once. In PowerShell:

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

2. Double-click `WorldRaceModkit.bat`. The first start downloads Python and Qt, which takes a few minutes.
3. Choose your game folder: the stock game or NitroXFueled. It must have the retail EXE, and you must have run the game's launcher once, so that `Config.cfg` exists.

The tool refuses a game inside Program Files, because Windows may redirect the game's saves there. It offers to copy the game to another folder instead.

## Play with mods

Add a mod zip, then move it to the active list. If two active mods change the same file or text, the tool warns you, and the mod lower in the list wins.

### Always start the game from the tool

To play with mods, press Play in the tool. Do not start `HotWheelsWorldRace.exe`, the launcher, or a shortcut yourself. If you do, the game runs stock: no mods load, and it uses the stock save, not your profile's save. The mods reach the game only through the files that Play puts in place for that one run (see below).

While the game runs, the tool locks the profile list. Close the game before you change profiles.

### Profiles and saves

A profile is a list of active mods with its own save.

- **Stock** runs the unmodified game with the game's own save in `<game folder>\saves`. It cannot hold mods, and you cannot rename or delete it.
- **Every other profile** keeps its save in `%LOCALAPPDATA%\WorldRaceModkit\profiles\<name>\save\HOTWHEEL\PROGRESS`. A new profile starts with fresh progress. The tool does not copy the stock save into it.
- **Duplicate** copies the mod list only. The new profile starts with fresh progress.
- **Rename** keeps the save. **Delete** removes the profile and its save, after it asks you.
- You can turn mods on and off and keep the profile's save. Added cars and teams do not change the save format.
- To back up a profile's progress, copy its `PROGRESS` file while the game is closed. To start a profile with your stock progress, copy `<game folder>\saves\HOTWHEEL\PROGRESS` into the profile's `save\HOTWHEEL` folder.

The tool keeps all its data in `%LOCALAPPDATA%\WorldRaceModkit`: `mods`, `profiles` and `settings.json`, which remembers the game folder. To use a different folder, set `WRMOD_DATA` before you start the tool.

### NitroXFueled and other overhauls

NitroXFueled 1.3 runs on the same EXE as the stock game, but it has no `harchive.bah` and runs on loose files. For a game folder like that, the tool uses the loose files as the base, so mods merge on top of the overhaul's changes. A game folder with `harchive.bah` uses the archive, as before.

On NitroXFueled, added cars and teams get:

- Their icons, logos and team names added to the overhaul's HD art, so Results and car select show every team.
- On car select, their still picture in their team's garage, or the mod's own render clip if it has one. See [docs/making-mods.md](docs/making-mods.md).
- The logo of their own team, although the overhaul orders its car list differently.

NitroXFueled also changes the physics of every car. A mod made on the stock game would be much slower there. When you press Play on NitroXFueled, the tool moves the physics of each such mod's cars onto the overhaul's version of the base car. The mod's own changes stay, as a share of the stock values, and its wheels stay as they are. A mod made on NitroXFueled has a `nitroxfueled.tag` file, and the tool leaves its physics as they are. See [docs/making-mods.md](docs/making-mods.md).

An overhaul's save can be different from a stock save. NitroXFueled crashes on a stock save. Profiles are shared between game folders, so give each game its own data folder:

```powershell
$env:WRMOD_DATA = "D:\WorldRaceModkit-NitroXFueled"; .\WorldRaceModkit.bat
```

### What Play does

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
uv run --script worldrace.py alternate PROJECT_FOLDER neon_mill_movie --game PATH
uv run --script worldrace.py addon world_race_models.zip
uv run --script worldrace.py build PROJECT_FOLDER mod.zip --game PATH
uv run --script worldrace.py install mod.zip
uv run --script worldrace.py play PROFILE --game PATH
uv run --script worldrace.py recover --game PATH
```

## Status

Works now: texture, physics and text mods, new cars beside the stock ones, new car bodies through a Blender 4.5 add-on, car icons, new teams, new cars and teams as AI opponents, zips, profiles, Play on the unchanged stock EXE, and the NitroXFueled 1.3 overhaul.

Not tested yet: a mod's own render clip in the game. On NitroXFueled, new car projects made from an overhaul car do not yet export its PNG and JPEG textures for editing.

Not tested yet in a race: a hitbox edited in Blender, and a car's own Smashmouth cheat model.

Not done yet: custom wheel models, effects refitted to a new body, and new tracks. Tracks depend on decoding the game's track format.

## Development

```text
uv run --no-project --with pytest --with PySide6-Essentials --with Pillow pytest
```

Tests that need the game are skipped unless `WRMOD_GAME` points at a game folder. Tests that need Blender 4.5 are skipped if it is not installed, and `WRMOD_BLENDER` can point at it. Do not commit game files or extracted data.

The base mod needs Rust with the `i686-pc-windows-msvc` target. Run these from `base_mod/`, then copy the DLL to `wrmod/bin/`:

```text
cargo test
cargo build --release --target i686-pc-windows-msvc
```
