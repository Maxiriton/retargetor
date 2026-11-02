"""Generate In-betweens with Kimodo (needs the Kimodo venv and a CUDA GPU), on the Phase 1 Rigify rig.

    blender -b --factory-startup <rig_keyposes.blend> --python tests/blender/test_generate_kimodo.py --
        <base|heading|fps24> <kimodo python> <out dir> [<spike rig_result.json dump>]

base:    key poses on frames 1, 61, 120 at 30 fps, prompt and seed of the Phase 1 spike. Writes the rig's motion
         to <out dir>/base.json. Compared with the spike's result if its dump is given (tests/run_tests.py
         makes it with dump_pose.py). Then regenerates, to time a generation with the model already loaded.
heading: the whole character turned 90 degrees around Z (its torso control, on every key pose): the result
         must be the base result turned 90 degrees.
fps24:   the scene at 24 fps, key poses moved to the same times (frames 1, 49, 96): the result must follow
         the base result at the same times.
"""
import json
import math
import os
import sys
import time

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402
from bootstrap import angle_deg, bone_direction  # noqa: E402

PROMPT = "A person walks forward and raises both arms"
SEED = 1


def setup(kimodo_python):
    bootstrap.register_addon()
    bootstrap.set_backend("kimodo", python=kimodo_python)
    rig = bpy.data.objects["rig"]
    bpy.context.view_layer.objects.active = rig
    bpy.ops.retargetor.profile_load_preset(preset="rigify_human")
    bpy.context.scene.retargetor_target = rig
    rig.retargetor.prompt = PROMPT
    rig.retargetor.seed = SEED
    return rig


def org_bones(rig):
    return [b.read_bone for b in rig.data.retargetor_profile.to_core().roles if b.read_bone]


def motion_snapshot(rig, frames):
    """{frame: {bone: (head, direction)}} in world space, for the ORG bones"""
    scene = bpy.context.scene
    result = {}
    for frame in frames:
        scene.frame_set(frame)
        result[frame] = {n: ((rig.matrix_world @ rig.pose.bones[n].head).copy(), bone_direction(rig, n))
                         for n in org_bones(rig)}
    return result


def save_snapshot(snapshot, path):
    data = {str(f): {n: [list(h), list(d)] for n, (h, d) in bones.items()} for f, bones in snapshot.items()}
    with open(path, "w") as f:
        json.dump(data, f)


def load_snapshot(path):
    with open(path) as f:
        data = json.load(f)
    return {int(f): {n: (Vector(h), Vector(d)) for n, (h, d) in bones.items()} for f, bones in data.items()}


def compare(a, b, pairs, transform=Matrix.Identity(4)):
    """Mean and worst direction (deg) and head distance (cm) between snapshots, on (frame a, frame b) pairs.
    transform is applied to b first."""
    rotation = transform.to_3x3()
    angles, dists = [], []
    for fa, fb in pairs:
        for n, (head, direction) in a[fa].items():
            head_b, dir_b = b[fb][n]
            angles.append(angle_deg(direction, rotation @ dir_b))
            dists.append((head - transform @ head_b).length * 100)
    return sum(angles) / len(angles), max(angles), sum(dists) / len(dists), max(dists)


def generate(checks, label):
    rig = bpy.data.objects["rig"]
    from retargetor import generation
    task = generation.GenerationTask()
    start = time.perf_counter()
    ok = task.run(bpy.context, rig)
    checks.check(ok and task.result is not None, f"{label}: generated")
    print(f"FINDING {label}: {time.perf_counter() - start:.1f} s in all; " +
          ", ".join(f"{name} {seconds:.2f} s" for name, seconds in task.timings.items()))
    return task


def check_follows_model(checks, rig, frames, label):
    """The rig's limbs follow the model's joints"""
    from retargetor.backends.kimodo.joints import JOINT_MAP
    model = rig.retargetor.model_armature
    profile = rig.data.retargetor_profile.to_core()
    limbs = [(b.read_bone, JOINT_MAP[b.role]) for b in profile.roles if b.offset_mode == 'ROLL']
    total = count = 0
    worst = 0.0
    lowest_toe = 1.0
    scene = bpy.context.scene
    for frame in frames:
        scene.frame_set(frame)
        for bone, joint in limbs:
            a = angle_deg(bone_direction(rig, bone), bone_direction(model, joint))
            total, count, worst = total + a, count + 1, max(worst, a)
        lowest_toe = min(lowest_toe, min((rig.matrix_world @ rig.pose.bones[n].tail).z for n in ("ORG-toe.L", "ORG-toe.R")))
    checks.below(total / count, 0.1, f"{label}: rig follows the model, mean limb direction (deg)")
    checks.below(worst, 2.0, f"{label}: rig follows the model, worst limb direction (deg)")
    checks.check(-0.02 < lowest_toe < 0.1, f"{label}: feet on the floor (lowest toe tip {lowest_toe * 100:.1f} cm)")


