"""The add-on on real rigs other than the Phase 1 Rigify rig (not committed: see tests/fixtures/real_rigs.json).

    blender -b --factory-startup <rig.blend> --python tests/blender/test_rigs.py -- <object> <expected source>
            [<Kimodo venv python.exe>]
    blender -b --factory-startup --python tests/blender/test_rigs.py -- <object> <expected source> [...]
            --fbx <file.fbx>

<expected source>: the preset's name, or "detected" for a skeleton set up by the detection.
--pose <bone>: also turn that control 20 degrees on both key poses (Rigify's hips control, between the control
written for the hips and the bone read: it must not be counted twice).
Checks: chosen as the character, the rig sets itself up; the rig check finds no error; two key poses made with the
rig's own controls (an IK hand moved where the limb is in IK, else the FK controls turned), then Generate
In-betweens with the interpolation backend: the key poses stay, the motion goes between them. With Kimodo's
Python: the prompt alone, 2 s, the character walks.
"""
import math
import os
import sys
import time

import bpy
from mathutils import Euler, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402

KEY_FRAMES = (1, 41)


def include(obj):
    """Put the object's collections back in the view layer (a file may exclude them)"""
    def walk(layer_collection):
        if obj.name in layer_collection.collection.objects:
            layer_collection.exclude = False
            layer_collection.hide_viewport = False
            return True
        found = False
        for child in layer_collection.children:
            if walk(child):
                layer_collection.exclude = False
                found = True
        return found
    walk(bpy.context.view_layer.layer_collection)
    obj.hide_set(False)
    obj.hide_viewport = False


def in_ik(rig, limb):
    if not limb.switch_bone or not limb.switch_property:
        return False
    return abs(rig.pose.bones[limb.switch_bone][limb.switch_property] - limb.fk_value) > 0.5


def key_bone(pb, frame):
    from retargetor.core.retarget.snap import rotation_data_path
    pb.keyframe_insert(rotation_data_path(pb), frame=frame)
    if not any(pb.lock_location):
        pb.keyframe_insert("location", frame=frame)


def pose_key_poses(rig, profile, extra=()):
    """Two key poses made with the rig's controls, and the `extra` controls turned on both; returns the bones
    keyed"""
    from retargetor.core.retarget.snap import set_rotation
    limbs = {limb.name: limb for limb in profile.limbs}
    posed = []   # (pose bone, posed callback)

    def turn(name, euler):
        def apply(pb):
            set_rotation(pb, pb.rotation_mode, pb.matrix_basis.to_quaternion() @ Euler(euler).to_quaternion())
        return name, apply

    def move(name, offset):
        def apply(pb):
            target = pb.matrix.copy()
            target.translation += Vector(offset)
            pb.matrix = target
        return name, apply

    for role, limb_name, euler, offset in (("upper_arm.L", "arm.L", (math.radians(60), 0.0, math.radians(20)), (0.0, -0.25, 0.3)),
                                           ("thigh.R", "leg.R", (math.radians(-40), 0.0, 0.0), (0.0, -0.3, 0.15))):
        limb = limbs.get(limb_name)
        if limb is not None and in_ik(rig, limb):
            follow = next(s for s in limb.ik_snap if s.mode == 'FOLLOW')
            posed.append(move(follow.ik_control, offset))
        else:
            posed.append(turn(profile.binding(role).write_bone, euler))
    for role in ("upper_chest", "spine", "chest"):
        binding = profile.binding(role)
        if binding is not None and binding.write_bone:
            spine = limbs.get("spine")
            if spine is None or not in_ik(rig, spine):
                posed.append(turn(binding.write_bone, (math.radians(20), 0.0, 0.0)))
            break

    scene = bpy.context.scene
    for name in extra:
        pb = rig.pose.bones[name]
        set_rotation(pb, pb.rotation_mode, pb.matrix_basis.to_quaternion() @ Euler((math.radians(20), 0.0, 0.0)).to_quaternion())
        for frame in KEY_FRAMES:
            key_bone(pb, frame)
    for frame in KEY_FRAMES:
        scene.frame_set(frame)
        for name, apply in posed:
            pb = rig.pose.bones[name]
            if frame != KEY_FRAMES[0]:
                apply(pb)
                bpy.context.view_layer.update()
            key_bone(pb, frame)
    return [name for name, _apply in posed] + list(extra)


def read_points(rig, profile, frames):
    scene = bpy.context.scene
    names = [b.read_bone for b in profile.roles if b.read_bone]
    result = {}
    for frame in frames:
        scene.frame_set(frame)
        result[frame] = {n: (rig.matrix_world @ rig.pose.bones[n].head).copy() for n in names}
    return result


