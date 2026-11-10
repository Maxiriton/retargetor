"""Rig setup for rigs other than Rigify: skeletons detected (synthetic ones named like Mixamo, Unreal, SMPL...),
the Rig Setup panel's operators, the rig check, and a generation on a detected skeleton (interpolation backend).

    blender -b --factory-startup --python tests/blender/test_rig_setup.py
"""
import math
import os
import sys

import bpy
from mathutils import Euler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "fixtures"))
import bootstrap  # noqa: E402
import humanoids  # noqa: E402


def build(scheme, prefix="", name=None, skip=()):
    """An armature from a synthetic skeleton (tests/fixtures/humanoids.py), without the bones ending with one of
    `skip`"""
    bones = []
    for bone, parent, head, tail in humanoids.skeleton(scheme, prefix):
        if any(bone.endswith(s) for s in skip):
            continue
        if head == tail:
            tail = (head[0], head[1] - 0.03, head[2])
        bones.append((bone, head, tail, 0.0, parent))
    obj = bootstrap.make_armature(name or scheme, bones)
    bpy.ops.object.select_all(action='DESELECT')
    return obj


def run(operator, **kwargs):
    """An operator's result; an error report raises in background mode, it counts as CANCELLED"""
    try:
        return operator('EXEC_DEFAULT', **kwargs)
    except RuntimeError as e:
        print(f"(operator report) {e}")
        return {'CANCELLED'}


def draw_errors():
    from test_panel import draw_panels
    return draw_panels()


