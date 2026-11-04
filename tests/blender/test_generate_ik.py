"""Generate In-betweens on the Phase 1 Rigify rig posed with its IK controls only (limbs in IK, FK limb keys
removed), with the interpolation backend: the FK controls are snapped to the IK pose automatically, and the IK
controls to the generated motion afterwards.

    blender -b --factory-startup <rig_keyposes_ik.blend> --python tests/blender/test_generate_ik.py

<rig_keyposes_ik.blend>: made by spikes/phase1/make_rig_ik.py from rig_keyposes.blend (tests/run_tests.py makes
both in a scratch folder). Checks: a key on an IK control alone makes a key pose, the FK controls take the IK pose
on the key poses, the limbs are back in IK after the generation and play the generated motion there (hands and
feet exact, elbows and knees within Rigify's IK stretch), without jump; the user's IK keys are kept; an edited
generated IK key makes a key pose for the next generation; an animated switch is put back as it was; a limb
without IK snap stays in FK; a cancelled generation puts the switches back.
"""
import os
import sys
import time

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402
from test_generate import edit_key, key_type, keys_by_type, quaternion_flips, snapshot, user_keys  # noqa: E402

LIMBS = ["arm.L", "arm.R", "leg.L", "leg.R"]
# Hands and feet (the IK targets: the wrist, the ankle, the toe), elbows and knees
ENDS = ["ORG-hand.L", "ORG-hand.R", "ORG-foot.L", "ORG-foot.R", "ORG-toe.L", "ORG-toe.R"]
JOINTS = ["ORG-forearm.L", "ORG-forearm.R", "ORG-shin.L", "ORG-shin.R"]


def heads(rig, names, frames):
    """{frame: {name: world head}}"""
    scene = bpy.context.scene
    result = {}
    for frame in frames:
        scene.frame_set(frame)
        result[frame] = {n: (rig.matrix_world @ rig.pose.bones[n].head).copy() for n in names}
    return result


def set_switches(rig, switches, value):
    for switch in switches.values():
        switch["IK_FK"] = value
    rig.update_tag()
    bpy.context.view_layer.update()


def in_fk(rig, switches, function):
    """function() with every limb in FK (static switches), then the switches put back"""
    values = {name: float(s["IK_FK"]) for name, s in switches.items()}
    set_switches(rig, switches, 1.0)
    try:
        return function()
    finally:
        for name, switch in switches.items():
            switch["IK_FK"] = values[name]
        rig.update_tag()
        bpy.context.view_layer.update()


def ik_vs_fk(rig, switches, frames):
    """The rig played in IK (as it is) and in FK: worst gap on the hands and feet and on the elbows and knees
    (mm), and the worst jump of the IK playback: how much further a bone moves in IK than in FK from a frame to
    the next (mm; a fast FK motion that IK follows more smoothly isn't a jump)"""
    names = ENDS + JOINTS
    ik = heads(rig, names, frames)
    fk = in_fk(rig, switches, lambda: heads(rig, names, frames))
    gap_ends = max((ik[f][n] - fk[f][n]).length for f in frames for n in ENDS) * 1000
    joint_gaps = [((ik[f][n] - fk[f][n]).length * 1000, n, f) for f in frames for n in JOINTS]
    ordered = sorted(frames)
    jumps = [(((ik[b][n] - ik[a][n]).length - (fk[b][n] - fk[a][n]).length) * 1000, n, b)
             for a, b in zip(ordered, ordered[1:]) if b == a + 1 for n in names]
    jump = max(jumps, default=(0.0, "", 0))
    worst_joint = max(joint_gaps)
    mean_joint = sum(gap for gap, _n, _f in joint_gaps) / len(joint_gaps)
    print(f"FINDING IK vs FK on {len(frames)} frames: elbows and knees {mean_joint:.1f} mm on average, worst "
          f"{worst_joint[0]:.1f} mm ({worst_joint[1]}, frame {worst_joint[2]}); worst jump "
          f"{max(jump[0], 0.0):.1f} mm ({jump[1]} into frame {jump[2]})")
    return gap_ends, worst_joint[0], max(jump[0], 0.0)


