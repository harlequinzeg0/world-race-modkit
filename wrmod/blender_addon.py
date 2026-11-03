"""Blender add-on: bring World Race cars in and out of Blender.

Blender runs this file, not the mod tool. `wrmod.addon` packages it with `rom.py` and `wheels.py`.

Import reads a .rom as a template. Export writes the scene into a car project made by the tool's
"New car based on this one": all detail levels, the shadow and the points file. The project's own
files are the templates, so its materials and named points stay.

Wheels come from the car's .params file as stand-ins, because the wheel model is game data and
stays out of the add-on. Export writes their place and size back to that file.

Brake lights are separate models. They come in as their own collection and go back to their own files.
"""
import importlib
import json
import math
import re
import struct
from pathlib import Path

import bpy
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector

from . import rom as rom_format
from . import wheels as wheel_format

# Installing an add-on again reruns only this file, so an open Blender would keep the old library.
importlib.reload(rom_format)
importlib.reload(wheel_format)

from .rom import COM_TAG, Material, Mesh, RomError, Vertex, centre_of_mass, read_rom, work_out_bounds, write_points, write_rom
from .wheels import params_radius, params_width, read_wheels, visible_radius, visible_width, write_wheels

bl_info = {
    "name": "World Race Models",
    "author": "Harlequinz Eg0",
    "version": (0, 1, 0),
    "blender": (4, 5, 0),
    "location": "File > Import and File > Export",
    "description": "Import and export Hot Wheels World Race car models",
    "category": "Import-Export",
}

BODY_FLAGS = 0x40
# Stock cars keep about these shares of their triangles at each detail level.
DETAIL_LEVELS = (("med", 1.0), ("lower_med", 0.68), ("low", 0.35))
SHADOW_LEVELS = ("high", "med", "lower_med")
# The player's car reads "high" and AI cars read "low". Most stock cars have one model in both.
BRAKE_LEVELS = ("high", "low")
BRAKE_FLAGS = 0x10
BRAKE_COLOUR = 0xFFFF0000
BRAKE_MARK = "rom_brake"
# Below this a mesh is a light or a trim, and stock cars keep those whole at every level.
MIN_FACES_TO_REDUCE = 40
MAX_MESH_VERTICES = 65535
TEXTURE_FOLDER = "tex_high"
UV_LAYER = "UVMap"
COLOUR_ATTRIBUTE = "Col"
DEFAULT_COLOUR = 0x84808080
DETAIL_MODIFIER = "WorldRaceDetail"
WELD_MODIFIER = "WorldRaceWeld"
WELD_DISTANCE = 0.0001
SAME_NORMAL = 0.999
# A material names a texture file. The record has 20 bytes for it, ending in a null.
MATERIAL_NAME = re.compile(r"[a-z0-9_]{1,19}")
# The game finds these in cars/generic, so a copy in the car's folder would hide the real one.
SHARED_TEXTURES = ("generic_headlight",)
PLACEHOLDER_SIZE = 64
PLACEHOLDER_COLOUR = 0x8410  # middle grey, in 5:6:5
# The game reads a light's strength and colour from the name of its point.
LIGHT_TAG = re.compile(r"((?:head|back)light \S+) (\d*\.?\d+) (\d*\.?\d+) (\d*\.?\d+)")
LIGHT_COLOUR = "rom_light_colour"
SAME_COLOUR = 0.005
WHEEL_NAMES = {0: "front_left", 1: "front_right", 2: "back_left", 3: "back_right"}
WHEEL_SEGMENTS = 32


class ExportError(Exception):
    pass


def to_blender(point):
    """The game is left-handed with Y up and Z forward. A Blender car faces -Y with Z up."""
    return (-point[0], -point[2], point[1])


def from_blender(point):
    return (-point[0], point[2], -point[1])


def _unpack_colour(value):
    return tuple(((value >> shift) & 0xFF) / 255 for shift in (16, 8, 0, 24))


def _pack_colour(colour):
    red, green, blue, alpha = (min(255, max(0, round(channel * 255))) for channel in colour)
    return alpha << 24 | red << 16 | green << 8 | blue


