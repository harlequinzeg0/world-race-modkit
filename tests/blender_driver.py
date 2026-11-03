"""Runs inside Blender. Usage: blender --background --factory-startup --python this -- ARGS

ARGS: ADDON_ZIP ROM_PATH PROJECT MODE OUT_JSON
"""
import importlib
import json
import sys
import tempfile
import traceback
import zipfile

import bpy

addon_zip, rom_path, project, mode, out_json = sys.argv[sys.argv.index("--") + 1:]
folder = tempfile.mkdtemp()
zipfile.ZipFile(addon_zip).extractall(folder)
sys.path.insert(0, folder)
for default_object in list(bpy.data.objects):
    bpy.data.objects.remove(default_object)
import world_race_models

world_race_models.register()

report = {}


def in_lights(obj):
    return any("rom_brake" in collection for collection in obj.users_collection)


def meshes():
    return [o for o in bpy.context.scene.objects if o.type == "MESH" and "rom_wheel" not in o and not in_lights(o)]


def lights(car="neon"):
    return [o for o in bpy.context.scene.objects if any(c.get("rom_brake") == car for c in o.users_collection)]


def light_collection(car="neon"):
    return next(c for c in bpy.data.collections if c.get("rom_brake") == car)


def wheels():
    return sorted((o for o in bpy.context.scene.objects if "rom_wheel" in o), key=lambda o: o["rom_wheel"])


def wheel_named(name):
    return next(o for o in wheels() if o.name == name)


def add_sphere(name, material=None, uv=True):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.5, location=(0, 0, 1))
    sphere = bpy.context.active_object
    sphere.name = name
    if not uv:
        sphere.data.uv_layers.remove(sphere.data.uv_layers[0])
    if material:
        sphere.data.materials.append(bpy.data.materials.get(material) or bpy.data.materials.new(material))
    return sphere


def remove_body():
    for mesh in meshes():
        bpy.data.objects.remove(mesh)


def export():
    try:
        bpy.ops.export_scene.world_race_car(directory=project)
        report["exported"] = True
    except RuntimeError as e:
        report["error"] = str(e)