def ik_snap_controls(rig_profile):
    return [snap.ik_control for limb in rig_profile.limbs for snap in limb.ik_snap]


def generated_frames(rig, generation, path, index=0):
    frames = keys_by_type(rig, generation).get((path, index), {})
    return {f for f, (_v, t) in frames.items() if t == 'GENERATED'}


def main():
    checks = bootstrap.Checks("test_generate_ik")
    bootstrap.register_addon()
    from retargetor import generation

    bootstrap.set_backend("interpolate", developer=True)
    scene = bpy.context.scene
    rig = bpy.data.objects["rig"]
    bpy.context.view_layer.objects.active = rig
    scene.retargetor_target = rig
    # An empty profile (cleared after choosing the character): the generation applies the preset itself
    from retargetor.profile_operators import detect_preset
    rig.data.retargetor_profile.roles.clear()
    rig.data.retargetor_profile.limbs.clear()
    rig_profile = detect_preset(rig.data)[1]
    switches = {limb.name: rig.pose.bones[limb.switch_bone] for limb in rig_profile.limbs}
    checks.check(all(s["IK_FK"] == 0.0 for s in switches.values()), "every limb starts in IK")

    # A key on the left IK hand alone, on frame 90: a key pose
    hand = rig.pose.bones["hand_ik.L"]
    scene.frame_set(90)
    hand.location += Vector((0.0, 0.0, 0.05))
    hand.keyframe_insert("location", frame=90)
    checks.check(generation.find_key_frames(rig, rig_profile) == [1, 61, 90, 120],
                 "a key on an IK control makes a key pose")

    org = [b.read_bone for b in rig_profile.roles if b.read_bone and b.offset_mode == 'ROLL']
    key_frames = [1, 61, 90, 120]
    ik_pose = snapshot(rig, org, key_frames)
    ik_controls = [name for limb in rig_profile.limbs for name in limb.ik_controls]
    ik_keys = {curve: frames for curve, frames in user_keys(keys_by_type(rig, generation)).items()
               if any(f'"{name}"' in curve[0] for name in ik_controls)}
    # The animator's own keys (edits made below are added): what Clear Generated Keys must leave at the end
    animator_keys = user_keys(keys_by_type(rig, generation))

    task = generation.GenerationTask()
    checks.check(task.run(bpy.context, rig) and task.result is not None, "generated with every limb in IK")
    print("FINDING " + "; ".join(task.notes))
    checks.check(len(rig.data.retargetor_profile.roles) == 23 and "Rigify" in task.notes[0],
                 "the generation applied the Rigify preset to the empty profile")
    checks.check(task.modified, "the task knows the rig was changed before generating")
    checks.check(any("back in IK" in note for note in task.notes), "the report says the limbs are back in IK")
    checks.check(all(s["IK_FK"] == 0.0 for s in switches.values()), "every limb back in IK")
    ik_frames = len(task.ik_writer.frames)
    print(f"FINDING IK snap: {task.timings['IK snap']:.2f} s for {ik_frames} frames "
          f"({task.timings['IK snap'] / ik_frames * 1000:.0f} ms per frame of 4 limbs; key writing "
          f"{task.timings['writing']:.2f} s)")

    # The FK controls took the IK pose on the key poses (in FK, the rig shows them)
    from test_generate import worst_change
    angle, dist = in_fk(rig, switches, lambda: worst_change(rig, ik_pose))
    print(f"FINDING IK pose vs FK snapped on the key poses: worst direction {angle:.4f} deg, worst head {dist:.2f} cm")
    checks.below(angle, 0.05, "the FK controls take the IK pose on the key poses, worst direction (deg)")
    # Rigify's IK bones stretch a little (ik_stretch 0.1), FK controls don't: hands and feet move a few mm (5 mm
    # on frames 1, 61 and 120, as in Phase 2; up to 1 cm on frame 90, where the left IK hand pulls the arm)
    checks.below(dist, 1.5, "the FK controls take the IK pose on the key poses, worst head (cm)")
    angle, dist = worst_change(rig, ik_pose)
    checks.below(angle + dist, 1e-3, "in IK, the key poses are still the user's")

    after = keys_by_type(rig, generation)
    checks.check(all(after.get(curve, {}).get(f) == key for curve, frames in ik_keys.items()
                     for f, key in frames.items()), "the user's IK keys are kept")
    fk_frames = after[('pose.bones["forearm_fk.L"].rotation_quaternion', 0)]
    checks.check(all(fk_frames[f][1] == 'KEYFRAME' for f in key_frames), "snapped FK keys on every key pose, user keys")
    generated = {f for f, (_v, t) in fk_frames.items() if t == 'GENERATED'}
    checks.check(generated == set(range(1, 121)) - set(key_frames), "GENERATED FK keys between the key poses")
    in_range = set(range(1, 121)) - set(key_frames)
    poles = {snap.ik_control for limb in rig_profile.limbs for snap in limb.ik_snap if snap.mode == 'POLE'}
    missing = [(name, path) for name in ik_snap_controls(rig_profile)
               for path in ("location", "rotation_quaternion", "rotation_euler")
               if (f'pose.bones["{name}"].{path}', 0) in after and not (name in poles and path != "location")
               and generated_frames(rig, generation, f'pose.bones["{name}"].{path}') != in_range]
    checks.check(not missing, f"GENERATED IK keys on every frame between the key poses ({missing[:3]})")
    checks.check(not any(generated_frames(rig, generation, f'pose.bones["{name}"].rotation_quaternion')
                         for name in poles), "the poles get their position only")
    # Frame 90 keys the left IK hand's location only: the IK controls there are keyed as they were (user keys)
    checks.check(key_type(rig, generation, 'pose.bones["upper_arm_ik_target.L"].location', 0, 90) == 'KEYFRAME'
                 and key_type(rig, generation, 'pose.bones["foot_ik.R"].location', 0, 90) == 'KEYFRAME',
                 "on a key pose, the IK controls are keyed as they were")
    controls = [b.write_bone for b in rig_profile.roles if b.write_bone]
    checks.check(quaternion_flips(rig, generation, controls + ik_snap_controls(rig_profile)) == 0,
                 "quaternion signs continuous, FK and IK controls")

    # Played in IK, the rig follows the generated FK motion. On the key poses it shows the user's IK pose, a few
    # mm from the snapped FK one (Rigify's IK chain is a little shorter); that gap is blended between them
    keyed_ends, _joints, _jump = ik_vs_fk(rig, switches, key_frames)
    between = sorted(in_range)
    gap_ends, gap_joints, _jump = ik_vs_fk(rig, switches, between)
    print(f"FINDING IK vs FK: on the key poses (the user's IK pose) hands and feet {keyed_ends:.2f} mm; between "
          f"them hands and feet {gap_ends:.2f} mm, elbows and knees {gap_joints:.1f} mm")
    checks.below(gap_ends, keyed_ends + 0.5, "in IK, the hands and feet follow the FK motion, up to the gap of "
                                             "the key poses (mm)")
    mid = [31, 46, 75, 105]  # midway between key poses: the gap blended
    mid_ends, _joints, _jump = ik_vs_fk(rig, switches, mid)
    print(f"FINDING midway between the key poses: hands and feet {mid_ends:.2f} mm from FK")
    # Rigify's IK chain gets shorter than the FK one (ik_stretch 0.1): the elbows and knees come in a little
    checks.below(gap_joints, 20.0, "in IK, the elbows and knees follow the FK motion (mm)")
    _ends, _joints, jump = ik_vs_fk(rig, switches, list(range(1, 121)))
    print(f"FINDING worst jump of the IK playback compared with the FK one, over the range: {jump:.1f} mm")
    checks.below(jump, 5.0, "no jump playing in IK, compared with FK (mm)")

    # An edited generated IK key becomes a key pose; a user IK key edited on a key pose re-snaps its FK keys
    hand_path = 'pose.bones["hand_ik.L"].location'
    scene.frame_set(30)
    value = rig.pose.bones["hand_ik.L"].location[2] + 0.05
    edit_key(rig, generation, hand_path, 2, 30, value=value)
    checks.check(all(key_type(rig, generation, hand_path, i, 30) == 'KEYFRAME' for i in range(3)),
                 "an edited generated IK key becomes a Keyframe at once")
    edit_key(rig, generation, 'pose.bones["hand_ik.R"].location', 1, 61,
             value=generation.channelbag(rig).fcurves.find('pose.bones["hand_ik.R"].location', index=1)
             .evaluate(61) - 0.08)
    edited = keys_by_type(rig, generation)
    for curve, frame in [((hand_path, i), 30) for i in range(3)] + [(('pose.bones["hand_ik.R"].location', 1), 61)]:
        animator_keys.setdefault(curve, {})[frame] = edited[curve][frame]
    checks.check(generation.find_key_frames(rig, rig_profile) == [1, 30, 61, 90, 120], "frame 30 is a key pose")
    fk_61 = keys_by_type(rig, generation)[('pose.bones["forearm_fk.R"].rotation_quaternion', 1)][61]
    edited_pose = snapshot(rig, org, [30, 61])
    task = generation.GenerationTask()
    checks.check(task.run(bpy.context, rig), "generated again after editing IK keys")
    checks.check(task.key_frames == [1, 30, 61, 90, 120], f"the edited frame is a key pose ({task.key_frames})")
    angle, dist = in_fk(rig, switches, lambda: worst_change(rig, edited_pose))
    print(f"FINDING edited IK keys, FK snapped on frames 30 and 61: worst direction {angle:.4f} deg, worst head "
          f"{dist:.2f} cm")
    checks.below(angle, 0.05, "the FK controls take the edited IK pose (deg)")
    fk_61_after = keys_by_type(rig, generation)[('pose.bones["forearm_fk.R"].rotation_quaternion', 1)][61]
    checks.check(fk_61_after[1] == 'KEYFRAME' and abs(fk_61_after[0] - fk_61[0]) > 1e-3,
                 f"the FK key snapped before is snapped again to the edited IK pose ({fk_61[0]:.4f} -> "
                 f"{fk_61_after[0]:.4f})")
    angle, dist = worst_change(rig, edited_pose)
    checks.below(angle + dist, 0.01, "in IK, the edited key poses are the user's (deg + cm: the round trip through the backend)")
    scene.frame_set(30)
    checks.close(rig.pose.bones["hand_ik.L"].location[2], value, 1e-6, "the edited IK key is kept")
    checks.check(generated_frames(rig, generation, hand_path) == set(range(1, 121)) - {1, 30, 61, 90, 120},
                 "the generated IK keys are rewritten around the new key pose")
    _ends, _joints, jump = ik_vs_fk(rig, switches, list(range(1, 121)))
    checks.below(jump, 5.0, "no jump playing in IK after the regeneration (mm)")

    # The left arm's switch animated, going to FK between the key poses: generated (the arm plays the motion in
    # IK and FK alike), the switch's keys put back as they were
    switch = switches["arm.L"]
    for frame, value in ((1, 0.0), (80, 1.0), (100, 0.0)):
        switch["IK_FK"] = value
        switch.keyframe_insert('["IK_FK"]', frame=frame)
    path = f'pose.bones["{switch.name}"]["IK_FK"]'
    before = [(tuple(p.co), p.type) for p in generation.channelbag(rig).fcurves.find(path).keyframe_points]
    task = generation.GenerationTask()
    checks.check(task.run(bpy.context, rig), "generated with the switch going to FK between key poses")
    fcurve = generation.channelbag(rig).fcurves.find(path)
    checks.check([(tuple(p.co), p.type) for p in fcurve.keyframe_points] == before and not fcurve.mute,
                 "the switch's keys are put back as they were")
    hands = heads(rig, ["ORG-hand.L"], range(70, 112))
    gap = max((hands[f + 1]["ORG-hand.L"] - hands[f]["ORG-hand.L"]).length for f in range(70, 111)) * 1000
    print(f"FINDING switch animated IK -> FK -> IK: the left hand moves {gap:.1f} mm per frame at most on 70-110")
    checks.below(gap, 60.0, "the left hand doesn't jump where the switch changes (mm per frame)")
    generation.channelbag(rig).fcurves.remove(fcurve)
    switch["IK_FK"] = 0.0
    rig.update_tag()

    # A cancelled generation: the switches go back to IK
    keys_before = user_keys(keys_by_type(rig, generation))
    task = generation.GenerationTask()
    task.start(bpy.context, rig)
    checks.check(all(s["IK_FK"] == 1.0 for s in switches.values()), "the limbs are in FK while generating")
    task.cancel()
    begin = time.perf_counter()
    while not task.update(bpy.context, budget=1.0) and time.perf_counter() - begin < 60:
        time.sleep(0.01)
    if task.cancelled:
        task.abandon(bpy.context)
    print(f"FINDING cancel test: the generation was {'cancelled' if task.cancelled else 'already finished'}")
    checks.check(all(s["IK_FK"] == 0.0 for s in switches.values()), "the switches are back in IK after a cancel")
    checks.check(user_keys(keys_by_type(rig, generation)).keys() >= keys_before.keys(), "user keys kept")

    # A limb without IK snap: switched to FK for good, the report says so
    rig.data.retargetor_profile.limbs[LIMBS.index("leg.R")].ik_snap.clear()
    task = generation.GenerationTask()
    checks.check(task.run(bpy.context, rig), "generated with a limb without IK snap")
    print("FINDING " + "; ".join(task.notes))
    checks.check(switches["leg.R"]["IK_FK"] == 1.0 and all(switches[n]["IK_FK"] == 0.0 for n in LIMBS if n != "leg.R"),
                 "the limb without IK snap stays in FK, the others are back in IK")
    checks.check(any("leg.R switched to FK" in note and "no IK snap" in note for note in task.notes),
                 "the report names the limb without IK snap")

    # Generating again: the right leg is in FK now, the other limbs are snapped again, the user keys stay
    keys_before = user_keys(keys_by_type(rig, generation))
    task = generation.GenerationTask()
    checks.check(task.run(bpy.context, rig), "generated again")
    checks.check(user_keys(keys_by_type(rig, generation)).keys() == keys_before.keys(), "user keys kept")

    # Clear Generated Keys: the Generated keys and the keys the add-on made on the key poses go, except one of
    # them the animator changed; the animator's keys stay; controls left without keys go back to rest
    snapped = ('pose.bones["forearm_fk.R"].rotation_quaternion', 1)
    edit_key(rig, generation, snapped[0], snapped[1], 61,
             value=keys_by_type(rig, generation)[snapped][61][0] + 0.05)
    animator_keys.setdefault(snapped, {})[61] = keys_by_type(rig, generation)[snapped][61]
    try:
        result = bpy.ops.retargetor.clear_generated_keys('EXEC_DEFAULT')
    except RuntimeError as e:
        print(f"(operator error) {e}")
        result = {'CANCELLED'}
    checks.check(result == {'FINISHED'}, "Clear Generated Keys")
    after = keys_by_type(rig, generation)
    checks.check(not any(t == 'GENERATED' for frames in after.values() for _v, t in frames.values()),
                 "no Generated key left")
    left = user_keys(after)
    extra = [(c, f) for c, frames in left.items() for f in frames if f not in animator_keys.get(c, {})]
    missing = [(c, f) for c, frames in animator_keys.items() for f, key in frames.items()
               if left.get(c, {}).get(f) != key]
    checks.check(not extra, f"no key made by the add-on left ({len(extra)}, for example {extra[:2]})")
    checks.check(not missing, f"the animator's keys are all there, edited ones included ({missing[:2]})")
    forearm = rig.pose.bones["forearm_fk.L"]
    checks.check(generation.channelbag(rig).fcurves.find('pose.bones["forearm_fk.L"].rotation_quaternion') is None
                 and tuple(forearm.rotation_quaternion) == (1.0, 0.0, 0.0, 0.0),
                 "an FK control left without keys is back at rest")
    checks.check(not rig.retargetor.get("generated_keys") and not rig.retargetor.get("added_keys"),
                 "the records are forgotten")
    try:
        result = bpy.ops.retargetor.clear_generated_keys('EXEC_DEFAULT')
    except RuntimeError:
        result = {'CANCELLED'}
    checks.check(result == {'CANCELLED'}, "nothing more to clear")
    checks.finish()


if __name__ == "__main__":
    main()