def main():
    checks = bootstrap.Checks("test_rig_setup")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bootstrap.register_addon()
    bootstrap.set_backend("interpolate", developer=True)
    from retargetor import profile_operators, rig_check
    scene, view_layer = bpy.context.scene, bpy.context.view_layer

    # Every convention, detected through Blender's bones
    for scheme in humanoids.SCHEMES:
        obj = build(scheme, name=f"detect_{scheme}")
        detected = profile_operators.detect_profile(obj.data)
        found = {b.role: b.read_bone for b in detected[1].roles} if detected else {}
        checks.check(found == humanoids.expected(scheme), f"{scheme}: every role detected")
        bpy.data.objects.remove(obj)

    # A Mixamo character: chosen, it sets itself up
    rig = build("mixamo", "mixamorig1:", name="mixamo")
    view_layer.objects.active = rig
    scene.retargetor_target = rig
    profile = rig.data.retargetor_profile
    checks.check(profile.source == profile_operators.DETECTED_SOURCE and len(profile.roles) == 22,
                 "a Mixamo skeleton is set up when chosen as the character")
    checks.check(not profile.use_controls, "its bones are read and written")
    hips = next(b for b in profile.to_core().roles if b.role == "hips")
    checks.check(hips.write_bone == "mixamorig1:Hips" and hips.use_translation, "the hips are written and translated")
    checks.check(draw_errors() == [], "the Rig Setup panels draw")

    checks.check(run(bpy.ops.retargetor.check_rig) == {'FINISHED'}, "Check Rig")
    checks.check(profile_operators.last_check(rig.data, profile.to_core()) == [], "no problem on the skeleton")
    checks.check(draw_errors() == [], "the panels draw the check")

    # A role taken out, then given back by picking its bone
    checks.check(run(bpy.ops.retargetor.profile_clear_role, role="hand.L") == {'FINISHED'}, "Clear Role")
    problems = rig_check.profile_problems(rig.data, profile.to_core())
    checks.check([p.subject for p in problems if p.level == rig_check.ERROR] == ["hand.L"], "the missing hand is an error")
    checks.check(draw_errors() == [], "the panels draw a missing role")
    bpy.ops.object.mode_set(mode='POSE')
    rig.data.bones.active = rig.data.bones["mixamorig1:LeftHand"]
    checks.check(run(bpy.ops.retargetor.profile_assign, role="hand.L") == {'FINISHED'}, "Assign Active Bone")
    from retargetor.core.roles import ROLES
    order = [r.id for r in ROLES]
    roles = [b.role for b in profile.roles]
    checks.check(roles == sorted(roles, key=order.index), "the role goes back in its place")
    checks.check(profile.to_core().binding("hand.L").write_bone == "mixamorig1:LeftHand", "the picked bone is written")
    checks.check(run(bpy.ops.retargetor.profile_select_role, role="forearm.L") == {'FINISHED'}, "Select Bones")
    checks.check([pb.name for pb in rig.pose.bones if pb.select] == ["mixamorig1:LeftForeArm"], "the role's bone selected")
    bpy.ops.object.mode_set(mode='OBJECT')

    # The check finds a bone a constraint drives, and swapped sides
    constraint = rig.pose.bones["mixamorig1:LeftForeArm"].constraints.new('COPY_ROTATION')
    constraint.target, constraint.subtarget = rig, "mixamorig1:Spine"
    problems = rig_check.check(rig, profile.to_core(), view_layer)
    checks.check(any(p.subject == "forearm.L" and p.level == rig_check.ERROR for p in problems),
                 "a control driven by a constraint is an error")
    rig.pose.bones["mixamorig1:LeftForeArm"].constraints.remove(constraint)
    # A limb posed by IK only (no FK control to write): named as such
    target = bpy.data.objects.new("ik_target", None)
    scene.collection.objects.link(target)
    target.location = rig.matrix_world @ rig.pose.bones["mixamorig1:LeftHand"].head
    constraint = rig.pose.bones["mixamorig1:LeftForeArm"].constraints.new('IK')
    constraint.target, constraint.chain_count = target, 2
    problems = rig_check.check(rig, profile.to_core(), view_layer)
    checks.check(any(p.subject == "forearm.L" and "IK only" in p.message for p in problems),
                 "a limb posed by IK only is named in the check")
    rig.pose.bones["mixamorig1:LeftForeArm"].constraints.remove(constraint)
    bpy.data.objects.remove(target)
    swapped = profile.to_core()
    left, right = swapped.binding("thigh.L"), swapped.binding("thigh.R")
    left.read_bone, right.read_bone = right.read_bone, left.read_bone
    checks.check(any("swapped" in p.message for p in rig_check.profile_problems(rig.data, swapped)),
                 "swapped sides are noticed")

    # Generation on the detected skeleton: key poses on 1 and 31
    for frame, angle in ((1, 0.0), (31, 70.0)):
        for name in ("mixamorig1:LeftArm", "mixamorig1:RightUpLeg", "mixamorig1:Spine1"):
            pb = rig.pose.bones[name]
            pb.rotation_quaternion = Euler((math.radians(angle), 0.0, math.radians(angle / 2)), 'XYZ').to_quaternion()
            pb.keyframe_insert("rotation_quaternion", frame=frame)
        hips = rig.pose.bones["mixamorig1:Hips"]
        hips.location = (0.0, 0.0, 0.3 * angle / 70.0)
        hips.keyframe_insert("location", frame=frame)
    scene.frame_set(1)
    from retargetor import generation
    checks.check(run(bpy.ops.retargetor.generate_inbetweens) == {'FINISHED'}, "Generate on the Mixamo skeleton")
    fcurve = generation.channelbag(rig).fcurves.find('pose.bones["mixamorig1:LeftArm"].rotation_quaternion', index=0)
    types = {round(p.co.x): p.type for p in fcurve.keyframe_points}
    checks.check(types.get(1) == 'KEYFRAME' and types.get(31) == 'KEYFRAME' and types.get(16) == 'GENERATED',
                 "key poses kept, generated keys between them")
    scene.frame_set(16)
    halfway = rig.pose.bones["mixamorig1:LeftArm"].rotation_quaternion.angle
    checks.check(0.1 < halfway < math.radians(70.0), "the arm is between its key poses halfway")

    # A skeleton missing an arm: Detect Bones finds the rest and says what is missing
    incomplete = build("ue5", name="no_right_arm", skip=("_r",))
    view_layer.objects.active = incomplete
    checks.check(profile_operators.detect_profile(incomplete.data) is None, "an incomplete skeleton isn't applied alone")
    scene.retargetor_target = incomplete
    checks.check(len(incomplete.data.retargetor_profile.roles) == 0, "choosing it leaves its profile empty")
    run(bpy.ops.retargetor.profile_detect)
    found = {b.role for b in incomplete.data.retargetor_profile.roles}
    checks.check("hand.L" in found and "thigh.L" in found and "hand.R" not in found and "thigh.R" not in found,
                 "Detect Bones keeps what it found")
    checks.check(draw_errors() == [], "the panels draw an incomplete profile")
    checks.finish()


if __name__ == "__main__":
    main()
