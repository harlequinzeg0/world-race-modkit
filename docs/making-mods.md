# Making mods

A mod can change a stock car, add a new car beside the originals, or add a new team.

## Start a project

1. Open the **Make a mod** tab.
2. Pick a stock car and press **Start from this car**.
3. Choose a folder. The tool creates a project there and fills in the details form.

A project looks like this:

```text
mod.json                 mod details, edited by the form
files/...                text and raw game files
textures/...             textures as DDS
reference/               the car's stock listing, for reading only
strings.json             optional text changes, which you add yourself
```

Paths under `files/` and `textures/` match the game's own paths. Leave the folders and names as they are.

## Add a new car

1. In the **Make a mod** tab, pick the stock car to start from.
2. Type a **New car name**, in lower case letters, digits and underscores, such as `neon_mill`.
3. Choose a team, and press **New car based on this one**.

The project holds a full copy of the car under the new name, plus `cars.json`:

```json
[
  {
    "internal_name": "neon_mill",
    "team": "road_beasts",
    "display_name": "NEON MILL",
    "based_on": "ballistic",
    "ai_car": false,
    "driver": "RICK ROD",
    "rim_colour": "red",
    "speed": 5
  }
]
```

`display_name` is the name shown in the game. `driver` is optional, and sets the driver's name on the car select screen. Without it, the car shows the `based_on` car's driver. The driver's face stays the base car's. `rim_colour` is optional, and sets the ring on the car's wheels to `yellow`, `green`, `silver`, `blue` or `red`. Without it, the rims are yellow, like every stock car. `speed`, `grip`, `boost` and `accel` are optional, and run from 0 to 10. They set the bars on the car select screen. Other values come from the `based_on` car. Set `ai_car` to `true` to let the car race as an opponent.

A new car starts unlocked, is never written to the save, and uses the `based_on` car's model until you change the files. Edit the skin at `textures/cars/<new name>/cache/tex_high/<new name>.bog.dds`. The tool writes it under the base car's name too, because the model asks for that name.

A zip for a new car holds all of the car's files, so it is much larger than a zip that changes a stock car.

## Give a new car its own body in Blender

You need Blender 4.5.

1. In the **Make a mod** tab, press **Save Blender add-on**.
2. In Blender, open Edit > Preferences > Add-ons, then the arrow at the top right > **Install from Disk**, and choose the zip.
3. Make a new car project in the tool, as above.
4. In Blender, choose File > Import > **World Race Model**, and open `files/cars/<new name>/cache/<new name>_med.rom` in your project.
5. Edit the body, or delete it and bring in your own. Assign a material to each mesh, and make sure it has a UV map.
6. Choose File > Export > **World Race Car**, and pick your project folder.
7. Paint your textures, then build the zip in the tool as usual.

If a project holds more than one car, export writes the car that you imported into the scene. Keep one of the project's cars in a scene. Export refuses a scene that has two of them, or none.

Export replaces the three detail levels, fits the shadow to the new body, and updates the named points and wheels. Every visible mesh in the scene goes in, except the wheels and brake lights, so hide anything you want left out. The lower detail levels are automatic reductions of your body.

**More than one texture:** a car can use several. Give each part its own material, and name the material after the texture file, in up to 19 lower case letters, digits and underscores, such as `wild_thing_engine`. Export adds the material to the car. If the texture does not exist yet, export writes a plain grey image at `textures/cars/<new name>/cache/tex_high/<material>.bog.dds`, and tells you. Paint over it and save it as DXT1 or DXT5. Build also puts it in `tex_low` for AI cars. To give AI cars a smaller version, add your own file in `tex_low`.

The car's main skin has `_stunt`, `_combo` and `_reward` versions: small "hot" images, tinted orange and red, that the game fades to while those timed effects run. Extra textures have no such versions.

**Scale and position:** match the base car you imported, and keep it as a guide while you place your body. Cars face -Y. Stock cars run from 3.9 to 5.8 units long. Collision does not move with the body, so choose a base car of about the right size. On Ballistik the wheel centres are at Z -0.29, and the tyres meet the ground near Z -0.72.