def _texture_path(rom_path, name):
    """A project keeps a car's textures in `textures/`, and the skin under the car's own name."""
    parts = Path(rom_path).parts
    if "files" not in parts:
        return None
    at = len(parts) - 1 - parts[::-1].index("files")
    folder = Path(*parts[:at]) / "textures" / Path(*parts[at + 1:-1]) / TEXTURE_FOLDER
    car = parts[at + 2] if len(parts) > at + 2 else name
    for stem in (name, car):
        path = folder / f"{stem}.bog.dds"
        if path.is_file():
            return path
    return None


def _make_material(name, rom_path):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    texture = _texture_path(rom_path, name)
    if texture is None or material.use_nodes:
        return material
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    node = material.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.load(str(texture), check_existing=True)
    material.node_tree.links.new(node.outputs["Color"], shader.inputs["Base Color"])
    return material


def _make_object(name, rom_mesh, order, material, collection):
    data = bpy.data.meshes.new(name)
    points = [to_blender(v.position) for v in rom_mesh.vertices]
    # The axis change mirrors the model, so the corner order must flip to stay facing out.
    faces = [(a, c, b) for a, b, c in rom_mesh.triangles]
    data.from_pydata(points, [], faces)
    corners = [corner for face in faces for corner in face]
    data.uv_layers.new(name=UV_LAYER)
    data.color_attributes.new(COLOUR_ATTRIBUTE, "BYTE_COLOR", "CORNER")
    # Adding a layer moves the others, so a reference taken earlier would be stale.
    uv = data.uv_layers[UV_LAYER]
    colour = data.color_attributes[COLOUR_ATTRIBUTE]
    for at, index in enumerate(corners):
        vertex = rom_mesh.vertices[index]
        uv.uv[at].vector = (vertex.uv[0], 1.0 - vertex.uv[1])
        colour.data[at].color_srgb = _unpack_colour(vertex.colour)
    data.normals_split_custom_set_from_vertices([to_blender(v.normal) for v in rom_mesh.vertices])
    data.update()
    if material is not None:
        data.materials.append(material)
    obj = bpy.data.objects.new(name, data)
    obj["rom_flags"] = rom_mesh.flags
    obj["rom_order"] = order
    collection.objects.link(obj)


def _wheel_shape(name):
    """A cylinder along X of radius 1 and width 1, so object scale reads as width, radius, radius."""
    count = WHEEL_SEGMENTS
    ring = [(math.cos(2 * math.pi * i / count), math.sin(2 * math.pi * i / count)) for i in range(count)]
    points = [(side, y, z) for side in (-0.5, 0.5) for y, z in ring]
    faces = [(i, (i + 1) % count, count + (i + 1) % count, count + i) for i in range(count)]
    faces += [tuple(reversed(range(count))), tuple(range(count, 2 * count))]
    data = bpy.data.meshes.new(name)
    data.from_pydata(points, [], faces)
    data.update()
    return data


def _make_wheel(car, wheel, collection):
    name = f"wheel_{WHEEL_NAMES.get(wheel.index, wheel.index)}"
    obj = bpy.data.objects.new(name, _wheel_shape(name))
    obj.location = to_blender(wheel.offset)
    radius = visible_radius(wheel)
    obj.scale = (visible_width(wheel), radius, radius)
    # The game turns wheels itself, so a rotation here would look like it counts and would not.
    obj.lock_rotation = (True, True, True)
    obj["rom_wheel"] = wheel.index
    obj["rom_car"] = car
    collection.objects.link(obj)


def add_wheels(context, path):
    """Returns the number of wheels added. A car's wheels already in the scene stay as they are."""
    car = Path(path).stem
    if any(o.get("rom_car") == car for o in context.scene.objects):
        return 0
    wheels = read_wheels(Path(path).read_bytes().decode("latin-1"))
    if wheels:
        collection = bpy.data.collections.new(f"{car}_wheels")
        context.scene.collection.children.link(collection)
        for wheel in wheels:
            _make_wheel(car, wheel, collection)
    return len(wheels)


def _brake_path(cache, car, level):
    return Path(cache) / f"{car}_brakelights_{level}.rom"


