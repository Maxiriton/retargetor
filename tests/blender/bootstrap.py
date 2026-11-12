"""Shared helpers for the headless Blender tests.

Each test runs in its own Blender process, always with --factory-startup (your Blender may already load the
repository as an extension), for example:
    blender -b --factory-startup [file.blend] --python tests/blender/test_panel.py -- [args]

The add-on is imported from this repository as the package "retargetor", whatever the folder is called.
"""
import importlib.util
import json
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
FIXTURES = os.path.join(REPO, "tests", "fixtures")
PRESETS = os.path.join(REPO, "presets")

# Spike outputs (not committed). Override with the RETARGETOR_SPIKES environment variable,
# pointing to a folder holding phase0/out and phase1/out.
SPIKES = os.environ.get("RETARGETOR_SPIKES", os.path.join(REPO, "spikes"))
PHASE0_OUT = os.path.join(SPIKES, "phase0", "out")
PHASE1_OUT = os.path.join(SPIKES, "phase1", "out")


def script_args():
    """Arguments after "--" on the Blender command line"""
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def register_addon():
    """Import the add-on from the repository as "retargetor" and register it. Returns the package."""
    if "retargetor" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "retargetor", os.path.join(REPO, "__init__.py"), submodule_search_locations=[REPO])
        package = importlib.util.module_from_spec(spec)
        sys.modules["retargetor"] = package
        spec.loader.exec_module(package)
    package = sys.modules["retargetor"]
    if not hasattr(bpy.types.Object, "retargetor"):
        package.register()
    # The add-on isn't enabled through Blender here: give it an entry so its preferences exist
    if bpy.context.preferences.addons.get("retargetor") is None:
        bpy.context.preferences.addons.new().module = "retargetor"
    return package


def set_backend(backend_id, developer=False, python=None, **settings):
    """Choose the active backend in the add-on preferences, and set its settings. python: the model's existing
    environment (its Python executable), instead of one installed by the add-on; "managed": the one the add-on
    installed, in the models' folder given by the RETARGETOR_MODELS_FOLDER environment variable (else the default)."""
    prefs = bpy.context.preferences.addons["retargetor"].preferences
    prefs.developer = developer
    prefs.backend = backend_id
    if python == "managed":
        getattr(prefs, f"setup_{backend_id}").environment = 'MANAGED'
        prefs.models_folder = os.environ.get("RETARGETOR_MODELS_FOLDER", "")
    elif python is not None:
        setup = getattr(prefs, f"setup_{backend_id}")
        setup.environment = 'EXISTING'
        setup.python = python
    backend_settings = getattr(prefs, f"settings_{backend_id}", None)
    for name, value in settings.items():
        setattr(backend_settings, name, value)
    return prefs


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def soma_fixture():
    """(role -> SOMA joint map, root joint) of the Kimodo backend"""
    from retargetor.backends.kimodo.joints import JOINT_MAP, ROOT_JOINT
    return dict(JOINT_MAP), ROOT_JOINT


def rigify_profile():
    from retargetor.core.profile import RigProfile
    return RigProfile.from_dict(load_json(os.path.join(PRESETS, "rigify_human.json")))


def require(path):
    if not os.path.exists(path):
        raise SystemExit(f"Missing test input: {path}\nRun the spike commands (spikes/*/README.md) or set RETARGETOR_SPIKES.")
    return path


def bone_direction(arm, name):
    return ((arm.matrix_world @ arm.pose.bones[name].matrix).to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()


def angle_deg(a, b):
    return math.degrees(a.angle(b, 0.0))


class Checks:
    """Collects test results; exits with code 1 at the end if one failed."""

    def __init__(self, name):
        self.name = name
        self.failures = []
        self.count = 0

    def check(self, condition, message):
        self.count += 1
        status = "ok  " if condition else "FAIL"
        print(f"[{status}] {message}")
        if not condition:
            self.failures.append(message)

    def close(self, value, expected, tolerance, message):
        self.check(abs(value - expected) <= tolerance, f"{message}: {value:.4f} (expected {expected:.4f} ± {tolerance})")

    def below(self, value, limit, message):
        self.check(value <= limit, f"{message}: {value:.4f} (limit {limit})")

    def finish(self):
        print(f"{self.name}: {self.count - len(self.failures)}/{self.count} checks passed")
        if self.failures:
            print(f"{self.name}: FAILED")
            sys.stdout.flush()
            os._exit(1)
        print(f"{self.name}: OK")
        sys.stdout.flush()


### A small test scene: two armatures with different rest poses and an animated source

SOURCE_BONES = [
    # name, head, tail, roll (degrees), parent
    ("Hips", (0.0, 0.0, 1.0), (0.0, 0.0, 1.1), 0.0, None),
    ("Spine", (0.0, 0.0, 1.1), (0.0, 0.0, 1.4), 0.0, "Hips"),
    ("Arm.L", (0.1, 0.0, 1.35), (0.4, 0.0, 1.35), 0.0, "Spine"),
    ("Forearm.L", (0.4, 0.0, 1.35), (0.7, 0.0, 1.35), 0.0, "Arm.L"),
    ("Leg.L", (0.1, 0.0, 1.0), (0.1, 0.0, 0.5), 0.0, "Hips"),
    ("Shin.L", (0.1, 0.0, 0.5), (0.1, 0.0, 0.05), 0.0, "Leg.L"),
]
# Bigger, arms sloping down (A-pose), other rolls, other names
TARGET_BONES = [
    ("hips", (0.0, 0.0, 1.2), (0.0, 0.05, 1.35), 30.0, None),
    ("spine", (0.0, 0.05, 1.35), (0.0, 0.0, 1.7), -20.0, "hips"),
    ("arm.L", (0.12, 0.0, 1.65), (0.4, 0.0, 1.4), 45.0, "spine"),
    ("forearm.L", (0.4, 0.0, 1.4), (0.68, 0.02, 1.15), 90.0, "arm.L"),
    ("leg.L", (0.12, 0.0, 1.2), (0.12, 0.02, 0.6), 10.0, "hips"),
    ("shin.L", (0.12, 0.02, 0.6), (0.12, 0.0, 0.06), -35.0, "leg.L"),
]


def make_armature(name, bones, location=(0.0, 0.0, 0.0)):
    data = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, data)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    for bone_name, head, tail, roll, parent in bones:
        eb = data.edit_bones.new(bone_name)
        eb.head, eb.tail, eb.roll = head, tail, math.radians(roll)
        if parent:
            eb.parent = data.edit_bones[parent]
            eb.use_connect = False
    bpy.ops.object.mode_set(mode='OBJECT')
    for pb in obj.pose.bones:
        pb.rotation_mode = 'QUATERNION'
    return obj