**Named points:** the empties called `tag_...` that you imported from your project mark the headlights and tail lights, at the place the game draws them. Move them to fit your body. Empties that come in with another model are ignored at export. If your scene still has a `tag_com` empty from an older import, it does nothing, and you can delete it.

**Light colours:** the small lights you see on a car from a distance are flares at two kinds of named point. `tag_backlight ...` is a taillight and `tag_headlight ...` is a headlight. The numbers in the name are the light's strength, then its red, green and blue. New cars keep the base car's colours, because stock taillights follow the team. To change a colour, select the empty, open Object Properties > Custom Properties, and use the `rom_light_colour` swatch. Each light has its own empty, so change both sides. The name in Blender stays the same, but export writes the new colour to the game's files.

The steady red lamps on the body are part of the skin texture, so paint those.

**Wheels:** import also brings in four cylinders called `wheel_...`. They show where the game draws each wheel, at the size it draws them. Move and scale them to fit your body, and export writes the new values to `<new name>.params`. Each wheel is separate, so change the left and right wheels by the same amount.

- For a scene that has no wheels, choose File > Import > **World Race Model** and open `<new name>.params`. This adds only the wheels.
- The cylinders are stand-ins. All cars share one wheel model, and the game draws that model in their place.
- Rotation is locked, because the game turns the wheels itself.
- Wheel size and place probably also change how the car drives. A small radius may let the car sit lower, so test it in a race.
- Wheels that come in with another model are ignored at export.

**Brake lights:** import also brings in a collection called `<new name>_brakelights`. These are separate models, and the game draws them only while the car brakes. Move them to fit your body. Export writes them to `<new name>_brakelights_high.rom` for your car and `<new name>_brakelights_low.rom` for AI cars.

- They use the shared texture `TLANG_lightning`, and their red comes from vertex colours. The normal Blender view shows neither, so they look plain there. Export keeps both.
- To add a light, duplicate a stock one, or move your own mesh into the collection. Your mesh needs a UV map. If it has no vertex colours, export makes it red.
- If the collection has no visible mesh, the car's brake light files stay as they are.
- The lights cannot use your own textures. The game opens these files with `cars/generic/cache` as the texture folder, so export refuses any other material.
- Lights that come in with another model are ignored at export. To use them, move them into your car's collection.
- To change their colour, select a light, switch to Vertex Paint mode, pick a colour and use Paint > Set Vertex Colors. To see the colour in Solid view, set Viewport Shading > Color to Attribute.
- The empties `tag_lefttaillight` and `tag_righttaillight` are separate from these models. Move them to match.

**Car select picture:** a new car shows a still picture, not a moving clip, on the single player screen. The multiplayer screen has no still, so it plays the base car's clip. Edit `textures/frontend/<new name>_movie.bog.dds`, then save it as DXT1 with mipmaps at 256×128. It starts as the base car's picture. The driver's portrait covers the left of the picture and the right edge fades, so keep your car near the middle.

To edit the wheel numbers by hand, see `WHEELOFFSET`, `WHEELRADIUS` and `WHEELWIDTH` in the `.params` file. In `WHEELOFFSET X Y Z`, X is left (-) and right (+), Y is up, and Z is forward. The visible radius is about 0.87 × `WHEELRADIUS`, and the visible width is about `WHEELWIDTH`.

**Car icon:** the icon shows in the Team Select bar, on Results and in the League standings. A new car project has two files to paint in `textures/frontend/`, and both start as the base car's. If you opened an older project, the tool adds them when you open it.

- `<new name>_icon.bog.dds` is the icon.
- `<new name>_icon_hlight.bog.dds` is the glow added on top when the car is selected. It adds light, so black shows nothing. Three stock cars have no highlight: Zotic, Golden Arrow and Silhouette II, so cars based on them have no file for it.

Save both as DXT5 at 96×48. An icon you do not change stays the base car's.

**Driver portrait:** paint `textures/player_textures/cache/player_<new name>.bog.dds`, then save it at 128×128 as DXT5. This one picture is the big head on the car select screens, and the game also uses it where it shows the player's face.

**What stays from the base car:**