def _make_objects(rom, path, collection):
    stem = Path(path).stem
    materials = [_make_material(m.name, path) for m in rom.materials]
    for number, mesh in enumerate(rom.meshes):
        material = materials[mesh.material] if mesh.material < len(materials) else None
        _make_object(f"{stem}_{number}", mesh, number, material, collection)


def add_brake_lights(context, path, car):
    """Returns False if this car's lights are already in the scene.

    The file's tags stay out of the scene: _move_tags would apply them to the body.
    """
    if any(c.get(BRAKE_MARK) == car for c in context.scene.collection.children_recursive):
        return False
    rom = read_rom(Path(path).read_bytes())
    collection = bpy.data.collections.new(f"{car}_brakelights")
    collection[BRAKE_MARK] = car
    context.scene.collection.children.link(collection)
    _make_objects(rom, path, collection)
    return True


def import_rom(context, path):
    """Returns False if the file added nothing, because its brake lights are already in the scene."""
    stem = Path(path).stem
    cache = Path(path).parent
    car = cache.parent.name
    if stem in [_brake_path(cache, car, level).stem for level in BRAKE_LEVELS]:
        return add_brake_lights(context, path, car)
    rom = read_rom(Path(path).read_bytes())
    collection = bpy.data.collections.new(stem)
    context.scene.collection.children.link(collection)
    _make_objects(rom, path, collection)
    # The game draws a point at its .pts value, on the body. A model's tag is that value plus com.
    origin = centre_of_mass(rom.tags)
    for number, tag in enumerate(rom.tags):
        if tag.name == COM_TAG:
            continue
        empty = bpy.data.objects.new(f"tag_{tag.name}", None)
        empty.location = to_blender(tuple(tag.position[i] - origin[i] for i in range(3)))
        empty.empty_display_size = 0.1
        empty["rom_tag"] = tag.name
        empty["rom_tag_index"] = number
        empty["rom_source"] = Path(path).name
        _add_light_colour(empty, tag.name)
        collection.objects.link(empty)
    # A car keeps its models in cars/<car>/cache, beside <car>.params.
    params = cache / f"{car}.params"
    if params.is_file():
        add_wheels(context, params)
    brake = _brake_path(cache, car, BRAKE_LEVELS[0])
    if stem in [f"{car}_{level}" for level, _ in DETAIL_LEVELS] and brake.is_file():
        add_brake_lights(context, brake, car)
    return True


def _add_light_colour(empty, name):
    match = LIGHT_TAG.fullmatch(name)
    if match:
        empty[LIGHT_COLOUR] = [float(number) for number in match.groups()[1:]]
        # COLOR would store linear values, and the game reads these numbers as they are written.
        empty.id_properties_ui(LIGHT_COLOUR).update(subtype="COLOR_GAMMA", min=0.0, max=1.0)


def _light_name(name, colour):
    """An unchanged colour keeps the stock text."""
    match = LIGHT_TAG.fullmatch(name)
    if match is None or all(abs(float(old) - new) < SAME_COLOUR for old, new in zip(match.groups()[1:], colour)):
        return name
    return " ".join([match.group(1), *(f"{channel:.2f}" for channel in colour)])


def _in_order(objects):
    return sorted(objects, key=lambda o: (o.get("rom_order", len(objects)), o.name))


def _body_objects(context):
    objects = [
        o for o in context.scene.objects
        if o.type == "MESH" and o.visible_get() and "rom_wheel" not in o
        and not any(BRAKE_MARK in collection for collection in o.users_collection)
    ]
    if not objects:
        raise ExportError("The scene has no visible mesh to export")
    return _in_order(objects)


def _brake_objects(context, car):
    return _in_order([
        o for o in context.scene.objects
        if o.type == "MESH" and o.visible_get() and any(c.get(BRAKE_MARK) == car for c in o.users_collection)
    ])


def _material_index(obj, slot, names):
    material = obj.material_slots[slot].material if slot < len(obj.material_slots) else None
    return 0 if material is None else names.index(material.name)