def key_poses_kept(checks, rig, before, label):
    after = motion_snapshot(rig, before.keys())
    _ma, worst_angle, _md, worst_dist = compare(before, after, [(f, f) for f in before])
    checks.below(worst_angle, 1e-4, f"{label}: key poses untouched, worst direction (deg)")
    checks.below(worst_dist, 1e-3, f"{label}: key poses untouched, worst head (cm)")


def run_base(checks, kimodo_python, out_dir, spike_dump):
    rig = setup(kimodo_python)
    keys = [1, 61, 120]
    before = motion_snapshot(rig, keys)
    generate(checks, "base, first generation (starts Kimodo, loads the model)")
    model = rig.retargetor.model_armature
    checks.check(len(model.data.bones) == 77, f"SOMA armature built from the Kimodo install ({len(model.data.bones)} bones)")

    # The armature built from Kimodo's skeleton is the one Phase 0 imported from Kimodo's BVH
    reference_path = os.path.join(bootstrap.PHASE0_OUT, "soma_reference.blend")
    if os.path.exists(reference_path):
        with bpy.data.libraries.load(reference_path, link=False) as (_data_from, data_to):
            data_to.armatures = [name for name in _data_from.armatures]
        reference = data_to.armatures[0]
        worst_head = max((b.head_local - reference.bones[b.name].head_local).length for b in model.data.bones)
        # End joints (no child) are 1 mm long, up. Blender's BVH importer makes one of them (RightToeEnd) follow
        # its parent instead: its length lands a hair under its 1 mm threshold. Not mapped, no effect.
        worst_tail = max((b.tail_local - reference.bones[b.name].tail_local).length
                         for b in model.data.bones if b.children)
        checks.below(worst_head * 100, 0.001, "SOMA bones vs the Phase 0 BVH import, worst head (cm)")
        checks.below(worst_tail * 100, 0.001, "SOMA bones vs the Phase 0 BVH import, worst tail (cm, end joints aside)")

    key_poses_kept(checks, rig, before, "base")
    check_follows_model(checks, rig, range(1, 121), "base")
    first = motion_snapshot(rig, range(1, 121))
    save_snapshot(first, os.path.join(out_dir, "base.json"))

    if spike_dump:
        # The spike's result (generated by kimodo_gen from the same key poses, prompt and seed)
        dump = bootstrap.load_json(spike_dump)
        names = org_bones(rig)
        spike = {}
        for frame in range(1, 121):
            spike[frame] = {}
            for n in names:
                m = Matrix(dump[str(frame)][n])
                spike[frame][n] = (m.to_translation(), (m.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized())
        mean_a, worst_a, mean_d, worst_d = compare(spike, first, [(f, f) for f in range(1, 121)])
        print(f"FINDING base vs the Phase 1 spike's result: directions mean {mean_a:.2f} deg, worst {worst_a:.1f} deg; "
              f"heads mean {mean_d:.1f} cm, worst {worst_d:.1f} cm")
        checks.below(mean_a, 10.0, "close to the spike's result (same key poses, prompt and seed), mean direction (deg)")

    # Again, with the model loaded: same seed, same result
    task = generate(checks, "base, second generation (model loaded)")
    checks.below(task.timings["generation"], 8.0, "second generation, model already loaded (s)")
    again = motion_snapshot(rig, range(1, 121))
    mean_a, worst_a, mean_d, worst_d = compare(first, again, [(f, f) for f in range(1, 121)])
    print(f"FINDING same seed twice: directions mean {mean_a:.4f} deg, worst {worst_a:.3f} deg; worst head {worst_d:.3f} cm")
    checks.below(worst_d, 1.0, "same seed twice, worst head (cm)")


def run_heading(checks, kimodo_python, out_dir):
    rig = setup(kimodo_python)
    scene = bpy.context.scene
    # Rigify's root control turns everything; the torso alone would leave the head and the FK arms behind
    # (they follow the root, not the torso, by default)
    turn = Matrix.Rotation(math.radians(90.0), 4, 'Z')
    root = rig.pose.bones["root"]
    root.rotation_mode = 'QUATERNION'
    root.matrix = rig.matrix_world.inverted() @ turn @ rig.matrix_world @ root.matrix
    bpy.context.view_layer.update()
    root.keyframe_insert("rotation_quaternion", frame=1)
    keys = [1, 61, 120]
    before = motion_snapshot(rig, keys)
    base = load_snapshot(os.path.join(out_dir, "base.json"))
    _ma, worst_angle, _md, worst_dist = compare(before, base, [(f, f) for f in keys], turn)
    checks.below(worst_angle, 0.01, "key poses turned 90 degrees around Z, worst direction (deg)")
    checks.below(worst_dist, 0.01, "key poses turned 90 degrees around Z, worst head (cm)")

    task = generate(checks, "heading 90")
    key_poses_kept(checks, rig, before, "heading")
    check_follows_model(checks, rig, range(1, 121), "heading")
    turned = motion_snapshot(rig, range(1, 121))
    mean_a, worst_a, mean_d, worst_d = compare(turned, base, [(f, f) for f in range(1, 121)], turn)
    print(f"FINDING turned 90 degrees vs base turned: directions mean {mean_a:.3f} deg, worst {worst_a:.2f} deg; "
          f"heads mean {mean_d:.2f} cm, worst {worst_d:.2f} cm")
    checks.below(mean_d, 1.0, "the turned character's motion is the base motion turned, mean head (cm)")
    checks.below(worst_d, 5.0, "the turned character's motion is the base motion turned, worst head (cm)")
    return task


def run_fps24(checks, kimodo_python, out_dir):
    rig = setup(kimodo_python)
    scene = bpy.context.scene
    from retargetor import generation
    # Same times at 24 fps: 0 s, 2 s, 3.97 s -> frames 1, 49, 96 (the last one 0.01 s earlier)
    moves = {61: 49, 120: 96}
    for fcurve in generation.bone_fcurves(rig):
        for point in fcurve.keyframe_points:
            new = moves.get(round(point.co.x))
            if new is not None:
                shift = new - point.co.x
                point.co.x += shift
                point.handle_left.x += shift
                point.handle_right.x += shift
        fcurve.update()
    scene.render.fps = 24
    scene.render.fps_base = 1.0
    scene.frame_end = 96
    keys = [1, 49, 96]
    before = motion_snapshot(rig, keys)
    generate(checks, "24 fps")
    key_poses_kept(checks, rig, before, "24 fps")
    check_follows_model(checks, rig, range(1, 97), "24 fps")
    bag = generation.channelbag(rig)
    fcurve = bag.fcurves.find('pose.bones["upper_arm_fk.L"].rotation_quaternion', index=0)
    generated = sorted(round(p.co.x) for p in fcurve.keyframe_points if p.type == 'GENERATED')
    checks.check(generated == [f for f in range(2, 96) if f != 49], "one GENERATED key per scene frame, 24 fps")

    # Kimodo gets the same inputs as at 30 fps (model frames 0, 60, 119): frame 25 at 24 fps is model frame 30,
    # frame 31 at 30 fps. The motion must be the base one at the same times.
    fps24 = motion_snapshot(rig, range(1, 97))
    base = load_snapshot(os.path.join(out_dir, "base.json"))
    pairs = [(f24, 1 + round((f24 - 1) * 30 / 24)) for f24 in range(1, 49, 4)]  # first segment: exact times
    mean_a, worst_a, mean_d, worst_d = compare(fps24, base, pairs)
    print(f"FINDING 24 fps vs 30 fps at the same times (first segment): directions mean {mean_a:.3f} deg, "
          f"worst {worst_a:.2f} deg; heads worst {worst_d:.2f} cm")
    checks.below(mean_d, 1.0, "24 fps result follows the 30 fps one at the same times, mean head (cm)")


def main():
    args = bootstrap.script_args()
    mode, kimodo_python, out_dir = args[0], args[1], args[2]
    spike_dump = args[3] if len(args) > 3 else None
    checks = bootstrap.Checks(f"test_generate_kimodo {mode}")
    try:
        if mode == "base":
            run_base(checks, kimodo_python, out_dir, spike_dump)
        elif mode == "heading":
            run_heading(checks, kimodo_python, out_dir)
        elif mode == "fps24":
            run_fps24(checks, kimodo_python, out_dir)
    finally:
        from retargetor.backends import registry
        registry.stop_all()
    checks.finish()


if __name__ == "__main__":
    main()