- The wheel model.
- Collision, in the `.hsc` file.
- Effects, such as boost lightning, the nose cone and the combo rings. These are shaped for the base car, so they may not line up.

Cars have no rig, so there is no weight painting. Tests raced a body of 71,000 triangles, about 24 times a stock car, on one machine. A mesh is limited to 65,535 vertices.

## Add a new team

1. Make a new car project, or open one.
2. In the **Make a mod** tab, type a **New team name**, and choose a team for **Based on**.
3. Press **Make a team for this car**. The car moves to the new team, and it can now race as an opponent.
4. To add more cars, make more new car projects, and type the team's id in **Team**. The id is the name in lower case with underscores, such as `neon_riders`. The tool shows it in that box after step 3.

The new team takes its effects and its stage on the League podium from the team in **Based on**.

**Team art:** the project has two files to paint in `textures/frontend/`, and both start as the base team's. Save them as DXT5. An image you do not change stays the base team's.

- `<team id>_logo.bog.dds` is the big logo on Team Select, at 128×96.
- `<team id>_team_name.bog.dds` is the team's name as a picture, at 128×32. It shows on Results.

**By hand:** the button writes `teams.json`, which you can edit:

```json
[
  {
    "id": "neon_riders",
    "display_name": "Neon Riders",
    "leader": "neon_mill",
    "base_team": "road_beasts"
  }
]
```

Set `team` in `cars.json` to the team's `id` for each of its cars. The cars can come from different mods. A team needs at least one car with `ai_car` set to `true`, and `leader` must be one of its cars.

`base_team` is a stock team: `dune_rats`, `street_breed`, `road_beasts`, `wave_rippers` or `scorchers`. To change an effect, add your own file, such as `files/cars/effects/cache/stunt_neon_riders.xml`.

An optional `logo` field names a box on another sprite sheet, such as `{ "texture": "misc/cache/flash", "box": "flash_1" }`. A painted logo file wins over it.

The game allows up to 16 teams, and up to 16 cars in a team. Tests reached 6 teams and 9 cars.

## Edit textures

Open a `.dds` file from `textures/` in Photoshop or another editor that handles DDS. A car's main skin is `textures/cars/<car>/cache/tex_high/<car>.bog.dds`. The lower-detail copy is in `tex_low`, so change both.

**Save as DXT1, or DXT5 if the texture needs transparency.** The tool does not compress textures, so it refuses an uncompressed DDS. Stock car skins export as uncompressed because that is how they convert cleanly for editing, so remember to choose DXT when you save.

Tested in the game on a car skin slot: 1024×1024 and 512×256, with and without mipmaps. A full mip chain is still the better choice, because it looks cleaner at a distance.

## Edit physics

`files/cars/<car>/cache/<car>.params` is plain text. For example, `ENGINETORQUEMAX` sets engine power. Tripling it took Ballistik from 128 MPH to 176 MPH at the same point in a race.

## Change game text

Add a `strings.json` file to the project. Names are the game's internal text IDs:

```json
{
  "TWIN_MILL": "NEON MILL",
  "BACK_DRAFT": { "default": "SIDEWINDER", "french": "CROTALE" }
}
```

A plain string applies to all six languages. An object sets text by language: `english`, `usa`, `french`, `german`, `italian`, `spanish`, plus `default`.

## Build the zip

1. Press **Refresh** to see which files changed. Only those go in the zip, so it stays small and does not copy unchanged game files.
2. Fill in the details and press **Build zip**.
3. Add the zip in the **Play with mods** tab, activate it in a profile, and press Play.

To share a mod, upload the zip. Only share work that you have the right to share.

## Zip format

```text
mod.json        required
files/...       loose files at game paths
strings.json    optional
cars.json       optional
teams.json      optional
```

`mod.json` holds `format_version`, `id`, `name`, `version`, `author`, `description`, `kind` and `requires_game`. The game opens files under `movies/` and `sound/` directly, so a mod cannot replace them, and the tool shows a warning for those files. A mod cannot change saves. Mods cannot contain programs, such as `.exe` or `.dll` files, because the game would load them and run their code. Only the base mod is native code.