def _add_new_materials(objects, materials):
    """Each new material is a copy of the skin's record, because most of a record is not decoded."""
    added = []
    for obj in objects:
        for slot in obj.material_slots:
            name = slot.material.name if slot.material else None
            if name is None or name in [material.name for material in materials]:
                continue
            if not MATERIAL_NAME.fullmatch(name):
                raise ExportError(
                    f"Material {name} on {obj.name} cannot name a texture. Use up to 19 lower case letters, digits and underscores"
                )
            material = Material(materials[0].record)
            material.name = name
            materials.append(material)
            added.append(name)
    return added


def _placeholder_dds():
    """A plain DXT1 image, so the game never meets a material with no texture."""
    blocks = PLACEHOLDER_SIZE // 4
    pixels = struct.pack("<HHI", PLACEHOLDER_COLOUR, 0, 0) * (blocks * blocks)
    header = b"DDS " + struct.pack("<7I", 124, 0x81007, PLACEHOLDER_SIZE, PLACEHOLDER_SIZE, len(pixels), 0, 1) + bytes(44)
    header += struct.pack("<2I", 32, 4) + b"DXT1" + bytes(20)
    return header + struct.pack("<I", 0x1000) + bytes(16) + pixels


class _MeshBuilder:
    """A game vertex holds one UV and one normal, so a Blender vertex can become several."""

    def __init__(self, flags, material):
        self.mesh = Mesh(flags=flags, material=material, triangles=[], vertices=[])
        self.index = {}

    def corner(self, position, normal, uv, colour):
        # Blender stores custom normals with small noise, so close normals count as one.
        matches = self.index.setdefault((position, uv, colour), [])
        for number in matches:
            other = self.mesh.vertices[number].normal
            if sum(a * b for a, b in zip(normal, other)) >= SAME_NORMAL:
                return number
        matches.append(len(self.mesh.vertices))
        self.mesh.vertices.append(Vertex(position, normal, uv, colour))
        return matches[-1]


def _corner_colour(attribute, data, corner, default):
    if attribute is None:
        return default
    index = corner if attribute.domain == "CORNER" else data.loops[corner].vertex_index
    return _pack_colour(attribute.data[index].color_srgb)


def _extract(obj, data, names, colour):
    if not data.uv_layers.active:
        raise ExportError(f"{obj.name} has no UV map")
    data.calc_loop_triangles()
    uv = data.uv_layers.active.uv
    colours = data.color_attributes.active_color
    normals = data.corner_normals
    matrix = obj.matrix_world
    turn = matrix.to_3x3().inverted_safe().transposed()
    flipped = matrix.determinant() < 0
    builders = {}
    for triangle in data.loop_triangles:
        slot = triangle.material_index
        if slot not in builders:
            builders[slot] = _MeshBuilder(obj.get("rom_flags", BODY_FLAGS), _material_index(obj, slot, names))
        first, second, third = triangle.loops
        order = (first, second, third) if flipped else (first, third, second)
        corners = []
        for corner in order:
            position = matrix @ data.vertices[data.loops[corner].vertex_index].co
            normal = (turn @ Vector(normals[corner].vector)).normalized()
            u, v = uv[corner].vector
            corners.append(builders[slot].corner(
                tuple(round(c, 5) for c in from_blender(position)),
                tuple(round(c, 4) for c in from_blender(normal)),
                (round(u, 5), round(1.0 - v, 5)),
                _corner_colour(colours, data, corner, colour),
            ))
        builders[slot].mesh.triangles.append(tuple(corners))
    return [builders[slot].mesh for slot in sorted(builders)]


def _level_meshes(context, objects, ratio, names, colour=DEFAULT_COLOUR):
    meshes = []
    for obj in objects:
        reduce = ratio < 1.0 and len(obj.data.polygons) >= MIN_FACES_TO_REDUCE
        modifiers = []
        if reduce:
            # A game model has separate vertices along every UV seam, and reducing each side
            # on its own would open cracks, so the seams close first.
            weld = obj.modifiers.new(WELD_MODIFIER, "WELD")
            weld.merge_threshold = WELD_DISTANCE
            detail = obj.modifiers.new(DETAIL_MODIFIER, "DECIMATE")
            detail.ratio = ratio
            modifiers = [detail, weld]
        evaluated = obj.evaluated_get(context.evaluated_depsgraph_get())
        data = evaluated.to_mesh()
        try:
            meshes.extend(_extract(obj, data, names, colour))
        finally:
            evaluated.to_mesh_clear()
            for modifier in modifiers:
                obj.modifiers.remove(modifier)
    for mesh in meshes:
        if len(mesh.vertices) > MAX_MESH_VERTICES:
            raise ExportError(f"A mesh has {len(mesh.vertices)} vertices, and the limit is {MAX_MESH_VERTICES}")
    return meshes


