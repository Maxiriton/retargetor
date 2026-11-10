"""Generate In-betweens with Kimodo (needs the Kimodo venv and a CUDA GPU), on the Phase 1 Rigify rig.

    blender -b --factory-startup <rig_keyposes.blend> --python tests/blender/test_generate_kimodo.py --
        <base|heading|fps24|range|ik|partial|segments|segment> <kimodo python> <out dir> [<spike rig_result.json dump>]

base:    key poses on frames 1, 61, 120 at 30 fps, prompt and seed of the Phase 1 spike. Writes the rig's motion
         to <out dir>/base.json. Compared with the spike's result if its dump is given (tests/run_tests.py
         makes it with dump_pose.py). Then regenerates, to time a generation with the model already loaded.
heading: the whole character turned 90 degrees around Z (its torso control, on every key pose): the result
         must be the base result turned 90 degrees.
fps24:   the scene at 24 fps, key poses moved to the same times (frames 1, 49, 96): the result must follow
         the base result at the same times.
ik:      on rig_keyposes_ik.blend (the same key poses made with the IK controls only, every limb in IK): the
         FK controls are snapped to the IK pose automatically; the result must be close to the base one.
partial: after the base generation, the left arm raised and keyed alone on frame 90 (over the generated keys,
         as an animator would): a partial key pose, Kimodo's left hand end-effector.
range:   custom ranges: the prompt alone (no key pose, the character turned 90 degrees), starting from one key
         pose, ending on one key pose.
segments: on rig_keyposes_ik.blend, three prompt segments of 5 s (15 s in all, past Kimodo's 10 s), the key poses in
         the first one: one request, key poses untouched, no jump where the segments meet, same seeds same motion.
segment: on rig_keyposes_ik.blend, the same track generated, then its second segment regenerated alone with another
         prompt and seed: the rest of the track unchanged, no jump where the segment meets its neighbours.
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


def generate(checks, label, segment=None):
    rig = bpy.data.objects["rig"]
    from retargetor import generation
    task = generation.GenerationTask()
    start = time.perf_counter()
    ok = task.run(bpy.context, rig, segment=segment)
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


def hips_heading(rig):
    """Where the character faces (radians around Z, 0 = -Y, Blender's front), from its thighs"""
    left = rig.matrix_world @ rig.pose.bones["ORG-thigh.L"].head
    right = rig.matrix_world @ rig.pose.bones["ORG-thigh.R"].head
    side = left - right  # points to the character's left (+X when facing -Y)
    return math.atan2(side.y, side.x)


def angle_between(a, b):
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


def generated_frames(rig, bone="upper_arm_fk.L"):
    from retargetor import generation
    bag = generation.channelbag(rig)
    fcurve = bag.fcurves.find(f'pose.bones["{bone}"].rotation_quaternion', index=0)
    return {round(p.co.x) for p in fcurve.keyframe_points if p.type == 'GENERATED'}


def jump_cm(rig, frame_a, frame_b, bone="ORG-spine"):
    scene = bpy.context.scene
    scene.frame_set(frame_a)
    a = rig.matrix_world @ rig.pose.bones[bone].head
    scene.frame_set(frame_b)
    return ((rig.matrix_world @ rig.pose.bones[bone].head) - a).length * 100


def run_range(checks, kimodo_python):
    rig = setup(kimodo_python)
    scene = bpy.context.scene
    state = rig.retargetor

    # The prompt alone, frames 200-289, past every key pose; the whole character turned 90 degrees (Rigify's
    # root: not a control of the profile, so it doesn't make a key pose)
    root = rig.pose.bones["root"]
    root.rotation_mode = 'QUATERNION'
    root.rotation_quaternion = Matrix.Rotation(math.radians(90.0), 4, 'Z').to_quaternion()
    root.keyframe_insert("rotation_quaternion", frame=200)
    scene.frame_set(200)
    start_hips = (rig.matrix_world @ rig.pose.bones["ORG-spine"].head).copy()
    start_heading = hips_heading(rig)
    state.range_mode = 'CUSTOM'
    state.range_start, state.range_duration = 200, 90
    rig.retargetor.prompt = "A person walks forward"
    task = generate(checks, "prompt only, first generation (starts Kimodo)")
    checks.check(task.key_frames == [] and (task.start_frame, task.end_frame) == (200, 289),
                 f"no key pose, frames 200-289 ({task.key_frames})")
    checks.check(generated_frames(rig) == set(range(200, 290)), "GENERATED keys on every frame of the range")
    check_follows_model(checks, rig, range(200, 290), "prompt only")
    scene.frame_set(200)
    hips = rig.matrix_world @ rig.pose.bones["ORG-spine"].head
    moved = ((hips - start_hips) * Vector((1.0, 1.0, 0.0))).length * 100
    turn = math.degrees(angle_between(hips_heading(rig), start_heading))
    print(f"FINDING prompt only: the motion starts {moved:.1f} cm from the character, turned {turn:.1f} deg")
    checks.below(moved, 15.0, "prompt only: starts where the character stands (cm, horizontal)")
    checks.below(turn, 20.0, "prompt only: starts facing where the character faces (deg)")
    scene.frame_set(289)
    walked = ((rig.matrix_world @ rig.pose.bones["ORG-spine"].head) - hips).length
    # The character's left side is (cos h, sin h): its front is left x up
    left = Vector((math.cos(start_heading), math.sin(start_heading), 0.0))
    forward = left.cross(Vector((0.0, 0.0, 1.0)))
    along = ((rig.matrix_world @ rig.pose.bones["ORG-spine"].head) - hips).dot(forward)
    print(f"FINDING prompt only: walked {walked:.2f} m, {along:.2f} m forward")
    checks.check(along > 0.5, f"prompt only: walks forward, where the character faces ({along:.2f} m)")

    # The generation made prompt segment 1 (shown in the timeline)
    checks.check([(i.frame_start, i.frame_end, i.prompt) for i in state.segments] == [(200, 289, "A person walks forward")],
                 "the generation became prompt segment 1")
    # One key pose, at the start: frames 120-239 start from the key pose on frame 120 (without the segment, the
    # custom range is used again)
    state.segments.clear()
    state.range_start, state.range_duration = 120, 120
    before = motion_snapshot(rig, [120])
    task = generate(checks, "starting from one key pose")
    checks.check(task.key_frames == [120], f"one key pose ({task.key_frames})")
    key_poses_kept(checks, rig, before, "one key pose at the start")
    checks.check(generated_frames(rig) >= set(range(121, 240)), "GENERATED keys after the key pose")
    check_follows_model(checks, rig, range(120, 240), "one key pose at the start")
    checks.below(jump_cm(rig, 120, 121), 5.0, "one key pose at the start: no jump after it (cm)")

    # One key pose, at the end: frames 70-120 end on the key pose on frame 120
    state.segments.clear()
    state.range_start, state.range_duration = 70, 51
    state.prompt = "A person takes a few steps"
    before = motion_snapshot(rig, [120])
    task = generate(checks, "ending on one key pose")
    checks.check(task.key_frames == [120], f"one key pose ({task.key_frames})")
    key_poses_kept(checks, rig, before, "one key pose at the end")
    checks.check(generated_frames(rig) >= set(range(70, 120)), "GENERATED keys before the key pose")
    checks.below(jump_cm(rig, 119, 120), 5.0, "one key pose at the end: no jump before it (cm)")


def run_ik(checks, kimodo_python, out_dir):
    rig = setup(kimodo_python)
    keys = [1, 61, 120]
    before = motion_snapshot(rig, keys)
    from test_generate_ik import ik_vs_fk, in_fk
    switches = {limb.name: rig.pose.bones[limb.switch_bone] for limb in rig.data.retargetor_profile.to_core().limbs}
    checks.check(all(s["IK_FK"] == 0.0 for s in switches.values()), "every limb starts in IK")
    task = generate(checks, "IK limbs, first generation (starts Kimodo)")
    print("FINDING " + "; ".join(task.notes))
    checks.check(all(s["IK_FK"] == 0.0 for s in switches.values()), "every limb back in IK")
    after = in_fk(rig, switches, lambda: motion_snapshot(rig, keys))
    _ma, worst_angle, _md, worst_dist = compare(before, after, [(f, f) for f in keys])
    checks.below(worst_angle, 0.05, "the FK controls take the IK pose on the key poses, worst direction (deg)")
    checks.below(worst_dist, 1.0, "the FK controls take the IK pose on the key poses, worst head (cm, Rigify's IK "
                                  "stretch)")
    key_poses_kept(checks, rig, before, "IK limbs, in IK")
    in_fk(rig, switches, lambda: check_follows_model(checks, rig, range(1, 121), "IK limbs, in FK"))
    # The IK key poses are the FK ones up to Rigify's IK stretch (up to 2.7 degrees on the elbows)
    base = load_snapshot(os.path.join(out_dir, "base.json"))
    generated = in_fk(rig, switches, lambda: motion_snapshot(rig, range(1, 121)))
    mean_a, worst_a, mean_d, worst_d = compare(base, generated, [(f, f) for f in range(1, 121)])
    print(f"FINDING IK limbs vs base (FK key poses): directions mean {mean_a:.2f} deg, worst {worst_a:.1f} deg; "
          f"heads mean {mean_d:.1f} cm, worst {worst_d:.1f} cm")
    checks.below(mean_a, 5.0, "IK limbs: close to the base result, mean direction (deg)")
    # Played in IK: the IK controls follow the generated motion
    between = [f for f in range(1, 121) if f not in keys]
    keyed_ends, _joints, _jump = ik_vs_fk(rig, switches, keys)
    gap_ends, gap_joints, _jump = ik_vs_fk(rig, switches, between)
    _ends, _joints, jump = ik_vs_fk(rig, switches, list(range(1, 121)))
    print(f"FINDING IK limbs played in IK vs FK: on the key poses hands and feet {keyed_ends:.1f} mm; between them "
          f"hands and feet {gap_ends:.1f} mm, elbows and knees {gap_joints:.1f} mm; worst jump {jump:.1f} mm")
    checks.below(gap_ends, keyed_ends + 0.5, "in IK, the hands and feet follow the motion, up to the gap of the key "
                                             "poses (mm)")
    # Rigify's IK chain is a little shorter than the FK one: where the generated leg is straight (frames 76-79), the
    # IK knee stays bent, 3 to 4.5 cm forward
    checks.below(gap_joints, 50.0, "in IK, the elbows and knees follow the motion (mm)")
    # Where the generated leg straightens (frame 76), Rigify's IK knee pops forward by up to 3 cm: its IK solver,
    # with ik_stretch, stays bent near full extension (the foot is in place and the pole stable)
    checks.below(jump, 30.0, "no jump playing in IK beyond Rigify's IK pop on a straightening leg (mm)")


def arm_key_values(rig, frame=90):
    from retargetor import generation
    bag = generation.channelbag(rig)
    values = {}
    for name in ("upper_arm_fk.L", "forearm_fk.L", "hand_fk.L"):
        for index in range(4):
            fcurve = bag.fcurves.find(f'pose.bones["{name}"].rotation_quaternion', index=index)
            values[(name, index)] = next((p.co.y, p.type) for p in fcurve.keyframe_points if round(p.co.x) == frame)
    return values


def run_partial(checks, kimodo_python):
    rig = setup(kimodo_python)
    scene = bpy.context.scene
    generate(checks, "partial, base generation (starts Kimodo)")
    # Raise the left arm on frame 90, bend the elbow and the wrist a little, and key the arm's FK controls there
    scene.frame_set(90)
    for name, degrees in (("upper_arm_fk.L", -70.0), ("forearm_fk.L", 20.0), ("hand_fk.L", 10.0)):
        bone = rig.pose.bones[name]
        bone.rotation_quaternion = bone.rotation_quaternion @ Matrix.Rotation(math.radians(degrees), 4, 'X').to_quaternion()
    bpy.context.view_layer.update()
    for name in ("upper_arm_fk.L", "forearm_fk.L", "hand_fk.L"):
        rig.pose.bones[name].keyframe_insert("rotation_quaternion", frame=90)
    bpy.context.view_layer.update()  # the add-on retypes the keys made over generated ones
    from retargetor import generation
    bag = generation.channelbag(rig)
    fcurve = bag.fcurves.find('pose.bones["forearm_fk.L"].rotation_quaternion', index=0)
    checks.check(next(p.type for p in fcurve.keyframe_points if round(p.co.x) == 90) == 'KEYFRAME',
                 "the arm keyed over generated keys: user keys")
    arm_keys = arm_key_values(rig)
    hand_target = (rig.matrix_world @ rig.pose.bones["ORG-hand.L"].head).copy()
    hand_direction = bone_direction(rig, "ORG-hand.L")

    task = generate(checks, "partial pose: the left arm alone on frame 90")
    pose = task.request.key_poses[90]
    checks.check(pose.constrained_joints == ["LeftArm", "LeftForeArm", "LeftHand"],
                 f"frame 90 constrains the left arm ({pose.constrained_joints})")
    checks.check(all(task.request.key_poses[f].constrained_joints is None for f in (1, 61, 120)),
                 "the other key poses are whole")
    checks.check(90 in generated_frames(rig, "upper_arm_fk.R") and 90 not in generated_frames(rig, "upper_arm_fk.L"),
                 "frame 90: the rest of the body generated, the keyed arm kept")
    check_follows_model(checks, rig, [f for f in range(1, 121) if f != 90], "partial")
    scene.frame_set(90)
    rig_hand = rig.matrix_world @ rig.pose.bones["ORG-hand.L"].head
    model = rig.retargetor.model_armature
    model_hand = model.matrix_world @ model.pose.bones["LeftHand"].head
    print(f"FINDING partial pose: on frame 90 the rig's left hand is {(rig_hand - hand_target).length * 100:.1f} cm "
          f"from the key pose ({angle_deg(bone_direction(rig, 'ORG-hand.L'), hand_direction):.1f} deg); the model's "
          f"hand is {(model_hand - hand_target).length * 100:.1f} cm from it (other proportions)")
    # Kimodo puts its hand exactly where the key pose has it (checked in the Kimodo venv: 0.0001 cm), and builds
    # the rest of the body freely. The rig keeps the arm's FK keys (local rotations) on that new body: its hand
    # lands elsewhere. Measured, not checked (see ROADMAP.md, Phase 4 findings).
    print(f"FINDING partial pose: the rig's left hand moves {jump_cm(rig, 89, 90, 'ORG-hand.L'):.1f} cm from frame 89 "
          "to frame 90")
    checks.check(arm_key_values(rig) == arm_keys, "partial: the arm's keys on frame 90 are untouched")


SEGMENTS = [(1, 150, "A person walks forward and raises both arms", 1), (151, 300, "A person turns left and waves", 2),
            (301, 450, "A person jumps on the spot", 3)]


def frame_steps(rig, frames):
    """{frame: (hips movement in cm, worst ORG bone direction change in degrees) from the frame before}"""
    snapshot = motion_snapshot(rig, [frames[0] - 1] + list(frames))
    steps = {}
    for frame in frames:
        before, after = snapshot[frame - 1], snapshot[frame]
        hips = (after["ORG-spine"][0] - before["ORG-spine"][0]).length * 100
        turn = max(angle_deg(before[n][1], after[n][1]) for n in after)
        steps[frame] = (hips, turn)
    return steps


def run_segments(checks, kimodo_python):
    rig = setup(kimodo_python)
    from retargetor import segment_track
    from retargetor.core.segments import PromptSegment
    state = rig.retargetor
    segment_track.write_track(state, [PromptSegment(*segment) for segment in SEGMENTS])
    key_frames = [1, 61, 120]
    before = motion_snapshot(rig, key_frames)
    task = generate(checks, "three prompt segments, 15 s (starts Kimodo)")
    checks.check(len(task.chunks) == 1 and len(task.request.segments) == 3 and (task.start_frame, task.end_frame)
                 == (1, 450), "one request for the three segments, frames 1-450")
    checks.check(task.key_frames == key_frames, f"the key poses of the first segment ({task.key_frames})")
    key_poses_kept(checks, rig, before, "segments")
    checks.check(generated_frames(rig) >= set(range(1, 451)) - set(key_frames), "GENERATED keys on the whole track")
    checks.check(all(segment_track.segment_state(item) == 'GENERATED' for item in state.segments),
                 "the segments are marked generated")

    # Where the segments meet, the motion moves no more than inside them
    steps = frame_steps(rig, list(range(2, 451)))
    boundaries = [151, 301]
    inside = [step for frame, step in steps.items() if all(abs(frame - b) > 6 for b in boundaries)]
    hips_limit = sorted(h for h, _t in inside)[int(0.99 * len(inside))]
    turn_limit = sorted(t for _h, t in inside)[int(0.99 * len(inside))]
    for boundary in boundaries:
        near = [steps[f] for f in range(boundary - 6, boundary + 7)]
        hips, turn = max(h for h, _t in near), max(t for _h, t in near)
        print(f"FINDING segments: around frame {boundary}, hips {hips:.2f} cm and limbs {turn:.2f} deg per frame at "
              f"most (99% of the frames inside the segments: {hips_limit:.2f} cm, {turn_limit:.2f} deg)")
        checks.below(hips, 1.5 * hips_limit, f"no hips jump where the segments meet, frame {boundary} (cm/frame)")
        checks.below(turn, 1.5 * turn_limit, f"no limb jump where the segments meet, frame {boundary} (deg/frame)")
    scene = bpy.context.scene
    scene.frame_set(1)
    start = rig.matrix_world @ rig.pose.bones["ORG-spine"].head
    for frame in (150, 300, 450):
        scene.frame_set(frame)
        hips = rig.matrix_world @ rig.pose.bones["ORG-spine"].head
        print(f"FINDING segments: hips on frame {frame}: {((hips - start) * Vector((1, 1, 0))).length:.2f} m from the "
              f"start, {hips.z:.2f} m high")

    # Same seeds, same key poses, same prompts: the same motion (the model is loaded now)
    first = motion_snapshot(rig, [75, 225, 375])
    generate(checks, "three prompt segments again")
    _ma, worst_angle, _md, worst_dist = compare(first, motion_snapshot(rig, [75, 225, 375]),
                                                [(f, f) for f in (75, 225, 375)])
    checks.below(worst_dist, 0.1, "same seeds: same motion, worst head (cm)")


def all_keys(rig):
    """{(data_path, index): {frame: (value, type)}} for every F-curve of the rig"""
    from retargetor import generation
    return {(fc.data_path, fc.array_index): {round(p.co.x): (p.co.y, p.type) for p in fc.keyframe_points}
            for fc in generation.bone_fcurves(rig)}


def boundary_jumps(checks, rig, boundaries, label):
    """Around each boundary, the motion moves no more than inside the segments (99% of their frames)"""
    steps = frame_steps(rig, list(range(2, 451)))
    inside = [step for frame, step in steps.items() if all(abs(frame - b) > 6 for b in boundaries)]
    hips_limit = sorted(h for h, _t in inside)[int(0.99 * len(inside))]
    turn_limit = sorted(t for _h, t in inside)[int(0.99 * len(inside))]
    for boundary in boundaries:
        near = [steps[f] for f in range(boundary - 6, boundary + 7)]
        hips, turn = max(h for h, _t in near), max(t for _h, t in near)
        print(f"FINDING {label}: around frame {boundary}, hips {hips:.2f} cm and limbs {turn:.2f} deg per frame at "
              f"most (99% of the frames inside the segments: {hips_limit:.2f} cm, {turn_limit:.2f} deg)")
        checks.below(hips, 1.5 * hips_limit, f"{label}: no hips jump at frame {boundary} (cm/frame)")
        checks.below(turn, 1.5 * turn_limit, f"{label}: no limb jump at frame {boundary} (deg/frame)")


def run_segment(checks, kimodo_python):
    rig = setup(kimodo_python)
    from retargetor import segment_track
    from retargetor.core.segments import PromptSegment
    state = rig.retargetor
    segment_track.write_track(state, [PromptSegment(*segment) for segment in SEGMENTS])
    key_frames = [1, 61, 120]
    generate(checks, "the whole track (starts Kimodo)")
    state.segments[0].prompt = "A person walks forward slowly and raises both arms"  # edited, not regenerated
    outside = [f for f in range(1, 451) if not 151 <= f <= 300]
    motion_before = motion_snapshot(rig, range(1, 451))
    keys_before = all_keys(rig)

    # Segment 2 (frames 151-300) regenerated alone, with another prompt and seed
    state.segments[1].prompt = "A person turns right and crouches"
    state.segments[1].seed = 7
    task = generate(checks, "segment 2 regenerated alone", segment=1)
    request = task.request
    checks.check((request.start_frame, request.end_frame, request.prompt, request.seed, request.key_poses)
                 == (151, 300, "A person turns right and crouches", 7, {}),
                 "the request: segment 2, its prompt and seed, no key pose in it")
    checks.check((request.context_before.start_frame, request.context_before.end_frame,
                  request.context_after.start_frame, request.context_after.end_frame) == (146, 150, 301, 305),
                 "the motion around it: 5 frames on each side")
    states = [segment_track.segment_state(item) for item in state.segments]
    checks.check(states == ['MODIFIED', 'GENERATED', 'GENERATED'], f"only segment 2 marked generated ({states})")

    keys_after = all_keys(rig)
    changed = [(c, f) for c in set(keys_before) | set(keys_after)
               for f in set(keys_before.get(c, {})) | set(keys_after.get(c, {}))
               if not 151 <= f <= 300 and keys_before.get(c, {}).get(f) != keys_after.get(c, {}).get(f)]
    checks.check(not changed, f"the keys outside segment 2 are unchanged ({len(changed)}: {changed[:3]})")
    motion_after = motion_snapshot(rig, range(1, 451))
    _ma, worst_angle, _md, worst_dist = compare(motion_before, motion_after, [(f, f) for f in outside])
    checks.below(worst_dist, 1e-3, "the motion outside segment 2 is unchanged, worst head (cm)")
    checks.below(worst_angle, 1e-3, "the motion outside segment 2 is unchanged, worst direction (deg)")
    mean_angle, _wa, mean_dist, _wd = compare(motion_before, motion_after, [(f, f) for f in range(151, 301)])
    print(f"FINDING segment 2 regenerated: {mean_dist:.1f} cm, {mean_angle:.1f} deg from the previous motion on average")
    checks.check(mean_dist > 5.0, f"segment 2 is a new motion ({mean_dist:.1f} cm from the previous one)")
    key_poses_kept(checks, rig, {f: motion_before[f] for f in key_frames}, "segment 2 regenerated")
    boundary_jumps(checks, rig, [151, 301], "segment 2 regenerated")
    # Frame by frame across each boundary: the step onto the regenerated segment, or off it, is like its neighbours
    for boundary in (151, 301):
        steps = frame_steps(rig, list(range(boundary - 4, boundary + 5)))
        print(f"FINDING segment 2 regenerated, steps around frame {boundary} (cm, deg): " +
              ", ".join(f"{f}: {h:.2f} {t:.1f}" for f, (h, t) in steps.items()))
        around = [steps[f] for f in steps if f != boundary]
        checks.below(steps[boundary][0], 2.0 * max(h for h, _t in around) + 0.1,
                     f"segment 2 regenerated: hips step onto frame {boundary} like the frames around it (cm)")
        checks.below(steps[boundary][1], 2.0 * max(t for _h, t in around) + 0.5,
                     f"segment 2 regenerated: limbs step onto frame {boundary} like the frames around it (deg)")


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
        elif mode == "range":
            run_range(checks, kimodo_python)
        elif mode == "ik":
            run_ik(checks, kimodo_python, out_dir)
        elif mode == "partial":
            run_partial(checks, kimodo_python)
        elif mode == "segments":
            run_segments(checks, kimodo_python)
        elif mode == "segment":
            run_segment(checks, kimodo_python)
    finally:
        from retargetor.backends import registry
        registry.stop_all()
    checks.finish()


if __name__ == "__main__":
    main()