def main():
    args = bootstrap.script_args()
    if "--fbx" in args:
        fbx = args[args.index("--fbx") + 1]
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=fbx)
    name, expected = args[0], args[1]
    kimodo_python = args[2] if len(args) > 2 and not args[2].startswith("--") else None
    extra = [args[i + 1] for i, arg in enumerate(args) if arg == "--pose"]
    checks = bootstrap.Checks(f"test_rigs {name}")
    bootstrap.register_addon()
    bootstrap.set_backend("interpolate", developer=True)
    from retargetor import profile_operators, rig_check
    scene, view_layer = bpy.context.scene, bpy.context.view_layer
    rig = bpy.data.objects[name]
    include(rig)
    if rig.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    view_layer.objects.active = rig
    scene.retargetor_target = rig
    profile = rig.data.retargetor_profile
    want = profile_operators.DETECTED_SOURCE if expected == "detected" else expected
    checks.check(profile.source == want, f"set up when chosen: {profile_operators.source_label(profile.source)}")
    rig_profile = profile.to_core()
    print(f"FINDING {len(rig_profile.roles)} roles, {len(rig_profile.limbs)} IK/FK limbs")

    start = time.perf_counter()
    problems = profile_operators.run_check(rig, rig_profile, view_layer)
    print(f"FINDING rig check: {time.perf_counter() - start:.1f} s")
    for problem in problems:
        print(f"FINDING check {problem.level}: {problem.message}")
    checks.check(not any(p.level == rig_check.ERROR for p in problems), "the rig check finds no error")

    posed = pose_key_poses(rig, rig_profile, extra)
    print(f"FINDING key poses made with {', '.join(posed)}")
    before = read_points(rig, rig_profile, KEY_FRAMES)
    halfway = (KEY_FRAMES[0] + KEY_FRAMES[1]) // 2
    scene.frame_set(KEY_FRAMES[0])
    from retargetor import generation
    task = generation.GenerationTask()
    start = time.perf_counter()
    ok = task.run(bpy.context, rig)
    checks.check(ok and task.result is not None, f"Generate In-betweens ({time.perf_counter() - start:.1f} s)")
    for note in getattr(task, "notes", []):
        print(f"FINDING note: {note}")
    after = read_points(rig, rig_profile, KEY_FRAMES)
    worst = max((after[f][n] - p).length for f in KEY_FRAMES for n, p in before[f].items()) * 100
    print(f"FINDING key poses moved at most {worst:.2f} cm")
    for frame in KEY_FRAMES:
        moved = sorted(((after[frame][n] - p).length * 100, n) for n, p in before[frame].items())[-4:]
        print(f"FINDING frame {frame}: most moved " + ", ".join(f"{n} {d:.2f} cm" for d, n in reversed(moved)))
    checks.below(worst, 1.0, "the key poses stay (cm)")
    hand = rig_profile.binding("hand.L").read_bone
    mid = read_points(rig, rig_profile, [halfway])[halfway][hand]
    a, b = before[KEY_FRAMES[0]][hand], before[KEY_FRAMES[1]][hand]
    print(f"FINDING the left hand halfway: {(mid - a).length * 100:.1f} cm from the first key pose, "
          f"{(mid - b).length * 100:.1f} cm from the second ({(b - a).length * 100:.1f} cm apart)")
    checks.check((mid - a).length > 0.02 and (mid - b).length > 0.02, "the left hand moves between the key poses")

    # The writers' rig model gives the keys Blender's evaluation gives
    # The file is opened again: look the objects up again
    rig = bootstrap.check_rig_model(checks, rig, name)
    scene, view_layer = bpy.context.scene, bpy.context.view_layer

    if kimodo_python:
        bootstrap.set_backend("kimodo", python=kimodo_python)
        state = rig.retargetor
        state.prompt = "A person walks forward"
        state.range_mode = 'CUSTOM'
        state.range_start, state.range_duration = 100, 60
        hips = rig_profile.binding("hips").read_bone
        scene.frame_set(100)
        origin = rig.matrix_world @ rig.pose.bones[hips].head
        task = generation.GenerationTask()
        start = time.perf_counter()
        ok = task.run(bpy.context, rig)
        checks.check(ok and task.result is not None, f"Kimodo, the prompt alone ({time.perf_counter() - start:.1f} s)")
        scene.frame_set(159)
        walked = ((rig.matrix_world @ rig.pose.bones[hips].head) - origin) * Vector((1.0, 1.0, 0.0))
        print(f"FINDING Kimodo: walked {walked.length:.2f} m in 2 s")
        checks.check(walked.length > 0.5, "Kimodo: the character walks")
        # The feet turn from their rest pose like the model's (on tiptoe when a flat foot control was given the
        # direction of a sloping foot)
        from retargetor.backends.kimodo.joints import JOINT_MAP
        model = state.model_armature

        def from_rest(obj, name):
            pb = obj.pose.bones[name]
            return ((obj.matrix_world @ pb.matrix).to_quaternion()
                    @ (obj.matrix_world @ pb.bone.matrix_local).to_quaternion().inverted())
        gaps = []
        for frame in range(100, 160, 3):
            scene.frame_set(frame)
            for side in ("L", "R"):
                foot = rig_profile.binding(f"foot.{side}").read_bone
                gap = from_rest(rig, foot).rotation_difference(from_rest(model, JOINT_MAP[f"foot.{side}"])).angle
                gaps.append(abs(math.degrees(min(gap, 2 * math.pi - gap))))
        mean_gap = sum(gaps) / len(gaps)
        print(f"FINDING Kimodo: the feet turn {mean_gap:.1f} deg away from the model's on average, "
              f"{max(gaps):.1f} at most")
        checks.below(mean_gap, 5.0, "Kimodo: the feet turn like the model's (deg)")
    checks.finish()


if __name__ == "__main__":
    main()