def _move_tags(context, rom, car):
    """Only this car's empties count. A body brought in from another model has its own."""
    origin = centre_of_mass(rom.tags)
    for empty in context.scene.objects:
        index = empty.get("rom_tag_index")
        if index is None or index >= len(rom.tags) or not _from_car(empty, car):
            continue
        # The game has no use for com, and moving it would only shift every point.
        if rom.tags[index].name != COM_TAG:
            position = from_blender(empty.matrix_world.translation)
            rom.tags[index].position = tuple(position[i] + origin[i] for i in range(3))
            if LIGHT_COLOUR in empty:
                rom.tags[index].name = _light_name(rom.tags[index].name, empty[LIGHT_COLOUR])


def _fit_shadow(shadow, bounds):
    """The shadow is a simple shell, so the stock one stretched to the new body works for any car."""
    old = shadow.bounds
    scale = [(bounds[i + 3] - bounds[i]) / (old[i + 3] - old[i]) if old[i + 3] > old[i] else 1.0 for i in range(3)]
    for mesh in shadow.meshes:
        for vertex in mesh.vertices:
            vertex.position = tuple(bounds[i] + (vertex.position[i] - old[i]) * scale[i] for i in range(3))
    shadow.bounds = None


def _wheel_file(context, path, car):
    """The .params text with this car's wheels applied, or None if the scene has none of them."""
    objects = {o["rom_wheel"]: o for o in context.scene.objects if "rom_wheel" in o and o.get("rom_car") == car}
    if not objects:
        return None
    text = path.read_bytes().decode("latin-1")
    wheels = read_wheels(text)
    for wheel in wheels:
        obj = objects.get(wheel.index)
        if obj is None:
            continue
        width, depth, height = obj.dimensions
        if min(width, depth, height) <= 0:
            raise ExportError(f"{obj.name} has no size")
        wheel.offset = from_blender(obj.matrix_world.translation)
        wheel.radius = params_radius((depth + height) / 4)
        wheel.width = params_width(width)
    return write_wheels(text, wheels).encode("latin-1")


def _brake_file(context, objects, cache, car):
    rom = read_rom(_brake_path(cache, car, BRAKE_LEVELS[0]).read_bytes())
    names = [material.name for material in rom.materials]
    for obj in objects:
        for slot in obj.material_slots:
            if slot.material and slot.material.name not in names:
                # The game opens these files with cars/generic as its texture folder.
                raise ExportError(f"Material {slot.material.name} on {obj.name} is not a brake light texture. Use one of: {', '.join(names)}")
    rom.meshes = _level_meshes(context, objects, 1.0, names, BRAKE_COLOUR)
    # A part moved in from the body keeps its body flags, and every stock light has this one.
    for mesh in rom.meshes:
        mesh.flags = BRAKE_FLAGS
    rom.bounds = None
    return write_rom(rom)


def _from_car(obj, car):
    """Whole file names, because one car's name can start with another's."""
    return obj.get("rom_car") == car or obj.get("rom_source") in [f"{car}_{level}.rom" for level, _ in DETAIL_LEVELS]


def _project_car(context, project):
    try:
        cars = [entry["internal_name"] for entry in json.loads((project / "cars.json").read_text(encoding="utf-8"))]
    except (OSError, ValueError, LookupError, TypeError) as e:
        raise ExportError(f"{project} is not a new car project: {e}") from e
    if not cars:
        raise ExportError(f"{project} is not a new car project: its cars.json is empty")
    # A guess here would replace another car's body with this one, and export gives no sign of it.
    found = [car for car in cars if any(_from_car(obj, car) for obj in context.scene.objects)]
    if len(found) > 1:
        raise ExportError(f"This scene holds {' and '.join(found)}, and export writes one car. Remove all but one.")
    if not found and len(cars) > 1:
        raise ExportError(f"This scene holds none of this project's cars ({', '.join(cars)}). Import the car's model from this project first.")
    car = found[0] if found else cars[0]
    return car, project / "files" / "cars" / car / "cache"