def animate_source(source, frames=range(1, 11)):
    """Some motion on every bone of the source, and the hips moving forward"""
    from mathutils import Euler
    for frame in frames:
        t = (frame - 1) / 9.0
        for i, pb in enumerate(source.pose.bones):
            pb.rotation_quaternion = Euler((0.6 * t * (1 + i % 2), 0.3 * t * (i % 3 - 1), 0.4 * t), 'XYZ').to_quaternion()
            pb.keyframe_insert("rotation_quaternion", frame=frame)
        hips = source.pose.bones["Hips"]
        hips.location = (0.0, 0.5 * t, 0.1 * t)
        hips.keyframe_insert("location", frame=frame)


def make_test_scene():
    """New empty scene with SRC (animated, frames 1-10) and TGT next to it. Returns (source, target)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 10
    source = make_armature("SRC", SOURCE_BONES)
    target = make_armature("TGT", TARGET_BONES, location=(2.0, 0.0, 0.0))
    animate_source(source)
    return source, target


### The rig model (core/retarget/rig_model.py) against Blender's evaluation

def rig_keys(rig):
    """{(data path, index, frame): value} of every key of the rig's action"""
    from retargetor import generation
    bag = generation.channelbag(rig)
    keys = {}
    if bag is None:
        return keys
    for fcurve in bag.fcurves:
        for point in fcurve.keyframe_points:
            keys[(fcurve.data_path, fcurve.array_index, round(point.co.x, 3))] = point.co.y
    return keys


def check_rig_model(checks, rig, label, expect_model=True):
    """Generate In-betweens with the rig model, then again from the same file through Blender's evaluation (the
    writers' old way): the keys must be the same. The file is saved to a temporary copy and opened again (a
    generation changes what the next one starts from): the objects must be looked up again afterwards. Returns
    the rig of the file opened again, with the second generation's keys."""
    import tempfile
    from retargetor import generation
    name = rig.name
    copy = os.path.join(tempfile.mkdtemp(prefix="retargetor_"), "before.blend")
    bpy.ops.wm.save_as_mainfile(filepath=copy, copy=True)

    def generate(use_model):
        generation.USE_RIG_MODEL = use_model
        try:
            task = generation.GenerationTask()
            ok = task.run(bpy.context, bpy.data.objects[name])
        finally:
            generation.USE_RIG_MODEL = True
        how = "with the rig model" if use_model else "through Blender's evaluation"
        checks.check(ok and task.result is not None, f"{label}: generated {how}")
        return task, rig_keys(bpy.data.objects[name])

    # Both from the file as saved (what Blender keeps in memory besides, the rig check done once, is left out)
    bpy.ops.wm.open_mainfile(filepath=copy)
    task, fast = generate(True)
    if expect_model:
        for writer in (task.writer, task.ik_writer):
            if writer is None:
                continue
            updates = writer.model.updates if writer.model is not None else None
            checks.check(writer.model is not None, f"{label}: {type(writer).__name__} uses the rig model "
                                                   f"({writer.model_problem or f'{updates} scene updates per frame'})")
    bpy.ops.wm.open_mainfile(filepath=copy)
    reference, slow = generate(False)

    def timing(t):
        return ", ".join(f"{part} {seconds:.2f} s" for part, seconds in t.timings.items()
                         if part in ("writing", "IK snap"))
    print(f"FINDING {label}: with the rig model {timing(task)}; through Blender's evaluation {timing(reference)}")
    checks.check(set(fast) == set(slow), f"{label}: the same keys ({len(set(fast) ^ set(slow))} differ: "
                                         f"{sorted(set(fast) ^ set(slow))[:3]})")
    common = set(fast) & set(slow)
    worst = max((abs(fast[k] - slow[k]), k) for k in common) if common else (0.0, None)
    print(f"FINDING {label}: worst key difference {worst[0]:.2e} ({worst[1]})")
    for difference, key in sorted(((abs(fast[k] - slow[k]), k) for k in common), reverse=True)[:12]:
        if difference > 1e-4:
            print(f"   {difference:.2e} {key}: {fast[key]:.5f} with the model, {slow[key]:.5f} without")
    checks.below(worst[0], 1e-4, f"{label}: the rig model writes the same values as Blender's evaluation")
    return bpy.data.objects[name]