try:
    bpy.ops.import_scene.world_race_rom(filepath=rom_path)
    report["objects"] = sorted(o.name for o in meshes())
    report["flags"] = sorted(o["rom_flags"] for o in meshes())
    report["materials"] = sorted(m.name for m in bpy.data.materials)
    report["tags"] = sorted(o["rom_tag"] for o in bpy.context.scene.objects if "rom_tag" in o)
    report["triangles"] = sum(len(o.data.polygons) for o in meshes())
    report["up"] = max((v.co.z for o in meshes() for v in o.data.vertices), default=0)
    report["wheels"] = [
        {"name": o.name, "location": list(o.location), "size": list(o.dimensions), "locked": list(o.lock_rotation)}
        for o in wheels()
    ]
    report["has_uv"] = all(o.data.uv_layers for o in meshes())
    report["has_colour"] = all(o.data.color_attributes for o in meshes())
    report["lights"] = [o.name for o in lights()]
    report["light_collections"] = [c.name for c in bpy.data.collections if "rom_brake" in c]
    report["light_materials"] = sorted(s.material.name for o in lights() for s in o.material_slots)
    report["light_colours"] = {
        o["rom_tag"]: [round(c, 3) for c in o["rom_light_colour"]]
        for o in bpy.context.scene.objects if "rom_light_colour" in o
    }
    report["tag_places"] = {
        o["rom_tag"]: list(o.location) for o in bpy.context.scene.objects if "rom_tag" in o
    }

    if mode == "roundtrip":
        export()
    elif mode == "replace":
        remove_body()
        add_sphere("my_body", "skin")
        export()
    elif mode == "tail_move":
        for empty in bpy.context.scene.objects:
            if empty.get("rom_tag") == "lefttaillight":
                empty.location = (0.4, 2.5, 0.6)
        export()
    elif mode == "old_com":
        # Scenes imported before this version hold an empty for com.
        empty = bpy.data.objects.new("tag_com", None)
        empty.location = (0.0, 0.0, 1.0)
        empty["rom_tag"] = "com"
        empty["rom_tag_index"] = 0
        empty["rom_source"] = "neon_med.rom"
        tail = next(o for o in bpy.context.scene.objects if o.get("rom_tag") == "lefttaillight")
        tail.users_collection[0].objects.link(empty)
        export()
    elif mode == "second_car":
        bpy.ops.import_scene.world_race_rom(filepath=project + "/files/cars/first/cache/first_med.rom")
        export()
    elif mode == "no_marks":
        for obj in list(bpy.context.scene.objects):
            if "rom_source" in obj or "rom_car" in obj:
                bpy.data.objects.remove(obj)
        export()
    elif mode == "no_uv":
        remove_body()
        add_sphere("my_body", "skin", uv=False)
        export()
    elif mode == "new_material":
        remove_body()
        add_sphere("my_body", "second_part")
        export()
    elif mode == "bad_material":
        remove_body()
        add_sphere("my_body", "Bad Name!")
        export()
    elif mode == "long_material":
        remove_body()
        add_sphere("my_body", "a_name_too_long_for_the_game")
        export()
    elif mode == "shared_material":
        remove_body()
        add_sphere("my_body", "generic_headlight")
        export()
    elif mode == "two_materials":
        remove_body()
        sphere = add_sphere("my_body", "skin")
        sphere.data.materials.append(bpy.data.materials.new("second_part"))
        for number, face in enumerate(sphere.data.polygons):
            face.material_index = number % 2
        export()
    elif mode == "no_material":
        remove_body()
        add_sphere("my_body")
        export()
    elif mode == "empty":
        remove_body()
        export()
    elif mode == "donor":
        remove_body()
        bpy.ops.import_scene.world_race_rom(filepath=project + "/donor.rom")
        for obj in meshes():
            obj.data.materials.clear()
            obj.data.materials.append(bpy.data.materials["skin"])
        export()
    elif mode == "edit_mode":
        bpy.context.view_layer.objects.active = max(meshes(), key=lambda o: len(o.data.polygons))
        bpy.ops.object.mode_set(mode="EDIT")
        export()
    elif mode == "wheels_again":
        bpy.ops.import_scene.world_race_rom(filepath=rom_path)
        report["wheel_count"] = len(wheels())
    elif mode == "wheels_move":
        wheel = wheel_named("wheel_front_left")
        wheel.location = (0.5, -1.25, -0.25)
        wheel.dimensions = (0.2, 0.3, 0.3)
        bpy.context.view_layer.update()
        export()
    elif mode == "wheels_applied":
        wheel = wheel_named("wheel_front_left")
        wheel.scale = (1.0, 1.0, 1.0)
        for vertex in wheel.data.vertices:
            vertex.co *= 0.5
        wheel.data.update()
        bpy.context.view_layer.update()
        export()
    elif mode == "wheels_flat":
        wheel_named("wheel_front_left").scale = (0.0, 0.3, 0.3)
        bpy.context.view_layer.update()
        export()
    elif mode == "wheels_donor":
        bpy.ops.import_scene.world_race_rom(filepath=project + "/donor/cars/other/cache/other_med.rom")
        report["wheel_count"] = len(wheels())
        for wheel in wheels():
            if wheel["rom_car"] == "other":
                wheel.location = (9.0, 9.0, 9.0)
        export()
    elif mode == "install_again":
        library = sys.modules["world_race_models.rom"]
        library.COM_TAG = "from_the_old_install"
        world_race_models.unregister()
        importlib.reload(world_race_models)
        world_race_models.register()
        report["com_tag"] = library.COM_TAG
    elif mode == "tail_colour":
        for empty in bpy.context.scene.objects:
            if empty.get("rom_tag", "").startswith("backlight"):
                empty["rom_light_colour"] = (1.0, 0.0, 0.5)
        export()
    elif mode == "head_colour":
        for empty in bpy.context.scene.objects:
            if empty.get("rom_tag", "").startswith("headlight"):
                empty["rom_light_colour"] = (0.25, 0.75, 1.0)
        export()
    elif mode == "lights_move":
        for light in lights():
            light.location = (0.0, 0.0, 0.5)
        bpy.context.view_layer.update()
        export()
    elif mode == "lights_new":
        for light in lights():
            bpy.data.objects.remove(light)
        sphere = add_sphere("my_light")
        for collection in sphere.users_collection:
            collection.objects.unlink(sphere)
        light_collection().objects.link(sphere)
        export()
    elif mode == "lights_body_part":
        part = max(meshes(), key=lambda o: len(o.data.polygons))
        part.data.materials.clear()
        part.data.materials.append(bpy.data.materials["TLANG_lightning"])
        for collection in part.users_collection:
            collection.objects.unlink(part)
        light_collection().objects.link(part)
        export()
    elif mode == "lights_hidden":
        for light in lights():
            light.location = (0.0, 0.0, 0.5)
            light.hide_set(True)
        export()
    elif mode == "lights_deleted":
        for light in lights():
            bpy.data.objects.remove(light)
        export()
    elif mode == "lights_bad_material":
        for light in lights():
            light.location = (0.0, 0.0, 0.5)
            light.data.materials.clear()
            light.data.materials.append(bpy.data.materials["skin"])
        export()
    elif mode == "lights_again":
        bpy.ops.import_scene.world_race_rom(filepath=rom_path)
        report["lights"] = [o.name for o in lights()]
    elif mode == "lights_donor":
        remove_body()
        bpy.ops.import_scene.world_race_rom(filepath=project + "/donor/cars/other/cache/other_med.rom")
        for obj in meshes():
            obj.data.materials.clear()
            obj.data.materials.append(bpy.data.materials["skin"])
        for light in lights("other"):
            light.location = (0.0, 0.0, 0.5)
        export()
    report["objects_after"] = len(meshes())
    report["modifiers_after"] = sum(len(o.modifiers) for o in meshes())
except Exception:
    report["crash"] = traceback.format_exc()

with open(out_json, "w", encoding="utf-8") as f:
    json.dump(report, f)