def export_car(context, project):
    project = Path(project)
    car, cache = _project_car(context, project)
    if context.mode != "OBJECT":
        # Edit Mode holds changes outside the mesh, and modifiers would not see them.
        bpy.ops.object.mode_set(mode="OBJECT")
    objects = _body_objects(context)
    outputs = {}
    bounds = None
    tags = None
    # Some stock cars drop a material at low detail, so the top level's list is used for all.
    materials = read_rom((cache / f"{car}_{DETAIL_LEVELS[0][0]}.rom").read_bytes()).materials
    added = _add_new_materials(objects, materials)
    names = [material.name for material in materials]
    for level, ratio in DETAIL_LEVELS:
        path = cache / f"{car}_{level}.rom"
        rom = read_rom(path.read_bytes())
        rom.materials = materials
        rom.meshes = _level_meshes(context, objects, ratio, names)
        rom.bounds = None
        _move_tags(context, rom, car)
        bounds = bounds or work_out_bounds(rom.meshes)
        tags = tags or rom.tags
        outputs[path] = write_rom(rom)
    for level in SHADOW_LEVELS:
        path = cache / f"{car}_{level}.shm"
        shadow = read_rom(path.read_bytes())
        _fit_shadow(shadow, bounds)
        outputs[path] = write_rom(shadow)
    outputs[cache / f"{car}.pts"] = write_points(tags)
    lights = _brake_objects(context, car)
    if lights:
        data = _brake_file(context, lights, cache, car)
        for level in BRAKE_LEVELS:
            outputs[_brake_path(cache, car, level)] = data
    params = cache / f"{car}.params"
    wheels = _wheel_file(context, params, car)
    if wheels is not None:
        outputs[params] = wheels
    textures = project / "textures" / "cars" / car / "cache" / TEXTURE_FOLDER
    painting = []
    for name in added:
        path = textures / f"{name}.bog.dds"
        if name not in SHARED_TEXTURES and not path.exists():
            outputs[path] = _placeholder_dds()
            painting.append(name)
    # Nothing is written until everything has been built, so a refused export changes no file.
    for path, data in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return painting


class IMPORT_OT_world_race_rom(bpy.types.Operator, ImportHelper):
    """Import a World Race model as a template"""

    bl_idname = "import_scene.world_race_rom"
    bl_label = "Import World Race Model"
    filename_ext = ".rom"
    filter_glob: bpy.props.StringProperty(default="*.rom;*.params", options={"HIDDEN"})

    def execute(self, context):
        try:
            if Path(self.filepath).suffix == ".params":
                if not add_wheels(context, self.filepath):
                    self.report({"WARNING"}, "No new wheels: they are already in the scene, or the file has none")
            elif not import_rom(context, self.filepath):
                self.report({"WARNING"}, "No new brake lights: they are already in the scene")
        except (OSError, RomError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class EXPORT_OT_world_race_car(bpy.types.Operator):
    """Export the scene into a World Race new car project"""

    bl_idname = "export_scene.world_race_car"
    bl_label = "Export World Race Car"
    directory: bpy.props.StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            painting = export_car(context, self.directory)
        except (ExportError, OSError, RomError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        message = "Car exported to the project"
        if painting:
            message += f". New textures to paint: {', '.join(painting)}"
        self.report({"INFO"}, message)
        return {"FINISHED"}


def _import_menu(self, context):
    self.layout.operator(IMPORT_OT_world_race_rom.bl_idname, text="World Race Model (.rom, .params)")


def _export_menu(self, context):
    self.layout.operator(EXPORT_OT_world_race_car.bl_idname, text="World Race Car (project folder)")


CLASSES = (IMPORT_OT_world_race_rom, EXPORT_OT_world_race_car)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(_import_menu)
    bpy.types.TOPBAR_MT_file_export.append(_export_menu)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(_import_menu)
    bpy.types.TOPBAR_MT_file_export.remove(_export_menu)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
