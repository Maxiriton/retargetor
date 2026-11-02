"""The Phase 1 chain through the new API, on the spike's Rigify rig, compared with the spike's results.

    blender -b --factory-startup <rig.blend> --python tests/blender/test_chain.py -- <fk|ik2fk> <spike out dir> <reference dir>

fk:    <rig.blend> is spikes/phase1/out/rig_keyposes.blend, <spike out dir> spikes/phase1/out
ik2fk: <rig.blend> is spikes/phase1/out/rig_keyposes_ik.blend (posed in IK), <spike out dir> spikes/phase1/out/ik2fk.
       The FK controls are first snapped to the IK key poses with the rig profile.
<reference dir>: dumps of the spike's results made with dump_pose.py (soma_keyposes.json from rig_to_soma.blend,
       rig_result.json from result.blend). See tests/run_blender_tests.py.

Steps: Rigify preset -> rig profile; rig -> SOMA on the key frames (to model); the motion Kimodo generated
in the spike from those poses (generated.bvh) -> rig over the whole clip (from model).
The motion model is not run: Phase 1 already generated it from the same key poses, which this test checks.
"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402
from bootstrap import angle_deg, bone_direction  # noqa: E402

KEY_FRAMES = [1, 61, 120]
END_BONES = ["ORG-hand.L", "ORG-hand.R", "ORG-foot.L", "ORG-foot.R", "ORG-spine.006"]


def append_soma():
    """The SOMA reference armature (Phase 0) in its rest pose, without animation"""
    path = bootstrap.require(os.path.join(bootstrap.PHASE0_OUT, "soma_reference.blend"))
    with bpy.data.libraries.load(path, link=False) as (_data_from, data_to):
        data_to.objects = ["SOMA_reference"]
    soma = data_to.objects[0]
    soma.name = "SOMA"
    bpy.context.scene.collection.objects.link(soma)
    soma.animation_data_clear()
    for pb in soma.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()
    return soma


def import_generated(spike_dir):
    """The generated motion (BVH from the spike), placed back where the spike's canonicalization took it from.
    Kimodo-specific conversions, as done by the spike; Phase 3 moves them into backends/kimodo/."""
    with open(bootstrap.require(os.path.join(spike_dir, "canonical.json"))) as f:
        canonical = json.load(f)
    bpy.ops.import_anim.bvh(filepath=bootstrap.require(os.path.join(spike_dir, "generated.bvh")), global_scale=0.01,
                            axis_forward="-Z", axis_up="Y", frame_start=canonical["first_frame"])
    soma = bpy.context.active_object
    soma.name = "SOMA_generated"
    offset = canonical["kimodo_offset"]
    soma.location = (offset[0], -offset[2], 0.0)
    bpy.context.view_layer.update()
    return soma


def limb_bones(rig_profile):
    return [b.read_bone for b in rig_profile.roles if b.offset_mode == 'ROLL' and b.read_bone]


def snapshot(rig, names):
    """World head positions and directions of bones at the current frame"""
    return {n: ((rig.matrix_world @ rig.pose.bones[n].head).copy(), bone_direction(rig, n)) for n in names}


def compare_matrices(obj, reference, frames, names=None):
    """Worst rotation (deg) and position (cm) difference between the object's bones and a dump_pose.py dump"""
    scene = bpy.context.scene
    worst_rot = worst_loc = 0.0
    for frame in frames:
        scene.frame_set(frame)
        for name, rows in reference[str(frame)].items():
            if names is not None and name not in names:
                continue
            old = Matrix(rows)
            new = obj.matrix_world @ obj.pose.bones[name].matrix
            angle = math.degrees(old.to_quaternion().rotation_difference(new.to_quaternion()).angle)
            worst_rot = max(worst_rot, min(angle, 360.0 - angle))
            worst_loc = max(worst_loc, (old.to_translation() - new.to_translation()).length * 100)
    return worst_rot, worst_loc


