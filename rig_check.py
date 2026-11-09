"""Check a character's rig profile: what is missing or inconsistent, then what its controls really do.

- profile_problems(): from the profile and the armature alone (bones that don't exist, required roles not mapped,
  read bones out of order, a control written by two roles...).
- control_problems(): moves the rig and measures. Each write control is turned (and the hips moved): its read bone
  must turn with it, or the generated motion won't reach the rig. Each limb with an IK snap is posed in FK, its IK
  controls snapped and the limb switched to IK: its bones must stay where they were. Then its FK controls are
  snapped back to that IK pose. The rig's pose and switches are put back afterwards; nothing is keyed.

Both return Problem lists, worst first.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from mathutils import Euler, Matrix

from .core import roles as core_roles
from .core.retarget import fk_snap

ERROR = "ERROR"      # generating would give a wrong result: the Generate button refuses
WARNING = "WARNING"  # the result may be off: the user should look
LEVELS = (ERROR, WARNING)

# Tolerances of the control checks
ANGLE_WARNING = 1.0     # degrees between a read bone's turn and its control's
ANGLE_ERROR = 10.0
# How far a limb moves when switched between IK and FK after a snap, over its length. Rigify's IK chain is a little
# shorter than its FK one (IK stretch): its legs move 2.7% of their length in the test pose
DISTANCE_WARNING = 0.04
DISTANCE_ERROR = 0.10

# Read bones that must be parents of the next one (chains of the profile)
CHAINS = [("upper_arm", "forearm", "hand"), ("thigh", "shin", "foot", "toes")]


@dataclass(frozen=True)
class Problem:
    level: str
    subject: str   # role id, limb name, or "" for the whole profile
    message: str


def _sorted(problems):
    return sorted(problems, key=lambda p: LEVELS.index(p.level))


def _label(role_id):
    try:
        return core_roles.get_role(role_id).label
    except KeyError:
        return role_id


def profile_problems(armature, rig_profile):
    """Problems found from the profile and the armature data, without moving anything"""
    problems = []
    bones = armature.bones
    mapped = [b.role for b in rig_profile.roles if b.read_bone]
    for role_id in core_roles.missing_required(mapped):
        what = "a spine bone (Spine, Chest or Upper Chest)" if role_id == "spine" else _label(role_id)
        problems.append(Problem(ERROR, role_id, f"No bone for {what}"))

    written = {}
    for binding in rig_profile.roles:
        label = _label(binding.role)
        for kind, name in (("read", binding.read_bone), ("written", binding.write_bone)):
            if name and bones.get(name) is None:
                problems.append(Problem(ERROR, binding.role, f"{label}: the {kind} bone '{name}' does not exist"))
        if binding.write_bone:
            if binding.write_bone in written:
                problems.append(Problem(ERROR, binding.role, f"{label}: '{binding.write_bone}' is already written "
                                                             f"by {_label(written[binding.write_bone])}"))
            written.setdefault(binding.write_bone, binding.role)
        elif binding.read_bone and core_roles.get_role(binding.role).required:
            problems.append(Problem(WARNING, binding.role, f"{label} has no control to write: the generated motion "
                                                           "won't move it"))

    def read_bone(role_id):
        binding = rig_profile.binding(role_id)
        bone = bones.get(binding.read_bone) if binding is not None and binding.read_bone else None
        return bone

    for side in ("L", "R"):
        for chain in CHAINS:
            for parent_role, child_role in zip(chain, chain[1:]):
                parent, child = read_bone(f"{parent_role}.{side}"), read_bone(f"{child_role}.{side}")
                if parent is None or child is None or parent in child.parent_recursive:
                    continue
                # Not its child, but where it ends (Auto-Rig Pro's foot hangs from the FK shin, not the read one)
                if (child.head_local - parent.tail_local).length > 0.1 * parent.length:
                    problems.append(Problem(WARNING, f"{child_role}.{side}",
                                            f"{_label(f'{child_role}.{side}')}: '{child.name}' is not under "
                                            f"'{parent.name}' ({_label(f'{parent_role}.{side}')})"))
    from .core.rig_detect import sides_swapped
    mapped_bones = {b.role: bones.get(b.read_bone) for b in rig_profile.roles if b.read_bone}
    mapped_bones = {role: bone for role, bone in mapped_bones.items() if bone is not None}
    if sides_swapped({r: tuple(b.head_local) for r, b in mapped_bones.items()},
                     {r: tuple(b.tail_local) for r, b in mapped_bones.items()}):
        problems.append(Problem(WARNING, "upper_arm.L", "The bones of the left roles are on the character's right "
                                                        "(its feet point the other way): are the sides swapped?"))

    for limb in rig_profile.limbs:
        names = [p.fk_control for p in limb.controls] + [p.followed_bone for p in limb.controls]
        names += list(limb.ik_controls) + [s.ik_control for s in limb.ik_snap]
        names += [s.followed_bone for s in limb.ik_snap if s.followed_bone]
        names += [limb.switch_bone] if limb.switch_bone else []
        for name in dict.fromkeys(names):
            if bones.get(name) is None:
                problems.append(Problem(ERROR, limb.name, f"Limb {limb.name}: the bone '{name}' does not exist"))
    return _sorted(problems)


def _turn(q):
    """Angle in radians of a rotation (quaternion), either sign"""
    return min(q.angle, 2.0 * math.pi - q.angle)


def _angle(a, b):
    """Angle in degrees between two rotations (quaternions)"""
    return math.degrees(_turn(a.rotation_difference(b)))


class _SavedPose:
    """The rig's pose (every bone's basis) and its switches, put back on exit"""
    def __init__(self, rig_obj, limbs, view_layer):
        self.rig, self.view_layer = rig_obj, view_layer
        self.limbs = [limb for limb in limbs if limb.switch_bone and limb.switch_property]

    def __enter__(self):
        self.basis = {pb.name: pb.matrix_basis.copy() for pb in self.rig.pose.bones}
        self.switches = {}
        for limb in self.limbs:
            pb = self.rig.pose.bones.get(limb.switch_bone)
            if pb is not None and limb.switch_property in pb:
                self.switches[(limb.switch_bone, limb.switch_property)] = pb[limb.switch_property]
        return self

    def restore_basis(self, names=None):
        for name in names if names is not None else self.basis:
            self.rig.pose.bones[name].matrix_basis = self.basis[name]

    def __exit__(self, *exc):
        self.restore_basis()
        for (bone, prop), value in self.switches.items():
            self.rig.pose.bones[bone][prop] = value
        self.rig.update_tag()
        self.view_layer.update()
        return False


def _set_switch(rig_obj, limb, value, view_layer):
    if limb.switch_bone and limb.switch_property:
        rig_obj.pose.bones[limb.switch_bone][limb.switch_property] = value
        rig_obj.update_tag()
        view_layer.update()


TEST_TURN = Euler((math.radians(25.0), math.radians(-15.0), math.radians(20.0))).to_matrix()
TEST_MOVE = (0.05, -0.04, 0.03)


def _write_problems(rig_obj, rig_profile, view_layer, saved):
    """Turn each write control and measure its read bone"""
    problems = []
    pose_bones = rig_obj.pose.bones
    for binding in rig_profile.roles:
        control, read = pose_bones.get(binding.write_bone), pose_bones.get(binding.read_bone)
        if control is None or read is None:
            continue
        label = _label(binding.role)
        control_before, read_before = control.matrix.copy(), read.matrix.copy()
        turned = Matrix.Translation(control_before.to_translation()) @ (TEST_TURN @ control_before.to_3x3()).to_4x4()
        control.matrix = turned @ Matrix.Diagonal(control_before.to_scale().to_4d())
        view_layer.update()
        control_turn = control.matrix.to_quaternion() @ control_before.to_quaternion().inverted()
        read_turn = read.matrix.to_quaternion() @ read_before.to_quaternion().inverted()
        if _turn(control_turn) < math.radians(1.0):
            problems.append(Problem(ERROR, binding.role, f"{label}: the control '{control.name}' doesn't turn when "
                                                         "written (a constraint drives it?)"))
        elif _turn(read_turn) < math.radians(1.0):
            problems.append(Problem(ERROR, binding.role, f"{label}: turning '{control.name}' doesn't move "
                                                         f"'{read.name}' (wrong control, or the limb isn't in FK?)"))
        else:
            error = _angle(control_turn, read_turn)
            if error > ANGLE_WARNING:
                level = ERROR if error > ANGLE_ERROR else WARNING
                problems.append(Problem(level, binding.role, f"{label}: '{read.name}' turns {error:.1f}° away from "
                                                             f"its control '{control.name}'"))
        saved.restore_basis([control.name])
        view_layer.update()

        if binding.use_translation:
            head_before = read.head.copy()
            control.matrix = Matrix.Translation(TEST_MOVE) @ control_before
            view_layer.update()
            moved = (read.head - head_before - Matrix.Translation(TEST_MOVE).to_translation()).length
            if moved > 0.002:
                problems.append(Problem(WARNING, binding.role, f"{label}: moving '{control.name}' moves "
                                                               f"'{read.name}' {moved * 100:.1f} cm off: the root "
                                                               "motion won't follow"))
            saved.restore_basis([control.name])
            view_layer.update()
    return problems


def _limb_points(rig_obj, limb):
    pose_bones = rig_obj.pose.bones
    return {pair.followed_bone: (pose_bones[pair.followed_bone].head.copy(), pose_bones[pair.followed_bone].tail.copy())
            for pair in limb.controls}


def _gap(before, after):
    return max(max((b[0] - a[0]).length, (b[1] - a[1]).length) for b, a in zip(before.values(), after.values()))


def _distance_problem(rig_obj, limb, what, gap):
    length = sum(rig_obj.pose.bones[pair.followed_bone].bone.length for pair in limb.controls) or 1.0
    if gap <= DISTANCE_WARNING * length:
        return None
    level = ERROR if gap > DISTANCE_ERROR * length else WARNING
    return Problem(level, limb.name, f"Limb {limb.name}: {what} moves it {gap * 100:.1f} cm "
                                     f"({gap / length:.0%} of its length)")


# An FK test pose: each FK control bent around its own X axis (the bend axis of Blender's limbs)
FK_BENDS = (35.0, 50.0, 20.0, 10.0)


def _limb_problems(rig_obj, limb, view_layer, saved):
    problems = []
    pose_bones = rig_obj.pose.bones
    if not limb.switch_bone or not limb.switch_property:
        return problems
    if limb.switch_property not in pose_bones[limb.switch_bone]:
        return [Problem(ERROR, limb.name, f"Limb {limb.name}: '{limb.switch_bone}' has no property "
                                          f"'{limb.switch_property}'")]
    ik_value = 1.0 - limb.fk_value

    # Does the switch switch? An FK pose, seen in IK, must change
    _set_switch(rig_obj, limb, limb.fk_value, view_layer)
    for pair, bend in zip(limb.controls, FK_BENDS):
        pb = pose_bones[pair.fk_control]
        pb.matrix_basis = pb.matrix_basis @ Matrix.Rotation(math.radians(bend), 4, 'X')
    view_layer.update()
    fk_pose = _limb_points(rig_obj, limb)
    _set_switch(rig_obj, limb, ik_value, view_layer)
    if _gap(fk_pose, _limb_points(rig_obj, limb)) < 0.001:
        problems.append(Problem(ERROR, limb.name, f"Limb {limb.name}: setting '{limb.switch_property}' to "
                                                  f"{ik_value:g} or {limb.fk_value:g} changes nothing (wrong switch, "
                                                  "or wrong FK value?)"))
        return problems

    if limb.ik_snap:
        _set_switch(rig_obj, limb, limb.fk_value, view_layer)
        fk_snap.snap_ik_pose(rig_obj, [limb], view_layer)
        _set_switch(rig_obj, limb, ik_value, view_layer)
        problem = _distance_problem(rig_obj, limb, "switching to IK after snapping its IK controls", _gap(fk_pose, _limb_points(rig_obj, limb)))
        if problem:
            problems.append(problem)

    # Back from that IK pose (or the rest one) to FK
    ik_pose = _limb_points(rig_obj, limb)
    # The FK controls away from it, except those posing the limb in IK too (CloudRig's toe)
    shared = set(limb.ik_controls) | {snap.ik_control for snap in limb.ik_snap}
    saved.restore_basis([pair.fk_control for pair in limb.controls if pair.fk_control not in shared])
    view_layer.update()
    fk_snap.snap_fk_pose(rig_obj, [limb], view_layer)
    _set_switch(rig_obj, limb, limb.fk_value, view_layer)
    problem = _distance_problem(rig_obj, limb, "switching to FK after snapping its FK controls", _gap(ik_pose, _limb_points(rig_obj, limb)))
    if problem:
        problems.append(problem)
    return problems


def control_problems(rig_obj, rig_profile, view_layer):
    """Problems found by moving the rig's controls (the pose is put back). Run on a rig whose profile has no
    ERROR in profile_problems()."""
    problems = []
    limbs = [limb for limb in rig_profile.limbs if limb.switch_bone and limb.switch_property]
    with _SavedPose(rig_obj, limbs, view_layer) as saved:
        for limb in limbs:
            if limb.switch_property in rig_obj.pose.bones[limb.switch_bone]:
                _set_switch(rig_obj, limb, limb.fk_value, view_layer)
        problems += _write_problems(rig_obj, rig_profile, view_layer, saved)
        for limb in limbs:
            problems += _limb_problems(rig_obj, limb, view_layer, saved)
            saved.restore_basis()
            for other in limbs:
                if other.switch_property in rig_obj.pose.bones[other.switch_bone]:
                    _set_switch(rig_obj, other, other.fk_value, view_layer)
    return _sorted(problems)


def check(rig_obj, rig_profile, view_layer):
    """Every problem of a character's profile: the static ones, then, if none is an error, the controls'"""
    problems = profile_problems(rig_obj.data, rig_profile)
    if rig_obj.name not in view_layer.objects:
        problems.append(Problem(ERROR, "", f"'{rig_obj.name}' is not in the view layer (its collection is excluded): "
                                           "its controls can't be checked"))
    if not any(p.level == ERROR for p in problems):
        problems += control_problems(rig_obj, rig_profile, view_layer)
    return _sorted(problems)
