"""Generate In-betweens on the Phase 1 Rigify rig posed with its IK controls only (limbs in IK, FK limb keys
removed), with the interpolation backend: the FK controls are snapped to the IK pose automatically.

    blender -b --factory-startup <rig_keyposes_ik.blend> --python tests/blender/test_generate_ik.py

<rig_keyposes_ik.blend>: made by spikes/phase1/make_rig_ik.py from rig_keyposes.blend (tests/run_tests.py makes
both in a scratch folder). Checks: a key on an IK control alone makes a key pose, the limbs keep their IK pose
on the key poses, are switched to FK, the IK keys are kept, the snapped FK keys are user keys.
"""
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402
from test_generate import keys_by_type, quaternion_flips, snapshot, user_keys, worst_change  # noqa: E402

LIMBS = ["arm.L", "arm.R", "leg.L", "leg.R"]


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
    ik_keys = {curve: frames for curve, frames in keys_by_type(rig, generation).items()
               if any(f'"{name}"' in curve[0] for name in ik_controls)}

    task = generation.GenerationTask()
    checks.check(task.run(bpy.context, rig) and task.result is not None, "generated with every limb in IK")
    print("FINDING " + "; ".join(task.notes))
    checks.check(len(rig.data.retargetor_profile.roles) == 23 and "Rigify" in task.notes[0],
                 "the generation applied the Rigify preset to the empty profile")
    checks.check(task.modified, "the task knows the rig was changed before generating")
    checks.check(all(abs(s["IK_FK"] - 1.0) < 1e-6 for s in switches.values()), "every limb switched to FK")
    angle, dist = worst_change(rig, ik_pose)
    print(f"FINDING IK pose vs FK snapped on the key poses: worst direction {angle:.4f} deg, worst head {dist:.2f} cm")
    checks.below(angle, 0.05, "the limbs keep their IK pose on the key poses, worst direction (deg)")
    # Rigify's IK bones stretch a little (ik_stretch 0.1), FK controls don't: hands and feet move a few mm (5 mm
    # on frames 1, 61 and 120, as in Phase 2; up to 1 cm on frame 90, where the left IK hand pulls the arm)
    checks.below(dist, 1.5, "the limbs keep their IK pose on the key poses, worst head (cm)")

    after = keys_by_type(rig, generation)
    checks.check(all(after.get(curve) == frames for curve, frames in ik_keys.items()), "the IK keys are kept")
    fk_frames = after[('pose.bones["forearm_fk.L"].rotation_quaternion', 0)]
    checks.check(all(fk_frames[f][1] == 'KEYFRAME' for f in key_frames), "snapped FK keys on every key pose, user keys")
    generated = {f for f, (_v, t) in fk_frames.items() if t == 'GENERATED'}
    checks.check(generated == set(range(1, 121)) - set(key_frames), "GENERATED keys between the key poses")
    leg_frames = after[('pose.bones["shin_fk.R"].rotation_quaternion', 0)]
    checks.check({f for f, (_v, t) in leg_frames.items() if t != 'GENERATED'} == set(key_frames),
                 "every limb is snapped on every key pose, frame 90 included")
    controls = [b.write_bone for b in rig_profile.roles if b.write_bone]
    checks.check(quaternion_flips(rig, generation, controls) == 0, "quaternion signs continuous")

    # Generating again: the limbs are in FK now, nothing more is snapped, the user keys stay
    keys_before = user_keys(keys_by_type(rig, generation))
    task = generation.GenerationTask()
    checks.check(task.run(bpy.context, rig) and not task.modified and not task.notes, "second generation, no snap")
    checks.check(user_keys(keys_by_type(rig, generation)) == keys_before, "user keys untouched")
    checks.finish()


if __name__ == "__main__":
    main()