def main(mode, spike_dir, reference_dir):
    checks = bootstrap.Checks(f"test_chain {mode}")
    bootstrap.register_addon()
    from retargetor.core import profile as core_profile
    from retargetor.core.motion import GenerationRequest
    from retargetor.core.pose_io import read_pose
    from retargetor.core.retarget.snap import Retargeter, compute_translation_scale

    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    rig = bpy.data.objects["rig"]
    joints, root_joint = bootstrap.soma_fixture()

    # 1. Rig profile from the Rigify preset, through the operator
    view_layer.objects.active = rig
    checks.check(bpy.ops.retargetor.profile_load_preset(preset="rigify_human") == {'FINISHED'}, "Rigify preset loaded")
    rig_profile = rig.data.retargetor_profile.to_core()
    limbs = limb_bones(rig_profile)
    org_bones = [b.read_bone for b in rig_profile.roles]

    # 2. IK-posed rig: snap the FK controls to the IK key poses and switch to FK
    if mode == "ik2fk":
        before = {}
        for frame in KEY_FRAMES:
            scene.frame_set(frame)
            before[frame] = snapshot(rig, org_bones)
        frames_text = ", ".join(str(f) for f in KEY_FRAMES)
        checks.check(bpy.ops.retargetor.snap_fk_to_ik(frames=frames_text) == {'FINISHED'}, "Snap FK to IK")
        switches = [rig.pose.bones[limb.switch_bone][limb.switch_property] for limb in rig_profile.limbs]
        checks.check(switches == [1.0] * 4, "limbs switched to FK")
        worst_angle = worst_dist = 0.0
        for frame in KEY_FRAMES:
            scene.frame_set(frame)
            after = snapshot(rig, org_bones)
            worst_angle = max(worst_angle, max(angle_deg(before[frame][n][1], after[n][1]) for n in limbs))
            worst_dist = max(worst_dist, max((before[frame][n][0] - after[n][0]).length * 100 for n in END_BONES))
        checks.below(worst_angle, 0.01, "FK snap vs IK key poses, worst limb direction (deg)")
        # Rigify's IK bones stretch slightly (ik_stretch 0.1); FK keeps the true lengths (spikes/phase1/README.md)
        checks.below(worst_dist, 0.6, "FK snap vs IK key poses, worst hand/foot/head position (cm, IK stretch)")

    # 3. Rig -> SOMA on the key frames (to model), baked on those frames only
    soma = append_soma()
    to_model = core_profile.compose(rig_profile, joints, core_profile.TO_MODEL)
    checks.check(len(to_model) == 23, f"{len(to_model)} pairs rig -> SOMA")
    scale = compute_translation_scale(rig, soma, to_model)
    retargeter = Retargeter(rig, soma, to_model, scale[0])
    checks.check(not retargeter.errors, f"no missing bone rig -> SOMA {sorted(retargeter.errors)}")
    retargeter.bake(scene, view_layer, KEY_FRAMES)

    key_poses = {}
    worst = 0.0
    for frame in KEY_FRAMES:
        scene.frame_set(frame)
        worst = max(worst, max(angle_deg(bone_direction(rig, b.read_bone), bone_direction(soma, joints[b.role]))
                               for b in rig_profile.roles if b.read_bone in limbs))
        key_poses[frame] = read_pose(soma, joints.values(), root_joint)
    checks.below(worst, 0.01, "SOMA vs rig on the key frames, worst limb direction (deg)")

    reference = bootstrap.load_json(os.path.join(reference_dir, "soma_keyposes.json"))
    rot, loc = compare_matrices(soma, reference, KEY_FRAMES)
    checks.below(rot, 0.001, "SOMA key poses vs the spike's, worst rotation (deg)")
    checks.below(loc, 0.001, "SOMA key poses vs the spike's, worst position (cm)")

    request = GenerationRequest(KEY_FRAMES[0], KEY_FRAMES[-1], scene.render.fps / scene.render.fps_base, key_poses,
                                prompt="A person walks forward and raises both arms", seed=1)
    again = GenerationRequest.from_dict(json.loads(json.dumps(request.to_dict())))
    checks.check(again == request and len(again.key_poses[61].rotations) == len(joints),
                 "key poses as a GenerationRequest, through JSON")

    # 4. Generated motion -> rig over the whole clip (from model)
    before = {}
    for frame in KEY_FRAMES:
        scene.frame_set(frame)
        before[frame] = snapshot(rig, org_bones)

    generated = import_generated(spike_dir)
    from_model = core_profile.compose(rig_profile, joints, core_profile.FROM_MODEL, backend="test")
    checks.check(len(from_model) == 20, f"{len(from_model)} pairs SOMA -> rig")
    scale = compute_translation_scale(generated, rig, from_model)
    retargeter = Retargeter(generated, rig, from_model, scale[0])
    clip = range(scene.frame_start, scene.frame_end + 1)
    retargeter.bake(scene, view_layer, clip)

    worst_angle = worst_dist = 0.0
    for frame in KEY_FRAMES:
        scene.frame_set(frame)
        after = snapshot(rig, org_bones)
        worst_angle = max(worst_angle, max(angle_deg(before[frame][n][1], after[n][1]) for n in limbs))
        worst_dist = max(worst_dist, max((before[frame][n][0] - after[n][0]).length * 100 for n in END_BONES))
    checks.below(worst_angle, 0.05, "rig key poses back after the round trip, worst limb direction (deg)")
    checks.below(worst_dist, 0.05, "rig key poses back after the round trip, worst hand/foot/head position (cm)")

    total = count = 0
    worst = 0.0
    lowest_toe = 1.0
    for frame in clip:
        scene.frame_set(frame)
        for b in rig_profile.roles:
            if b.read_bone in limbs:
                a = angle_deg(bone_direction(rig, b.read_bone), bone_direction(generated, joints[b.role]))
                total, count, worst = total + a, count + 1, max(worst, a)
        lowest_toe = min(lowest_toe, min((rig.matrix_world @ rig.pose.bones[n].tail).z for n in ("ORG-toe.L", "ORG-toe.R")))
    checks.below(total / count, 0.001, f"rig follows the generated motion over {len(clip)} frames, mean limb direction (deg)")
    checks.below(worst, 0.01, "rig follows the generated motion, worst limb direction (deg)")
    checks.check(-0.02 < lowest_toe < 0.1, f"feet on the floor (lowest toe tip {lowest_toe * 100:.1f} cm)")

    reference = bootstrap.load_json(os.path.join(reference_dir, "rig_result.json"))
    # The spike snapped with 5 fixed passes, too few for the hands (6 levels of dependencies): they were up to
    # 1.9 degrees off the generated motion. Snapping by dependency level is exact (checked just above).
    hands = {"ORG-hand.L", "ORG-hand.R"}
    rot, loc = compare_matrices(rig, reference, clip, names=set(org_bones) - hands)
    checks.below(rot, 0.001, "rig vs the spike's result over the clip, worst rotation of the ORG bones but the hands (deg)")
    checks.below(loc, 0.001, "rig vs the spike's result over the clip, worst position of the ORG bones (cm)")
    rot, _loc = compare_matrices(rig, reference, clip, names=hands)
    checks.below(rot, 2.0, "rig vs the spike's result, hands (deg, the spike's were not converged)")

    keys = rig.animation_data.action
    from bpy_extras.anim_utils import action_get_channelbag_for_slot
    channelbag = action_get_channelbag_for_slot(keys, rig.animation_data.action_slot)
    fcurve = channelbag.fcurves.find('pose.bones["upper_arm_fk.L"].rotation_quaternion', index=0)
    checks.check(fcurve is not None and len(fcurve.keyframe_points) == len(clip),
                 f"one key per frame on upper_arm_fk.L ({len(fcurve.keyframe_points) if fcurve else 0})")
    checks.finish()


if __name__ == "__main__":
    args = bootstrap.script_args()
    main(args[0], args[1], args[2])
