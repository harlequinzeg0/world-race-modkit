import json
import math
import os
import re
import struct
import subprocess
import zipfile
from pathlib import Path

import pytest

from test_rom import material_record, tag_record
from wrmod.addon import ADDON_NAME, build_addon
from wrmod.bark import Archive
from wrmod.bog import dds_to_bog, parse_header
from wrmod.hsc import Hitbox, read_hsc, write_hsc
from wrmod.rom import Material, Mesh, Rom, Tag, Vertex, read_rom, work_out_bounds, write_rom, write_points
from wrmod.wheels import read_wheels, visible_radius, visible_width

BLENDER = Path(os.environ.get("WRMOD_BLENDER", r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"))
DRIVER = Path(__file__).parent / "blender_driver.py"
CAR = "neon"
COLOUR = 0x84604020
RED = 0xFFFF0000


def grid_mesh(size=30):
    """A bumpy sheet with enough triangles for detail levels to matter."""
    vertices = []
    for i in range(size):
        for j in range(size):
            x, z = i / 10 - 1.5, j / 10 - 1.5
            y = 0.3 * math.sin(i * 0.7) * math.cos(j * 0.9)
            vertices.append(Vertex((x, y, z), (0.0, 1.0, 0.0), (i / size, j / size), COLOUR))
    triangles = []
    for i in range(size - 1):
        for j in range(size - 1):
            a, b, c, d = i * size + j, i * size + j + 1, (i + 1) * size + j, (i + 1) * size + j + 1
            triangles += [(a, b, c), (b, d, c)]
    return Mesh(flags=0x40, material=0, triangles=triangles, vertices=vertices)


def light_mesh():
    vertices = [Vertex((x, 0.5, 2.0), (0.0, 0.0, 1.0), (0.0, 0.0), COLOUR) for x in (0.0, 0.5, 1.0)]
    return Mesh(flags=0x44, material=1, triangles=[(0, 1, 2)], vertices=vertices)


def sample_rom():
    tags = [Tag(tag_record(b"com", (0.0, 0.1, 0.2))), Tag(tag_record(b"lefttaillight", (-0.5, 0.3, -1.8)))]
    materials = [Material(material_record(b"skin")), Material(material_record(b"generic_headlight"))]
    return Rom(materials=materials, tags=tags, meshes=[grid_mesh(), light_mesh()])


def shadow_rom():
    vertices = [Vertex(p, (0.0, 1.0, 0.0), (0.0, 0.0), 0xFF000000) for p in ((-1.0, 0.0, -2.0), (1.0, 0.0, -2.0), (0.0, 1.0, 2.0))]
    return Rom(tags=[Tag(tag_record(b"com"))], meshes=[Mesh(0, 0xFFFFFFFF, [(0, 1, 2)], vertices)])


def box_planes(bounds):
    planes = []
    for axis in range(3):
        normal = [0.0, 0.0, 0.0]
        normal[axis] = 1.0
        planes.append((*normal, -bounds[axis + 3]))
        normal[axis] = -1.0
        planes.append((*normal, bounds[axis]))
    return planes


SAMPLE_BOUNDS = work_out_bounds(sample_rom().meshes)
SAMPLE_HITBOX = Hitbox(1, [box_planes(SAMPLE_BOUNDS)], [(0.0, 0.3, 0.5, 0.2)], [(0.5, 0.0, -1.0, 0.6), (-0.5, 0.0, 1.0, 0.6)])


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "project"
    cache = folder / "files/cars" / CAR / "cache"
    cache.mkdir(parents=True)
    (folder / "cars.json").write_text(json.dumps([{"internal_name": CAR, "based_on": "donor"}]))
    (cache / f"{CAR}.hsc").write_bytes(write_hsc(SAMPLE_HITBOX))
    for level in ("med", "lower_med", "low"):
        (cache / f"{CAR}_{level}.rom").write_bytes(write_rom(sample_rom()))
    for level in ("high", "med", "lower_med"):
        (cache / f"{CAR}_{level}.shm").write_bytes(write_rom(shadow_rom()))
    (cache / f"{CAR}.pts").write_bytes(write_points(sample_rom().tags))
    return folder


def cache_of(project):
    return project / "files/cars" / CAR / "cache"


def run(project, mode, tmp_path, rom_path=None):
    if not BLENDER.is_file():
        pytest.skip("Blender 4.5 is not installed")
    addon = build_addon(tmp_path / "addon.zip")
    out = tmp_path / "report.json"
    rom_path = rom_path or cache_of(project) / f"{CAR}_med.rom"
    done = subprocess.run(
        [str(BLENDER), "--background", "--factory-startup", "--python", str(DRIVER), "--",
         str(addon), str(rom_path), str(project), mode, str(out)],
        capture_output=True, text=True, timeout=60,
    )
    assert out.is_file(), done.stdout[-2000:] + done.stderr[-2000:]
    report = json.loads(out.read_text(encoding="utf-8"))
    assert "crash" not in report, report["crash"]
    return report


def read_level(project, level="med"):
    return read_rom((cache_of(project) / f"{CAR}_{level}.rom").read_bytes())


def triangles(rom):
    return sum(len(mesh.triangles) for mesh in rom.meshes)


def test_addon_zip_holds_the_addon_and_the_library(tmp_path):
    with zipfile.ZipFile(build_addon(tmp_path / "a.zip")) as z:
        assert set(z.namelist()) == {f"{ADDON_NAME}/{name}.py" for name in ("__init__", "rom", "wheels", "hsc")}
        assert b"bl_info" in z.read(f"{ADDON_NAME}/__init__.py")
        assert z.read(f"{ADDON_NAME}/rom.py").startswith(b'"""Read and write')


def test_installing_again_replaces_the_library_too(project, tmp_path):
    assert run(project, "install_again", tmp_path)["com_tag"] == "com"


def test_import_makes_a_template(project, tmp_path):
    report = run(project, "import", tmp_path)
    assert len(report["objects"]) == 2
    assert report["flags"] == [0x40, 0x44]
    assert {"generic_headlight", "skin"} <= set(report["materials"])
    assert report["tags"] == ["lefttaillight"]
    assert report["triangles"] == triangles(sample_rom())
    assert report["has_uv"] and report["has_colour"]


def test_import_stands_the_car_up_on_blender_z(project, tmp_path):
    # Game Y is up, so the light mesh at y 0.5 sets the highest Blender Z.
    assert run(project, "import", tmp_path)["up"] == pytest.approx(0.5, abs=0.001)


def test_round_trip_keeps_shape_uv_colour_and_normals(project, tmp_path):
    assert run(project, "roundtrip", tmp_path).get("exported")
    rom = read_level(project)
    original = sample_rom()
    assert triangles(rom) == triangles(original)
    assert sorted(m.flags for m in rom.meshes) == [0x40, 0x44]
    def points(r):
        found = [v.position for m in r.meshes for v in m.vertices]
        return sorted(found, key=lambda p: (round(p[0], 2), round(p[2], 2)))
    for got, wanted in zip(points(rom), points(original)):
        assert got == pytest.approx(wanted, abs=1e-3)
    assert [len(m.vertices) for m in rom.meshes] == [len(m.vertices) for m in original.meshes]
    body = next(m for m in rom.meshes if m.flags == 0x40)
    first = next(v for v in body.vertices if abs(v.position[0] + 1.5) < 1e-3 and abs(v.position[2] + 1.5) < 1e-3)
    assert first.uv == pytest.approx((0.0, 0.0), abs=1e-3)
    assert first.normal == pytest.approx((0.0, 1.0, 0.0), abs=0.01)
    assert first.colour >> 24 == 0x84
    assert first.colour & 0xFF == pytest.approx(0x20, abs=2)


def test_round_trip_keeps_triangle_winding(project, tmp_path):
    run(project, "roundtrip", tmp_path)
    body = next(m for m in read_level(project).meshes if m.flags == 0x40)
    a, b, c = (body.vertices[i].position for i in body.triangles[0])
    u = [b[k] - a[k] for k in range(3)]
    v = [c[k] - a[k] for k in range(3)]
    cross_y = u[2] * v[0] - u[0] * v[2]
    # Stock triangles have a cross product along the normal. See the winding survey in FINDINGS.
    assert cross_y * sample_winding() > 0


def sample_winding():
    mesh = grid_mesh()
    a, b, c = (mesh.vertices[i].position for i in mesh.triangles[0])
    u = [b[k] - a[k] for k in range(3)]
    v = [c[k] - a[k] for k in range(3)]
    return u[2] * v[0] - u[0] * v[2]


def test_export_makes_smaller_detail_levels(project, tmp_path):
    run(project, "roundtrip", tmp_path)
    assert triangles(read_level(project)) > triangles(read_level(project, "lower_med")) > triangles(read_level(project, "low"))


def test_small_meshes_keep_their_detail(project, tmp_path):
    run(project, "roundtrip", tmp_path)
    low = read_level(project, "low")
    assert len(next(m for m in low.meshes if m.flags == 0x44).triangles) == 1


def test_export_keeps_materials_and_tag_records(project, tmp_path):
    run(project, "roundtrip", tmp_path)
    rom = read_level(project)
    assert [m.record for m in rom.materials] == [m.record for m in sample_rom().materials]
    assert [t.name for t in rom.tags] == ["com", "lefttaillight"]


def test_export_leaves_no_modifier_behind(project, tmp_path):
    assert run(project, "roundtrip", tmp_path)["modifiers_after"] == 0


def test_replaced_body_exports(project, tmp_path):
    assert run(project, "replace", tmp_path).get("exported")
    rom = read_level(project)
    assert len(rom.meshes) == 1 and rom.meshes[0].flags == 0x40
    # A sphere of radius 1.5 at Blender z 1 is at game y 1.
    assert rom.bounds[1] == pytest.approx(-0.5, abs=0.02)
    assert rom.bounds[4] == pytest.approx(2.5, abs=0.02)


def tail_point(project):
    data = (cache_of(project) / f"{CAR}.pts").read_bytes()
    return struct.unpack_from("<3f", data, 20 + 80 + 32)


def test_a_point_imports_where_the_game_draws_it(project, tmp_path):
    # The sample tag is at (-0.5, 0.3, -1.8) with com at (0.0, 0.1, 0.2).
    place = run(project, "import", tmp_path)["tag_places"]["lefttaillight"]
    assert place == pytest.approx((0.5, 2.0, 0.2), abs=1e-4)


def test_a_moved_point_lands_where_it_was_placed(project, tmp_path):
    assert run(project, "tail_move", tmp_path).get("exported")
    assert tail_point(project) == pytest.approx((-0.4, 0.6, -2.5), abs=1e-4)


def test_a_moved_point_reaches_every_level_with_com_added(project, tmp_path):
    run(project, "tail_move", tmp_path)
    for level in ("med", "lower_med", "low"):
        assert read_level(project, level).tags[1].position == pytest.approx((-0.4, 0.7, -2.3), abs=1e-4)


def test_an_unmoved_point_keeps_its_place(project, tmp_path):
    run(project, "roundtrip", tmp_path)
    assert tail_point(project) == pytest.approx((-0.5, 0.2, -2.0), abs=1e-4)


def test_an_old_scenes_com_empty_changes_nothing(project, tmp_path):
    assert run(project, "old_com", tmp_path).get("exported")
    assert read_level(project).tags[0].position == pytest.approx((0.0, 0.1, 0.2), abs=1e-4)
    assert tail_point(project) == pytest.approx((-0.5, 0.2, -2.0), abs=1e-4)


def list_first(project, name):
    """Adds a car ahead of the others in cars.json, as a team project has."""
    cache = project / "files/cars" / name / "cache"
    cache.mkdir(parents=True)
    for level in ("med", "lower_med", "low"):
        (cache / f"{name}_{level}.rom").write_bytes(write_rom(sample_rom()))
    for level in ("high", "med", "lower_med"):
        (cache / f"{name}_{level}.shm").write_bytes(write_rom(shadow_rom()))
    (cache / f"{name}.pts").write_bytes(write_points(sample_rom().tags))
    cars = json.loads((project / "cars.json").read_text())
    (project / "cars.json").write_text(json.dumps([{"internal_name": name, "based_on": "donor"}] + cars))
    return cache


def contents(folder):
    return {path.name: path.read_bytes() for path in folder.iterdir()}


def test_export_goes_to_the_car_in_the_scene(project, tmp_path):
    other = list_first(project, "first")
    before = contents(other)
    assert run(project, "tail_move", tmp_path).get("exported")
    assert contents(other) == before
    assert tail_point(project) == pytest.approx((-0.4, 0.6, -2.5), abs=1e-4)


def test_a_name_that_starts_like_another_car_is_not_mixed_up(project, tmp_path):
    longer = list_first(project, f"{CAR}_a")
    before = contents(cache_of(project))
    report = run(project, "roundtrip", tmp_path, rom_path=longer / f"{CAR}_a_med.rom")
    assert report.get("exported")
    assert contents(cache_of(project)) == before


def test_a_scene_with_two_cars_of_the_project_is_refused(project, tmp_path):
    other = list_first(project, "first")
    before = contents(other), contents(cache_of(project))
    error = run(project, "second_car", tmp_path)["error"]
    assert "first" in error and CAR in error
    assert (contents(other), contents(cache_of(project))) == before


def test_a_scene_with_none_of_several_cars_is_refused(project, tmp_path):
    list_first(project, "first")
    assert "first" in run(project, "no_marks", tmp_path)["error"]


def test_a_scene_with_no_marks_uses_a_projects_only_car(project, tmp_path):
    assert run(project, "no_marks", tmp_path).get("exported")


def test_shadow_scales_to_the_new_body(project, tmp_path):
    run(project, "replace", tmp_path)
    for level in ("high", "med", "lower_med"):
        shadow = read_rom((cache_of(project) / f"{CAR}_{level}.shm").read_bytes())
        assert shadow.bounds[0] == pytest.approx(-1.5, abs=0.02)
        assert shadow.bounds[3] == pytest.approx(1.5, abs=0.02)


def test_mesh_with_no_material_uses_the_first(project, tmp_path):
    assert run(project, "no_material", tmp_path).get("exported")
    assert read_level(project).meshes[0].material == 0


def test_missing_uv_map_is_refused_and_writes_nothing(project, tmp_path):
    before = (cache_of(project) / f"{CAR}_med.rom").read_bytes()
    report = run(project, "no_uv", tmp_path)
    assert "UV" in report["error"]
    assert (cache_of(project) / f"{CAR}_med.rom").read_bytes() == before


def test_unknown_material_is_refused(project, tmp_path):
    assert "Bad Name!" in run(project, "bad_material", tmp_path)["error"]


def test_empty_scene_is_refused(project, tmp_path):
    assert "mesh" in run(project, "empty", tmp_path)["error"].lower()


def test_real_car_round_trip(game_dir, tmp_path):
    archive = Archive(game_dir)
    project = tmp_path / "project"
    cache = project / "files/cars" / CAR / "cache"
    cache.mkdir(parents=True)
    (project / "cars.json").write_text(json.dumps([{"internal_name": CAR, "based_on": "ballistic"}]))
    (cache / f"{CAR}.hsc").write_bytes(archive.read("cars/ballistic/cache/ballistic.hsc"))
    for level in ("med", "lower_med", "low"):
        (cache / f"{CAR}_{level}.rom").write_bytes(archive.read(f"cars/ballistic/cache/ballistic_{level}.rom"))
    for level in ("high", "med", "lower_med"):
        (cache / f"{CAR}_{level}.shm").write_bytes(archive.read(f"cars/ballistic/cache/ballistic_{level}.shm"))
    (cache / f"{CAR}.pts").write_bytes(archive.read("cars/ballistic/cache/ballistic.pts"))
    stock = read_rom((cache / f"{CAR}_med.rom").read_bytes())
    assert run(project, "roundtrip", tmp_path).get("exported")
    rom = read_level(project)
    assert triangles(rom) == triangles(stock)
    assert rom.bounds == pytest.approx(stock.bounds, abs=0.001)
    assert sum(len(m.vertices) for m in rom.meshes) <= sum(len(m.vertices) for m in stock.meshes) * 1.05
    assert [m.flags for m in rom.meshes] == [m.flags for m in stock.meshes]
    assert 500 < triangles(read_level(project, "low")) < 1500
    stock_planes = [p for p in read_hsc(archive.read("cars/ballistic/cache/ballistic.hsc")).plane_groups[0] if any(p[:3])]
    assert same_planes(hitbox_of(project).plane_groups[0], stock_planes, 1e-4)


def test_a_donor_models_tags_do_not_replace_the_cars(project, tmp_path):
    donor = sample_rom()
    donor.tags = [Tag(tag_record(b"com", (9.0, 9.0, 9.0))), Tag(tag_record(b"backlight 0.4", (8.0, 8.0, 8.0)))]
    (project / "donor.rom").write_bytes(write_rom(donor))
    assert run(project, "donor", tmp_path).get("exported")
    tags = read_level(project).tags
    assert tags[0].position == pytest.approx((0.0, 0.1, 0.2), abs=1e-4)
    assert tags[1].position == pytest.approx((-0.5, 0.3, -1.8), abs=1e-4)


def test_a_detail_level_may_have_fewer_materials(project, tmp_path):
    low = sample_rom()
    low.materials = low.materials[:1]
    low.meshes = low.meshes[:1]
    (cache_of(project) / f"{CAR}_low.rom").write_bytes(write_rom(low))
    assert run(project, "roundtrip", tmp_path).get("exported")
    assert [m.name for m in read_level(project, "low").materials] == ["skin", "generic_headlight"]


def seam_rom():
    """Two sheets that meet at x = 0 with separate vertices, as a UV seam arrives from the game."""
    rom = sample_rom()
    size = 20
    vertices, triangles = [], []
    for side in (0, 1):
        start = len(vertices)
        for i in range(size):
            for j in range(size):
                x = (i / (size - 1)) * (1 if side else -1)
                y = 0.2 * math.sin(i * 0.9) * math.cos(j * 0.8)
                vertices.append(Vertex((x, y, j / 10), (0.0, 1.0, 0.0), (side * 0.5, j / size), COLOUR))
        for i in range(size - 1):
            for j in range(size - 1):
                a, b, c, d = start + i * size + j, start + i * size + j + 1, start + (i + 1) * size + j, start + (i + 1) * size + j + 1
                triangles += [(a, b, c), (b, d, c)] if side else [(a, c, b), (b, c, d)]
    rom.meshes = [Mesh(flags=0x40, material=0, triangles=triangles, vertices=vertices)]
    return rom


def edges_open_along_the_seam(mesh):
    """Edges used by one triangle, away from the outer rim of the two sheets."""
    key = lambda p: tuple(round(c, 3) for c in p)
    count = {}
    for triangle in mesh.triangles:
        points = [key(mesh.vertices[i].position) for i in triangle]
        for a, b in ((0, 1), (1, 2), (2, 0)):
            edge = tuple(sorted((points[a], points[b])))
            count[edge] = count.get(edge, 0) + 1
    return [e for e, n in count.items() if n == 1 and all(abs(p[0]) < 0.05 for p in e) and all(0.05 < p[2] < 1.85 for p in e)]


def test_lower_levels_do_not_tear_at_seams(project, tmp_path):
    (cache_of(project) / f"{CAR}_med.rom").write_bytes(write_rom(seam_rom()))
    assert run(project, "roundtrip", tmp_path).get("exported")
    low = read_level(project, "low")
    assert triangles(low) < triangles(read_level(project)) * 0.6
    assert edges_open_along_the_seam(low.meshes[0]) == []


def test_export_from_edit_mode_still_makes_detail_levels(project, tmp_path):
    assert run(project, "edit_mode", tmp_path).get("exported")
    assert triangles(read_level(project, "low")) < triangles(read_level(project)) * 0.6


def wheel_block(index, offset, radius, width):
    return (
        f"WHEEL\t{index}\r\nWHEELOFFSET\t{offset[0]}\t{offset[1]}\t{offset[2]}\r\n"
        f"WHEELRADIUS\t{radius}\r\nWHEELWIDTH\t{width}\r\n"
    )


PARAMS = "".join(
    wheel_block(number, offset, radius, width)
    for number, (offset, radius, width) in enumerate((
        ((-0.75, -0.3, 1.5), 0.43, 0.35),
        ((0.75, -0.3, 1.5), 0.43, 0.35),
        ((-0.8, -0.25, -1.5), 0.46, 0.4),
        ((0.8, -0.25, -1.5), 0.46, 0.4),
    ))
)


@pytest.fixture
def params(project):
    path = cache_of(project) / f"{CAR}.params"
    path.write_bytes(PARAMS.encode("latin-1"))
    return path


def test_import_shows_each_wheel_where_the_game_draws_it(project, params, tmp_path):
    wheels = run(project, "import", tmp_path)["wheels"]
    assert [w["name"] for w in wheels] == [
        "wheel_front_left", "wheel_front_right", "wheel_back_left", "wheel_back_right",
    ]
    assert wheels[0]["location"] == pytest.approx((0.75, -1.5, -0.3), abs=1e-5)
    assert wheels[3]["location"] == pytest.approx((-0.8, 1.5, -0.25), abs=1e-5)
    wheel = read_wheels(PARAMS)[2]
    expected = (visible_width(wheel), 2 * visible_radius(wheel), 2 * visible_radius(wheel))
    assert wheels[2]["size"] == pytest.approx(expected, abs=1e-5)


def test_import_locks_wheel_rotation_because_the_game_ignores_it(project, params, tmp_path):
    assert run(project, "import", tmp_path)["wheels"][0]["locked"] == [True, True, True]


def test_a_project_without_params_imports_no_wheels(project, tmp_path):
    assert run(project, "import", tmp_path)["wheels"] == []


def test_importing_twice_does_not_double_the_wheels(project, params, tmp_path):
    assert run(project, "wheels_again", tmp_path)["wheel_count"] == 4


def test_a_params_file_imports_wheels_without_a_body(project, params, tmp_path):
    report = run(project, "wheels_only", tmp_path, rom_path=params)
    assert len(report["wheels"]) == 4
    assert report["objects"] == []


def test_wheels_stay_out_of_the_body(project, params, tmp_path):
    assert run(project, "roundtrip", tmp_path).get("exported")
    assert triangles(read_level(project)) == triangles(sample_rom())


def test_export_of_unmoved_wheels_keeps_the_file(project, params, tmp_path):
    assert run(project, "roundtrip", tmp_path).get("exported")
    assert params.read_bytes() == PARAMS.encode("latin-1")


def test_export_writes_a_moved_and_sized_wheel(project, params, tmp_path):
    assert run(project, "wheels_move", tmp_path).get("exported")
    wheels = read_wheels(params.read_bytes().decode("latin-1"))
    assert wheels[0].offset == pytest.approx((-0.5, -0.25, 1.25), abs=1e-4)
    assert visible_radius(wheels[0]) == pytest.approx(0.15, abs=1e-3)
    assert visible_width(wheels[0]) == pytest.approx(0.2, abs=1e-3)
    assert wheels[1].offset == (0.75, -0.3, 1.5)
    assert wheels[1].radius == 0.43


def test_export_reads_size_after_scale_is_applied(project, params, tmp_path):
    assert run(project, "wheels_applied", tmp_path).get("exported")
    wheel = read_wheels(params.read_bytes().decode("latin-1"))[0]
    assert visible_radius(wheel) == pytest.approx(0.5, abs=1e-3)
    assert visible_width(wheel) == pytest.approx(0.5, abs=1e-3)


def test_a_wheel_with_no_size_is_refused_and_writes_nothing(project, params, tmp_path):
    before = (cache_of(project) / f"{CAR}_med.rom").read_bytes()
    report = run(project, "wheels_flat", tmp_path)
    assert "wheel_front_left" in report["error"]
    assert (cache_of(project) / f"{CAR}_med.rom").read_bytes() == before
    assert params.read_bytes() == PARAMS.encode("latin-1")


def test_another_cars_wheels_are_ignored(project, params, tmp_path):
    donor = project / "donor/cars/other/cache"
    donor.mkdir(parents=True)
    (donor / "other_med.rom").write_bytes(write_rom(sample_rom()))
    (donor / "other.params").write_bytes(PARAMS.encode("latin-1"))
    report = run(project, "wheels_donor", tmp_path)
    assert report["wheel_count"] == 8
    assert report.get("exported")
    assert params.read_bytes() == PARAMS.encode("latin-1")


def texture_of(project, name):
    return project / "textures/cars" / CAR / "cache/tex_high" / f"{name}.bog.dds"


def test_a_new_material_joins_every_level(project, tmp_path):
    assert run(project, "new_material", tmp_path).get("exported")
    for level in ("med", "lower_med", "low"):
        rom = read_level(project, level)
        assert [m.name for m in rom.materials] == ["skin", "generic_headlight", "second_part"]
        assert {mesh.material for mesh in rom.meshes} == {2}


def test_a_new_material_gets_a_texture_to_paint(project, tmp_path):
    run(project, "new_material", tmp_path)
    bog = dds_to_bog(texture_of(project, "second_part").read_bytes(), None)
    assert parse_header(bog).width == 64


def test_export_keeps_a_texture_already_painted(project, tmp_path):
    path = texture_of(project, "second_part")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"painted")
    run(project, "new_material", tmp_path)
    assert path.read_bytes() == b"painted"


def test_each_part_keeps_its_own_material(project, tmp_path):
    assert run(project, "two_materials", tmp_path).get("exported")
    rom = read_level(project)
    assert {mesh.material for mesh in rom.meshes} == {0, 2}
    assert all(mesh.triangles for mesh in rom.meshes)


def test_a_material_name_that_is_too_long_is_refused(project, tmp_path):
    assert "a_name_too_long_for_the_game" in run(project, "long_material", tmp_path)["error"]
    assert not texture_of(project, "a_name_too_long_for_the_game").exists()


def test_the_shared_headlight_gets_no_texture_of_its_own(project, tmp_path):
    only_skin = sample_rom()
    only_skin.materials = only_skin.materials[:1]
    only_skin.meshes = only_skin.meshes[:1]
    (cache_of(project) / f"{CAR}_med.rom").write_bytes(write_rom(only_skin))
    assert run(project, "shared_material", tmp_path).get("exported")
    assert "generic_headlight" in [m.name for m in read_level(project).materials]
    assert not texture_of(project, "generic_headlight").exists()


def brake_rom():
    vertices = [Vertex((x, 0.3, -2.0), (0.0, 0.0, -1.0), (0.5, 0.5), RED) for x in (-0.5, 0.0, 0.5)]
    mesh = Mesh(flags=0x10, material=0, triangles=[(0, 1, 2)], vertices=vertices)
    return Rom(materials=[Material(material_record(b"TLANG_lightning"))], tags=[Tag(tag_record(b"com"))], meshes=[mesh])


def brake_path(project, level="high"):
    return cache_of(project) / f"{CAR}_brakelights_{level}.rom"


def read_brake(project, level="high"):
    return read_rom(brake_path(project, level).read_bytes())


@pytest.fixture
def lit_project(project):
    for level in ("high", "low"):
        brake_path(project, level).write_bytes(write_rom(brake_rom()))
    return project


def test_import_brings_in_the_brake_lights(lit_project, tmp_path):
    report = run(lit_project, "import", tmp_path)
    assert report["light_collections"] == [f"{CAR}_brakelights"]
    assert len(report["lights"]) == 1
    assert report["light_materials"] == ["TLANG_lightning"]


def test_brake_lights_bring_no_tags(lit_project, tmp_path):
    assert run(lit_project, "import", tmp_path)["tags"] == ["lefttaillight"]


def test_a_car_with_no_brake_file_imports_without_lights(project, tmp_path):
    assert run(project, "import", tmp_path)["light_collections"] == []


def test_other_models_bring_no_lights(lit_project, tmp_path):
    other = cache_of(lit_project) / f"{CAR}_nosecone.rom"
    other.write_bytes(write_rom(sample_rom()))
    assert run(lit_project, "import", tmp_path, rom_path=other)["light_collections"] == []


def test_importing_the_brake_file_makes_lights_not_body(lit_project, tmp_path):
    report = run(lit_project, "import", tmp_path, rom_path=brake_path(lit_project))
    assert len(report["lights"]) == 1
    assert report["objects"] == []
    assert report["tags"] == []


def test_a_second_import_adds_no_more_lights(lit_project, tmp_path):
    assert len(run(lit_project, "lights_again", tmp_path)["lights"]) == 1


def test_brake_lights_stay_out_of_the_body(lit_project, tmp_path):
    assert run(lit_project, "roundtrip", tmp_path).get("exported")
    rom = read_level(lit_project)
    assert "TLANG_lightning" not in [m.name for m in rom.materials]
    assert sorted(m.flags for m in rom.meshes) == [0x40, 0x44]


@pytest.mark.parametrize("level", ["high", "low"])
def test_a_moved_brake_light_reaches_its_file(lit_project, tmp_path, level):
    assert run(lit_project, "lights_move", tmp_path).get("exported")
    rom = read_brake(lit_project, level)
    assert [v.position[1] for v in rom.meshes[0].vertices] == pytest.approx([0.8, 0.8, 0.8], abs=1e-3)


def test_export_keeps_the_brake_light_format(lit_project, tmp_path):
    run(lit_project, "lights_move", tmp_path)
    rom = read_brake(lit_project)
    assert [m.name for m in rom.materials] == ["TLANG_lightning"]
    assert [t.name for t in rom.tags] == ["com"]
    assert [m.flags for m in rom.meshes] == [0x10]
    assert {v.colour for v in rom.meshes[0].vertices} == {RED}


def test_a_new_light_mesh_is_a_red_brake_light(lit_project, tmp_path):
    assert run(lit_project, "lights_new", tmp_path).get("exported")
    rom = read_brake(lit_project)
    assert [(m.flags, m.material) for m in rom.meshes] == [(0x10, 0)]
    assert {v.colour for v in rom.meshes[0].vertices} == {RED}


def test_a_body_part_moved_to_the_lights_takes_the_brake_flag(lit_project, tmp_path):
    assert run(lit_project, "lights_body_part", tmp_path).get("exported")
    assert [m.flags for m in read_brake(lit_project).meshes] == [0x10, 0x10]


@pytest.mark.parametrize("mode", ["lights_hidden", "lights_deleted"])
def test_no_visible_lights_leaves_the_files_alone(lit_project, tmp_path, mode):
    before = brake_path(lit_project).read_bytes(), brake_path(lit_project, "low").read_bytes()
    assert run(lit_project, mode, tmp_path).get("exported")
    assert (brake_path(lit_project).read_bytes(), brake_path(lit_project, "low").read_bytes()) == before


def test_a_light_with_another_texture_is_refused(lit_project, tmp_path):
    before = brake_path(lit_project).read_bytes()
    assert "skin" in run(lit_project, "lights_bad_material", tmp_path)["error"]
    assert brake_path(lit_project).read_bytes() == before


def test_another_cars_lights_are_ignored(lit_project, tmp_path):
    donor = lit_project / "donor/cars/other/cache"
    donor.mkdir(parents=True)
    (donor / "other_med.rom").write_bytes(write_rom(sample_rom()))
    (donor / "other_brakelights_high.rom").write_bytes(write_rom(brake_rom()))
    assert run(lit_project, "lights_donor", tmp_path).get("exported")
    assert [v.position[1] for v in read_brake(lit_project).meshes[0].vertices] == pytest.approx([0.3, 0.3, 0.3], abs=1e-3)
    assert "TLANG_lightning" not in [m.name for m in read_level(lit_project).materials]


TAIL = "backlight 0.4 1.0 0.2 0.0"
HEAD = "headlight 0.3 1.0 1.0 0.9"


@pytest.fixture
def light_tags(project):
    rom = sample_rom()
    rom.tags += [Tag(tag_record(name.encode(), (0.5, 0.1, z))) for name, z in ((TAIL, -2.0), (TAIL, -2.0), (HEAD, 2.0), ("backlight", -1.0))]
    for level in ("med", "lower_med", "low"):
        (cache_of(project) / f"{CAR}_{level}.rom").write_bytes(write_rom(rom))
    (cache_of(project) / f"{CAR}.pts").write_bytes(write_points(rom.tags))
    return project


def point_names(project):
    data = (cache_of(project) / f"{CAR}.pts").read_bytes()
    return [name.split(b"\0")[0].decode() for name in re.findall(rb"(?:backlight|headlight|com|lefttaillight)[^\0]*\0", data)]


def test_import_shows_a_light_tags_colour(light_tags, tmp_path):
    colours = run(light_tags, "import", tmp_path)["light_colours"]
    assert colours == {TAIL: [1.0, 0.2, 0.0], HEAD: [1.0, 1.0, 0.9]}


@pytest.mark.parametrize("level", ["med", "lower_med", "low"])
def test_a_new_tail_colour_reaches_every_level(light_tags, tmp_path, level):
    assert run(light_tags, "tail_colour", tmp_path).get("exported")
    assert [t.name for t in read_level(light_tags, level).tags].count("backlight 0.4 1.00 0.00 0.50") == 2


def test_a_new_tail_colour_reaches_the_points_file(light_tags, tmp_path):
    run(light_tags, "tail_colour", tmp_path)
    assert point_names(light_tags).count("backlight 0.4 1.00 0.00 0.50") == 2


def test_a_new_head_colour_changes_only_the_headlights(light_tags, tmp_path):
    run(light_tags, "head_colour", tmp_path)
    names = [t.name for t in read_level(light_tags).tags]
    assert "headlight 0.3 0.25 0.75 1.00" in names
    assert names.count(TAIL) == 2


def test_an_unchanged_colour_keeps_the_stock_name(light_tags, tmp_path):
    assert run(light_tags, "roundtrip", tmp_path).get("exported")
    names = [t.name for t in read_level(light_tags).tags]
    assert names.count(TAIL) == 2 and HEAD in names and "backlight" in names


def hitbox_of(project):
    return read_hsc((cache_of(project) / f"{CAR}.hsc").read_bytes())


def flat(entries):
    return [value for entry in entries for value in entry]


def same_planes(found, expected, tolerance=1e-4):
    return len(found) == len(expected) and all(
        any(all(abs(a - b) < tolerance for a, b in zip(plane, other)) for other in found) for plane in expected
    )


def test_import_brings_in_the_hitbox(project, tmp_path):
    report = run(project, "import", tmp_path)
    assert report["hitbox"] == {"hull": 1, "upper": 1, "body": 2, "wire": True, "rendered": False}
    extent = [SAMPLE_BOUNDS[axis + 3] - SAMPLE_BOUNDS[axis] for axis in (0, 2, 1)]
    assert report["hitbox_extent"] == pytest.approx(extent, abs=1e-4)


def test_importing_twice_keeps_the_edited_hitbox(project, tmp_path):
    assert run(project, "hitbox_again", tmp_path)["hitbox_after"]["body"] == 3


def test_the_hitbox_is_not_exported_as_body(project, tmp_path):
    before = triangles(read_level(project))
    assert run(project, "roundtrip", tmp_path).get("exported")
    assert triangles(read_level(project)) == before


def test_an_unedited_hitbox_exports_as_it_was(project, tmp_path):
    assert run(project, "roundtrip", tmp_path).get("exported")
    hitbox = hitbox_of(project)
    assert same_planes(hitbox.plane_groups[0], SAMPLE_HITBOX.plane_groups[0])
    assert flat(hitbox.upper_spheres) == pytest.approx(flat(SAMPLE_HITBOX.upper_spheres), abs=1e-5)
    assert flat(hitbox.body_spheres) == pytest.approx(flat(SAMPLE_HITBOX.body_spheres), abs=1e-5)


def test_a_scaled_hull_and_a_moved_sphere_reach_the_file(project, tmp_path):
    assert run(project, "hitbox_edit", tmp_path).get("exported")
    hitbox = hitbox_of(project)
    # The driver doubles the hull on Blender X, which is game X.
    wide = [b * (2 if axis % 3 == 0 else 1) for axis, b in enumerate(SAMPLE_BOUNDS)]
    assert same_planes(hitbox.plane_groups[0], box_planes(wide))
    # It moves the first body sphere 0.5 up on Blender Z, which is game Y, and doubles its size.
    assert hitbox.body_spheres[0] == pytest.approx((0.5, 0.5, -1.0, 1.2), abs=1e-5)


def test_a_duplicated_sphere_joins_its_list(project, tmp_path):
    assert run(project, "hitbox_duplicate", tmp_path).get("exported")
    assert len(hitbox_of(project).body_spheres) == 3 and len(hitbox_of(project).upper_spheres) == 1


def test_a_concave_hull_exports_as_its_convex_shape(project, tmp_path):
    assert run(project, "hitbox_dent", tmp_path).get("exported")
    assert same_planes(hitbox_of(project).plane_groups[0], SAMPLE_HITBOX.plane_groups[0])


def test_a_hidden_hitbox_leaves_the_file_alone(project, tmp_path):
    before = (cache_of(project) / f"{CAR}.hsc").read_bytes()
    assert run(project, "hitbox_hidden", tmp_path).get("exported")
    assert (cache_of(project) / f"{CAR}.hsc").read_bytes() == before


@pytest.mark.parametrize("mode, words", [("hitbox_stretched", "stretched"), ("hitbox_stray", "not a hitbox sphere"), ("hitbox_no_hull", "no hull")])
def test_a_bad_hitbox_is_refused_and_writes_nothing(project, tmp_path, mode, words):
    before = contents(cache_of(project))
    assert words in run(project, mode, tmp_path)["error"]
    assert contents(cache_of(project)) == before

